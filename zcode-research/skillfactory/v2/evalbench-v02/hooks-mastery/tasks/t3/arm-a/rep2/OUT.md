# T3 · Claude Code Hooks 事件触发分析（arm-a / rep2）

> 分析依据：任务给定的 6 事件表（ask 材料）+ 教学库 `disler/claude-code-hooks-mastery` 的 README 原文存证
> `_raw_README.md`（935 行，ASSET-DOC §13 记录其与上游逐字节一致）。文中所有 `README:L` 引用均指该文件，
> 本次分析已用 grep/sed 逐条核对行号（见文末「核实记录」）。

---

## (a) 逐步触发序列

配置前提：项目 `.claude/settings.json` 恰好为 SessionStart、UserPromptSubmit、PreToolUse、PostToolUse、Stop、PreCompact 这 6 个事件各配了一个 command hook——下表只可能在这些事件上触发。

| 步骤 | 用户操作 | 触发的 hook（按先后） | 可确定的关键 payload 字段值 |
|---|---|---|---|
| 1 | 仓库根目录启动 `claude`，全新会话 | **SessionStart** | `source: "startup"`——README:138 给出三个取值 `"startup"/"resume"/"clear"`；本步是全新启动，非恢复（resume）亦非清屏续接（clear），故取 `"startup"` |
| 2 | 输入 prompt「列出本目录的文件」 | **UserPromptSubmit** | `prompt: "列出本目录的文件"`；`session_id`：字段必在（README §3 payload 表），但其具体值是本次会话的 ID，从题面信息**无法确定**具体取值 |
| 3 | Claude 调用 Bash 执行 `ls`，成功返回 | ① **PreToolUse** →（工具实际执行）→ ② **PostToolUse** | PreToolUse：`tool_name: "Bash"`、`tool_input.command: "ls"`；PostToolUse：`tool_name: "Bash"`、`tool_input.command: "ls"`、`tool_response`（`ls` 的成功输出） |
| 4 | Claude 输出最终回答后尝试结束响应 | **Stop** | `stop_hook_active: false`——该布尔标志（README:123）用于标记「本次停止已是 Stop hook 强制继续后的再次停止」（README:568 以它防无限循环）；本步是本轮**第一次**尝试停止，不存在 hook 强制续跑的前史，故为 `false` |
| 5 | 用户执行 `/compact` 手动压缩 | **PreCompact** | `trigger: "manual"`——README:133 只有 `"manual"/"auto"` 两个取值；`/compact` 由用户显式键入，属 manual 而非上下文满时的 auto。`custom_instructions`：该字段「for manual」存在（README:133），用户裸敲 `/compact` 未附指令，故不带自定义压缩文本（为空/缺省） |

**每步仅触发上述各表中列出的 hook，未触发的**：SessionEnd（会话尚未退出）、SubagentStart/SubagentStop（全程未派发子代理）、以及不在 6 事件配置内的 Setup、Notification、PostToolUseFailure（工具成功返回，无失败）、PermissionRequest（README 生命周期图（ASSET-DOC §3）中它位于 PreToolUse 与工具执行之间；本项目未为它配置 hook，故即使弹权限框也无 hook 可触发）。

注意第 3 步内部顺序：PreToolUse 在工具执行**前**，PostToolUse 在工具执行**后**，二者之间夹着真实的 `ls` 执行，不可颠倒（README:316 「Blocks the tool call」的前提是尚未执行；README:327 「Tool Already Executed」）。

---

## (b) 第 3、4、5 步各 hook 的阻断能力

### 第 3 步

| Hook | 阻断能力 | 原因（原文依据） |
|---|---|---|
| PreToolUse | **能阻断**（拦下 `ls` 这次工具调用） | 它在工具执行**前**触发；退出码 2 = 「Blocks the tool call entirely, shows error message to Claude」（README:316），示例代码 `sys.exit(2)  # Blocks tool call, shows error to Claude`（README:324）；也可用结构化输出 `"decision": "block"`（reason 反馈给 Claude）。工具尚未运行，拦下即不执行 |
| PostToolUse | **不能阻断** | 它在工具成功完成后触发，标题即「CANNOT BLOCK (Tool Already Executed)」——「tool already ran, cannot be undone」（README:327-329）；即便退出码 2 也只是把错误给 Claude，`ls` 的结果已经产生且无法撤销。它能做的只是结果层面的校验/反馈（`"decision": "block"` 让 Claude 据此重试，但那是补救，不是阻断执行） |

