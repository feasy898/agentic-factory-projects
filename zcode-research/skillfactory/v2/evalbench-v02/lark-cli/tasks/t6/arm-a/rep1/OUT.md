# T6 · lark-cli 输出解读与后续动作（arm-a / rep1）

> 依据：任务题面给出的 A–E 五段输出摘录（stdout/stderr 归属 + 退出码）+ 输出 JSON 本身的字段。
> 未运行的检查一律不声称已运行；本文全部结论仅基于题面材料，未引用 skillfactory/ 目录下任何其他文件。

---

## 〇、判读总纲（从 A–E 归纳出的本 CLI 输出契约）

| 信号 | 约定 |
|---|---|
| 成功 | JSON 写 **stdout**，`"ok":true`，携带 `data`，退出码 **0** |
| 失败 | JSON 写 **stderr**，`"ok":false`，携带 `error`（含 `type`/`message`，可能还有 `subtype`/`hint`/`retryable` 等细分字段），退出码 **非 0** |
| 退出码语义（依本次题面归纳） | 0=成功；2=validation（校验/分发不含该命令）；3=authorization（授权/权限不足）；4=network（网络错误，本例标记可重试）；10=confirmation（高危操作等待用户确认，**操作未执行**） |

自动化脚本的正确分流：先按退出码分流 → 成功路径解析 stdout 并断言 `ok==true` 且校验所需数据字段；失败路径解析 stderr 的 `error.type`，按「可重试 / 需用户动作 / 需用户确认 / 环境缺陷」四类分别处理。

---

## A（stdout，退出码 0）

**① 判定：成功。**
依据（三个信号一致）：
- JSON 写入 **stdout**（成功才走 stdout）；
- 退出码 **0**；
- `"ok":true`，且有数据载荷 `"data":{"guid":"docx#V3mQ8x"}` 与 `"meta":{"count":1}`。

**② 下一步：无需重试、无需上报，直接消费结果。**
- 读取 `data.guid`（`docx#V3mQ8x`）供后续调用使用；
- 可顺手校验 `meta.count == 1` 与 `data.guid` 非空，确认不是"成功但空结果"（见概念题Ⅰ）；
- 原样重试无意义且浪费配额；不涉及用户确认。

---

## B（stderr，退出码 3）

**① 判定：失败（授权类，不可自动重试）。**
依据：
- JSON 写入 **stderr**、退出码 **3**（非 0）；
- `"ok":false`；`error.type=="authorization"`、`error.subtype=="missing_scope"`、`error.code==99991679`（permission denied）；
- 题面摘录原文：`"hint":"guide user to grant missing scopes"`、`"missing_scopes":["base:record:create"]`。

**② 下一步：需要用户动作，脚本不得自动重试。**
- **不要原样重试**：缺 scope 是账号/应用授权状态问题，重发同一命令必然再失败；
- 读取 `error.missing_scopes`（本例为 `base:record:create`），按 `hint` 引导用户去飞书开放平台为应用开通该权限（或重新走授权流程）；
- 权限开通后，用**原始 argv 原样重跑**一次即可，无需加任何参数；
- 该次失败应上报/记录（错误类型、缺失 scope 清单），属于"需要用户介入"的挂起项。

---

## C（stderr，退出码 4）

**① 判定：失败（网络类，官方标记可重试）。**
依据：
- JSON 写入 **stderr**、退出码 **4**（非 0）；
- `"ok":false`；`error.type=="network"`；`"message":"dial tcp 1.2.3.4:443: connect refused"`；
- 关键字段：`"retryable":true`、`"retry_after_seconds":2` —— 重试依据就是这两个字段，而非凭感觉。

**② 下一步：按字段指示自动重试。**
- 等待 `retry_after_seconds`（**2 秒**）后原样重跑；
- 脚本应实现有限次重试 + 退避（例如最多 3–5 次，间隔按 `retry_after_seconds` 递增），避免对拒绝连接的地址打风暴；
- 连续重试仍失败则停止并上报（检查本机网络/DNS/出口节点），不要无限重试。

---

## D（stderr，退出码 10）

**① 判定：失败——更准确地说是「被安全拦截、操作未执行」。**
依据：
- JSON 写入 **stderr**、退出码 **10**；
- `"ok":false`；`error.type=="confirmation"`；`"message":"high-risk action needs --yes"`；
- 摘录原文：`"action":"delete view vewFGH and its config"`、`"risk":"irreversible deletion"`、`"hint":"append --yes to the end of your original argv after explicit user consent"`。
- 重要推论：**目标视图 vewFGH 当前没有被删除**，退出码 10 是确认门（gate），不是事故。

