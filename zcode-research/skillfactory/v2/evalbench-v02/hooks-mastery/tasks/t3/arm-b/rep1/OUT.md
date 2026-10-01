# T3 · Claude Code Hooks 事件触发分析（arm-b / rep1）

分析对象：项目 `.claude/settings.json` 中为 **SessionStart、UserPromptSubmit、PreToolUse、PostToolUse、Stop、PreCompact** 这 6 个事件各配置的一个 command hook。

依据：题目所给的教学库 README 事件表（触发时机 / payload / 阻断能力），以及本次会话实测抓取的官方 hooks 参考文档（`https://code.claude.com/docs/en/hooks`，2026-09-29 抓取）对执行环境事实的核实。凡超出题目表格的结论均单独标注来源。

---

## (a) 逐步触发的 hook 序列与关键 payload

整条时间线（按触发先后）：

```
① SessionStart → ② UserPromptSubmit → ③ PreToolUse → (Bash ls 真实执行) → ③ PostToolUse
→ ④ Stop → ⑤ PreCompact
```

| 步骤 | 用户操作 / 系统动作 | 触发的 hook（按序） | 可确定的关键 payload 字段值 |
|---|---|---|---|
| 1 | 仓库根目录启动 `claude`，全新会话 | **SessionStart** | `source = "startup"`（全新启动，既非 `"resume"` 也非 `"clear"`） |
| 2 | 输入 prompt「列出本目录的文件」 | **UserPromptSubmit** | `prompt = "列出本目录的文件"`；`session_id` = 本会话 ID（UUID，具体值只有运行时才生成，无法从题面确定） |
| 3 | Claude 调用 Bash 工具执行 `ls`，成功返回 | **PreToolUse** →（工具真实执行）→ **PostToolUse** | PreToolUse：`tool_name = "Bash"`，`tool_input` 含 `command = "ls"`（及 description 等字段）；PostToolUse：`tool_name = "Bash"`、`tool_input` 同上、`tool_response` = `ls` 的成功输出结果 |
| 4 | Claude 输出最终回答后尝试结束响应 | **Stop** | `stop_hook_active = false`（这是本次会话**首次**尝试停止，此前没有任何 Stop hook 触发过"继续"；只有当 Stop hook 已让 Claude 继续过、再次尝试停止时才为 `true`） |
| 5 | 用户执行 `/compact` 手动压缩 | **PreCompact** | `trigger = "manual"`（手动 `/compact`，非 `"auto"`）；`custom_instructions = null/空`（用户未附带自定义压缩指令） |

补充说明（每一步只触发表中列出的 hook，不更多）：

- **步骤 1** 只触发 SessionStart。source 取值由进入方式决定：新会话启动 = `"startup"`；若是恢复旧会话则为 `"resume"`，`/clear` 后为 `"clear"`。本题为全新启动，故 `"startup"` 是唯一可确定的取值。
- **步骤 3** 是一对前后夹击的 hook：PreToolUse 在工具执行**之前**触发（此时才能拦截），PostToolUse 在工具**成功完成之后**触发（payload 比前者多出 `tool_response`）。注意若 PreToolUse 当真阻断了调用，`ls` 不会执行、PostToolUse 也不会触发——本题中工具成功返回，所以两者都触发了。
- **步骤 4** Stop 只在 Claude 自身完成响应、主动尝试结束回合时触发；用户手动打断（Esc）不触发它。
- **步骤 5** `/compact` 是手动触发，故 `trigger = "manual"`；若是上下文用量达到阈值自动压缩，则为 `"auto"`。
- 另外，按官方文档，这 6 个事件的 payload 都携带公共字段（`session_id`、`transcript_path`、`cwd`、`hook_event_name` 等），各事件的专有字段叠加其上（来源：本次实测抓取的官方 hooks 参考）。

---

## (b) 第 3、4、5 步中各 hook 的阻断能力及原因

涉及 4 个 hook：PreToolUse、PostToolUse（步骤 3）、Stop（步骤 4）、PreCompact（步骤 5）。

### 步骤 3

| Hook | 能否阻断 | 原因 |
|---|---|---|
| **PreToolUse** | **能**（阻断工具调用） | 它在工具执行**前**运行，拦截在物理上来得及：以退出码 2（或 JSON 决策 deny/block）退出即可取消这次 Bash `ls` 调用，并把 stderr（或 JSON 中的原因）反馈给 Claude，让其调整后重试。拦截点在动作发生前，所以是真正意义上的阻断。 |
| **PostToolUse** | **不能**（无法撤销工具） | 它在工具**成功执行完毕之后**才运行——`ls` 已经跑完、输出已经产生，此时无论 hook 返回什么都无法让工具"没发生过"。退出码 2 的 stderr 会展示给 Claude（可引导它补救/纠正），但这只是"事后反馈"，不是撤销；题目表格亦明确"工具已执行，无法撤销"。 |