### 第 4 步

| Hook | 阻断能力 | 原因（原文依据） |
|---|---|---|
| Stop | **能阻断「停止」** | 它拦截的是 Claude 的收尾动作而非工具；退出码 2 = 「Blocks stoppage … (forces continuation)」（README:341），结构化 `"decision": "block"` 时**必须给 reason** 告诉 Claude 如何继续（ASSET-DOC §5）。阻断后 Claude 被强制续跑。**附带风险**：Stop/SubagentStop 可把停止无限顶回去，务必检查 `stop_hook_active` 防无限循环（README:568）——这正是第 4 步 payload 里该标志的用途：若 hook 见到 `stop_hook_active: true` 仍再次阻断，就会死循环 |

### 第 5 步

| Hook | 阻断能力 | 原因（原文依据） |
|---|---|---|
| PreCompact | **不能阻断** | 明确标注「CANNOT BLOCK」；退出码 2 的行为是「N/A - shows stderr to user only, no blocking capability」（README:351-353）。压缩该发生照样发生，hook 的 stderr 只给用户看，无法给 Claude 也不影响流程；它只能做旁路动作（如本库示例的 transcript 备份） |

一句话总结：**第 3 步一能一不能（PreToolUse 能、PostToolUse 不能）；第 4 步能（但须防死循环）；第 5 步不能。**

---

## (c) Hook 执行环境三事实

以下三条全部出自 README「Hook Execution Environment」节（README:463-467），每条均已在本次会话中用 sed 原文核对：

1. **单 hook 超时上限：60 秒**——「**Timeout**: 60-second execution limit per hook」（README:463）。超时即该 hook 执行被掐断。
2. **同一事件的多个匹配 hook 并行执行**——「**Parallelization**: All matching hooks run in parallel」（README:464）。同一事件若匹配到多个 hook，它们不排队、并发跑。（本题每事件只配了一个 hook，该事实在多 hook 场景才显影。）
3. **输入经 stdin 以 JSON 传入**——「**Input**: JSON via stdin with session and tool data」（README:467）；相应地，输出走 stdout/stderr 加退出码（README:468）。即 hook 脚本从标准输入读整段事件 JSON（含 session 与 tool 数据），而不是靠命令行参数拿 payload。

（同节还有两条可作补充：环境变量继承自 Claude Code（README:465）、工作目录为当前项目目录（README:466）——题目只要求三条，列出备查。）

---

## 核实记录（本次会话实际执行的检查）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `Read ASSET-DOC.md` | 全文 287 行读取；§3（13 事件表）、§5（退出码与阻断表）、§11（限制）为分析主依据 |
| 2 | `grep -n "Timeout.*60" / "Parallelization" / "Input.*JSON via stdin" ... _raw_README.md` | 命中 463/464/466/467 行，另得 123/133/138/324/568 行 |
| 3 | `grep -n "Exit Code 2 Behavior" ...` | 命中 310（UserPromptSubmit 拦 prompt）、316（PreToolUse 拦工具）、329（PostToolUse 不可撤销）、341（Stop 强制继续）、353/359（PreCompact/SessionStart 无阻断） |
| 4 | `grep -n "^## " _raw_README.md` + `sed -n '290,360p' \| grep "^#"` | 确认 290 行起为「Hook Error Codes & Flow Control」，308/314/327/339/351/357 行分别为各 hook 的 CAN/CANNOT BLOCK 小节标题，上文引用行号与章节归属一致 |

全部引用均有原文行号支撑，无凭记忆作答的条目。

---

## 与 ASSET-DOC 的冲突说明

按任务要求核对 ASSET-DOC 与任务正文：**未发现实质冲突**。任务给的 6 事件表（触发时机/payload/阻断能力）与 ASSET-DOC §3、§5 的 README 整理一致，仅两处**范围裁剪**（非矛盾）：① 任务的 payload 列是 README 字段的子集（如 UserPromptSubmit 少列了时间戳、PreCompact 少列了会话信息）；② 任务的科目生命周期省略了 README 图中的 PermissionRequest 环节。依任务指令「以任务为准」，(a) 的触发判定严格限定在任务给定的 6 事件内，PermissionRequest 仅在脚注提及、不计入触发序列。
