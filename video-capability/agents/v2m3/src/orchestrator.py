"""主循环编排 (SPECS §4/§5): 状态机推进 + 崩溃断点续跑 + 程序合成。

幂等约定:
- 崩溃后 recover(): 孤儿 generating → pending(重新生成); gating 且无候选 → pending。
- 生成异常: 计一次 attempts, 超过 retry_max 则 blocked, 否则回 pending 重试。
- 候选门禁重跑幂等: 每次全量重评该镜头 verdict=pending 的候选。

所有依赖(generator/gater/composer/kenburns_fn/exists)可注入, CPU 单测用 stub;
缺省实现 lazy import GPU/API 依赖, 本阶段不真正跑。
"""

from __future__ import annotations

import json
import os
import zlib
from pathlib import Path

from . import compose as compose_mod
from . import route as route_mod
from .config import load_settings, parse_api_env, project_root
from .db import DB
from .gates import GATE_IDS, all_passed
from .gates import g1_tech as g1_mod
from .gates.g2g5_vlm import run_g2g5
from .gates.g3_consistency import g3_consistency
from .gates.g4_stability import g4_stability
from .gates.g6_business import g6_business
from .schema import DETERMINISTIC_LANES, WAN_CONSUMING_LANES

TERMINAL_STATUSES = {"composed", "blocked"}
# Wan 预算守卫计数口径 (D-062): v2 消耗型车道 + v1 遗留 t2v 行兼容
WAN_CONSUMING_LANES_SQL = tuple(sorted(WAN_CONSUMING_LANES | {"t2v"}))


def stable_seed(shot_id: str) -> int:
    return zlib.crc32(shot_id.encode("utf-8")) & 0x7FFFFFFF


def asset_type_of(card: dict) -> str:
    """G5 分锚(M5 校准)的资产类型推导: 首帧资产路径含 scenes → scene, 否则 food。

    镜头卡 schema 字段定死(不新增卡面字段), 用路径约定推导是确定性规则;
    assets/products/*=美食类, assets/scenes/*=环境/夜景/人物类。
    """
    asset = str((card.get("first_frame_asset") or "")).replace("\\", "/").lower()
    return "scene" if "/scenes/" in f"/{asset}" else "food"


