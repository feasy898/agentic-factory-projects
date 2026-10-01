#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_avatar.py — G9a 口播专线：台词 → TTS → Vidu avatar 数字人 → 暂存+元数据 → qc_orch 钩子
=====================================================================================

定位（vpipe SPEC.md §2 家族的第五模块，单文件、不 import 任何 vpipe 兄弟模块）：
  G9a 口播主体镜头（工程方案v3.1 §2.1 G9 拆行）：TTS（StepFun stepaudio-2.5-tts，默认音色
  或零样本克隆）→ Vidu s_avatar/offline（audio 驱动，参考图即身份源，1 积分/s 整秒取整）
  → 本地暂存 + gen_meta 元数据（积分/耗时/池差）→ 输出 qc_hint 供 qc_orch/qc_detectors_v2 挂接。

输入契约（VDL v2 口播镜头 spec 兼容；编译器/投影器未就绪——VDL_v2_草案.md §10-5——
故按草案字段直接消费：v1 基础字段语义见 contracts/shot.schema.json，v2 扩展段按
数字人实验报告.md §7-2 的登记规格）：

  {
    "schema_version": "2.0",            # 接受 "1.0"|"2.0"（本模块是 v2 草案超集的消费者，
                                        #   v1 冻结引擎不读本模块的文件，无破契约风险）
    "shot_id": "g9a_demo",              # ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$
    "axis": "G9",
    "duration_s": 60,                   # 仅目标参考；口播成片实际时长 = ceil(音频时长)，
                                        #   由音频驱动（整秒取整垫尾是平台行为，L0 豁免，
                                        #   工程方案v3.1 §3.1）
    "aspect": "9:16",
    "prompt": "...",                    # 仅登记（avatar 通道不消费 prompt，画面=参考图+音频）
    "characters": [ {"char_id": "charA",
                     "ref_image": "references/charA.png"} ],   # 必填且仅 1 张（Vidu 单人图限制）
    "audio": { "speech": "台词文本" },   # 必填（除非 tts.audio_file 直接给音频）
    "tts": {                            # v2 草案扩展（均可省，取默认）
      "engine": "stepfun",              # stepfun（默认）| design-seedaudio（备用，本机网关）
      "model": "stepaudio-2.5-tts",
      "voice": "cixingnansheng",        # 默认音色；给 clone_audio 时被克隆 voice_id 覆盖
      "clone_audio": "path/to/ref.wav", # 可选克隆音频（3s 官方口径，实测 5-10s 起效，
                                        #   stepfun_smoke_20260930.json voice_clone）
      "clone_text": "克隆音频的文字转写", # 克隆登记用（/audio/voices 的 text 字段）
      "instruction": "语速适中，口播风格，清晰亲和",
      "audio_file": null                # 可选：直接提供已生成音频（跳过 TTS）
    },
    "avatar": { "resolution": "720p",   # 540p|720p（实测档，工程方案v3.1 §2.4①）
                "watermark": false,     # 默认 false（无水印 url）
                "timeline": null }      # 可选动作编排（序列化 JSON，本轮未用）
  }

行为要点（全部来自既有实测资产的结论，出处逐条内联）：
  - 积分守卫：提交前查 Vidu `/ent/v2/credits`（工程方案v3.1 §6 S3 登记口径）——
    「通用池余额 < 预估+45」（vidu_avatar_client.py:24 文档口径：余额<45 不能发起任务）
    与「本轮累计已扣 + 预估 > credit-cap」双拦截，任一命中 exit 3（沿 gen_api 口径，
    vpipe SPEC.md §2.2）。任务后回查两池差值，逐任务记账入 state 文件。
  - 计价：Vidu avatar 1 积分/s、按音频时长整秒向上取整、失败不扣（工程方案v3.1 §2.4①）；
    StepFun TTS ¥5.8/万字符（stepfun_smoke_20260930.json pricing_doc，模块内只记估算值，
    实扣以钱包端点为准——API 无逐调用账单，如实记录）。
  - 产物 24h 失效：`creations[].url` 24h 有效，即时下载落盘（工程方案v3.1 §8 红线）。
  - 克隆音色按「克隆音频 sha256 → voice_id」缓存在 state，重复用同一段克隆音频不重复建音色。
  - 失败如实记录：一切异常/降级写进 gen_meta 的 `errors`，不静默吞（SPEC.md §2 纪律）。
  - 密钥纪律：两把 key 全部经上游客户端从 env/secrets 读取，本文件与产物无密钥字面量；
    日志掩码由上游客户端保证（key 前 6 字符）。

