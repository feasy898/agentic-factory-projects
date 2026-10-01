# T3：Claude Code Hooks 事件触发分析（arm-a / rep1）

> **依据**：任务给定的 6 事件表（摘自教学库 README）、disler/claude-code-hooks-mastery 原文存证 `_raw_README.md`（935 行，本目录上两级，行号引用格式 `_raw_README.md:<行号>`）、`ASSET-DOC.md`；另以 Claude Code 官方文档（code.claude.com/docs/en/hooks，2026-09-29 抓取全文）做交叉核验。所有结论的出处见正文行号引用与文末「验证记录」；未能实测的项目已如实标注。

**场景设定**：项目 `.claude/settings.json` 恰好为 6 个事件各配 1 个 command hook——`SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`Stop`、`PreCompact`。其余 7 个生命周期事件（Setup、SessionEnd、Notification、PermissionRequest、PostToolUseFailure、SubagentStart、SubagentStop）**未配置**，因此下文只统计这 6 个事件的触发情况。

---

## (a) 逐步触发序列（按触发先后排序）

### 汇总表

| 步骤 | 用户操作 | 触发的已配置 hook（按序） | 可确定的关键 payload 值 |
|---|---|---|---|
| 1 | 仓库根目录启动 `claude`，全新会话 | ① SessionStart | `source = "startup"` |
| 2 | 输入 prompt「列出本目录的文件」 | ② UserPromptSubmit | `prompt = "列出本目录的文件"`；`session_id` = 本会话 ID（字段必在，具体值运行时生成、**不可预知**） |
| 3 | Claude 调 Bash 执行 `ls`，成功返回 | ③ PreToolUse →（工具执行）→ ④ PostToolUse | PreToolUse：`tool_name = "Bash"`、`tool_input = {"command": "ls"}`；PostToolUse：`tool_name = "Bash"`、`tool_input` 同前、`tool_response` = `ls` 的目录列表（**具体内容取决于目录内容，不可确定**） |
| 4 | Claude 输出最终回答后尝试结束响应 | ⑤ Stop | `stop_hook_active = false`（推理见下） |
| 5 | 用户执行 `/compact` 手动压缩 | ⑥ PreCompact | `trigger = "manual"`；`custom_instructions` = `null`（未附带说明） |

### 逐步说明

**第 1 步 → SessionStart（source="startup"）**
SessionStart 的触发时机是"新会话启动或恢复"（`_raw_README.md:136-137`），payload 含 `source`，取值 "startup"/"resume"/"clear"（`_raw_README.md:138`）。本次是**全新会话**（非 `--resume`/`--continue` 恢复、非 `/clear` 后重开），故 **`source = "startup"`**，此值可确定。
附注：完整生命周期中 Setup 位于 SessionStart 之前（`_raw_README.md:48-49, 82`；其触发时机为进入仓库 init 或周期 maintenance，`_raw_README.md:161-163`），但 Setup 不在本项目配置的 6 个 hook 之列，故本步在「已配置 hook」范围内只触发 SessionStart 一个。

**第 2 步 → UserPromptSubmit（prompt 可确定）**
触发时机：用户提交 prompt 后、Claude 处理前（`_raw_README.md:102-104`）。payload：`prompt = "列出本目录的文件"`（可确定）；`session_id` = 第 1 步建立的会话 ID——字段必然存在，但 ID 由 Claude Code 运行时生成，题目信息不足以确定其具体值（README 原文另提到 timestamp 字段，`_raw_README.md:104`；任务表未列，不影响结论）。

**第 3 步 → PreToolUse → 工具执行 → PostToolUse（两个 hook，先后触发）**
Claude 决定调用 Bash 工具后：

1. **PreToolUse** 先触发（"任何工具执行前"，`_raw_README.md:107-109`）：`tool_name = "Bash"`、`tool_input = {"command": "ls"}`（二者可确定；`tool_input` 的形态即 Bash 工具的参数对象，命令串在 `command` 字段）。hook 若放行，工具才继续往下走。
   （完整生命周期里 PreToolUse 与工具执行之间还可能有 PermissionRequest 权限对话框事件——`_raw_README.md:61-62, 86-87`——但它未配置，且 `ls` 这类只读命令通常也不弹权限框，故不在统计范围。）
2. **工具成功执行**：`ls` 返回目录列表。
3. **PostToolUse** 后触发（"工具成功完成后"，`_raw_README.md:112-114`）：`tool_name = "Bash"`、`tool_input = {"command": "ls"}`、`tool_response` = 工具返回结果（即 `ls` 的输出）。`tool_response` 的**具体内容不可确定**——它取决于该目录下有什么文件。
   注意 **PostToolUseFailure 不触发**：它只在工具执行失败时触发（`_raw_README.md:151-153`），本步 `ls` 成功返回。

**第 4 步 → Stop（stop_hook_active=false）**
触发时机：Claude 完成响应时（`_raw_README.md:121-123`），payload 关键字段是布尔标志 `stop_hook_active`。该标志的语义（官方文档原文）："`true` when Claude Code is already continuing as a result of a stop hook"——即只有当 Claude **已经因上一次 Stop hook 阻断而被强制继续**、再次走到停止点时才为 `true`（教学库的对应告诫：Stop hook 必须检查该标志以防无限循环，`_raw_README.md:343, 568`）。本序列此前没有任何 Stop 阻断发生，这是**第一次**尝试停止，故可推定 **`stop_hook_active = false`**。

**第 5 步 → PreCompact（trigger="manual"）**
触发时机：压缩操作执行前（`_raw_README.md:131-133`）。payload：`trigger` 取 "manual" 或 "auto"（`_raw_README.md:133`）——用户**显式执行 `/compact`** 属手动触发，故 **`trigger = "manual"`**（可确定）；`custom_instructions` 是手动压缩时用户随 `/compact` 传入的说明，本次用户未附带任何说明，故为 **`null`/无**（官方文档明确：manual 时 `custom_instructions` 为用户传入内容、"is `null` when they pass nothing"）。
附注：压缩完成后会话继续存在，**SessionEnd 不触发**（会话并未结束）；全程未使用 Task/子代理，**SubagentStart、SubagentStop 也不触发**。

---

## (b) 第 3、4、5 步中各 hook 的阻断能力

### 第 3 步（Bash `ls` 调用）

| Hook | 能否阻断 | 原因 |
|---|---|---|
| PreToolUse | **能**（阻断工具调用） | 此刻工具**尚未执行**。退出码 2 的语义就是 "Blocks the tool call entirely, shows error message to Claude"（`_raw_README.md:314-318`，示例代码 `sys.exit(2)  # Blocks tool call` 在 320-325 行）；结构化 JSON 路径上 `"decision": "block"` 使工具不执行且 `reason` 给 Claude、`"approve"` 可绕过权限系统放行（`_raw_README.md:376-386`）。阻断发生在破坏发生之前，所以是真正的拦截点。 |
| PostToolUse | **不能** | 触发时工具**已经成功执行完毕**，结果无法撤销——README 该节标题即 "CANNOT BLOCK (Tool Already Executed)"，"Cannot prevent tool execution since it fires after completion"（`_raw_README.md:327-331`）。退出码 2 只是把错误信息给 Claude（`_raw_README.md:329`）；JSON `"decision": "block"` 也只是"自动以 `reason` 重新提示 Claude"（`_raw_README.md:388-397`），即最多促使 Claude 去补救（如删掉刚写的文件），改变不了"命令已经跑过"这一事实。 |

