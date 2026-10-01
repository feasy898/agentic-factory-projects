# lark-cli 调用输出判读与处置决策（A–E × 概念题 2 道）

> 判读依据：`skillfactory/v2/evalbench-v02/lark-cli/ASSET-DOC.md`（2026-09-29 版，本会话已完整读取）——§5.2 JSON 输出契约、§7 错误契约（ERROR_CONTRACT 摘录）、§8.1 lark-shared 安全规则。
> A–E 五条输出为任务给定的脚本日志摘录（含写入流与退出码），非本机复跑结果；本次未在本机执行 lark-cli（任务是按契约判读给定日志，非复跑）。

---

## 0. 判读总则（均引自 ASSET-DOC.md）

- **成功信封**：写 **stdout**、退出码 0、顶层 `ok:true`；成功信封**没有**顶层 `code`/`msg` 字段（`ASSET-DOC.md:138`、`:141`、`:150`）。
- **错误信封**：写 **stderr**、退出码非 0、顶层 `ok:false`；`error` 内含 `type`/`subtype`（wire-stable）、`code`（上游 OpenAPI 数字码，"`omitempty` and never carries CLI-internal meaning"）、`message`/`hint`/`log_id`（仅信息性，**不可用于分支判断**）（`:144`、`:240`–`:243`）。
- **关键规则（原文）**："判断成功应检查 `ok == true`（或退出码），不要用 `code == 0`"（`:150`）。
- **分支只看 wire-stable 字段**：`type`、`subtype`、`code`、`retryable`、`retry_after_seconds` 及声明的扩展字段（如 `missing_scopes`）；未知字段 "ignore, don't fail"（`:246`、`:270`）。
- `retryable`："**`true` when present; omitted when `false`**"；`retry_after_seconds` 仅在可重试的网络 / api-rate_limit 错误时由上游提供（`:244`–`:245`）。
- 防御性做法：解析前先用 `jq -e .` 确认输出确为 JSON（`:268`）。

九类 `error.type` 与退出码对照（`:252`–`:260`）：

| type | validation | authentication | authorization | config | network | api | policy | internal | confirmation |
|---|---|---|---|---|---|---|---|---|---|
| 退出码 | 2 | 3 | 3 | 3 | 4 | 1 | 6 | 5 | **10** |

---

## 1. 逐条判读

### A（stdout，退出码 0）— ✅ 成功

```json
{"ok":true,"identity":"user","data":{"guid":"docx#V3mQ8x"},"meta":{"count":1}}
```

**① 成功。** 依据（三重一致，完全符合 §5.2 成功契约）：顶层 **`ok:true`**（权威判据，`:150`）＋ 写入 **stdout** ＋ **退出码 0**（`:138`）。信封形状与 §5.2 成功示例逐字段一致（`:141`）。

**② 下一步：无需任何纠错动作。**
- 业务侧读取 **`data.guid`**（`"docx#V3mQ8x"`）作为后续命令的输入；`meta.count` 为信息性元数据。
- 不重试（操作已完成）；无需用户确认；无需上报。
- 提醒：此刻**不要**再对响应做 `code == 0` 之类的旧惯例校验——成功信封里根本没有 `code` 字段（见概念题 Ⅰ）。

### B（stderr，退出码 3）— ❌ 失败：缺 scope 授权错误

```json
{"ok":false,"identity":"user","error":{"type":"authorization","subtype":"missing_scope","code":99991679,"message":"permission denied","hint":"guide user to grant missing scopes","missing_scopes":["base:record:create"]}}
```

**① 失败。** 依据：**`ok:false`** ＋ 写入 **stderr** ＋ **退出码 3**；wire-stable 分类 `type=authorization` / `subtype=missing_scope`（authorization → 3，`:254`）。`code=99991679` 是上游 OpenAPI 数字码，无 CLI 内部含义，仅作参考；`message`/`hint` 仅信息性、不作为分支依据（`:242`–`:243`）。

**② 下一步：不可原样重试，需用户先授权后重跑。**
- 读**声明的扩展字段 `missing_scopes`**（= `["base:record:create"]`，`:246`），据此提示用户授予该 scope——这正是 §7.4 的标准处置："authorization → 读 `missing_scopes` 提示用户授权"（`:271`）。
- 授权途径：`lark-cli auth login --scope "base:record:create"`（`:83`）；授权后可用 `lark-cli auth check` 复核（exit 0 = 有权限，`:75`），再重跑原命令。
- 原样重试无意义（缺 scope 是确定性失败，重试前必失败）；本条**需要用户介入**，应作为"等待用户授权"上报/提示。

### C（stderr，退出码 4）— ❌ 失败：网络错误（可重试）

```json
{"ok":false,"identity":"user","error":{"type":"network","message":"dial tcp 1.2.3.4:443: connect refused","retryable":true,"retry_after_seconds":2}}
```

**① 失败。** 依据：**`ok:false`** ＋ 写入 **stderr** ＋ **退出码 4**；`type=network`（network → 4，`:256`）。

**② 下一步：可安全重试，且契约已给出重试节奏。**
- 可重试的**依据是 wire-stable 字段 `retryable:true`**（字段出现即为 true，`:244`）＋ §7.4 明文 "network → 可安全重试"（`:271`）。
- **尊重 `retry_after_seconds:2`**：等待 ≥2 秒后原样重跑同一命令。
- 建议脚本做**有限次退避重试**（如 3 次；重试次数上限契约未规定，属脚本自身策略），仍失败再上报（附 `message` 及 `log_id` 如有）。
- 无需用户确认。

