# lark-cli 输出解读与处置决策（A–E）+ 概念题

> 交付物：对 5 次调用输出（A–E）的逐条判定与下一步动作，以及两道概念题的解答。
>
> **判定依据来源**（全部为本次会话实际读取的材料）：
> - 任务原文给出的 5 段输出摘录（A–E，含 stdout/stderr 归属与退出码）——本任务题面；
> - `skillfactory/v2/evalbench-v02/lark-cli/ASSET-DOC.md`（2026-09-29 版，本次会话完整读取 423 行），主要引用：
>   - §5.2「JSON 输出契约」（L136–150）：成功 → 写 **stdout**、退出码 **0**、`ok:true`；错误 → 写 **stderr**、退出码非 0、`ok:false`；关键规则原文："判断成功应检查 `ok == true`（或退出码），不要用 `code == 0`"；**成功信封没有顶层 `code`/`msg` 字段**，`code` 仅出现在错误信封内、为上游 OpenAPI 数字码；
>   - §7.1「错误信封结构与字段稳定性」（L222–246）：`type`/`subtype` 为 wire-stable；`code` 为上游码、"never carries CLI-internal meaning"；`message`/`hint`/`log_id` 属 informational、**不可用于分支判断**；`retryable` "true when present; omitted when false"；`retry_after_seconds` 由可重试错误的上游提供；
>   - §7.2「error.type 九大类与退出码」（L249–261）：validation=2、authentication=3、authorization=3、config=3、network=4、api=1、policy=6、internal=5、**confirmation=10**；
>   - §7.3「退出码 10（高风险确认门禁）」（L263–264）；
>   - §7.4「Shell / AI 消费者建议」（L266–272）：`authorization` → 读 `missing_scopes` 提示用户授权；`network` → 可安全重试；`internal` → 收集 `log_id` 报 issue；`command_unavailable`（validation 子类）表示能力不在当前分发版中，不应视为认证失败或尝试绕过；
>   - §8.1 lark-shared 通用准则与安全规则（L281–299）：成功判定用 `ok == true`；退出码 10 是确认门禁；写/删前确认意图、支持 `--dry-run` 先预览。

---

## 一、逐条解读

### A（stdout，退出码 0）— ✅ 成功

**① 判定：成功。**
依据（三重一致，缺一才需警惕）：
- 写入 **stdout**（契约 §5.2：成功信封写 stdout）；
- 退出码 **0**（契约 §5.2：成功退出码 0）；
- **`ok == true`**（契约 §5.2 与 §8.1 准则 4：判定成功看 `ok`，不看 `code`）。

特别提醒：该成功信封里**不存在顶层 `code`/`msg` 字段**——`"guid":"docx#V3mQ8x"` 是 `data` 的业务内容，不是错误码。若脚本此时去找 `code` 字段做判断，会掉进概念题 Ⅰ 的坑。

**② 下一步动作：无需处理、无需重试。**
直接消费 `data.guid`（`docx#V3mQ8x`）作为后续操作的引用句柄；`meta.count: 1` 表示本次返回 1 条数据。不安排任何复核查询。

---

### B（stderr，退出码 3）— ❌ 失败：缺授权（authorization / missing_scope）

**① 判定：失败，且失败原因是权限不足，不是认证失效。**
依据：
- 写入 **stderr** + 退出码 **3** + `ok == false`（契约 §5.2：错误信封特征）；
- `error.type == "authorization"` 与 §7.2 退出码表一致（authorization → 3）；
- 可用于分支的 wire-stable 字段：`type`、`subtype == "missing_scope"`、扩展字段 **`missing_scopes: ["base:record:create"]`**（§7.1：各 subtype 有声明扩展字段）。
- 注意：`code: 99991679` 是上游 OpenAPI 数字码（§7.1："never carries CLI-internal meaning"），`message`/`hint` 属 informational，**不可用于分支判断**——分支只认 type/subtype/missing_scopes。