### 第 4 步（Claude 尝试停止）

| Hook | 能否阻断 | 原因 |
|---|---|---|
| Stop | **能**（阻断"停止"这个动作） | README 该节标题 "CAN BLOCK STOPPING"：退出码 2 "Blocks stoppage, shows error to Claude (**forces continuation**)"（`_raw_README.md:339-342`）；JSON 路径 `"decision": "block"` **必须提供 `reason`**，告诉 Claude 该如何继续（`_raw_README.md:399-408`）。它阻断的不是某个工具，而是"结束本轮响应"本身——强制 Claude 继续工作。**附带的警戒**：README 明示 "Can cause infinite loops if not properly controlled"（`_raw_README.md:343`），最佳实践要求在 Stop hook 里检查 `stop_hook_active` 标志（`_raw_README.md:568`；ASSET-DOC §11 第 1 条）。本序列中 hook 未阻断，Claude 正常停止。 |

### 第 5 步（`/compact` 手动压缩）

| Hook | 能否阻断 | 原因 |
|---|---|---|
| PreCompact | **不能**（按教学库 README / 任务给定表） | README 该节标题 "CANNOT BLOCK"，退出码 2 行为 "N/A - shows stderr to user only, no blocking capability"，stderr 仅给用户看（`_raw_README.md:351-355`）；ASSET-DOC §5 阻断表同判："PreCompact / SessionStart / SessionEnd 不能，stderr 仅给用户"。压缩照常进行，hook 只能做转录备份等副作用（本库 `pre_compact.py` 的用途即 transcript 备份）。 |

---

## (c) 3 条 hook 执行环境事实

出处：`_raw_README.md:461-468`（"Hook Execution Environment" 一节），ASSET-DOC §4 同文转述。