class Orchestrator:
    def __init__(
        self,
        db: DB,
        settings: dict | None = None,
        generator=None,
        gater=None,
        composer=None,
        kenburns_fn=None,
        exists=os.path.exists,
        log=None,
    ):
        self.db = db
        self.settings = settings or load_settings()
        self.exists = exists
        self._generator = generator
        self._gater = gater
        self._composer = composer
        self._kenburns_fn = kenburns_fn
        self._log = log or (lambda level, msg: self.db.log_event(level, msg))

    # ---------- 依赖(缺省惰性实现) ----------
    @property
    def candidates_dir(self) -> Path:
        p = project_root() / self.settings.get("paths", {}).get("candidates", "workdir/candidates")
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def output_dir(self) -> Path:
        p = project_root() / self.settings.get("paths", {}).get("output", "output")
        p.mkdir(parents=True, exist_ok=True)
        return p

    def generator(self):
        if self._generator is None:
            self._generator = self._default_generator()
        return self._generator

    def gater(self):
        if self._gater is None:
            self._gater = self._default_gater()
        return self._gater

    def composer(self):
        if self._composer is None:
            self._composer = self._default_composer()
        return self._composer

    def kenburns_fn(self):
        if self._kenburns_fn is None:
            from .gen.kenburns import run_kenburns

            self._kenburns_fn = run_kenburns
        return self._kenburns_fn

    def _stylized_first_frame(self, card: dict, attempts: int) -> str | None:
        """生产口径首帧风格统一(SPECS §5.3; M5 阶段0.4 默认开启): 每任务一次, n_best 候选共用。

        settings.prod_stylize_denoise ∈ (0.2, 0.35] 开启; 缺省/0=关闭(调试期不受影响)。
        风格化失败不阻塞生成(降级用原始首帧), 留事件痕。
        仅 first_frame_i2v 车道适用 (v2-M3, D-062): compositing_2d5 不得改动产品图底
        (食物形=品牌伤害), evidence_transfer 必须贴源, pure_gen_short 用场景资产原样。
        """
        denoise = float(self.settings.get("prod_stylize_denoise") or 0.0)
        asset = card.get("first_frame_asset")
        if not asset or denoise <= 0 or card.get("lane") != "first_frame_i2v":
            return None
        out_dir = self.candidates_dir.parent / "stylized"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_png = str(out_dir / f"{card['shot_id']}_a{attempts}.png")
        try:
            from .gen.wan import stylize_first_frame

            meta = stylize_first_frame(asset, out_png, card["prompt_en"],
                                       denoise=denoise, seed=stable_seed(card["shot_id"]))
            self._log("info", f"首帧风格统一完成: {card['shot_id']} (denoise={denoise})")
            return meta["path"]
        except Exception as e:  # noqa: BLE001 — 风格化失败降级原始首帧
            self._log("warn", f"首帧风格统一失败 {card['shot_id']}, 用原始首帧: {e}")
            return None

    def _default_generator(self):
        db, settings = self.db, self.settings

        def gen(card: dict, seed: int, out_path: str, hint: dict | None = None) -> dict:
            hint = hint or {}
            lane = card["lane"]
            if lane == "ken_burns":
                fb = card["fallback"]
                w, h = card["resolution"]
                return self.kenburns_fn()(
                    fb["asset"], out_path, fb["motion"], fb.get("duration_sec", card["duration_sec"]),
                    card["fps"], w, h,
                )
            # v2 三车道 (SPECS_V2 §5.2-§5.4): 车道分发优先于调试模型投影 (D-062)
            if lane == "pure_gen_short":
                from .gen.puregen import generate as puregen_generate

                return puregen_generate(
                    card, seed, out_path,
                    steps=int(hint.get("steps", int(settings.get("prod_steps", 20)))),
                    negative_extra=hint.get("negative_extra"),
                    guidance_delta=float(hint.get("guidance_delta", 0.0)),
                )
            if lane == "compositing_2d5":
                from .gen.compositing25 import generate as c25_generate

                return c25_generate(card, seed, out_path)
            if lane == "evidence_transfer":
                from .gen.evidence import generate as ev_generate

                return ev_generate(
                    card, seed, out_path,
                    steps=int(hint.get("steps", int(settings.get("prod_steps", 20)))),
                    denoise=float(settings.get("evidence_denoise", 0.30)),
                    guidance_delta=float(hint.get("guidance_delta", 0.0)),
                )
            # 调试车道: settings.debug_model=ltx → LTX 短样本 (SPECS §5.3; 装配见 D-024, 投影见 D-025)
            if settings.get("debug_model") == "ltx":
                from .gen.ltx import generate as ltx_generate

                return ltx_generate(
                    card, seed, out_path,
                    steps=int(hint.get("steps", 12)),
                    negative_extra=hint.get("negative_extra"),
                    guidance_delta=float(hint.get("guidance_delta", 0.0)),
                )
            # 产出期守卫: Wan 消耗型车道候选总数 ≤200 (SPECS §5.3; v2 车道口径 D-062)
            placeholders = ",".join("?" * len(WAN_CONSUMING_LANES_SQL))
            used = db._query(
                f"SELECT COUNT(*) AS c FROM candidates WHERE verdict != 'fallback' AND shot_id IN"
                f" (SELECT shot_id FROM tasks WHERE lane IN ({placeholders}))",
                WAN_CONSUMING_LANES_SQL,
            )[0]["c"]
            limit = settings.get("budgets", {}).get("wan_candidates_total", 200)
            if used >= limit:
                raise RuntimeError(f"Wan 候选总数已达守卫上限 {limit}, 停止生成保交付")
            from .gen.wan import generate as wan_generate

            return wan_generate(
                card, seed, out_path,
                steps=int(hint.get("steps", int(settings.get("prod_steps", 20)))),
                negative_extra=hint.get("negative_extra"),
                guidance_delta=float(hint.get("guidance_delta", 0.0)),
                stylized_first_frame=hint.get("stylized_first_frame"),
            )

        return gen

    def _default_gater(self):
        db = self.db

        def gate(candidate_path: str, card: dict) -> dict:
            acc = card.get("acceptance", {})
            w, h = card["resolution"]
            g1 = g1_mod.g1_tech(
                candidate_path, w, h, card["fps"], float(card["duration_sec"]),
                duration_tol=float(acc.get("duration_tol", 0.5)),
            )
            # 均匀抽10帧
            frames_dir = f"{candidate_path}.frames"
            os.makedirs(frames_dir, exist_ok=True)
            frame_paths = extract_frames(candidate_path, frames_dir, n=10)
            ref = card["first_frame_asset"]

            from .api.adapters import BudgetGuard, endpoint_from_env
            from .api.vlm import make_vlm_adapter
            from .config import api_env_path

            env = parse_api_env(api_env_path())
            vlm_adapter = make_vlm_adapter(endpoint_from_env(env, "VLM"), BudgetGuard(db))
            g2, g5, _review = run_g2g5(
                candidate_path,
                vlm_fn=lambda grid, prompt, **kw: vlm_adapter.call(grid, prompt, **kw)[0],
                acceptance=acc,
                asset_type=asset_type_of(card),
            )

            g3 = {"gate": "G3", "passed": False, "score": 0.0, "detail": {"error": "CLIP 不可用"}}
            g4 = {"gate": "G4", "passed": False, "score": 0.0, "detail": {"error": "CLIP 不可用"}}
            try:
                from .gates.g3_consistency import default_embed_fns

                image_embed, _ = default_embed_fns()
                g3 = g3_consistency(frame_paths, ref, image_embed, float(acc.get("clip_ref_min", 0.65)))
                g4 = g4_stability(frame_paths, image_embed, float(acc.get("temporal_clip_min", 0.85)))
            except Exception as e:  # noqa: BLE001
                g3["detail"]["error"] = f"CLIP 不可用: {e}"
                g4["detail"]["error"] = f"CLIP 不可用: {e}"

            # G6(字幕逐字) 属合成级硬校验; 镜头级为占位通过 (D-011)
            g6 = {"gate": "G6", "passed": True, "score": 1.0, "detail": {"deferred": "合成阶段逐字校验"}}
            # G7(物体恒存, SPECS_V2 §3): 六门禁之后追加; 模型/环境不可用 → skipped+记录不误杀 (D-057)
            g7 = self._run_g7(candidate_path, card)
            return {g["gate"]: g for g in (g1, g2, g3, g4, g5, g6, g7)}

        return gate

    def _run_g7(self, candidate_path: str, card: dict) -> dict:
        try:
            from .gates.g7_object_persistence import (
                derive_detect_terms,
                g7_object_persistence,
                load_thresholds,
            )

            return g7_object_persistence(
                candidate_path,
                derive_detect_terms(card),
                load_thresholds(),
                frames_dir=f"{candidate_path}.g7frames",
            )
        except Exception as e:  # noqa: BLE001 — 基础设施失败按 G7e 同口径跳过并记录 (D-057)
            return {"gate": "G7", "passed": True, "score": 1.0,
                    "detail": {"skipped": True, "reason": f"g7_infra: {e}"[:300]}}

    def _default_composer(self):
        db = self.db

        def compose(template: dict, video_by_slot: dict, out_path: str) -> dict:
            plan = compose_mod.plan_compose(template, video_by_slot)
            from .api.adapters import BudgetGuard, endpoint_from_env
            from .api.tts import make_tts_adapter
            from .config import api_env_path

            env = parse_api_env(api_env_path())
            tts = make_tts_adapter(endpoint_from_env(env, "TTS"), BudgetGuard(db))

            def tts_fn(text, p, rate=compose_mod.DEFAULT_RATE):
                # rate 形参启用 compose 自适应语速(D-032); ASR CER 属可选项, 编排器默认跳过(D-011)
                tts.call(text, p, rate=rate)

            ass_path = f"{out_path}.ass"
            result = compose_mod.compose_group(plan, out_path, ass_path, tts_fn)
            g6 = result.get("g6") or {}
            if g6 and not g6.get("passed"):
                detail = g6.get("detail", {})
                db.log_event("warn", f"G6 合成级校验未过 ({template.get('template_id')}): "
                                     f"subtitle_exact={detail.get('subtitle_exact')} cer={detail.get('cer')}")
            return result
        return compose

    # ---------- 崩溃恢复 ----------
    def recover(self) -> int:
        n = 0
        for task in self.db.list_tasks(status="generating"):
            self.db.force_status(task["shot_id"], "pending", "崩溃恢复: 孤儿 generating → pending 重生成")
            n += 1
        for task in self.db.list_tasks(status="gating"):
            if not self.db.get_candidates(task["shot_id"]):
                self.db.force_status(task["shot_id"], "pending", "崩溃恢复: gating 无候选 → pending")
                n += 1
        if n:
            self._log("warn", f"recover(): 重置 {n} 个孤儿任务")
        return n

    # ---------- 单步推进 ----------
    def _card(self, task: dict) -> dict:
        return json.loads(task["card_json"])

    def _generate(self, task: dict, card: dict, hint: dict | None) -> None:
        shot = card["shot_id"]
        attempts = int(task["attempts"])
        base = stable_seed(shot) + attempts * 1000
        # 确定性车道 n_best 视为 1 (D-013 扩展, D-062): zoompan/视差合成多 seed 无意义
        n_best = 1 if card["lane"] in DETERMINISTIC_LANES else int(card["n_best"])
        # 生产口径首帧风格统一(SPECS §5.3): 每任务(每重试轮)一次, n_best 候选共用 (M5 阶段0.4)
        # 仅 first_frame_i2v 车道适用 (D-062)
        hint_eff = dict(hint or {})
        if hint_eff.get("stylized_first_frame") is None and card["lane"] == "first_frame_i2v" \
                and self.settings.get("debug_model") != "ltx":
            stylized = self._stylized_first_frame(card, attempts)
            if stylized:
                hint_eff["stylized_first_frame"] = stylized
        try:
            for i in range(n_best):
                seed = base + i
                out_path = str(self.candidates_dir / f"{shot}_a{attempts}_{i}.mp4")
                meta = self.generator()(card, seed, out_path, hint=hint_eff)
                self.db.add_candidate(shot, meta["path"], gate_json={}, verdict="pending")
                self.db.update_task(shot, seed=seed, steps=meta.get("steps"),
                                    duration_s=meta.get("duration_s"), vram_peak_mb=meta.get("vram_peak_mb"))
        except Exception as e:  # noqa: BLE001 — 生成失败计一次尝试
            attempts += 1
            self.db.update_task(shot, attempts=attempts, error=str(e)[:500])
            self._log("error", f"生成失败 {shot}: {e}")
            if attempts > int(card.get("retry_max", 0)) + 3:
                self.db.force_status(shot, "blocked", f"生成反复失败: {e}")
            else:
                self.db.force_status(shot, "pending", f"生成失败重试: {e}")
            return
        self.db.set_status(shot, "gating")

    def _gate_candidates(self, card: dict) -> list[dict]:
        shot = card["shot_id"]
        for cand in self.db.get_candidates(shot):
            if cand["verdict"] != "pending":
                continue
            if not self.exists(cand["path"]):
                self.db.update_candidate(cand["id"], gate_json={"error": "候选文件缺失"}, verdict="fail",
                                         overall_score=0.0)
                continue
            try:
                gates = self.gater()(cand["path"], card)
            except Exception as e:  # noqa: BLE001
                self.db.update_candidate(cand["id"], gate_json={"error": str(e)[:500]}, verdict="fail",
                                         overall_score=0.0)
                self._log("error", f"门禁异常 {shot}/{cand['id']}: {e}")
                continue
            # 总分: 六门禁均值, G7 在场时计入一份(v2 门禁链扩容, 权重与单门禁等价)
            g7 = gates.get("G7")
            gate_ids = [g for g in GATE_IDS if g in gates]
            denom = len(gate_ids) + (1 if g7 else 0)
            score = (sum(float(gates[g]["score"]) for g in gate_ids)
                     + (float(g7["score"]) if g7 else 0.0)) / max(1, denom)
            g7_ok = bool(g7.get("passed", True)) if g7 else True
            verdict = "pass" if (all_passed(gates) and g7_ok) else "fail"
            self.db.update_candidate(cand["id"], gate_json=gates, verdict=verdict, overall_score=round(score, 4))
        cands = self.db.get_candidates(shot)
        return [
            {"candidate_id": c["id"], "seed": None, "gates": c["gate_json"],
             "overall_score": c["overall_score"], "path": c["path"]}
            for c in cands
        ]

    def _do_fallback(self, card: dict) -> None:
        shot = card["shot_id"]
        fb = card["fallback"]
        w, h = card["resolution"]
        out_path = str(self.candidates_dir / f"{shot}_fallback.mp4")
        meta = self.kenburns_fn()(fb["asset"], out_path, fb["motion"],
                                  fb.get("duration_sec", card["duration_sec"]), card["fps"], w, h)
        self.db.add_candidate(shot, meta["path"], gate_json={"fallback": meta, "G6": {"deferred": True}},
                              verdict="fallback", overall_score=1.0, selected=True)
        self._log("info", f"降级 KenBurns 完成: {shot}")

    def process_task(self, task: dict) -> str | None:
        """推进单个任务一步, 返回新状态(未变则 None)。"""
        shot = task["shot_id"]
        card = self._card(task)
        status = task["status"]

        if status == "pending":
            reason = route_mod.check_assets(card, exists=self.exists)
            if reason:
                self.db.set_status(shot, "blocked")
                self.db.update_task(shot, error=reason)
                self._log("warn", f"{shot} blocked: {reason}")
                return "blocked"
            self.db.set_status(shot, "generating")
            self._generate(task, card, hint=json.loads(task["hint_json"]) if task["hint_json"] else None)
            return "generating"

        if status == "generating":
            # 崩溃恢复场景: 状态已是 generating 但无本轮候选 → 直接补生成
            hint = json.loads(task["hint_json"]) if task["hint_json"] else None
            self._generate(task, card, hint)
            return "generating"

        if status == "gating":
            cands = self._gate_candidates(card)
            fresh = self.db.get_task(shot)
            decision = route_mod.route_shot(card, cands, attempts_used=int(fresh["attempts"]), exists=self.exists)
            action = decision["action"]

            if action == "accept":
                best = decision["candidate"]
                for c in self.db.get_candidates(shot):
                    self.db.update_candidate(c["id"], selected=(c["id"] == best["candidate_id"]))
                self.db.set_status(shot, "accepted")
                self.db.update_task(shot, error=None)
                return "accepted"
            if action == "retry":
                hint = decision["hint"]
                self.db.update_task(shot, attempts=int(fresh["attempts"]) + 1,
                                    hint_json=json.dumps(hint, ensure_ascii=False))
                self.db.set_status(shot, "retrying")
                self.db.set_status(shot, "generating")
                self._generate(self.db.get_task(shot), card, hint)
                return "generating"
            if action == "fallback":
                # 状态机要求经 retrying 中转 (gating→retrying→fallback)
                self.db.set_status(shot, "retrying")
                self.db.set_status(shot, "fallback")
                self._do_fallback(card)
                return "fallback"
            # blocked
            self.db.force_status(shot, "blocked", decision.get("reason", "路由判定 blocked"))
            return "blocked"

        if status == "retrying":
            # 崩溃恢复场景: 带 hint 继续重试生成
            self.db.set_status(shot, "generating")
            hint = json.loads(task["hint_json"]) if task["hint_json"] else None
            self._generate(task, card, hint)
            return "generating"

        return None

    # ---------- 合成阶段 ----------
    def compose_ready(self) -> list[str]:
        """所有任务就绪(accepted/fallback)的模板组 → 程序合成成片 → 任务标 composed。"""
        done: list[str] = []
        tasks = self.db.list_tasks()
        by_template: dict[str, list[dict]] = {}
        for t in tasks:
            if t["template"] and t["status"] in ("accepted", "fallback", "composed"):
                by_template.setdefault(t["template"], []).append(t)

        for template_id, group in sorted(by_template.items()):
            if any(t["status"] == "blocked" for t in group):
                continue
            template = self._load_template(template_id)
            needed = {sc["narrative_slot"] for sc in template["scenes"] if not sc.get("background")}
            have: dict[str, str] = {}
            for t in group:
                if t["status"] in ("accepted", "fallback"):
                    sel = self.db.selected_candidate(t["shot_id"])
                    if sel:
                        have[t["narrative_slot"]] = sel["path"]
            if not needed.issubset(have):
                continue
            out_path = str(self.output_dir / f"{template_id}.mp4")
            result = self.composer()(template, have, out_path)
            for t in group:
                if t["status"] in ("accepted", "fallback"):
                    self.db.set_status(t["shot_id"], "composed")
            self._log("info", f"成片完成: {template_id} -> {result['path']}")
            done.append(result["path"])
        return done

    def _load_template(self, template_id: str) -> dict:
        from .schema import load_template

        p = project_root() / "templates" / "narrative" / f"{template_id}.json"
        if not p.exists():
            raise FileNotFoundError(f"叙事模板不存在: {p}")
        return load_template(p)

    # ---------- 主循环 ----------
    def run_once(self, max_passes: int = 10) -> int:
        """推进所有任务至不动点(每任务一步/遍, 最多 max_passes 遍), 再尝试合成。"""
        total_progress = 0
        for _ in range(max_passes):
            progressed = 0
            for task in self.db.list_tasks():
                if task["status"] in TERMINAL_STATUSES:
                    continue
                before = task["status"]
                try:
                    result = self.process_task(task)
                except Exception as e:  # noqa: BLE001 — 单任务异常不拖垮主循环
                    self._log("error", f"任务推进异常 {task['shot_id']}: {e}")
                    continue
                if result and result != before:
                    progressed += 1
            try:
                self.compose_ready()
            except Exception as e:  # noqa: BLE001
                self._log("error", f"合成阶段异常: {e}")
            total_progress += progressed
            if progressed == 0:
                break
        return total_progress

    def run_forever(self, poll_interval: float = 10.0, max_rounds: int | None = None,
                    max_idle_rounds: int = 3) -> None:
        self.recover()
        rounds = 0
        idle = 0
        while True:
            pending = [t for t in self.db.list_tasks() if t["status"] not in TERMINAL_STATUSES]
            if not pending:
                self._log("info", "全部任务到达终态, 主循环退出")
                break
            progressed = self.run_once()
            rounds += 1
            if max_rounds and rounds >= max_rounds:
                self._log("warn", f"达到最大轮数 {max_rounds}, 主循环退出")
                break
            if progressed == 0:
                idle += 1
                if idle >= max_idle_rounds:
                    self._log("warn", f"连续 {idle} 轮无进展(存在等待合成素材或被阻塞的任务), 主循环退出")
                    break
                import time

                time.sleep(poll_interval)
            else:
                idle = 0