**② 下一步动作：不可程序化重试；读 `missing_scopes` 引导用户授权，授权完成后重放原命令。**
- **不要盲目重试**：缺 scope 是确定性失败，原样重跑必然复现；
- **不要换命令硬绕**：绕过授权面违反安全边界；
- 按 §7.4（"authorization → 读 `missing_scopes` 提示用户授权"）与 `hint`，把缺失的 scope（`base:record:create`，多维表格记录写入权限）明确告知用户，引导其补授权（如重新执行 `lark-cli auth login --scope …`，或在飞书开放平台为应用开通该权限后再登录）；
- 用户补授权后，**原样重放该命令**即可；
- 无需作为故障上报——这是预期的权限门禁路径。

---

### C（stderr，退出码 4）— ❌ 失败：网络错误（network），可安全重试

**① 判定：失败，且是暂时性网络故障。**
依据：
- 写入 **stderr** + 退出码 **4** + `ok == false`；
- `error.type == "network"` 与 §7.2 退出码表一致（network → 4）；
- **可重试性有明确字段依据**：`retryable: true`（契约 §7.1："true when present; omitted when false"——字段出现即可信）+ `retry_after_seconds: 2`（§7.1：仅可重试错误时由上游提供建议等待秒数）。两者均为 §7.4 允许分支的 wire-stable 字段。
- `message` 里的 `dial tcp 1.2.3.4:443: connect refused` 是 informational 文本，不要解析它来写分支逻辑。

**② 下一步动作：等待 ≥2 秒后原样重试同一命令。**
- 重试依据：`type=network` 属 §7.4 明示"可安全重试"类别，且 `retryable:true` 由上游显式声明；
- 重试前遵守 `retry_after_seconds: 2`（等待至少 2 秒，避免立即冲击已拒绝的连接）；
- **设重试上限**（如 3–5 次退避重试）：若持续失败，说明不是抖动而是连通性问题（本机网络 / 代理 / 出口 / 防火墙，或目标 IP 不可达），此时停止重试并向运维/调用方上报网络故障，不要无限循环。

---

### D（stderr，退出码 10）— ⚠️ 形式上"失败"，实质是高风险确认门禁（confirmation）

**① 判定：调用以 `ok:false`、stderr、退出码 10 结束——形式上是失败；但按契约 §7.3，这是"高风险操作需 `--yes`"的**确认门禁（gate），不是执行错误**。**
- `error.type == "confirmation"` 与 §7.2 退出码表一致（confirmation → 10，且 10 不属于其他八类）；
- **关键语义：命令在执行前主动中止，`delete view vewFGH and its config` 这个删除动作并没有发生**，当前无任何副作用。绝不能把它当普通故障进自动重试循环。

**② 下一步动作：停下 → 向用户确认 → 同意后把 `--yes` 追加到原始 argv 末尾重试；绝不静默加 flag 绕过。**
标准流程（§7.3 + §8.1 安全规则 4）：
1. **停下**，该分支不得自动化放行；
2. 向用户展示门禁给出的关键信息：`action`（将删除视图 vewFGH 及其配置）、`risk`（**irreversible deletion，不可逆删除**）及相关参数，供用户决策；若该命令支持 `--dry-run`，可先预览请求再请确认（§8.1 安全规则 3）；
3. 取得用户**显式同意**（explicit consent）后才继续；用户拒绝则放弃该操作；
4. 同意后，按 `hint` 的指引把 `--yes` **追加到你原始 argv 的末尾**，原样重试该命令（不改动其他参数）；
5. **红线：绝不静默自动加 `--yes` 绕过门禁**——门禁存在的意义就是把不可逆删除的决定权留给用户。此事件本身无需作为错误上报。

---

### E（stderr，退出码 2）— ❌ 失败：该命令在当前分发版中不存在（validation / command_unavailable）

**① 判定：失败，且是"能力不存在"，不是用错了参数，更不是登录/授权问题。**
依据：
- 写入 **stderr** + 退出码 **2** + `ok == false`；
- `error.type == "validation"` 与 §7.2 退出码表一致（validation → 2）；
- `subtype == "command_unavailable"`：按 §7.4 特殊路径，表示**该能力不在当前分发版中**（例如精简构建/旧版本未包含此命令），不是暂时性故障。

