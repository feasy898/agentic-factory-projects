# T3 · Claude Code Hooks 事件触发分析（arm-b / rep2）

**分析对象**：一个在 `.claude/settings.json` 中恰好为 6 个事件各配置 1 个 command hook 的项目，涉及事件：`SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`Stop`、`PreCompact`。

**判定基准**：以任务给出的「教学库 README」事件表（触发时机 / payload / 阻断能力）为基准。文末「四」另附 2026-09-29 实际抓取的现行官方文档差异核对，凡两处口径不同均已标明，不混用。

---

## 一、(a) 逐步触发的 hook 序列与关键 payload

6 个已配置 hook 在本题序列中**恰好各触发一次**，总时序：

```
SessionStart → UserPromptSubmit → PreToolUse → [Bash(ls) 实际执行，无 hook] → PostToolUse → Stop → PreCompact
```

逐步明细（按触发先后排序）：

| # | 用户操作 | 触发的 hook（按序） | 可确定的关键 payload 字段 |
|---|---|---|---|
| 1 | 仓库根目录启动 `claude`，**全新**会话 | ① SessionStart | `source: "startup"`（非 resume / clear）；公共字段 `session_id`、`cwd`、`hook_event_name: "SessionStart"` |
| 2 | 输入 prompt「列出本目录的文件」 | ② UserPromptSubmit | `prompt: "列出本目录的文件"`；`session_id`；`hook_event_name: "UserPromptSubmit"` |
| 3 | Claude 调用 Bash 执行 `ls`，成功返回 | ③ PreToolUse →（工具执行）→ ④ PostToolUse | PreToolUse：`tool_name: "Bash"`、`tool_input: {"command": "ls"}`（另含 `tool_use_id`）；PostToolUse：`tool_name: "Bash"`、`tool_input: {"command": "ls"}`、`tool_response: <ls 的成功输出>` |
| 4 | Claude 输出最终回答后尝试结束响应 | ⑤ Stop | `stop_hook_active: false`（该字段为 true 仅当 Claude 已因 stop hook 阻断而继续过；本步是首次尝试停止，故为 false）；另含 `last_assistant_message`（最终回答文本） |
| 5 | 用户执行 `/compact`（无参数） | ⑥ PreCompact | `trigger: "manual"`；`custom_instructions: null`（按官方定义，manual 时该字段为用户传给 /compact 的内容，未传即 null） |

补充说明：

- 工具执行本身（`ls` 的运行过程）不触发任何 hook；hook 只在执行前（PreToolUse）与成功执行后（PostToolUse）触发，二者之间夹着一次真实工具执行。
- 本序列未使用子代理，`SubagentStart` / `SubagentStop` 不触发（项目也未配置这两个事件）；`Setup` 仅在 `--init-only` 等特殊启动下触发，本题不涉及。
- 步骤 5 按教学库表只触发 PreCompact：教学库表 SessionStart 的 source 取值仅 startup / resume / clear，压缩不再触发 SessionStart（现行官方文档口径有扩展，见「四」，主体结论仍按任务表）。

## 二、(b) 第 3、4、5 步各 hook 的阻断能力

| 步骤 | Hook | 能否阻断 | 原因 |
|---|---|---|---|
| 3（前半） | PreToolUse | **能**（阻断工具调用） | 触发点在工具**执行之前**，拦截窗口真实存在：exit code 2（或返回 `decision` / `permissionDecision: "deny"` 类 JSON）→ 工具调用不执行，stderr/理由反馈给 Claude。被阻断的是尚未发生的动作。 |
| 3（后半） | PostToolUse | **不能** | 触发点在工具**已成功执行之后**：`ls` 的副作用已经产生，不存在可取消的对象。阻断式退出码只能把 stderr 作为反馈给 Claude（影响它下一步怎么做），工具不会回滚或重跑。 |
| 4 | Stop | **能**（阻断「停止」） | 触发点在 Claude 试图结束响应时，「停止」本身是可拦截的动作：exit 2（或 `decision: "block"` + `reason`）→ 阻止停止、强制 Claude 继续，stderr/reason 作为继续的理由。防无限循环：必须检查 `stop_hook_active`（为 true 表示本轮已因 stop hook 继续过，不应再次阻断）；现行文档还注明有连续 8 次阻断上限兜底。 |
| 5 | PreCompact | **不能**（按教学库表） | 虽在压缩前触发，但教学库表判定压缩动作不可被 hook 取消：exit code 2 的 stderr 仅展示给用户，压缩照常进行。它属「通知型」hook，用于压缩前做记录/提醒，而非门禁。（现行官方文档已允许 exit 2 / `decision: "block"` 阻断压缩，见「四」。） |

一句话总结：**能阻断的是「动作尚未发生」的事件**（PreToolUse 拦工具调用、Stop 拦停止）；**不能阻断的是「动作已发生或不可取消」的事件**（PostToolUse 的工具结果、PreCompact 的压缩）。

## 三、(c) hook 执行环境事实（3 条）

以下事实均经本会话实际抓取现行官方文档核验（`code.claude.com/docs/en/hooks` 与 `.../hooks-guide`，抓取日期 2026-09-29），关键原文附后。

1. **单 hook 超时上限**：每个 hook 命令有独立超时，可在配置中用 `timeout` 字段（单位：秒）按 hook 覆盖。现行文档默认值按 handler 类型区分：`command` / `http` / `mcp_tool` 默认 **600 秒**，`prompt` 30 秒，`agent` 60 秒；且 `UserPromptSubmit` 事件上 command 类型默认降为 30 秒。到达超时即取消该 hook 并丢弃其输出；在 PreToolUse 上，超时的 command hook 不会阻断工具调用，调用转入正常权限流程。原文："Override per hook with the `timeout` field in seconds."、"Defaults: 600 for `command`, `http`, and `mcp_tool`; 30 for `prompt`; 60 for `agent`."、"UserPromptSubmit hooks have a default timeout of 30 seconds for command… shorter than the 600-second default"。
   *附注：不少教学材料（含可能的旧版教学库）写「默认 60 秒」，那是旧版文档口径；本条以本次核验到的现行文档为准。*
2. **同一事件多个匹配 hook 的执行方式**：**并行执行**，互不等待、互不短路。原文："All matching hooks run in parallel."。补充两条配套事实：同一 handler 在多个 settings 文件重复定义只运行一次（"If you define the same handler in more than one settings file, it runs once."）；一个 hook 返回 deny 不会阻止其余兄弟 hook 执行。
3. **hook 的输入如何传入**：事件上下文以 **JSON 通过 stdin** 传给 command hook（HTTP hook 则作为 POST body）。原文："For command hooks, input arrives on stdin."。公共字段含 `session_id`、`transcript_path`、`cwd`、`hook_event_name` 等，工具事件（PreToolUse/PostToolUse）额外附 `tool_name`、`tool_input`、`tool_use_id`。hook 通过退出码（0 成功 / 2 阻断 / 其他非阻断错误）、stdout、stderr 与宿主通信。

## 四、差异核对：任务表（教学库）vs 现行官方文档（2026-09-29 抓取）

主体结论按任务指定的教学库表给出；用现行文档复核时发现以下口径差异，如实列出备查：

| 项 | 任务表（教学库 README） | 现行官方文档（code.claude.com/docs/en/hooks） |
|---|---|---|
| PreCompact 阻断 | 不能；stderr 仅给用户 | **可阻断**："Exit with code 2 to block compaction… You can also block by returning JSON with `"decision": "block"`."（manual 时 stderr 给用户；阻断自动压缩时，若错过触发时机则照常压缩，Claude 会在下次响应时看到错误） |
| SessionStart source | startup / resume / clear | 还包括 `"compact"`（自动或手动压缩后再次触发）与 `"fork"`；按现行口径，步骤 5 压缩完成后还会再触发一次 SessionStart(source="compact") |
| command hook 默认超时 | （教学材料常见「60 秒」） | 600 秒（UserPromptSubmit 上 30 秒），见 (c)-1 |
| Stop 防循环 | 提示「小心无限循环」 | 明确机制：`stop_hook_active` 字段语义 + 连续 8 次阻断上限（`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` 可调） |
| PostToolUse 阻断 | 不能（工具已执行） | 一致：exit 2 仅 "Shows stderr to Claude; the tool already ran"；另支持 `updatedToolOutput` 改写返回值（但不改变「不可阻断/撤销执行」的定性） |

## 五、来源与核验记录

- 任务材料：任务描述中给出的「教学库 README」事件表（触发时机 / payload / 阻断能力），本题 (a)(b) 主体以其为判定基准。
- 官方文档核验（本会话实际执行）：
  - WebFetch `https://code.claude.com/docs/en/hooks`（两次定向提取：① 退出码/事件表，② 全文读取补充 Stop/PreCompact 细节）——取得 timeout 默认值、并行执行、stdin 输入、per-event exit-2 行为、`stop_hook_active` 定义、PreCompact trigger/custom_instructions 语义、SessionStart source 取值。
  - WebFetch `https://code.claude.com/docs/en/hooks-guide`（一次）——并行执行表述、timeout 按类型覆盖、stdin、`CLAUDE_PROJECT_DIR`。
- 文件操作（本会话实际执行）：`mkdir …\t3\arm-b\rep2` 后以 Write 写入本文件；目录创建经 `ls` 确认（列表出现 `rep1`、`rep2`）。
- 合规声明：按公平性要求，**未读取 skillfactory/ 目录下任何文件**（仅创建产物目录并写入本 OUT.md）。本题属分析题，无项目测试可运行；上文所有「核验」均指文档抓取核对，每个结论已标注出自任务材料还是现行官方文档。
