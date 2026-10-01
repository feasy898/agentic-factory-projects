"""路由策略引擎（开发指令 §5.2 决策矩阵，纯函数；M4）。

优先级冻结：BLOCK > GOVCLOUD > INTERNET。矩阵六行 → 三路由全判定路径::

    R1  CLASSIFICATION_MARK（密级词，命中即 BLOCK_FLAG）      → BLOCK（403 语义）
    R2  INJECTION（规则/语义层）                               → BLOCK（flag=injection）
    R3  WORK_SECRET / SENSITIVE_ATTR（即便已脱敏）             → GOVCLOUD
    R4  ID_CARD/BANK_CARD 同请求 ≥ batch_pii_min（批量名单）   → GOVCLOUD
    R5  单个结构化 PII（11 类，见 STRUCTURED_PII_TYPES）        → INTERNET（mask_required=true）
    R6  仅白名单命中 / 无命中                                  → INTERNET（mask_required 按实际 findings）

判定口径（本函数即口径权威，evals.m4_routing 逐格钉死）：

- 白名单（``Finding.whitelisted=true``）的语义是**豁免脱敏、不参与路由计数**：
  不计入 R3/R4/R5 的任何桶（R6 收口）。唯一安全例外是 ``action_hint="BLOCK_FLAG"``——
  白名单豁免的是"脱敏"不是"拦截"，密级词即便被误配进白名单也照拦（R1 不受白名单影响）。
- 理由列表有序，**第一条为决定性理由**；理由只来自决定性路由的桶（低优先级命中
  不随行，防 403 reasons 面扩散）——BLOCK 逐命中保留 fid 与密级词表面形式（契约示例
  「命中 机密★」，截断 ≤24 字）；GOVCLOUD = 词面类逐命中 + 批量名单聚合条；
  INTERNET 聚合为单条（SINGLE_STRUCTURED_PII / WHITELIST_ONLY / NO_FINDING）。
- **白名单命中留存**：R6 判定时每条白名单命中以 ``code=WHITELIST_HIT`` 附于
  WHITELIST_ONLY 之后，保留 fid 与类别标签——决策可追溯"因什么被豁免"；
  detail 只含类别标签与计数，**结构化 PII 原文永不进 reasons**（审计仅取 code，
  403 体带 detail 面向部门调用方）。
- ``mask_required`` = 存在非白名单且 ``action_hint="MASK"`` 的命中（按实际 findings，
  与路由桶无关：批量名单/政务云路径同样如实反映）。
- 纯函数：不改入参、不读可变全局、同入参恒同输出；reasons 顺序跟随入参 findings
  顺序（识别层按 span 升序产出，第一条命中即决定性理由）。
"""
from __future__ import annotations

from recognizers.models import EntityClass, Finding
from routing.models import RouteDecision, RouteReason

#: 批量名单计数类别（§5.2 R4：ID_CARD/BANK_CARD 同请求 ≥3 个）
BATCH_PII_TYPES: frozenset[EntityClass] = frozenset({EntityClass.ID_CARD, EntityClass.BANK_CARD})

#: 即便已脱敏也切政务云的类别（§5.2 R3：WORK_SECRET 或 SENSITIVE_ATTR）
GOVCLOUD_TYPES: frozenset[EntityClass] = frozenset({EntityClass.WORK_SECRET, EntityClass.SENSITIVE_ATTR})

#: 命中即拦截的类别（§5.2 R1/R2：CLASSIFICATION_MARK、INJECTION）
BLOCK_TYPES: frozenset[EntityClass] = frozenset({EntityClass.CLASSIFICATION_MARK, EntityClass.INJECTION})

#: 单个结构化 PII 类别（§5.2 R5；PHONE 含手机/座机两码值，共 12 码值 = 矩阵 11 类）
STRUCTURED_PII_TYPES: frozenset[EntityClass] = frozenset({
    EntityClass.PERSON, EntityClass.ADDRESS, EntityClass.ID_CARD,
    EntityClass.PHONE_MOBILE, EntityClass.PHONE_LANDLINE, EntityClass.BANK_CARD,
    EntityClass.USCC, EntityClass.PLATE, EntityClass.EMAIL, EntityClass.IP,
    EntityClass.SECRET_KEY, EntityClass.DATE_BIRTH,
})

#: BLOCK reason.detail 里密级词/注入文本表面形式的截断上限（契约示例「命中 机密★」）
_SURFACE_CAP = 24