### D（stderr，退出码 10）— ⚠️ 不是普通失败：高风险确认门禁（操作未执行）

```json
{"ok":false,"identity":"user","error":{"type":"confirmation","message":"high-risk action needs --yes","action":"delete view vewFGH and its config","risk":"irreversible deletion","hint":"append --yes to the end of your original argv after explicit user consent"}}
```

**① 判定：命令未执行任何删除——这是确认门禁而非错误。** 依据：**退出码 10** ＋ `type=confirmation`（confirmation → 10，`:260`）；§7.3 明文"**这是确认门禁而非错误**"（`:262`–`:263`）。信封虽是 `ok:false` 走 stderr，但语义是"参数与身份均合法，CLI 拒绝在未获明确同意前执行高风险操作"，本次 `delete view vewFGH` **尚未发生**。

**② 下一步：停下 → 用户确认 → 带 `--yes` 重跑。** 标准流程（§7.3 `:263`；lark-shared 安全规则第 4 条 `:296`）：
1. **停**：不当作一般失败自动重试；**绝不静默补 `--yes` 绕过门禁**；
2. **示**：向用户展示 `error.action`（"delete view vewFGH and its config"）、`error.risk`（"irreversible deletion"）及关键参数；
3. **确认**：取得用户**显式同意**；用户拒绝则不重试，任务挂起等待用户决定；
4. **重试**：仅在同意后，把 `hint` 指定的确认 flag **`--yes` 追加到原始 argv 的末尾**，重跑同一命令。

### E（stderr，退出码 2）— ❌ 失败：命令不在当前分发版

```json
{"ok":false,"identity":"user","error":{"type":"validation","subtype":"command_unavailable","message":"command not available in this distribution"}}
```

**① 失败。** 依据：**`ok:false`** ＋ 写入 **stderr** ＋ **退出码 2**；wire-stable 分类 `type=validation` / `subtype=command_unavailable`（validation → 2，`:252`）。

**② 下一步：不重试、不当认证问题、不绕过。**
- §7.4 特殊路径明文：`command_unavailable` 表示**能力不在当前分发版中**，"不应视为认证失败或尝试绕过"（`:272`）。
- 禁止的动作：反复重试（同一二进制下为确定性失败）；误判为登录/授权问题去重新登录；绕过该限制硬调。
- 合理动作：升级分发（`npx @larksuite/cli@latest install`，`:32`）后重试；或用 `lark-cli <service> --help` / `lark-cli schema` 找当前分发内存在的等价命令；若业务确需该能力且升级后仍缺失，上报维护者/上游。

---

## 2. 概念题

### Ⅰ. 为什么「用 code == 0 判断成功」是危险的？

1. **成功信封里根本没有 `code` 字段。** §5.2（`:150`）：成功信封没有顶层 `code`/`msg`；`code` 只出现在**失败**信封的 `error` 内，且是上游 OpenAPI 数字码（"`omitempty` and never carries CLI-internal meaning"，`:242`）。按旧 OpenAPI 惯例（顶层 `code:0` = 成功）写的判据，面对 lark-cli 的成功输出会取到 undefined/None，`code == 0` 永不成立——**把成功误判为失败**。文档原话即警示："按旧 OpenAPI 惯例判断会把成功误判为失败——'封装写入类命令时尤其危险'"。
2. **误判方向恰好最致命：成功 → 假失败。** 对封装的写入类命令（建记录、发消息、建文档），实际成功却被判为失败，脚本若自动重试就会**重复写入**（重复记录/重复消息/重复文档），或向用户虚报失败——多余的副作用远比一次漏报更难回收。
3. **失败侧的 `code` 也不能当 CLI 内部状态机用。** 它是上游业务数字码、可省略、不承载 CLI 内部含义（`:242`）；稳定的分支依据是顶层 `ok`、退出码，以及 `error.type`/`subtype`/`retryable`/`retry_after_seconds` 等 wire-stable 字段（`:240`–`:246`、`:270`）。

**正确判据**：`ok == true`（或退出码 0），辅以流方向（成功 stdout / 错误 stderr）；解析前先 `jq -e .` 防御性确认是 JSON（`:268`）。

### Ⅱ. 退出码 10 意味着什么？标准处理流程是什么？

**含义**：退出码 10 = `error.type=confirmation`——**高风险操作确认门禁**（§7.2 `:260`；§7.3 `:262`–`:263`）。它**不是错误**：命令已解析、身份可用，但目标操作属高风险（如不可逆删除），CLI 拒绝在未获明确同意时执行；此刻操作**尚未发生**，什么都没改。

**标准流程**（§7.3 `:263`，与 lark-shared 安全规则第 4 条 `:296` 一致）：
1. **停**：不当作一般失败自动重试；绝不静默加 flag 绕过；
2. **示**：向用户展示 `error.action`（将执行什么）、`error.risk`（后果）及关键参数；
3. **确认**：取得用户显式同意（明确拒绝 → 不重试，任务挂起）;
4. **重试**：仅在同意后，把 `hint` 指出的确认 flag（如 `--yes`）**追加到原始 argv 末尾**，重跑同一命令。

---

## 3. 资产说明与任务冲突核对

已按要求先完整读取 `skillfactory/v2/evalbench-v02/lark-cli/ASSET-DOC.md` 并严格按其契约方法判读。任务给定的 5 条输出（字段、流、退出码）与 ASSET-DOC §5.2 / §7 契约**完全一致，未发现冲突**，故未触发"冲突时以任务为准"条款。本次未在本机执行 lark-cli——任务给定的是固定日志摘录，要求的是按契约判读；全部结论的出处均为上文明示的 ASSET-DOC.md 行号。
