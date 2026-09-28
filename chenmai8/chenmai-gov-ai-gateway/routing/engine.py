"""路由策略引擎（开发指令 §5.2 决策矩阵，纯函数；v0 覆盖规则层可产出的命中类别）。

优先级冻结：BLOCK > GOVCLOUD > INTERNET。

v0 口径：
- BLOCK：CLASSIFICATION_MARK / INJECTION 命中（v0 规则只产出前者）；
- GOVCLOUD：WORK_SECRET / SENSITIVE_ATTR（v0 规则暂不产出，逻辑先行）或
  ID_CARD/BANK_CARD 同请求 ≥ 阈值（批量名单，BATCH_STRUCTURED_PII）；
- INTERNET：单个结构化 PII（mask_required=true）或无命中/仅白名单。

矩阵全格用例与冲突用例由 M4 任务补全（evals.m4_routing）。
"""
from __future__ import annotations

from recognizers.models import EntityClass, Finding
from routing.models import RouteDecision, RouteReason

#: 批量名单计数类别（§5.2 决策矩阵：ID_CARD/BANK_CARD 同请求 ≥3 个）
BATCH_PII_TYPES: frozenset[EntityClass] = frozenset({EntityClass.ID_CARD, EntityClass.BANK_CARD})

#: 即便已脱敏也切政务云的类别（§5.2：WORK_SECRET 或 SENSITIVE_ATTR）
GOVCLOUD_TYPES: frozenset[EntityClass] = frozenset({EntityClass.WORK_SECRET, EntityClass.SENSITIVE_ATTR})

#: 命中即拦截的类别（§5.2：CLASSIFICATION_MARK、INJECTION）
BLOCK_TYPES: frozenset[EntityClass] = frozenset({EntityClass.CLASSIFICATION_MARK, EntityClass.INJECTION})


def decide(
    findings: list[Finding],
    *,
    upstream_for: dict[str, str],
    batch_pii_min: int = 3,
) -> RouteDecision:
    """决策矩阵纯函数：findings + 上游名映射 → RouteDecision（无副作用、可独立测试）。

    ``upstream_for`` 形如 ``{"INTERNET": "internet_mock", "GOVCLOUD": "govcloud_local"}``，
    由网关按 config/app.yaml 构建；BLOCK 时 upstream 必为 null（契约校验兜底）。
    """
    active = [f for f in findings if not f.whitelisted]
    reasons: list[RouteReason] = []

    block_hits = [f for f in active if f.type in BLOCK_TYPES or f.action_hint == "BLOCK_FLAG"]
    gov_hits = [f for f in active if f.type in GOVCLOUD_TYPES]
    batch_count = sum(1 for f in active if f.type in BATCH_PII_TYPES)
    mask_hits = [f for f in active if f.action_hint == "MASK"]

    if block_hits:
        route = "BLOCK"
        reasons.extend(
            RouteReason(code=f.type.value, fid=f.fid, detail=f"命中 {f.raw}")
            for f in block_hits
        )
    else:
        if gov_hits:
            route = "GOVCLOUD"
            reasons.extend(
                RouteReason(code=f.type.value, fid=f.fid, detail=f"命中 {f.type.label}")
                for f in gov_hits
            )
        if batch_count >= max(1, batch_pii_min):
            route = "GOVCLOUD"
            reasons.append(RouteReason(
                code="BATCH_STRUCTURED_PII",
                detail=f"结构化号码 ×{batch_count} ≥ {batch_pii_min}",
            ))

    if not reasons:
        route = "INTERNET"
        if mask_hits:
            reasons.append(RouteReason(code="SINGLE_STRUCTURED_PII", fid=mask_hits[0].fid))
        elif active:
            reasons.append(RouteReason(code="WHITELIST_ONLY"))
        else:
            reasons.append(RouteReason(code="NO_FINDING"))

    return RouteDecision(
        route=route,
        reasons=reasons,
        upstream=None if route == "BLOCK" else upstream_for.get(route),
        mask_required=bool(mask_hits),
    )