### 步骤 4

| Hook | 能否阻断 | 原因 |
|---|---|---|
| **Stop** | **能**（阻断"停止"这个动作） | 退出码 2 可阻止 Claude 结束本轮响应，强制它以 stderr 内容为指令继续工作。两个限定：① 它阻断的是"停止"，不能修改或撤回 Claude 已经输出的回答；② **无限循环风险**——每次阻止停止后 Claude 再次尝试结束时 Stop 会再次触发，因此 payload 提供 `stop_hook_active` 布尔字段（当本回合已经是因 Stop hook 而继续时为 `true`），hook 脚本必须检查该标志并及时放行，否则会陷入"永不能停"的死循环。本题步骤 4 是首次尝试，`stop_hook_active = false`。 |

### 步骤 5

| Hook | 能否阻断 | 原因 |
|---|---|---|
| **PreCompact** | **不能**（按题目所给 README 表格） | 压缩是系统即将执行的维护操作，hook 只是"事前通知"：无论 hook 返回什么退出码，compaction 都照常进行，不存在取消压缩的决策通道；其 stderr 仅展示给用户（transcript / 详细模式），既不会回传给 Claude 也没有阻断语义。 |

> **备注（版本差异，实测核实）**：上表"阻断能力"以题目所给教学库 README 为准作答。本次实测抓取的**最新**官方文档（code.claude.com/docs/en/hooks，2026-09-29）显示两处演进：① 新版已允许 PreCompact 以退出码 2 **阻断压缩**（"Blocks compaction"）；② 新增了 PostCompact 事件、SessionStart 的 `source` 新增 `"compact"`/`"fork"` 取值。教学库基于经典版本表格，故按题面作答。

---

## (c) 3 条 hook 执行环境事实

1. **单 hook 超时上限**：每个 hook 命令有默认超时，且可按 hook 单独配置。经典文档：command hook 默认 **60 秒**/命令；最新官方文档（2026-09-29 实测抓取）：command 类默认 **600 秒**（`prompt` 类 30 秒、`agent` 类 60 秒；UserPromptSubmit 等事件上 command 默认降到 30 秒）。均可在该 hook 条目里用 `timeout` 字段（单位：秒）自定义，超时的 hook 视为失败，`async: true` 的 hook 不受此约束。
2. **同一事件多个匹配 hook 的执行方式**：**所有匹配的 hook 并行执行**（官方原文 "All matching hooks run in parallel"），不存在先后依赖；去重规则是——在多个 settings 文件（user / project / local）中定义的完全相同的 handler 只运行一次，而插件或 skill 自带的同名 handler 仍独立运行。
3. **hook 的输入如何传入**：hook 的 payload 以 **JSON 经 stdin** 传给命令进程（不是命令行参数、不是环境变量；HTTP 类 hook 则作为 POST body）。JSON 含公共字段（`session_id`、`transcript_path`、`cwd`、`permission_mode`、`hook_event_name`）加各事件专有字段（如 `tool_name`/`tool_input`、`prompt`、`trigger`）。返回方向：**退出码** 0 = 成功（stdout 默认只进调试日志，例外是 UserPromptSubmit / SessionStart 会把 stdout 加入上下文；stdout 若是 `{...}` JSON 则按结构化输出解析，可实现高级控制）、**2 = 阻断**（stderr 或 JSON 的 reason 作为阻断信息反馈）、其他非零 = 非阻断错误（stderr 展示给用户，不打断流程）。

---

### 核实记录

- 题面所给 6 事件表（触发时机 / payload / 阻断能力）：题目原文提供，作为 (a)(b) 的主要依据。
- (c) 与公共字段、并行执行、去重、退出码语义：本次会话用 WebFetch 抓取 `https://code.claude.com/docs/en/hooks` 实测核实（返回原文引句："All matching hooks run in parallel"、"a blocking error"、"Blocks the tool call"、"Prevents Claude from stopping, continues the conversation" 等）。
- 未做、也无法做的事：`session_id` 的具体值、`tool_response` 的具体内容属于运行时数据，题面信息不足以确定，文中已如实标注；因公平性限制未读取 skillfactory/ 下任何文件，教学库原文仅以题目摘录为据。