def _surface(raw: str, cap: int = _SURFACE_CAP) -> str:
    """表面形式截断（detail 面向部门调用方；超长以省略号收尾）。"""
    return raw if len(raw) <= cap else raw[:cap] + "…"


def _bucket_block(findings: list[Finding]) -> list[Finding]:
    """R1/R2 拦截桶：BLOCK_FLAG 提示（不受白名单豁免）或非白名单 BLOCK 类别。"""
    return [
        f for f in findings
        if f.action_hint == "BLOCK_FLAG" or (not f.whitelisted and f.type in BLOCK_TYPES)
    ]


def decide(
    findings: list[Finding],
    *,
    upstream_for: dict[str, str],
    batch_pii_min: int = 3,
) -> RouteDecision:
    """决策矩阵纯函数：findings + 上游名映射 → RouteDecision（无副作用、可独立测试）。

    ``upstream_for`` 形如 ``{"INTERNET": "internet_mock", "GOVCLOUD": "govcloud_local"}``，
    由网关按 config/app.yaml 构建；BLOCK 时 upstream 恒为 null（契约校验兜底）；
    映射缺键时 upstream=None（网关侧按 route_misconfigured 兜底，路由判定不受影响）。
    ``batch_pii_min`` 为批量名单阈值（config thresholds.batch_pii_to_govcloud，默认 3，
    下限钳到 1）。
    """
    wl_hits = [f for f in findings if f.whitelisted]
    active = [f for f in findings if not f.whitelisted]

    block_hits = _bucket_block(findings)
    gov_hits = [f for f in active if f.type in GOVCLOUD_TYPES]
    batch_hits = [f for f in active if f.type in BATCH_PII_TYPES]
    mask_hits = [f for f in active if f.action_hint == "MASK"]
    batch_min = max(1, batch_pii_min)

    reasons: list[RouteReason]
    if block_hits:
        # R1/R2 → BLOCK：逐命中保留 fid + 表面形式（契约示例 detail「命中 机密★」）
        route = "BLOCK"
        reasons = [
            RouteReason(code=f.type.value, fid=f.fid, detail=f"命中 {_surface(f.raw)}")
            for f in block_hits
        ]
    elif gov_hits or len(batch_hits) >= batch_min:
        # R3/R4 → GOVCLOUD：词面类逐命中在前（决定性），批量名单聚合条随后
        route = "GOVCLOUD"
        reasons = [
            RouteReason(
                code=f.type.value, fid=f.fid,
                detail=f"命中 {f.type.label}" + (f"·{f.subtype}" if f.subtype else ""),
            )
            for f in gov_hits
        ]
        if len(batch_hits) >= batch_min:
            reasons.append(RouteReason(
                code="BATCH_STRUCTURED_PII",
                detail=f"ID_CARD/BANK_CARD ×{len(batch_hits)} ≥ {batch_min}（批量名单）",
            ))
    elif mask_hits:
        # R5 → INTERNET：脱敏后出网；聚合单条（网关 e2e 契约 reasons==[SINGLE_STRUCTURED_PII]）
        route = "INTERNET"
        reasons = [RouteReason(
            code="SINGLE_STRUCTURED_PII", fid=mask_hits[0].fid,
            detail=f"结构化 PII ×{len(mask_hits)}（脱敏后出网）",
        )]
    elif wl_hits:
        # R6 → INTERNET：仅白名单命中；决定条 + **逐命中留存**（fid + 类别标签，无原文）
        route = "INTERNET"
        by_label: dict[str, int] = {}
        for f in wl_hits:
            by_label[f.type.label] = by_label.get(f.type.label, 0) + 1
        summary = "、".join(f"{label}×{n}" for label, n in by_label.items())
        reasons = [RouteReason(code="WHITELIST_ONLY", detail=f"白名单命中 ×{len(wl_hits)}（{summary}）")]
        reasons.extend(
            RouteReason(code="WHITELIST_HIT", fid=f.fid, detail=f"{f.type.label} 白名单豁免")
            for f in wl_hits
        )
    else:
        # R6 → INTERNET：无任何命中，原样透传
        route = "INTERNET"
        reasons = [RouteReason(code="NO_FINDING")]

    return RouteDecision(
        route=route,
        reasons=reasons,
        upstream=None if route == "BLOCK" else upstream_for.get(route),
        mask_required=bool(mask_hits),
    )