CLI:
  python src/gen_avatar.py --shot shot.json --out-dir out/avatar \
      [--credit-cap 3000] [--dry-run] [--validate-only] [--state out/avatar/avatar_state.json]
  python src/gen_avatar.py probe            # 探两把钱包（Vidu 双池 + StepFun），0 成本

退出码：0 成功 / 2 契约或输入校验失败 / 3 积分守卫拦截（对齐 gen_api）。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

# ---------- 控制台编码（Windows） ----------
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------- 上游实测客户端（overnight/数据/，非 vpipe 兄弟模块，SPEC §0 不适用） ----------
VPIPE_SRC = Path(__file__).resolve().parent
VPIPE_ROOT = VPIPE_SRC.parent
OVERNIGHT = VPIPE_ROOT.parent
DATA_DIR = OVERNIGHT / "数据"
sys.path.insert(0, str(DATA_DIR))

import vidu_avatar_client as vidu          # noqa: E402  (数据/vidu_avatar_client.py，实测 status=ok)
import stepfun_client as sf                # noqa: E402  (数据/stepfun_client.py)

MODULE_ID = "gen_avatar.py@vpipe-g9a-1.0"

# Design seedaudio 备用 TTS：出站仅写死本机网关常量（同 数据/digital_human/dh_design_tts.py，
# 非外部输入 URL，无任意抓取面；免鉴权，不涉及密钥）
DESIGN_GATEWAY = "http://127.0.0.1:8001"
DESIGN_WORKSPACE = Path(r"D:\d\MiniMax Design Data\output_files")

# 台词量→音频时长的估算基准（--dry-run 无音频实长时用；StepFun 实测 4.6 字/s，
# 数字人实验报告.md §2.1），估算只用于积分预拦，实际计费以任务 credits 字段为准
CHARS_PER_SEC_EST = 4.6
MIN_VIDU_BALANCE = 45          # vidu_avatar_client.py:24 文档口径：余额<45 不能发起任务
DEFAULT_CREDIT_CAP = 3000      # 本轮 avatar 预算红线（任务指示：avatar 专属池本轮预算 ≤3000 积分）