**② 下一步：人工确认门，绝不能自动通过。**
1. 解析 stderr，确认 `error.type=="confirmation"`，提取 `action` / `risk` / `hint`；
2. **禁止**脚本自作主张追加 `--yes`，禁止伪造"用户已同意"；也**不要原样重试**——不带 `--yes` 重跑只会再次得到 10；
3. 把 `action` 与 `risk`（"delete view vewFGH and its config" / "irreversible deletion"）原样呈现给用户，请求**明确同意**；
4. 用户明确同意后：在**原始 argv 末尾追加 `--yes`** 重跑（严格按 `hint` 的措辞执行）；
5. 用户拒绝或未响应：放弃该操作并上报，保留未执行状态；
6. 建议留痕：谁、何时、批准了对什么对象的不可逆操作。

---

## E（stderr，退出码 2）

**① 判定：失败（校验类：命令在本发行版中不存在）。**
依据：
- JSON 写入 **stderr**、退出码 **2**；
- `"ok":false`；`error.type=="validation"`、`error.subtype=="command_unavailable"`；`"message":"command not available in this distribution"`。

**② 下一步：不可重试，属于脚本/环境缺陷，须上报修复。**
- **不要重试**：这是发行版能力缺失（静态事实），重试与等待都不会改变结果，与 C 类的 `retryable:true` 形成对照；
- 排查方向：命令拼写是否正确 → 当前安装的 lark-cli 发行版/版本是否包含该子命令（升级、换发行版或安装对应插件）；
- 作为缺陷上报：注明命令名、`subtype:command_unavailable`、当前发行版信息；在环境修复前，脚本应跳过该步骤而非空转。

---

## 概念题

### Ⅰ. 为什么「用 code == 0 判断成功」是危险的？

因为退出码是**粗粒度的必要条件，而不是充分条件**，只看它会在两个方向上出错：

1. **假阳性（把失败/空结果当成功）**：
   - code==0 无法告诉你数据是否有效。A 里 success 的完整证据是 `ok:true` **加上** `data.guid` 非空、`meta.count==1`；如果某次返回 code==0 但 `ok:false`、或 `meta.count:0`、或 `data` 里没有你要的字段，只判 code 就会把空/坏结果当有效结果继续消费。
   - 管道与包装层会吞码：`lark-cli ... | tee log` 取到的是 `tee` 的退出码；外层 shell 包装脚本、超时被杀等场景下，0 未必代表 lark-cli 本身真的成功。
2. **假阴性/错误分流（把不同性质的失败混为一谈）**：反过来，"非 0 一律当普通失败"同样危险——B(3) 需要用户开权限、C(4) 需要等待 2 秒重试、D(10) 需要用户明确同意后加 `--yes`、E(2) 需要修环境。若只按 code 是否为 0 分流，最容易酿祸的是对 D **自动补 `--yes`**，绕过人审直接执行不可逆删除。
3. **正确姿势**：退出码用于 shell 层快速分流；权威判定永远是解析返回体——成功路径断言 `ok==true` 并校验所需数据字段，失败路径按 `error.type`/`retryable`/`subtype`/`hint` 分类处理。code==0 只回答"进程正常退出"，不回答"业务上拿到了你要的东西"。

### Ⅱ. 退出码 10 意味着什么？标准处理流程是什么？

**含义**：10 = 高危操作确认门（confirmation gate）。CLI 检测到该命令属于不可逆/高危动作（本例：`delete view vewFGH and its config`，`risk: irreversible deletion`），在**未执行**的状态下主动拦截，要求人类明确授权。它是刻意的 safety interlock，不是工具故障。

**标准处理流程**：
1. 解析 stderr JSON，确认 `error.type=="confirmation"`，记录 `action` / `risk` / `hint`；
2. **绝不自动重试、绝不自动加 `--yes`、绝不伪造用户同意**；不带 `--yes` 原样重跑必然再次得到 10；
3. 向用户原样呈现将要执行的动作与风险，请求**明确同意**（human-in-the-loop）；
4. 用户明确同意 → 按 `hint` 所述，在**原始 argv 末尾追加 `--yes`** 重新执行；
5. 用户拒绝/未响应 → 放弃操作并上报，保持"未执行"状态；
6. 对高危操作留审计痕（批准人、时间、目标对象）。

一句话：**10 的正确姿势是"停下、问人、经同意后带 `--yes` 重放原命令"；任何绕过人审的自动化都违背该设计。**

---

## 五条速查表

| 次 | stdout/stderr | 退出码 | ok | 判定 | 下一步 |
|---|---|---|---|---|---|
| A | stdout | 0 | true | 成功 | 读 `data.guid` 消费结果，无需处理 |
| B | stderr | 3 | false | 授权失败（缺 scope） | 引导用户开通 `base:record:create`，开通后原样重跑；不自动重试 |
| C | stderr | 4 | false | 网络失败（可重试） | 等 `retry_after_seconds`=2s 后重试，限次数+退避，仍败则上报 |
| D | stderr | 10 | false | 高危操作待确认（未执行） | 呈现 action/risk 请用户明确同意；同意后原 argv 末尾追加 `--yes` 重跑；拒绝则放弃并上报 |
| E | stderr | 2 | false | 命令不在本发行版 | 不可重试；核对拼写/升级发行版，作为缺陷上报 |
