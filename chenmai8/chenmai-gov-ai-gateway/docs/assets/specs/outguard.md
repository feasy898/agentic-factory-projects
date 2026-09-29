# M5 输出侧 spec（AI 标识 / 拒答代答 / 复检钩子）

> 状态：frozen（T2.2）。对照 `outguard/{label,fallback,models,moderation,service}.py` 与
> `config/outguard_texts.yaml` 逐行核验于 2026-09-29。

## 1. AI 生成标识（label.py，§5.6 冻结注入方式）

| 形态 | 注入 |
|---|---|
| 非流式 | `choices[0].message.content` 尾部加标识行（含前导换行）+ `choices[0].message.annotations` 字段 |
| 流式 | 最后一个内容 delta 尾部标识行（实现：finish 前注入一个只含尾注的 content delta）+ finish chunk `choices[0].delta.annotations`——与非流式同名同形 |
| 响应头 | `x-anongw-ai-label: 1`（流式随 SSE 头下发） |

- `annotations` 形状：`[{"type": "ai_generated", "text": <文案>}]`；
- 文案可配置：config/app.yaml `ai_label`（默认「本内容由AI生成」；空/空白 → 不注入）；
- **幂等**：已有 annotations 键不覆盖、content 已以标识行结尾不重复追加（重复调用不叠加）；
- 标识只加在**成功回答**上：BLOCK / 上游错误的错误信封不是 AI 生成内容，不加。

## 2. 拒答 / 代答文案库（fallback.py + config/outguard_texts.yaml）

- **拒答**：BLOCK 时按**决定性 reason code**（reasons[0]，§5.2）取模板——
  `CLASSIFICATION_MARK` → 保密提示卡 / `INJECTION` → 安全提示 / `OUTPUT_MODERATION` →
  复检拦截提示；未配置的 code 回落 `block.default`（默认「涉密/涉敏内容已拦截，请通过
  保密渠道办理或删除敏感标识后重试」）；
- **代答**：MVP = 关键词 → 固定口径问答（子串匹配，条目序即优先级，首个命中生效；
  内置一条：借阅/查阅流程/定密/解密/保密委员会 → 引导线下保密流程）。命中时代答文案拼在
  拒答文案之后，随 403 message 同体下发（WebUI 渲染提示卡）；
- 匹配输入是**脱敏后**的 prompt（占位符版本，无原文）——代答文案是 YAML 固定文本，
  原值零出场；P2 升级语义匹配（向量检索），返回形状不变；
- 加载：YAML 路径缺失/条目缺失回落内置默认（两者内容保持一致）；纯函数 + 无副作用。

## 3. 输出侧复检钩子（moderation.py，接口预留）

- 协议 `OutputModerationBackend`：`moderate(response) -> ModerationVerdict`
  （verdict ∈ safe|flagged + categories + detail）；
- P0 后端 `NullModerator` 恒 safe（主链路零影响）；P1 接语义审核后端采样执行；
- `flagged` → 网关按 `content_blocked` 拦截本次响应，reasons code=`OUTPUT_MODERATION`，
  审计 flag=`output_flagged`。

## 4. eval 指针

| eval | 通过线 | 六道门指针 |
|---|---|---|
| `evals.m5_outguard` | 标识存在性（流/非流/幂等）/ BLOCK 文案按 code 回退 / 代答命中拼接 / 复检钩子（flagged→403+审计 flag）；`M5 OUTGUARD: 13/13 checks passed`，exit 0（2026-09-29 实测 20.7s） | gate_b2 ③-2 首验；此后整门链回归 |
