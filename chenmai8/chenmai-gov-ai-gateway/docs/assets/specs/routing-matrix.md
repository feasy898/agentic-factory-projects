# M4 策略路由 spec（决策矩阵 R1–R6 + 43 格验收语义）

> 状态：frozen（§5.2 D2 冻结）。对照 `routing/{engine,models}.py` 与 `evals/m4_routing.py`
> 逐行核验于 2026-09-29；43 格口径以实测为准：`python -m evals.m4_routing` 输出
> `M4 ROUTING: 43/43 checks passed`（2026-09-29 实测通过）。

## 1. 决策矩阵（routing/engine.py:3-10 模块文档，纯函数）

优先级冻结：**BLOCK > GOVCLOUD > INTERNET**。六行全判定路径：

| 行 | 触发 | 路由 | 备注 |
|---|---|---|---|
| R1 | CLASSIFICATION_MARK（密级词，命中即 BLOCK_FLAG） | BLOCK | 403 语义 |
| R2 | INJECTION（规则/语义层） | BLOCK | flag=injection |
| R3 | WORK_SECRET / SENSITIVE_ATTR（即便已脱敏） | GOVCLOUD | 词面类 |
| R4 | ID_CARD/BANK_CARD 同请求 ≥ batch_pii_min（默认 3，下限钳 1） | GOVCLOUD | 批量名单 |
| R5 | 单个结构化 PII（12 码值 = 矩阵 11 类，见 §3） | INTERNET | mask_required=true |
| R6 | 仅白名单命中 / 无命中 | INTERNET | mask_required=false |

## 2. 判定口径（engine.py 模块文档 + 实现，冻结）

- **白名单语义**：`whitelisted=true` = 豁免脱敏、**不参与路由计数**——不计入 R3/R4/R5
  任何桶（R6 收口）。唯一安全例外：`action_hint="BLOCK_FLAG"` 照拦——白名单豁免的是
  "脱敏"不是"拦截"，R1 不受白名单影响（engine.py:61-66 `_bucket_block`）；
- **理由列表有序**，第一条为决定性理由；理由只来自决定性路由的桶（低优先级命中不随行，
  防 403 reasons 面扩散）；
- BLOCK：逐命中保留 fid 与密级词表面形式，detail = `命中 <词面>`（截断 ≤24 字符）；
- GOVCLOUD：词面类逐命中在前（决定性），批量名单聚合条随后
  （code=BATCH_STRUCTURED_PII，detail 含 `×N ≥ 阈值`）；
- INTERNET（R5）：**聚合单条** SINGLE_STRUCTURED_PII（网关 e2e 契约
  `reasons==[SINGLE_STRUCTURED_PII]`），fid 取首个 mask 命中；
- INTERNET（R6 仅白名单）：决定条 WHITELIST_ONLY（detail 按类别标签×计数汇总）+ 逐命中
  **WHITELIST_HIT 留存条**（fid + 类别标签，**结构化 PII 原文永不进 reasons**）；
- `mask_required` = 存在非白名单且 `action_hint="MASK"` 的命中（与路由桶无关，批量/政务云
  路径同样如实反映）；
- 纯函数：不改入参、不读可变全局、同入参恒同输出；reasons 序 = 输入 findings 序；
- `upstream_for` 映射缺键 → upstream=None（网关按 route_misconfigured 兜底）；BLOCK 恒 null
  （模型校验器强制，routing/models.py:47-49）。

## 3. 结构化 PII 名单（engine.py:44-51）

`STRUCTURED_PII_TYPES` 12 码值：PERSON / ADDRESS / ID_CARD / PHONE_MOBILE / PHONE_LANDLINE /
BANK_CARD / USCC / PLATE / EMAIL / IP / SECRET_KEY / DATE_BIRTH（PHONE 含手机/座机两码值，
即 §5.2 的"矩阵 11 类"）。

## 4. RouteReason.code 词汇表（routing/models.py:20-32，新增码值不构成契约变更）

```
CLASSIFICATION_MARK / INJECTION          → BLOCK
WORK_SECRET / SENSITIVE_ATTR             → GOVCLOUD
BATCH_STRUCTURED_PII                     → GOVCLOUD
SINGLE_STRUCTURED_PII                    → INTERNET（mask_required=true）
WHITELIST_ONLY / NO_FINDING              → INTERNET
WHITELIST_HIT（留存条，附于 WHITELIST_ONLY 之后）→ INTERNET
```

## 5. 43 格语义（evals/m4_routing.py，2026-09-29 实测逐格全绿）

43 = **38 矩阵格** + **5 横切检查**：

- 38 矩阵格（MATRIX_CASES，m4_routing.py:111 起）：
  - R1/R2 → BLOCK 8 格：单命中 / 注入 / 双密级词逐命中且理由序=输入序 / 冲突
    BLOCK>GOVCLOUD、BLOCK>批量、BLOCK>全低优先级（低优先级不随行） / 边界
    白名单里的密级词照拦 / R1+R2 同拦桶注入在前决定；
  - R3 → GOVCLOUD 5 格：工作秘密 / 敏感属性（detail 带 subtype）/ 词面类双命中逐条 /
    冲突 GOVCLOUD>单 PII / 边界 白名单不参与 R3 计数→R6；
  - R4 → GOVCLOUD 7 格：恰 3 身份证 / 恰 3 银行卡 / 混合 2+1 计数 / 低于阈值 2→单 PII /
    GOVCLOUD 桶内序（词面类决定性在前、批量随后）/ 批量+单 PII mask_required 如实 /
    边界 白名单身份证不参与批量计数→R6；
  - R5 → INTERNET 14 格：12 结构化码值逐格单命中（脱敏出网 mask_required=true）+
    多 PII 聚合单条理由 + 边界 非矩阵类别的 MASK 提示命中同走脱敏出网；
  - R6 → INTERNET 4 格：无命中透传（NO_FINDING）/ 仅公开文号 / 多白名单逐条留存 /
    白名单命中不触发 mask_required。
- 5 横切检查：matrix-scale（≥25 格下限 + 三路由覆盖 + 用例名唯一）/ purity（同入参恒同
  输出 + 入参零改动 + 理由序=输入序）/ wire（§5.2 五键形状 + RouteReason 三键 + 4 形态
  JSON 往返全等）/ upstream-edge（BLOCK 恒 null + 缺键容忍 + BLOCK 键不可注入）/
  threshold（批量阈值可配 + 下限钳 1）。

每格断言五键：`route / reasons[0].code（决定性）/ upstream / mask_required / labels=={"ai_generated": true}`，
关键格加断言码序列与 fid 序列。

## 6. eval 指针

| eval | 通过线 | 六道门指针 |
|---|---|---|
| `evals.m4_routing` | `M4 ROUTING: 43/43 checks passed`，exit 0（2026-09-29 实测） | gate_b2 ③-1 首验；此后经 gate_b3/b4/b5 整门链回归 |
