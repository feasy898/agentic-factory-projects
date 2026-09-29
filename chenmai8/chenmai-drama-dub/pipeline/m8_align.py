"""M8 时长对齐（规划 §4 M8；T14 定案口径，【本机】零外部依赖，全离线可验收）。

职责（只读 ``04_dial`` C2、``06_mt`` C4、``05_cast`` C3；只写 ``07_synth``）：
逐句把 M6 的译文候选（3–5 条）对齐到 C2 原句时间窗 ±10%（C4.budget 的
lo/hi，即 M6 按 pipeline.yaml ``budget.lo_ratio/hi_ratio`` 从 C2 窗口算出的
预算窗）。四级阶梯（任务 T14 定案序）：

  ① syl2dur 估算占位（拟合延后）—— 每候选基准时长 base 直接消费 C4 的
    ``candidates[*].est_dur``（M6 以同一占位口径写入；est_dur=0 而 syl>0
    时按 ``m6_translate.count_syllables/estimate_dur_s`` 补算）。
    ``models/syl2dur.json`` 拟合表回填后经 M6 透传，本模块接口不变；
  ② 二分 duration_factor ∈ [0.5, 2.0]（C5 契约域）—— 对占位模型
    ``base × f`` 二分求解窗中心时长（≤10 轮），落窗即定值。该旋钮即
    合成引擎的语速参数，M7 按 C5 执行；
  ③ 仍超长/过短 → 换下一候选译文 —— 按 C4 顺序（M6 的 in-budget-first
    序）依序重试 ①→②，消费 M6 的 3–5 候选；换译后仍失败进入 ④；
  ④ 微调 atempo ∈ [0.9, 1.1] 收口 —— 全候选二分均差窗时，取残差最小
    候选的边界 duration_factor，用 ffmpeg atempo（变速不变调）微调落窗；
    仍不可解记 ``unresolved``（best-effort 参数照常落盘，供人工回看/
    审校台处理），对齐率统计如实计入未命中。

  ⑤ nonverbal 句 ``keep_original=true``（冻结规则 4）直接复用原人声、
    不合成；C4 缺失的句子同样 keep-original（缺译文时保留原声是正确的
    兜底），两类都在报告中单列口径。

出口：
  - C5 ``07_synth/synth_plan.<lang>.jsonl``（每语种一份 —— C5 schema 无
    语种字段而 utt_id 键唯一，多语种共用一个文件会互踩，故按 --lang 分
    文件；同时刷新无后缀 ``synth_plan.jsonl`` 为当前语种副本，保持规划
    §3 布局中的契约文件始终指向最近一次对齐的语种）；
  - ``07_synth/align_report.<lang>.json``（工作纸，非冻结契约：逐句决策
    + 汇总指标：对齐率/换译次数/atempo 占比/平均语速调整幅度）。

CLI（规划 §4 M8 冻结形态）：
    python -m pipeline.m8_align --ep ep01 --lang en
    python -m pipeline.m8_align --ep ep01 --lang en --jobs-dir <dir> [--min-align-rate 0.70]
退出码：0 成功且对齐率达标；1 输入/契约错误或对齐率不达标；2 用法错误。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pipeline import contracts as C
from pipeline.config import load_pipeline_config
from pipeline.m6_translate import (
    budget_for,
    char_id_for,
    estimate_dur_s,
    load_syl_table,
)
from pipeline.scaffold import ep_dir

__all__ = [
    "AlignParams",
    "AlignDecision",
    "AlignError",
    "estimate_base_dur",
    "predict_dur",
    "bisect_duration_factor",
    "atempo_close",
    "align_utterance",
    "align_episode",
    "main",
]


class AlignError(RuntimeError):
    """M8 时长对齐失败（输入缺失/契约校验失败等）。"""


#: C5 契约域内的二分默认参数（configs/pipeline.yaml ``m8`` 段可覆盖）
_DEFAULT_DF_RANGE = (0.5, 2.0)      # duration_factor（C5 冻结域）
_DEFAULT_ATEMPO_WINDOW = (0.9, 1.1)  # atempo 微调窗（任务 T14 口径）
_DEFAULT_ROUNDS = 10                 # 二分轮数（1.5/2^10 ≈ 1.5e-3 分辨率）


@dataclass(frozen=True)
class AlignParams:
    """M8 策略常量（C5 契约域内的可调项；来自 configs/pipeline.yaml ``m8`` 段）。"""

    df_lo: float = _DEFAULT_DF_RANGE[0]
    df_hi: float = _DEFAULT_DF_RANGE[1]
    atempo_lo: float = _DEFAULT_ATEMPO_WINDOW[0]
    atempo_hi: float = _DEFAULT_ATEMPO_WINDOW[1]
    bisect_rounds: int = _DEFAULT_ROUNDS
    engine: str = "dub-tts"
    emo_alpha_min: float = 0.5       # 情绪强度映射下界（M7 生产规则）
    emo_alpha_max: float = 0.85      # 情绪强度映射上界（M7 生产规则）
    emo_alpha_default: float = 0.7   # 无情绪标签时的 C5 缺省


def params_from_cfg(cfg: Optional[dict[str, Any]]) -> AlignParams:
    """configs/pipeline.yaml ``m8`` 段 → :class:`AlignParams`（缺项回落默认）。"""
    m8 = ((cfg or {}).get("m8") or {})
    df_range = m8.get("df_range") or list(_DEFAULT_DF_RANGE)
    atempo = m8.get("atempo_window") or list(_DEFAULT_ATEMPO_WINDOW)
    return AlignParams(
        df_lo=float(df_range[0]),
        df_hi=float(df_range[1]),
        atempo_lo=float(atempo[0]),
        atempo_hi=float(atempo[1]),
        bisect_rounds=int(m8.get("bisect_rounds", _DEFAULT_ROUNDS)),
        engine=str(m8.get("engine", "dub-tts")),
    )


@dataclass
class AlignDecision:
    """单句对齐决策（报告口径 + C5 计划项）。"""

    utt_id: str
    # 决策
    status: str                    # in-budget | df-bisect | switch-df | atempo-final | keep-original | no-translation | unresolved
    cand_idx: Optional[int]        # 采用的 C4 候选下标（None=无译文）
    switched: bool                 # 是否发生过换译（用了 0 号候选以外的候选）
    text: str                      # 采用的台词（keep-original/no-translation 时为原句文本）
    est_dur: float                 # 采用候选的 syl2dur 基准时长（占位）
    duration_factor: float         # C5：合成引擎语速参数
    atempo: float                  # C5：最终微调（ffmpeg atempo）
    pred_dur: float                # 预测落盘时长 = est × df / atempo（= C5 expect_dur）
    window: tuple[float, float]    # (lo, hi) 目标窗
    # C5 合成项
    item: C.SynthPlanItem


# ---------------------------------------------------------------------------
# ① syl2dur 占位估长与预测模型
# ---------------------------------------------------------------------------

def estimate_base_dur(
    cand: C.Candidate, *, lang: str, rates: Optional[dict[str, float]] = None
) -> float:
    """候选基准时长：优先 C4 的 est_dur；为 0 而 syl>0 时按占位规则补算。

    ``models/syl2dur.json`` 拟合表回填后由 M6 透传进 C4，本函数只兜底
    （占位口径延后统一，见 training-plan §1.3）。
    """
    if cand.est_dur > 0:
        return round(cand.est_dur, 3)
    if cand.syl > 0:
        return estimate_dur_s(cand.syl, lang, rates)
    return 0.0


def predict_dur(base: float, duration_factor: float, atempo: float) -> float:
    """占位预测：合成时长 = base × duration_factor，再经 atempo 微调。

    atempo 是 ffmpeg 变速不变调滤镜参数（>1 加速、<1 减速），故时长先乘
    语速系数再除以 atempo。保留 3 位小数（冻结规则 1）。
    """
    return round(base * duration_factor / atempo, 3)


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


# ---------------------------------------------------------------------------
# ② 二分 duration_factor
# ---------------------------------------------------------------------------

def bisect_duration_factor(
    base: float,
    target: float,
    lo: float,
    hi: float,
    p: AlignParams,
) -> Optional[float]:
    """二分求解 ``base × f = target`` 中的 f ∈ [df_lo, df_hi]（合成语速系数）。

    目标时长 target 取窗中心（orig_dur，C4 预算窗已保证 lo ≤ orig ≤ hi；
    预算异常时 target 会被夹到可达域内，最终以落窗复核为准）。可行性：
    base×df_lo ≤ hi 且 base×df_hi ≥ lo（否则最快/最慢都出窗）。落定前用
    3 位小数值复核 ``lo ≤ base × f ≤ hi``，不满足返回 None（进入 ③/④）。
    """
    if base <= 0 or base * p.df_lo > hi or base * p.df_hi < lo:
        return None
    t = _clamp(target, base * p.df_lo, base * p.df_hi)
    a, b = p.df_lo, p.df_hi
    for _ in range(max(0, int(p.bisect_rounds))):
        m = 0.5 * (a + b)
        if base * m < t:
            a = m
        else:
            b = m
    f = round(_clamp(0.5 * (a + b), p.df_lo, p.df_hi), 3)
    return f if lo <= base * f <= hi else None


# ---------------------------------------------------------------------------
# ④ atempo 微调收口
# ---------------------------------------------------------------------------

def atempo_close(
    base: float,
    target: float,
    lo: float,
    hi: float,
    p: AlignParams,
) -> Optional[float]:
    """边界 duration_factor + atempo ∈ [atempo_lo, atempo_hi] 收口。

    过长取最快 df_lo、过短取最慢 df_hi 得 d = base × edge；atempo 可达
    时长域为 [d/atempo_hi, d/atempo_lo]，与 [lo, hi] 有交才可解，
    取交集中最接近窗中心的一个。返回 atempo（已复核落窗）或 None。
    仅当 ② 对全部候选失败后调用（任务 T14 的收口位）。
    """
    if base <= 0:
        return None
    if base * p.df_lo > hi:
        edge = p.df_lo
    elif base * p.df_hi < lo:
        edge = p.df_hi
    else:
        return None  # 落窗可行却仍被调用（调用方逻辑不应如此）——如实不解
    d = base * edge
    a_lo = max(p.atempo_lo, d / hi)
    a_hi = min(p.atempo_hi, d / lo)
    if a_lo > a_hi:
        return None
    a = round(_clamp(d / target, a_lo, a_hi), 3)
    return a if lo <= d / a <= hi else None


# ---------------------------------------------------------------------------
# 单句对齐（②→③→④ 阶梯 + ⑤ keep-original）
# ---------------------------------------------------------------------------

def _resolve_voice_ref(
    root: Path, char_id: str, cast: dict[str, C.Character]
) -> str:
    """C5 voice_ref：C3 角色卡的音色参考；缺卡回落 M6 暂定槽位路径。

    与 M6 ``draft_cast_from_utterances`` 的暂定卡口径一致
    （``05_cast/voicebank/<char_id>_ref.wav``，文件由人工/M5 后续放入）。
    """
    ch = cast.get(char_id)
    if ch is not None:
        return ch.voice_ref
    return f"05_cast/voicebank/{char_id}_ref.wav"


def _emo_alpha(u: C.Utterance, p: AlignParams) -> float:
    """情绪强度 → emo_alpha 映射（M7 生产规则：score × [0.5, 0.85]）。"""
    if u.emo is None or u.emo.score is None:
        return round(p.emo_alpha_default, 3)
    span = p.emo_alpha_max - p.emo_alpha_min
    alpha = p.emo_alpha_min + span * min(max(u.emo.score, 0.0), 1.0)
    return round(_clamp(alpha, p.emo_alpha_min, p.emo_alpha_max), 3)


def align_utterance(
    u: C.Utterance,
    row: Optional[C.Translation],
    *,
    cast: dict[str, C.Character],
    root: Path,
    lang: str,
    params: AlignParams,
    lo_ratio: float,
    hi_ratio: float,
    rates: Optional[dict[str, float]] = None,
) -> AlignDecision:
    """单句：候选阶梯（②→③→④）+ ⑤ keep-original → 决策（含 C5 计划项）。"""
    if row is not None:
        budget = row.budget
    else:  # C4 缺行（未翻译）：按 C2 窗 × 预算比自算，作 keep-original 兜底
        budget = budget_for(u, lo_ratio, hi_ratio)
    lo, hi = budget.lo, budget.hi
    target = _clamp(budget.orig_dur, lo, hi)

    char_id = char_id_for(u)
    voice_ref = _resolve_voice_ref(root, char_id, cast)
    emo_ref_path = root / "04_dial" / "emo_refs" / f"{u.utt_id}.wav"
    # 情绪参考（M4 产出口径）存在才写入 C5 —— 缺文件时 M7 无从取用，如实留空
    emo_ref = emo_ref_path.relative_to(root).as_posix() if emo_ref_path.is_file() else None
    emo_alpha = _emo_alpha(u, params)
    out = f"07_synth/wavs/{u.utt_id}.wav"

    def keep(text: str, status: str) -> AlignDecision:
        """keep-original / no-translation：不合成，expect_dur=原句窗长。"""
        item = C.SynthPlanItem(
            utt_id=u.utt_id, engine=params.engine, voice_ref=voice_ref,
            emo_ref=emo_ref, emo_alpha=emo_alpha, duration_factor=1.0,
            atempo=1.0, text=text, out=out,
            expect_dur=round(budget.orig_dur, 3), keep_original=True,
        )
        return AlignDecision(
            utt_id=u.utt_id, status=status, cand_idx=None, switched=False,
            text=text, est_dur=0.0, duration_factor=1.0, atempo=1.0,
            pred_dur=round(budget.orig_dur, 3), window=(lo, hi), item=item,
        )

    # ⑤ nonverbal（哭/尖叫）：冻结规则 4，直接复用原人声
    if u.nonverbal:
        return keep(u.text, "keep-original")
    if row is None or not row.candidates:
        return keep(u.text, "no-translation")

    # ②→③→④ 候选阶梯（status=in-budget 直接落窗 / df-bisect 二分落窗 /
    # atempo-final 收口落窗；换译与否由 switched 与 cand_idx 记录）
    best_residual: Optional[tuple[float, int, float]] = None  # (残差, cand_idx, base)
    for idx, cand in enumerate(row.candidates):
        base = estimate_base_dur(cand, lang=lang, rates=rates)
        if base <= 0:
            continue
        # ① 候选直接落窗：df=1.0/atempo=1.0，零调整
        if lo <= base <= hi:
            return _synth_decision(u, idx, idx > 0, cand.text, base, 1.0, 1.0,
                                   base, (lo, hi), "in-budget", params,
                                   voice_ref, emo_ref, emo_alpha, out)
        # ② 二分 duration_factor
        f = bisect_duration_factor(base, target, lo, hi, params)
        if f is not None:
            pred = predict_dur(base, f, 1.0)
            return _synth_decision(u, idx, idx > 0, cand.text, base, f, 1.0,
                                   pred, (lo, hi), "df-bisect", params,
                                   voice_ref, emo_ref, emo_alpha, out)
        # ④ 前置：记录残差最小候选（atempo 收口候选，③ 全败后才用）
        d = base * (params.df_lo if base * params.df_lo > hi else params.df_hi)
        residual = d - hi if d > hi else lo - d
        if best_residual is None or residual < best_residual[0]:
            best_residual = (residual, idx, base)

    # ③ 全候选二分失败 → ④ atempo 收口（取残差最小候选）
    if best_residual is not None:
        _, idx, base = best_residual
        cand = row.candidates[idx]
        a = atempo_close(base, target, lo, hi, params)
        if a is not None:
            edge = params.df_lo if base * params.df_lo > hi else params.df_hi
            pred = predict_dur(base, edge, a)
            return _synth_decision(u, idx, idx > 0, cand.text, base, edge, a,
                                   pred, (lo, hi), "atempo-final", params,
                                   voice_ref, emo_ref, emo_alpha, out)

    # 仍不可解：best-effort（残差最小候选 + 边界参数），如实记 unresolved
    if best_residual is not None:
        _, idx, base = best_residual
        cand = row.candidates[idx]
        edge = params.df_lo if base * params.df_lo > hi else params.df_hi
        edge = params.df_hi if base * params.df_hi < lo else edge
        pred = predict_dur(base, edge, 1.0)
        return _synth_decision(u, idx, idx > 0, cand.text, base, edge, 1.0,
                               pred, (lo, hi), "unresolved", params, voice_ref,
                               emo_ref, emo_alpha, out)
    # 所有候选 est 均为 0（空译法）：按无译文兜底
    return keep(u.text, "no-translation")


def _synth_decision(
    u: C.Utterance,
    cand_idx: int,
    switched: bool,
    text: str,
    base: float,
    duration_factor: float,
    atempo: float,
    pred: float,
    window: tuple[float, float],
    status: str,
    p: AlignParams,
    voice_ref: str,
    emo_ref: Optional[str],
    emo_alpha: float,
    out: str,
) -> AlignDecision:
    """构造「合成」决策与 C5 计划项（对齐成功/unresolved 共用）。"""
    item = C.SynthPlanItem(
        utt_id=u.utt_id, engine=p.engine, voice_ref=voice_ref,
        emo_ref=emo_ref, emo_alpha=emo_alpha,
        duration_factor=duration_factor, atempo=atempo,
        text=text, out=out, expect_dur=round(pred, 3), keep_original=False,
    )
    return AlignDecision(
        utt_id=u.utt_id, status=status, cand_idx=cand_idx, switched=switched,
        text=text, est_dur=round(base, 3), duration_factor=duration_factor,
        atempo=atempo, pred_dur=round(pred, 3), window=window, item=item,
    )


# ---------------------------------------------------------------------------
# 整集对齐主流程
# ---------------------------------------------------------------------------

def _write_json_atomic(path: Path, payload: Any) -> None:
    """单文档 JSON 原子写（与 M6/m5 同口径：tmp + os.replace）。"""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n",
    )
    os.replace(tmp, path)


def _synth_plan_name(lang: str) -> tuple[str, str]:
    """C5 文件名：(分语种主文件, 无后缀当前语种副本)。"""
    return f"synth_plan.{lang}.jsonl", "synth_plan.jsonl"


def align_episode(
    ep: str,
    lang: str,
    *,
    jobs_dir: str | Path,
    cfg: Optional[dict[str, Any]] = None,
    syl_table: Optional[Path] = None,
    params: Optional[AlignParams] = None,
) -> dict[str, Any]:
    """整集时长对齐主流程：C2+C4(+C3) → C5 合成计划 + 对齐报告。

    返回摘要 dict（句数/各状态计数/对齐率/atempo 占比/平均语速调整幅度/
    未解句清单/产物路径），供 CLI 与 eval 断言。
    """
    cfg = cfg if cfg is not None else load_pipeline_config()
    p = params if params is not None else params_from_cfg(cfg)
    budget_cfg = cfg.get("budget") or {}
    lo_ratio = float(budget_cfg.get("lo_ratio", 0.9))
    hi_ratio = float(budget_cfg.get("hi_ratio", 1.1))

    root = ep_dir(ep, jobs_dir)
    utt_path = root / "04_dial" / "utterances.jsonl"
    if not utt_path.is_file():
        raise AlignError(
            f"C2 不存在: {utt_path}（先跑 M2/M4 产出 04_dial/utterances.jsonl）"
        )
    utterances = C.load_jsonl(utt_path, C.UtteranceTable).root
    if not utterances:
        raise AlignError(f"C2 为空: {utt_path}")

    trans_path = root / "06_mt" / "translations.jsonl"
    rows: list[C.Translation] = []
    if trans_path.is_file():
        rows = [r for r in C.load_jsonl(trans_path, C.TranslationTable).root
                if r.tgt == lang]
    by_utt: dict[str, C.Translation] = {r.utt_id: r for r in rows}

    cast_path = root / "05_cast" / "characters.json"
    cast: dict[str, C.Character] = (
        dict(C.load_model(cast_path, C.CastBook).root) if cast_path.is_file() else {}
    )
    rates = load_syl_table(syl_table)

    decisions: list[AlignDecision] = []
    for u in utterances:
        decisions.append(
            align_utterance(
                u, by_utt.get(u.utt_id),
                cast=cast, root=root, lang=lang, params=p,
                lo_ratio=lo_ratio, hi_ratio=hi_ratio, rates=rates,
            )
        )

    # C5 写盘：分语种主文件（upsert：同 utt_id 替换，重跑不重复）+ 无后缀副本
    synth_dir = root / "07_synth"
    synth_dir.mkdir(parents=True, exist_ok=True)
    main_name, copy_name = _synth_plan_name(lang)
    main_path, copy_path = synth_dir / main_name, synth_dir / copy_name
    items = [d.item for d in decisions]
    C.upsert_jsonl(main_path, items, container=C.SynthPlanTable,
                   key_field="utt_id")
    C.dump_jsonl(copy_path, C.SynthPlanTable.model_validate(
        [line for line in C.load_jsonl(main_path, C.SynthPlanTable).root]
    ))

    # 汇总指标（计划 §4 M8 冻结线口径：对齐率 = ±10% 命中占比）
    n_total = len(decisions)
    statuses = [d.status for d in decisions]
    n_keep = statuses.count("keep-original")
    n_no_trans = statuses.count("no-translation")
    n_synth = n_total - n_keep - n_no_trans
    aligned_ids = [
        d.utt_id for d in decisions
        if d.window[0] <= d.pred_dur <= d.window[1]
    ]
    n_atempo = statuses.count("atempo-final")
    synth_speeds = [
        max(d.atempo / d.duration_factor, d.duration_factor / d.atempo)
        for d in decisions
        if d.status not in ("keep-original", "no-translation")
    ]
    unresolved = [d.utt_id for d in decisions if d.status == "unresolved"]
    report = {
        "ep": ep,
        "lang": lang,
        "module": "m8_align",
        "generated_by": "m8",
        "policy": {
            "df_range": [p.df_lo, p.df_hi],
            "atempo_window": [p.atempo_lo, p.atempo_hi],
            "bisect_rounds": p.bisect_rounds,
            "engine": p.engine,
            "syl2dur_placeholder": True,
            "syl_table": str(syl_table) if syl_table else None,
        },
        "summary": {
            "n_total": n_total,
            "n_synth": n_synth,
            "n_keep_original": n_keep,
            "n_no_translation": n_no_trans,
            "n_in_budget": statuses.count("in-budget"),
            "n_df": statuses.count("df-bisect"),
            "n_switch": sum(1 for d in decisions if d.switched),
            "n_atempo": n_atempo,
            "n_unresolved": len(unresolved),
            "n_aligned": len(aligned_ids),
            "alignment_rate": round(len(aligned_ids) / n_total, 3) if n_total else 0.0,
            "atempo_ratio": round(n_atempo / n_synth, 3) if n_synth else 0.0,
            "mean_speed_adj": (
                round(sum(synth_speeds) / len(synth_speeds), 3)
                if synth_speeds else 0.0
            ),
            "unresolved": unresolved,
        },
        "items": [
            {
                "utt_id": d.utt_id,
                "status": d.status,
                "cand_idx": d.cand_idx,
                "switched": d.switched,
                "text": d.text,
                "est_dur": d.est_dur,
                "duration_factor": d.duration_factor,
                "atempo": d.atempo,
                "pred_dur": d.pred_dur,
                "window": list(d.window),
                "voice_ref": d.item.voice_ref,
                "emo_ref": d.item.emo_ref,
                "out": d.item.out,
            }
            for d in decisions
        ],
        "notes": (
            "align_report.<lang>.json 为 M8 工作纸（非冻结契约）：status=in-budget"
            "（候选直接落窗，df=1.0）/df-bisect（duration_factor 二分落窗）"
            "/atempo-final（边界语速 + atempo 收口）/keep-original（nonverbal 复用原声）"
            "/no-translation（缺 C4 兜底原声）/unresolved（best-effort 落盘，未命中"
            " ±10% 窗）；换译与否以 switched/cand_idx 记录（消费 M6 的 3–5 候选）。"
            "mean_speed_adj=合成句变速幅度 max(atempo/df, df/atempo) 均值（离线刻意"
            "超长语料会显著高于规划 §4 的 1.06 参考线——该线针对真实 M6 输出质量语料）。"
        ),
    }
    report_path = synth_dir / f"align_report.{lang}.json"
    _write_json_atomic(report_path, report)

    return {
        "ep": ep,
        "lang": lang,
        "n_total": n_total,
        "n_synth": n_synth,
        "n_keep_original": n_keep,
        "n_no_translation": n_no_trans,
        "n_in_budget": report["summary"]["n_in_budget"],
        "n_df": report["summary"]["n_df"],
        "n_switch": report["summary"]["n_switch"],
        "n_atempo": n_atempo,
        "n_unresolved": len(unresolved),
        "alignment_rate": report["summary"]["alignment_rate"],
        "atempo_ratio": report["summary"]["atempo_ratio"],
        "mean_speed_adj": report["summary"]["mean_speed_adj"],
        "unresolved_utts": unresolved,
        "synth_plan_jsonl": str(main_path),
        "synth_plan_copy": str(copy_path),
        "report_json": str(report_path),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.m8_align",
        description="M8 时长对齐：syl2dur 占位 → duration_factor 二分 → 换译 → atempo 收口（输出 C5 合成计划）",
    )
    parser.add_argument("--ep", required=True, help="集 ID，如 ep01")
    parser.add_argument("--lang", default="en", help="目标语种（en/es/ar）")
    parser.add_argument("--jobs-dir", default=None,
                        help="jobs 根目录（默认取 configs/pipeline.yaml paths.jobs_dir）")
    parser.add_argument("--syl-table", default=None,
                        help="models/syl2dur.json 拟合表路径（缺省按 pipeline.yaml models_dir）")
    parser.add_argument("--min-align-rate", type=float, default=None,
                        help="全片对齐率（±10% 命中）通过线（默认取 pipeline.yaml m8.min_align_rate_mvp）")
    args = parser.parse_args(argv)

    cfg = load_pipeline_config()
    jobs_root = Path(args.jobs_dir) if args.jobs_dir else Path(cfg["paths"]["jobs_dir"])
    syl_table = (
        Path(args.syl_table) if args.syl_table
        else Path(cfg["paths"]["models_dir"]) / "syl2dur.json"
    )
    if args.min_align_rate is not None:
        min_rate = args.min_align_rate
    else:
        min_rate = float(((cfg.get("m8") or {}).get("min_align_rate_mvp", 0.70)))
    try:
        summary = align_episode(
            args.ep, args.lang, jobs_dir=jobs_root, cfg=cfg, syl_table=syl_table,
        )
    except (AlignError, ValueError, OSError) as exc:  # CLI 统一归一（含契约校验）
        print(f"FAIL m8_align: {exc}")
        return 1

    extra = []
    if summary["n_keep_original"]:
        extra.append(f"keep_original={summary['n_keep_original']}")
    if summary["n_no_translation"]:
        extra.append(f"no_translation={summary['n_no_translation']}")
    print(
        f"OK m8_align ep={summary['ep']} lang={summary['lang']} "
        f"utts={summary['n_total']} synth={summary['n_synth']} "
        f"aligned={summary['alignment_rate']:.3f} (min {min_rate:.2f}) "
        f"in_budget={summary['n_in_budget']} df={summary['n_df']} "
        f"switch={summary['n_switch']} atempo={summary['n_atempo']} "
        f"unresolved={summary['n_unresolved']}"
        + (f" [{', '.join(extra)}]" if extra else "")
    )
    print(f"  atempo 占比={summary['atempo_ratio']:.3f} "
          f"平均语速调整幅度={summary['mean_speed_adj']:.3f}")
    if summary["unresolved_utts"]:
        print(f"  WARN 未命中 ±10% 窗: {summary['unresolved_utts']}")
    print(f"  合成计划: {summary['synth_plan_jsonl']}")
    print(f"  当前语种副本: {summary['synth_plan_copy']}")
    print(f"  对齐报告: {summary['report_json']}")

    if summary["alignment_rate"] < min_rate:
        print(f"FAIL m8_align: 对齐率 {summary['alignment_rate']:.3f} "
              f"低于通过线 {min_rate:.3f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