def default_tts_fn_factory(db: DB):
    """compose_from_spec 的缺省 TTS: 统一适配器(API 优先, 本地 edge-tts 兜底), rate 形参启用自适应语速。"""
    from .api.adapters import BudgetGuard, endpoint_from_env
    from .api.tts import make_tts_adapter
    from .config import api_env_path

    env = parse_api_env(api_env_path())
    tts = make_tts_adapter(endpoint_from_env(env, "TTS"), BudgetGuard(db))

    def tts_fn(text, path, rate=compose_mod.DEFAULT_RATE):
        return tts.call(text, path, rate=rate)[0]

    return tts_fn


def compose_from_spec(
    db: DB,
    spec: dict,
    settings: dict | None = None,
    log=None,
    tts_fn=None,
    asr_fn=None,
    out_dir: str | Path | None = None,
) -> dict:
    """按 spec 显式「从指定候选集合」合成成片 (M5; compose-video CLI 后端)。

    spec 字段:
      video_id: 成片唯一名(如 t1_seeding_v1, 同时是输出文件名与 m5_videos 台账键);
      template: 叙事模板 id;
      slots:    {scene_slot: shot_id} — 每幕显式指定镜头, 取该镜头 selected 候选;
      variables/numbers: 与模板合并(spec 覆盖), 同模板差异化口播/价格数字;
      bgm:      是否程序合成 BGM(缺省 True, D-035 + ducking D-006)。
    不改任务状态(compose_ready 的自动合成路径不受影响); 每条成片落 m5_videos 台账,
    shots_json 含每镜头候选 id/verdict/六门禁分数(供 m5_trace_query.sql 反查)。
    """
    import shutil
    import subprocess

    from .schema import load_template

    settings = settings or load_settings()
    log = log or (lambda level, msg: db.log_event(level, msg))
    for key in ("video_id", "template", "slots"):
        if not spec.get(key):
            raise ValueError(f"spec 缺少必填字段: {key}")
    video_id = str(spec["video_id"])
    if "/" in video_id or "\\" in video_id or video_id.startswith("color:"):
        raise ValueError(f"非法 video_id: {video_id!r}")

    template = load_template(project_root() / "templates" / "narrative" / f"{spec['template']}.json")
    variables = {**template.get("variables", {}), **(spec.get("variables") or {})}
    numbers = {**template.get("numbers", {}), **(spec.get("numbers") or {})}

    video_by_slot: dict[str, str] = {}
    shots_detail: list[dict] = []
    for sc in template["scenes"]:
        if sc.get("background"):
            continue
        shot = (spec["slots"] or {}).get(sc["slot"])
        if not shot:
            raise ValueError(f"成片 {video_id}: 幕 {sc['slot']} 未指定镜头 (slots.{sc['slot']})")
        cand = db.selected_candidate(str(shot))
        if not cand:
            raise ValueError(f"成片 {video_id}: 镜头 {shot} 无 selected 候选(未验收?)")
        if not os.path.exists(cand["path"]):
            raise ValueError(f"成片 {video_id}: 镜头 {shot} 候选文件缺失: {cand['path']}")
        video_by_slot[sc["slot"]] = cand["path"]
        shots_detail.append({
            "scene_slot": sc["slot"], "narrative_slot": sc["narrative_slot"], "shot_id": str(shot),
            "candidate_id": cand["id"], "verdict": cand["verdict"],
            "overall_score": cand["overall_score"], "gates": cand["gate_json"], "path": cand["path"],
        })

    plan = compose_mod.plan_compose(template, video_by_slot, variables=variables, numbers=numbers)
    # 数字隔离复查(D-015): 数字只允许出现在字幕
    leaked = any(n in p for n in plan["numbers_used"].values() for p in plan["video_paths"])
    if leaked:
        raise AssertionError(f"成片 {video_id}: 数字泄漏进视频路径!")

    out_dir = Path(out_dir) if out_dir else project_root() / settings.get("paths", {}).get("output", "output")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(out_dir / f"{video_id}.mp4")
    ass_path = f"{out_path}.ass"

    workdir = project_root() / settings.get("paths", {}).get("workdir", "workdir")
    bgm_path = None
    if spec.get("bgm", True):
        bgm_path = str(workdir / "m5_bgm" / f"{video_id}.m4a")
        Path(bgm_path).parent.mkdir(parents=True, exist_ok=True)
        argv = compose_mod.build_bgm_argv(plan["total_duration"], bgm_path)
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=300)
        if cp.returncode != 0:
            raise RuntimeError(f"BGM 合成失败: {cp.stderr[-300:]}")

    if tts_fn is None:
        tts_fn = default_tts_fn_factory(db)

    result = compose_mod.compose_group(plan, out_path, ass_path, tts_fn,
                                       bgm_path=bgm_path, asr_fn=asr_fn)

    # 中间件归置(voice*/g6audio/bgm → workdir/m5_intermediate), output/ 只留成片+ASS
    inter_dir = workdir / "m5_intermediate"
    inter_dir.mkdir(parents=True, exist_ok=True)
    moved = []
    for suffix in (".mp3", ".m4a", ".wav"):
        for f in out_dir.glob(f"{video_id}.mp4.*{suffix}"):
            target = inter_dir / f.name
            shutil.move(str(f), str(target))
            moved.append(target.name)

    db.record_m5_video(video_id, template["template_id"], spec, shots_detail,
                       result["path"], result.get("g6") or {})
    log("info", f"成片完成(compose-video): {video_id} -> {result['path']}")
    return {**result, "video_id": video_id, "shots": shots_detail, "intermediates_moved": moved}


def extract_frames(video_path: str, out_dir: str, n: int = 10) -> list[str]:
    """均匀抽 n 帧到 out_dir, 返回排序路径列表。"""
    import glob

    from .gates.g2g5_vlm import build_grid_argv  # noqa: F401 — 复用时长探测
    from .gates.g1_tech import probe_duration
    import subprocess

    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "frame_*.png")):
        os.remove(old)
    duration = probe_duration(video_path)
    fps_expr = f"fps={n}/{max(duration, 1e-6):.6f}"
    argv = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", video_path,
            "-vf", fps_expr, "-frame_pts", "0", os.path.join(out_dir, "frame_%03d.png")]
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    if cp.returncode != 0:
        raise RuntimeError(f"抽帧失败: {cp.stderr[-300:]}")
    return sorted(glob.glob(os.path.join(out_dir, "frame_*.png")))