**② 下一步动作：如实上报环境缺口；不视为认证失败、不尝试绕过、盲目重试无意义。**
- 确定性失败：重试、重新登录、补 scope 都不会改变结果；
- 按 §7.4：**不应误判为认证/登录失败**（`type` 是 `validation` 而非 `authentication`/`authorization`），也**不应尝试绕过**；
- 处置：向调用方/用户报告"当前安装的 lark-cli 分发不包含该命令"；如业务确需该能力，评估修正安装（换完整 npm 分发、升级版本），或核对是否有官方替代命令/raw API 通道（`lark-cli api …`）能满足同一需求——替代路径同样要先经 `--help`/`schema` 核实，不臆造；
- 保留 `type`/`subtype` 原文进上报内容，便于定位是哪个分发缺了哪个命令。

---

## 二、概念题

### Ⅰ. 为什么「用 code == 0 判断成功」是危险的？

依据 ASSET-DOC.md §5.2（L136–150）的输出契约：

1. **成功信封里根本没有顶层 `code` 字段。** 契约规定成功信封只有 `ok` / `identity` / `data` / `meta`，**没有顶层 `code`/`msg`**；`code` 只出现在错误信封内部（`error.code`），且是上游 OpenAPI 的数字错误码。于是对成功输出（如 A）做 `jq .code` 会得到 `null`/空串，`null == 0` 不成立——**每次真正的成功都会被误判为失败**。A 就是现成反例：`{"ok":true,...,"data":{"guid":"docx#V3mQ8x"}}` 里无 `code` 可读。
2. **误判方向恰好是最危险的方向。** 把"成功"误判为"失败"后，脚本的典型反应是重试或补做——对写入类命令（创建文档、发消息、写记录）就意味着**重复创建、重复发送、重复写入**。契约原文点明："按旧 OpenAPI 惯例判断会把成功误判为失败——**封装写入类命令时尤其危险**"。这是沿用旧版飞书 OpenAPI 惯例（顶层 `code:0` = 成功）的存量脚本迁移到本 CLI 时最常见的坑。
3. **正确姿势**：以 `ok == true`（或退出码 0）判定成功；失败分支只用 wire-stable 字段（`type`/`subtype`/`code`/`retryable`/`retry_after_seconds` 及声明的扩展字段，§7.1/§7.4），且 `message`/`hint`/`log_id` 仅作展示、不参与分支。

### Ⅱ. 退出码 10 意味着什么，标准处理流程是什么？

**含义**（§7.2 L260、§7.3 L263–264）：退出码 10 对应 `error.type == "confirmation"`，即命令属于"high-risk action needs `--yes`"的高风险操作（典型如删除类不可逆操作）。它是**确认门禁而非错误**：CLI 在执行前主动中止，把"是否继续"的决定权交还给人——**目标动作尚未发生、无副作用**（如 D 中的 `delete view vewFGH and its config` 并未执行）。

**标准处理流程**（§7.3 + §8.1 安全规则 4）：
1. **停下**：不得把它当普通错误自动处理或自动重试；
2. **展示**：向用户呈现 `action`（要做什么）、`risk`（风险，如 irreversible deletion）及关键参数；
3. **确认**：取得用户显式同意；用户拒绝则放弃操作；
4. **重试**：同意后，把 `hint` 指出的确认 flag（`--yes`）**追加到原始 argv 的末尾**，原样重跑该命令；
5. **红线**：**绝不静默加 flag 绕过门禁**——门禁的目的就是强制人工对不可逆操作放行。

---

## 附注：任务与 ASSET-DOC 的冲突核对

按任务要求逐项比对：任务 A–E 的输出流归属与退出码（stdout/0、authorization/3、network/4、confirmation/10、validation/2）与 ASSET-DOC.md §5.2、§7.2 表完全一致；B 的错误信封结构（含扩展字段 `missing_scopes`）与 §7.1 一致；D 的 `action`/`risk`/`hint` 字段语义与 §7.3 流程一致；E 的 `command_unavailable` 处置与 §7.4 特殊路径一致。**未发现说明与任务冲突之处**，故无"以任务为准"的例外条款适用。

另注：本任务为对题面给定日志摘录的解读题（摘录数据由任务本身提供），无需且未实际运行 lark-cli；全部判定均引用题面原文与 ASSET-DOC.md 具体章节，未引入外部臆测。
