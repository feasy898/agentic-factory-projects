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


def candidate_passed(cand: dict) -> bool:
    gates = cand.get("gates") or {}
    return all(bool(gates[g].get("passed")) for g in GATE_IDS if g in gates) and len(gates) == len(GATE_IDS)


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

    retry_max = int(card.get("retry_max", 0))
    if attempts_used < retry_max:
        return {"action": "retry", "round": attempts_used + 1, "hint": retry_hint(attempts_used + 1)}

    fb = card.get("fallback") or {}
    if fb.get("asset") and exists(fb["asset"]):
        return {"action": "fallback"}

    return {"action": "blocked", "reason": "全部候选未通过且 fallback.asset 缺失, 无法降级"}