1. **单 hook 超时上限**：每个 hook 执行上限 **60 秒**（"**Timeout**: 60-second execution limit per hook"，`_raw_README.md:463`；ASSET-DOC §11 第 5 条同）。
2. **同一事件多个匹配 hook 的执行方式**：**并行执行**（"**Parallelization**: All matching hooks run in parallel"，`_raw_README.md:464`）——不是按顺序串行跑，官方文档同文确认（"All matching hooks run in parallel"），因此同事件的多个 hook 之间不能依赖先后顺序。
3. **hook 的输入如何传入**：以 **JSON 经 stdin 传入**（"**Input**: JSON via stdin with session and tool data"，`_raw_README.md:467`）——hook 脚本从标准输入读取含会话与工具数据的 JSON，输出则经 stdout/stderr 加退出码交回（`_raw_README.md:468`）。

（同节还有两条环境事实，供补全：hook **继承 Claude Code 的环境变量**、**在当前项目目录中运行**，`_raw_README.md:465-466`。）

---

## 与 ASSET-DOC 的一致性核对与注记（按任务要求置于文末）

1. **任务 vs ASSET-DOC**：逐项比对后，6 个事件的触发时机、payload 字段、阻断能力在任务表与 ASSET-DOC §3/§5 中**完全一致**；唯一差异是 ASSET-DOC §3 表（及 README:104）给 UserPromptSubmit 多列了一个「时间戳」字段，任务表未列——不构成实质冲突，正文已附带说明。**本任务未发生"说明与任务冲突需以任务为准"的裁决项。**
2. **README（=任务表依据）与当前官方文档的两处差异**（2026-09-29 抓取 code.claude.com/docs/en/hooks 核验，正文按任务给定的 README 基准作答，特此注明）：
   - **PreCompact 阻断能力**：README/任务表判"不能阻断"；当前官方文档已写明 "Exit with code 2 to block compaction"（也可用 JSON `decision: "block"`）。即按最新官方行为第 5 步的 PreCompact 其实**可以**阻断压缩，本文按题目基准答"不能"并在此存证。
   - **单 hook 默认超时**：README 记 60 秒；当前官方文档为可配置 `timeout` 字段，command hook 默认 600 秒（UserPromptSubmit 等个别事件降为 30 秒）。(c) 第 1 条按题目基准答 60 秒。
   - 另：官方文档的 SessionStart `source` 取值已扩展为 startup/resume/clear/compact/fork，本场景全新会话仍为 "startup"，结论不受影响。
3. **未实测项声明**：本机为 zcode 环境无 claude CLI，未实际运行该 5 步会话序列；(a)(b)(c) 全部结论基于对 `_raw_README.md`（935 行存证）、`ASSET-DOC.md` 与官方文档的文本证据，非运行时实测。`stop_hook_active=false`、`custom_instructions=null` 两值是依据字段语义从题面条件推出的确定值，推理过程已在正文标注。

---

## 验证记录（本次 ask 内实际执行的读取与命令）

| # | 操作 | 命令/方式 | 结果 |
|---|---|---|---|
| 1 | 读 ASSET-DOC | Read `skillfactory/v2/evalbench-v02/hooks-mastery/ASSET-DOC.md` 全文（288 行） | 取得 §3 事件表、§4 执行环境（60s/并行/stdin）、§5 阻断表、§11 注意事项 |
| 2 | 读 README 存证·退出码与执行环境 | `grep -n "" _raw_README.md \| sed -n '286,470p'` | 命中：退出码表(298-302)、各 hook 阻断能力原文(308-361)、JSON 决策字段(376-408)、优先级(410-417)、执行环境 5 条事实(461-468) |
| 3 | 读 README 存证·生命周期与 payload | `grep -n "" _raw_README.md \| sed -n '38,178p'` | 命中：Mermaid 生命周期(44-100)、13 事件触发时机与 payload 定义(102-164) |
| 4 | 读 README 存证·UserPromptSubmit 深入 | `grep -n "" _raw_README.md \| sed -n '470,570p'` | 命中：深入解析(470-559)、`$CLAUDE_PROJECT_DIR` 要求(554)、stop_hook_active 防循环告诫(568) |
| 5 | 官方文档交叉核验 | WebFetch `https://docs.anthropic.com/en/docs/claude-code/hooks` → 301 重定向 → WebFetch `https://code.claude.com/docs/en/hooks` → web_reader 全文抓取 | 取得原文引句：stop_hook_active 语义、"All matching hooks run in parallel"、"Command hooks receive JSON data via stdin"、SessionStart source 含 startup/resume/clear/compact/fork、PreCompact "Exit with code 2 to block compaction"、超时默认 600/30 秒 |
| 6 | 确认交付目录为新建 | `ls -R .../tasks`（写文件前） | 当时仅存在 t1、t2；t3/arm-a/rep1 由本次交付创建 |