SHOT_ID_RE = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
VIDU_STAGING_SAFE = r"^[\w][\w\- .]{0,120}$"   # vidu out_path_for 白名单（无 @）
# 输入路径安全姿态：允许 shot 内相对路径（沿既有 shots_demo 的 ..\数据\... 惯例），
# 但解析后必须落在项目根内——防任意系统文件被读进 data URI / 上传（Mimosa 出站约束的输入侧配对）
WORKSPACE_ROOT = OVERNIGHT.parent


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(msg):
    print(f"[gen_avatar {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_file(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# =====================================================================
# 1) 契约校验
# =====================================================================
def validate_shot(shot: dict) -> tuple[bool, list[str]]:
    """轻量校验（jsonschema 不可用时同此口径）：必填项 + 路径安全 + 词表检查。"""
    errs = []
    import re
    if not isinstance(shot, dict):
        return False, ["shot 不是 JSON 对象"]
    if str(shot.get("schema_version")) not in ("1.0", "2.0"):
        errs.append(f"schema_version 须为 1.0|2.0（VDL v2 草案超集），got {shot.get('schema_version')!r}")
    sid = shot.get("shot_id")
    if not isinstance(sid, str) or not re.match(SHOT_ID_RE, sid):
        errs.append(f"shot_id 不合法（{SHOT_ID_RE}）: {sid!r}")
    chars = shot.get("characters") or []
    if len(chars) < 1:
        errs.append("characters 至少 1 个（参考图=身份源）")
    elif len(chars) > 1:
        errs.append(f"Vidu avatar 仅支持 1 张单人参考图，got {len(chars)}（vidu_avatar_client.py:27）")
    elif not (chars[0].get("ref_image") or "").strip():
        errs.append("characters[0].ref_image 必填（参考图路径）")
    tts = shot.get("tts") or {}
    speech = ((shot.get("audio") or {}).get("speech") or "").strip()
    if not speech and not tts.get("audio_file"):
        errs.append("audio.speech（台词）与 tts.audio_file 至少提供一个")
    if tts.get("engine", "stepfun") not in ("stepfun", "design-seedaudio"):
        errs.append(f"tts.engine 须为 stepfun|design-seedaudio，got {tts.get('engine')!r}")
    if tts.get("engine", "stepfun") == "design-seedaudio" and tts.get("clone_audio"):
        errs.append("克隆仅支持 stepfun 通道（Design seedaudio 无克隆上传通道）")
    avatar = shot.get("avatar") or {}
    if avatar.get("resolution", "720p") not in ("540p", "720p"):
        errs.append(f"avatar.resolution 须为 540p|720p，got {avatar.get('resolution')!r}")
    base = shot.get("_base_dir") or Path.cwd()
    for label, p in [("characters[0].ref_image", (chars[0].get("ref_image") if chars else None) or ""),
                     ("tts.clone_audio", tts.get("clone_audio")),
                     ("tts.audio_file", tts.get("audio_file"))]:
        if not p:
            continue
        try:
            rp = resolve_input(p, base)
            if not rp.is_relative_to(WORKSPACE_ROOT):
                errs.append(f"{label} 解析越出项目根: {rp}")
        except ValueError as e:
            errs.append(f"{label}: {e}")
    return (not errs), errs


def resolve_input(path_str: str, base: Path) -> Path:
    r"""shot 内相对路径以 shot 文件所在目录为基准；解析结果必须落在项目根内
    （允许 ..\数据\... 既有惯例，拒绝读项目外任意文件）。"""
    p = Path(path_str)
    rp = p if p.is_absolute() else (base / p).resolve()
    rp = rp.resolve()
    if not rp.is_relative_to(WORKSPACE_ROOT):
        raise ValueError(f"路径越出项目根: {rp}")
    return rp


# =====================================================================
# 2) ffprobe / 音频时长
# =====================================================================
def ffprobe_json(path: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败 {path}: {r.stderr[:300]}")
    return json.loads(r.stdout)


def probe_av(path: Path) -> dict:
    meta = ffprobe_json(path)
    streams = meta.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = float(meta.get("format", {}).get("duration") or 0)
    return {
        "path": str(path), "duration_s": round(dur, 3),
        "vcodec": (v or {}).get("codec_name"), "acodec": (a or {}).get("codec_name"),
        "width": (v or {}).get("width"), "height": (v or {}).get("height"),
        "fps": (v or {}).get("avg_frame_rate"), "has_audio": a is not None,
    }


# =====================================================================
# 3) TTS（stepaudio-2.5-tts，默认音色或克隆；design-seedaudio 备用）
# =====================================================================
def _sf_billing_units(text: str) -> int:
    """计费字符单元估算：汉字 1 字符、两字母 1 字符（stepfun_smoke pricing_doc）。
    估算值仅供成本参考；实扣以钱包端点差值为准（API 无逐调用账单，如实记录）。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return cjk + math.ceil(letters / 2)


def sf_clone_voice(client, clone_wav: Path, transcript: str, state: dict,
                   state_path: Path) -> tuple[str, dict]:
    """零样本克隆：/v1/files(purpose=storage) 上传 → /step_plan/v1/audio/voices → voice_id。
    按 clone 音频 sha256 缓存，避免重复建音色。返回 (voice_id, info)。"""
    key = sha256_file(clone_wav)
    cached = (state.setdefault("voice_clones", {}).get(key))
    if cached and cached.get("voice_id"):
        return cached["voice_id"], {"cached": True, "clone_sha256": key}
    files_url = f"{client.account_base}/files"
    with open(clone_wav, "rb") as f:
        # multipart 必须清掉 session 级 json Content-Type 让 requests 自算 boundary
        # （同 stepfun_client.image_edit 的处理，stepfun_client.py:207）
        r = client.session.post(files_url,
                                data={"purpose": "storage"},
                                files={"file": (clone_wav.name, f, "audio/wav")},
                                headers={"Content-Type": None},
                                timeout=max(client.timeout, 300))
    if r.status_code != 200:
        raise RuntimeError(f"/v1/files 上传失败 HTTP {r.status_code}: {r.text[:300]}")
    file_id = r.json().get("id")
    if not file_id:
        raise RuntimeError(f"/v1/files 未返回 id: {r.text[:300]}")
    r2 = client.session.post(f"{client.base}/audio/voices", json={
        "model": "stepaudio-2.5-tts", "file_id": file_id, "text": transcript or ""},
        timeout=max(client.timeout, 300))
    if r2.status_code != 200:
        raise RuntimeError(f"/audio/voices 失败 HTTP {r2.status_code}: {r2.text[:300]}")
    voice_id = r2.json().get("id") or r2.json().get("voice_id")
    if not voice_id:
        raise RuntimeError(f"/audio/voices 未返回 voice_id: {r2.text[:300]}")
    state["voice_clones"][key] = {"voice_id": voice_id, "created_at": now_iso(),
                                  "file_id": file_id}
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return voice_id, {"cached": False, "clone_sha256": key, "file_id": file_id}


def tts_stepfun(shot: dict, out_path: Path, state: dict, state_path: Path,
                client=None) -> dict:
    """StepFun stepaudio-2.5-tts：默认音色或克隆。返回 TTS 段元数据。"""
    tts_cfg = shot.get("tts") or {}
    client = client or sf.StepFunClient()
    text = (shot.get("audio") or {}).get("speech", "").strip()
    voice = tts_cfg.get("voice", "cixingnansheng")
    voice_source = "default"
    clone_info = None
    if tts_cfg.get("clone_audio"):
        clone_wav = resolve_input(tts_cfg["clone_audio"], shot["_base_dir"])
        if not clone_wav.is_file():
            raise FileNotFoundError(f"克隆音频不存在: {clone_wav}")
        voice, clone_info = sf_clone_voice(client, clone_wav,
                                           tts_cfg.get("clone_text", ""), state, state_path)
        voice_source = "cloned"
    t0 = time.time()
    res = client.tts(model=tts_cfg.get("model", "stepaudio-2.5-tts"), text=text,
                     voice=voice, out_path=out_path,
                     instruction=tts_cfg.get("instruction", "语速适中，口播风格，清晰亲和"))
    if not res.get("ok"):
        raise RuntimeError(f"StepFun TTS 失败: {json.dumps(res, ensure_ascii=False)[:400]}")
    av = probe_av(out_path)
    return {
        "engine": "stepfun", "model": tts_cfg.get("model", "stepaudio-2.5-tts"),
        "voice": voice, "voice_source": voice_source, "clone": clone_info,
        "instruction": tts_cfg.get("instruction"),
        "chars": len(text), "billing_units_est": _sf_billing_units(text),
        "price_doc": "¥5.8/万字符（估算口径，实扣以钱包差值为准）",
        "cost_cny_est": round(_sf_billing_units(text) * 5.8 / 10000, 4),
        "out_path": str(out_path), "sha256": sha256_file(out_path),
        "audio_duration_s": av["duration_s"], "acodec": av["acodec"],
        "elapsed_s": res.get("elapsed_s"), "total_elapsed_s": round(time.time() - t0, 1),
    }


def tts_design_seedaudio(shot: dict, out_path: Path) -> dict:
    """备用通道：MiniMax Design 网关 backend=seedaudio（必填 backend 勘误见数字人实验报告 §2.2；
    出站仅写死本机网关常量，免鉴权无密钥）。"""
    text = (shot.get("audio") or {}).get("speech", "").strip()
    tts_cfg = shot.get("tts") or {}
    filename = f"gen-avatar-{uuid.uuid4().hex[:8]}.mp3"
    body = {"prompt": text, "filename": filename, "backend": "seedaudio",
            "params": {"voice_id": tts_cfg.get("voice", "Chinese_wenrounvxing"),
                       "language_boost": "auto"},
            "source_tool": "vpipe:gen_avatar"}
    import requests
    t0 = time.time()
    r = requests.post(f"{DESIGN_GATEWAY}/api/generate/speech/submit", json=body, timeout=30)
    r.raise_for_status()
    task_id = r.json().get("task_id")
    if not task_id:
        raise RuntimeError(f"Design speech submit 未返回 task_id: {r.text[:300]}")
    while True:
        q = requests.get(f"{DESIGN_GATEWAY}/api/generate/tasks/{task_id}/query", timeout=30)
        q.raise_for_status()
        task = q.json()
        st = str(task.get("status"))
        if st in ("queued", "processing", "running"):
            if time.time() - t0 > 300:
                raise TimeoutError(f"Design TTS 轮询超时，最后状态 {task}")
            time.sleep(3)
            continue
        if st in ("failed", "cancelled"):
            raise RuntimeError(f"Design TTS {st}: {json.dumps(task.get('result') or task.get('error') or {}, ensure_ascii=False)[:400]}")
        if st == "succeeded":
            break
        raise RuntimeError(f"未知状态 {st}: {json.dumps(task, ensure_ascii=False)[:300]}")
    rel = str((task.get("result") or {}).get("path") or "")
    src = (DESIGN_WORKSPACE / rel).resolve()
    if not src.is_relative_to(DESIGN_WORKSPACE.resolve()):
        raise ValueError(f"工作区路径越界: {src}")
    if not src.is_file():
        raise FileNotFoundError(f"工作区产物不存在: {src}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out_path)
    av = probe_av(out_path)
    return {
        "engine": "design-seedaudio", "model": "seed-audio-1.0（backend=seedaudio）",
        "voice": tts_cfg.get("voice", "Chinese_wenrounvxing"), "voice_source": "preset",
        "chars": len(text), "billing_units_est": _sf_billing_units(text),
        "cost_cny_est": 0.0, "cost_note": "Design Pro 年会员 TTS 不计积分（数字人实验报告 §2.2）",
        "out_path": str(out_path), "sha256": sha256_file(out_path),
        "audio_duration_s": av["duration_s"], "acodec": av["acodec"],
        "elapsed_s": None, "total_elapsed_s": round(time.time() - t0, 1),
    }


# =====================================================================
# 4) Vidu 积分守卫 + avatar 生成
# =====================================================================
def vidu_pools() -> dict | None:
    """解析 /ent/v2/credits：通用池 general_remains / avatar 专属池 exclusive_remains。
    端点为非文档探测端点（vidu_avatar_client.balance），失败返回 None 如实降级。"""
    bal = vidu.balance()
    if not bal or "resp" not in (bal or {}):
        return None
    resp = bal["resp"] or {}

    def _first_remains(sec):
        arr = resp.get(sec) or []
        return int(arr[0].get("credit_remain", -1)) if arr else None

    return {"endpoint": bal.get("endpoint"),
            "general": _first_remains("general_remains"),
            "exclusive": _first_remains("exclusive_remains"),
            "probed_at": now_iso()}


def credit_guard(state: dict, credit_cap: int, est_credits: int, errors: list) -> bool:
    """双拦截（沿 gen_api exit 3 口径）：
    ① 通用池余额 < 预估 + 45（文档：余额<45 不能发起任务；offline_avatar 实扣走通用池，
       工程方案v3.1 §4.1 账面自洽）② 本轮累计已扣 + 预估 > credit-cap。"""
    pools = vidu_pools()
    if pools is None:
        errors.append("balance_probe_failed: /ent/v2/credits 探测失败，积分守卫降级"
                      "（创建只预检不扣费、失败不扣，风险受控）")
        return True
    spent = int(state.get("spent_credits_total", 0))
    gen = pools["general"]
    if gen is not None and gen < est_credits + MIN_VIDU_BALANCE:
        log(f"[guard] 通用池 {gen} < 预估 {est_credits}+{MIN_VIDU_BALANCE} → 拒绝（exit 3）")
        return False
    if spent + est_credits > credit_cap:
        log(f"[guard] 累计 {spent}+预估 {est_credits} > 上限 {credit_cap} → 拒绝（exit 3）")
        return False
    log(f"[guard] 通用池={gen} 专属池={pools['exclusive']} 预估={est_credits} "
        f"累计已扣={spent}/{credit_cap} → 放行")
    return True


def register_manifest(manifest_path: Path, entries: list):
    """asset_manifest 契约登记（与 qc_orch.manifest_register 同形；本模块不 import 兄弟模块，
    此处为契约 JSON 的独立实现）。entries=[{asset_id,kind,path,sha256,size_bytes,provenance?}]"""
    doc = {"schema_version": "1.0", "name": manifest_path.stem, "generated_at": now_iso(),
           "generator": MODULE_ID, "items": []}
    if manifest_path.exists():
        try:
            doc["items"] = json.loads(manifest_path.read_text(encoding="utf-8")).get("items", [])
        except Exception as e:
            log(f"[manifest] 旧表读取失败，重建：{e}")
    by_id = {it.get("asset_id"): i for i, it in enumerate(doc["items"])}
    for e in entries:
        rec = {"asset_id": e["asset_id"], "kind": e["kind"], "path": str(e["path"]),
               "sha256": e["sha256"], "size_bytes": int(e["size_bytes"]),
               "registered_at": now_iso()}
        for k in ("provenance", "probe", "evidence"):
            if e.get(k):
                rec[k] = e[k]
        if rec["asset_id"] in by_id:
            doc["items"][by_id[rec["asset_id"]]] = rec
        else:
            doc["items"].append(rec)
            by_id[rec["asset_id"]] = len(doc["items"]) - 1
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def run_avatar_shot(shot: dict, out_dir: Path, credit_cap: int = DEFAULT_CREDIT_CAP,
                    dry_run: bool = False, state_path: Path | None = None) -> dict:
    """主流程：校验 → （积分守卫）→ TTS → Vidu avatar → 暂存+元数据+manifest → qc_hint。"""
    errors: list[str] = []
    t0 = time.time()
    state_path = state_path or (out_dir / "avatar_state.json")
    out_dir.mkdir(parents=True, exist_ok=True)
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"state_read_failed: {e}")

    ok, verrs = validate_shot(shot)
    if not ok:
        raise ValueError("shot 校验失败: " + "; ".join(verrs))

    sid = shot["shot_id"]
    tts_cfg = shot.get("tts") or {}
    avatar_cfg = shot.get("avatar") or {}
    resolution = avatar_cfg.get("resolution", "720p")
    watermark = bool(avatar_cfg.get("watermark", False))

    ref_path = resolve_input(shot["characters"][0]["ref_image"], shot["_base_dir"])
    if not ref_path.is_file():
        raise FileNotFoundError(f"参考图不存在: {ref_path}")
    log(f"[shot] {sid} ref={ref_path.name} resolution={resolution} dry_run={dry_run}")

    # ---------- TTS（或直接用给定音频） ----------
    audio_path = out_dir / f"{sid}.tts_audio"
    if tts_cfg.get("audio_file"):
        src = resolve_input(tts_cfg["audio_file"], shot["_base_dir"])
        if not src.is_file():
            raise FileNotFoundError(f"tts.audio_file 不存在: {src}")
        shutil.copy2(src, audio_path.with_suffix(src.suffix))
        audio_path = audio_path.with_suffix(src.suffix)
        tts_meta = {"engine": "external", "out_path": str(audio_path),
                    "audio_duration_s": probe_av(audio_path)["duration_s"],
                    "sha256": sha256_file(audio_path),
                    "chars": len((shot.get("audio") or {}).get("speech") or "")}
    elif dry_run:
        chars = len((shot.get("audio") or {}).get("speech") or "")
        est = round(chars / CHARS_PER_SEC_EST, 1)
        tts_meta = {"engine": tts_cfg.get("engine", "stepfun"), "chars": chars,
                    "audio_duration_s_est": est,
                    "estimate_basis": f"{CHARS_PER_SEC_EST} 字/s（数字人实验报告 §2.1 实测）"}
        audio_path = None
    else:
        engine = tts_cfg.get("engine", "stepfun")
        suffix = ".mp3"
        if engine == "design-seedaudio":
            suffix = ".wav"
        ap = audio_path.with_suffix(suffix)
        tts_meta = (tts_design_seedaudio(shot, ap) if engine == "design-seedaudio"
                    else tts_stepfun(shot, ap, state, state_path))
        audio_path = Path(tts_meta["out_path"])
        log(f"[tts] {engine} → {audio_path.name} "
            f"dur={tts_meta['audio_duration_s']}s chars={tts_meta['chars']}")

    audio_dur = (tts_meta.get("audio_duration_s")
                 or tts_meta.get("audio_duration_s_est") or 0.0)
    est_credits = math.ceil(audio_dur) if audio_dur else 1

    # ---------- 积分守卫 ----------
    guard_pass = credit_guard(state, credit_cap, est_credits, errors)
    pools_before = vidu_pools() if not dry_run else None
    if not guard_pass:
        meta = {"module": MODULE_ID, "shot_id": sid, "generated_at": now_iso(),
                "status": "credit_guard_rejected", "est_credits": est_credits,
                "pools_before": pools_before, "errors": errors}
        (out_dir / f"{sid}__vidu_avatar.gen_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        raise SystemExit(3)

    # ---------- Vidu avatar ----------
    avatar_meta: dict = {"skipped": "dry_run"}
    if not dry_run:
        timeline = avatar_cfg.get("timeline")
        staging_name = f"{sid}_vidu.mp4"
        import re as _re
        if not _re.match(VIDU_STAGING_SAFE, staging_name):
            raise ValueError(f"暂存名不合 vidu 白名单: {staging_name}")
        clip_path = out_dir / f"{sid}@vidu-s1.mp4"
        rec = vidu.run(image=str(ref_path), audio=str(audio_path),
                       resolution=resolution, watermark=watermark,
                       timeline=timeline, out=staging_name,
                       timeout_s=1800, interval_s=5, log=log)
        if rec.get("state") != "success":
            raise RuntimeError(f"Vidu avatar 终态非 success: {json.dumps(rec, ensure_ascii=False)[:400]}")
        shutil.copy2(rec["file"], clip_path)          # 暂存区(数据/avatar_out) → 模块 out_dir
        avatar_meta = {
            "task_id": rec.get("task_id"), "state": rec.get("state"),
            "credits_reported": rec.get("credits"), "duration_s": rec.get("duration"),
            "model": rec.get("model"), "resolution": resolution, "watermark": watermark,
            "elapsed_s": rec.get("elapsed_s"),
            "staging_path": rec.get("file"),
            "url_note": "creations[].url 24h 有效，已即时落盘（工程方案v3.1 §8）",
            "clip_path": str(clip_path), "clip_sha256": sha256_file(clip_path),
            "clip_size_bytes": clip_path.stat().st_size,
        }
        # 逐任务记账 + 池差
        pools_after = vidu_pools()
        delta = None
        if pools_before and pools_after and pools_before["general"] is not None \
                and pools_after["general"] is not None:
            delta = {"general": pools_before["general"] - pools_after["general"],
                     "exclusive": ((pools_before["exclusive"] or 0) - (pools_after["exclusive"] or 0))
                     if pools_before["exclusive"] is not None and pools_after["exclusive"] is not None else None}
        spent_add = rec.get("credits")
        if spent_add is None and delta and delta["general"] is not None:
            spent_add = delta["general"]          # credits 字段缺失时以池差记账（如实标注来源）
        state.setdefault("tasks", []).append({
            "shot_id": sid, "task_id": rec.get("task_id"), "credits": spent_add,
            "credits_source": "task_field" if rec.get("credits") is not None else "pool_delta",
            "at": now_iso()})
        if isinstance(spent_add, int):
            state["spent_credits_total"] = int(state.get("spent_credits_total", 0)) + spent_add
        state["credit_cap"] = credit_cap
        state["pools_before"] = pools_before
        state["pools_after"] = pools_after
        state["pools_delta"] = delta
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        avatar_meta["pools_before"] = pools_before
        avatar_meta["pools_after"] = pools_after
        avatar_meta["pools_delta"] = delta

    # ---------- 成片探针 + 时长豁免对照 ----------
    clip_probe = probe_av(Path(avatar_meta["clip_path"])) if not dry_run else None
    expected = math.ceil(audio_dur) if audio_dur else None
    dur_check = None
    if clip_probe:
        gap = round(clip_probe["duration_s"] - audio_dur, 3)
        dur_check = {"mode": "avatar_ceil_exemption",
                     "expected_s": expected, "actual_s": clip_probe["duration_s"],
                     "pad_tail_s": gap,
                     "note": "整秒取整垫尾是平台行为非缺陷（工程方案v3.1 §3.1 L0 豁免行）"}

    # ---------- qc_orch 钩子 ----------
    rel_clip = f"{sid}@vidu-s1.mp4"
    qc_hint = {
        "j6v2_cmd": (f"python src/qc_detectors_v2.py --clip {rel_clip} "
                     f"--out {rel_clip}.qc2.json --params-yaml eval/thresholds.yaml"),
        "j6v2_protocol_extract": ("qc2.json 的 temporal_protocol 字段即六字段协议，抽出后可作 "
                                  "--judge-file J6v2=<protocol.json> 喂 qc_orch --online"),
        "qc_orch_cmd": (f"python src/qc_orch.py --online --clip-id {sid} --clip {rel_clip} "
                        f"--judge-file J6v2={sid}.j6v2_protocol.json "
                        f"--thresholds eval/thresholds.yaml"),
        "known_context": [
            "J6 ghosting 规则在口播数字人上 2/2 误报机理（低运动平台，工程方案v3.1 §3.4-1）",
            "单镜头直出无拼接 → 无 known_cuts 白名单需求（§3.4-2 机理仅拼接件触发）",
            "时序结论不作自动放行依据，人工抽检是放行口径（v3.1 §2.3 红线）",
        ],
        "gen_meta": f"{sid}__vidu_avatar.gen_meta.json",
    }

    # ---------- 成本换算 ----------
    dur_final = (clip_probe or {}).get("duration_s") or expected or audio_dur or 0.0
    credits_final = avatar_meta.get("credits_reported") or est_credits
    cost = {
        "vidu_credits": credits_final,
        "vidu_rule": "1 积分/s × ceil(音频秒)（工程方案v3.1 §2.4①）",
        "stepfun_cny_est": tts_meta.get("cost_cny_est"),
        "per_second": {
            "vidu_credits_per_s": round(credits_final / dur_final, 4) if dur_final else None,
            "cny_est_per_s": (round((tts_meta.get("cost_cny_est") or 0) / dur_final, 6)
                              if dur_final else None),
        },
        "wall_clock_s": round(time.time() - t0, 1),
        "note": "Vidu 积分与 MiniMax/人民币不可直接换算（工程方案v3.1 §4.2）",
    }

    meta = {
        "module": MODULE_ID, "shot_id": sid, "generated_at": now_iso(),
        "status": "dry_run" if dry_run else "ok",
        "shot_file": shot.get("_shot_file"), "shot_sha256": shot.get("_shot_sha256"),
        "ref_image": str(ref_path), "ref_image_sha256": sha256_file(ref_path),
        "speech_chars": len((shot.get("audio") or {}).get("speech") or ""),
        "tts": tts_meta, "avatar": avatar_meta, "clip_probe": clip_probe,
        "duration_check": dur_check, "cost": cost, "qc_hint": qc_hint,
        "credit_cap": credit_cap, "spent_credits_total": state.get("spent_credits_total"),
        "errors": errors,
    }
    meta_path = out_dir / f"{sid}__vidu_avatar.gen_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------- manifest 登记 ----------
    entries = [{"asset_id": f"shot:{sid}", "kind": "spec",
                "path": shot.get("_shot_file") or "", "sha256": shot.get("_shot_sha256") or "",
                "size_bytes": 0}]
    if audio_path and Path(audio_path).exists():
        entries.append({"asset_id": f"audio:{sid}", "kind": "audio",
                        "path": audio_path, "sha256": sha256_file(audio_path),
                        "size_bytes": Path(audio_path).stat().st_size,
                        "provenance": {"tts_engine": tts_meta.get("engine")}})
    if not dry_run:
        entries.append({"asset_id": f"{sid}@vidu-s1", "kind": "clip",
                        "path": avatar_meta["clip_path"], "sha256": avatar_meta["clip_sha256"],
                        "size_bytes": avatar_meta["clip_size_bytes"],
                        "provenance": {"module": MODULE_ID, "task_id": avatar_meta.get("task_id"),
                                       "model": avatar_meta.get("model")},
                        "probe": clip_probe})
    entries.append({"asset_id": f"gen_meta:{sid}", "kind": "gen_meta",
                    "path": meta_path, "sha256": sha256_file(meta_path),
                    "size_bytes": meta_path.stat().st_size})
    register_manifest(out_dir / "asset_manifest_avatar.json", entries)

    log(f"[done] {sid} status={meta['status']} credits={credits_final} "
        f"dur={dur_final}s wall={cost['wall_clock_s']}s → {meta_path}")
    return meta


# =====================================================================
# CLI
# =====================================================================
def load_shot(path: Path) -> dict:
    shot = json.loads(path.read_text(encoding="utf-8"))
    shot["_base_dir"] = path.resolve().parent
    shot["_shot_file"] = str(path.resolve())
    shot["_shot_sha256"] = sha256_file(path)
    return shot


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="G9a 口播专线：TTS→Vidu avatar→暂存+元数据→qc 钩子")
    ap.add_argument("--shot", help="shot JSON（VDL v2 草案超集字段，见模块 docstring）")
    ap.add_argument("--out-dir", default=str(VPIPE_ROOT / "out" / "avatar"))
    ap.add_argument("--credit-cap", type=int, default=DEFAULT_CREDIT_CAP,
                    help=f"本轮 Vidu 累计扣费上限（默认 {DEFAULT_CREDIT_CAP}，任务预算红线）")
    ap.add_argument("--state", default=None, help="预算 state 文件（默认 <out-dir>/avatar_state.json）")
    ap.add_argument("--validate-only", action="store_true", help="只校验 shot+文件存在，0 API 调用")
    ap.add_argument("--dry-run", action="store_true", help="校验+守卫+估时，不提交 avatar（TTS 不跑）")
    ap.add_argument("probe_cmd", nargs="?", choices=["probe"], help="探两把钱包（0 成本）")
    a = ap.parse_args(argv)

    if a.probe_cmd == "probe":
        pools = vidu_pools()
        try:
            acct = sf.StepFunClient().account()
        except Exception as e:
            acct = {"error": str(e)}
        print(json.dumps({"vidu_pools": pools, "stepfun_account": acct}, ensure_ascii=False, indent=1))
        return 0

    if not a.shot:
        ap.error("需要 --shot 或 probe")
    shot = load_shot(Path(a.shot))
    ok, errs = validate_shot(shot)
    ref = shot.get("characters", [{}])[0].get("ref_image")
    print(f"[validate] shot_id={shot.get('shot_id')} ok={ok} errs={errs}")
    if ref:
        rp = resolve_input(ref, shot["_base_dir"])
        print(f"[validate] ref_image={rp} exists={rp.is_file()}")
    clone = (shot.get("tts") or {}).get("clone_audio")
    if clone:
        cp = resolve_input(clone, shot["_base_dir"])
        print(f"[validate] clone_audio={cp} exists={cp.is_file()}")
    if not ok:
        return 2
    if a.validate_only:
        return 0

    out_dir = Path(a.out_dir)
    state_path = Path(a.state) if a.state else out_dir / "avatar_state.json"
    try:
        run_avatar_shot(shot, out_dir, credit_cap=a.credit_cap,
                        dry_run=a.dry_run, state_path=state_path)
    except SystemExit:
        raise
    except Exception as e:  # 失败如实记录，不吞
        sid = shot.get("shot_id", "unknown")
        out_dir.mkdir(parents=True, exist_ok=True)
        fp = out_dir / f"{sid}__vidu_avatar.gen_meta.json"
        fp.write_text(json.dumps({"module": MODULE_ID, "shot_id": sid,
                                  "generated_at": now_iso(), "status": "failed",
                                  "error": f"{type(e).__name__}: {e}"},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"[FAIL] {type(e).__name__}: {e} → 已写入 {fp}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
