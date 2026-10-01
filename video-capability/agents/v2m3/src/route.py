"""路由与降级 (SPECS §5.5) — 纯逻辑, 每条分支可单测。

n_best 候选全过六门禁 → 有 pass 取 overall_score 最高;
全 fail → 换 seed 重试 ≤retry_max 轮(加强 negative / guidance -0.5 钩子);
仍 fail → fallback=ken_burns(校验 fallback.asset 存在);
源图缺失 → blocked。
"""

from __future__ import annotations

import os

from .gates import GATE_IDS

# 重试钩子: 每轮追加的 negative 词与 guidance 调整
RETRY_NEGATIVE_EXTRA = {
    1: ["blurry", "lowres", "jpeg artifacts", "distorted", "melted"],
    2: ["worst quality", "low quality", "watermark", "oversaturated", "warping", "extra limbs"],
}
RETRY_GUIDANCE_DELTA = -0.5

# stable-borderline 短路 (M5 校准; M2 实测: S08/S09/S11 重试耗 34/59=58% 生成量 0 收益,
# 同镜头 G5 分数逐 seed 恒定 ±0.01, 属确定性 borderline, 换 seed 重试无效):
# 同镜头已有 ≥2 候选且全部非 pass 且 overall 分数极差 <0.02 → 判定为稳定失败,
# 跳过剩余重试直接 fallback, 省预算。
BORDERLINE_MIN_CANDIDATES = 2
BORDERLINE_SPREAD = 0.02


def candidate_passed(cand: dict) -> bool:
    """六门禁全过才算 pass; gate_json 中的 v2 增补键(G7)只查 passed、不计入六门禁数量。"""
    gates = cand.get("gates") or {}
    present = [g for g in GATE_IDS if g in gates]
    ok = all(bool(gates[g].get("passed")) for g in present) and len(present) == len(GATE_IDS)
    g7 = gates.get("G7")
    if g7 is not None and not bool(g7.get("passed", True)):
        ok = False
    return ok


def is_stable_borderline(candidates: list[dict]) -> bool:
    """≥2 候选全部非 pass 且 overall_score 极差 < BORDERLINE_SPREAD → 稳定失败(短路条件)。"""
    if len(candidates) < BORDERLINE_MIN_CANDIDATES:
        return False
    if any(candidate_passed(c) for c in candidates):
        return False
    scores = [float(c.get("overall_score") or 0.0) for c in candidates]
    return (max(scores) - min(scores)) < BORDERLINE_SPREAD


def pick_best(candidates: list[dict]) -> dict:
    """取 overall_score 最高者; Python max 并列时返回先出现者(稳定)。"""
    return max(candidates, key=lambda c: (c.get("overall_score") or 0.0))


def retry_hint(round_no: int) -> dict:
    """重试参数钩子: 加强 negative + guidance -0.5。"""
    extra = RETRY_NEGATIVE_EXTRA.get(round_no, RETRY_NEGATIVE_EXTRA[max(RETRY_NEGATIVE_EXTRA)])
    return {"round": round_no, "negative_extra": list(extra), "guidance_delta": RETRY_GUIDANCE_DELTA}


def check_assets(card: dict, exists=os.path.exists) -> str | None:
    """源资产检查; 返回 blocked 原因或 None。"""
    if not card.get("first_frame_asset") or not exists(card["first_frame_asset"]):
        return f"源图缺失: first_frame_asset 不存在 ({card.get('first_frame_asset')})"
    if card.get("lane") == "evidence_transfer":
        ea = card.get("evidence_asset")
        if not ea or not exists(ea):
            return f"证据源缺失: evidence_asset 不存在 ({ea}) (SPECS_V2 §5.4)"
    fb = card.get("fallback") or {}
    if fb.get("asset") and not exists(fb["asset"]):
        return f"降级源图缺失: fallback.asset 不存在 ({fb.get('asset')})"
    return None


def route_shot(
    card: dict,
    candidates: list[dict],
    attempts_used: int,
    exists=os.path.exists,
) -> dict:
    """路由决策。

    candidates: [{candidate_id?, seed?, gates: {G1..G6: {passed,...}}, overall_score: float}, ...]
    返回 action ∈ {accept, retry, fallback, blocked}。
    """
    blocked_reason = check_assets(card, exists=exists)
    if blocked_reason:
        return {"action": "blocked", "reason": blocked_reason}

    passing = [c for c in candidates if candidate_passed(c)]
    if passing:
        return {"action": "accept", "candidate": pick_best(passing)}

    # stable-borderline 短路: 全部非 pass 且分数极差 <0.02 → 重试注定无效, 直接 fallback/择优
    if is_stable_borderline(candidates):
        fb = card.get("fallback") or {}
        scores = [float(c.get("overall_score") or 0.0) for c in candidates]
        detail = {"short_circuit": "stable_borderline", "n_candidates": len(candidates),
                  "spread": round(max(scores) - min(scores), 4),
                  "best_overall": round(max(scores), 4),
                  "retry_rounds_saved": max(0, int(card.get("retry_max", 0)) - attempts_used)}
        if fb.get("asset") and exists(fb["asset"]):
            return {"action": "fallback", **detail}
        return {"action": "blocked", "reason": "stable-borderline 短路命中但 fallback.asset 缺失", **detail}

    retry_max = int(card.get("retry_max", 0))
    if attempts_used < retry_max:
        return {"action": "retry", "round": attempts_used + 1, "hint": retry_hint(attempts_used + 1)}

    fb = card.get("fallback") or {}
    if fb.get("asset") and exists(fb["asset"]):
        return {"action": "fallback"}

    return {"action": "blocked", "reason": "全部候选未通过且 fallback.asset 缺失, 无法降级"}
