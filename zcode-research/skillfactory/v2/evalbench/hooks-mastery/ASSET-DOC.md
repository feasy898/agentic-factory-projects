# ASSET-DOC：disler/claude-code-hooks-mastery（Claude Code Hooks 实战教学库）

> 抓取日期：2026-09-29
> 来源：https://github.com/disler/claude-code-hooks-mastery
> 抓取方式：WebFetch 访问仓库页与 raw 地址 + GitHub API 核实元数据 + `curl -sL` 下载 raw README.md 全文（935 行，已存为本目录 `_raw_README.md` 作为原文存证，下文引用行号均指该文件）
> **关于 SKILL.md**：经 GitHub git trees API 全树检索（`/repos/disler/claude-code-hooks-mastery/git/trees/HEAD?recursive=1`），该仓库**不存在 SKILL.md**（含任意分支路径下无 SKILL 命名文件；`raw.../main/SKILL.md` 实测返回 HTTP 404）。本库的使用说明正文即根目录 `README.md`，本文档据此整理。

---

## 1. 资产基本信息（GitHub API 实测核实）

| 项 | 值 |
|---|---|
| 仓库 | `disler/claude-code-hooks-mastery` |
| 官方描述 | "Master Claude Code Hooks" |
| Stars / Forks | 3929 / 632（API 实测于 2026-09-29） |
| 默认分支 | `main` |
| 最后 push | 2026-03-04（pushed_at；updated_at 2026-09-28） |
| 许可/定位 | 公开教学库：通过可运行示例教你用 Claude Code hooks，对 Claude Code 行为加**确定性（或非确定性）控制**；并覆盖子代理（Sub-Agents）、Meta-Agent、团队化验证（Team-Based Validation） |

---

## 2. 前置依赖（README "Prerequisites"，原文 _raw_README.md:22-36）

**必需：**
- **[Astral UV](https://docs.astral.sh/uv/getting-started/installation/)** — 快速 Python 包安装器与解析器
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Anthropic 的 Claude CLI

**可选：**
- ElevenLabs（TTS 提供方，含 MCP server 集成）及 ElevenLabs MCP Server
- Firecrawl MCP Server（网页抓取）
- OpenAI（LLM + TTS）、Anthropic（LLM）、Ollama（本地 LLM）

---

## 3. 用法总览：13 个 Hook 生命周期事件与 Payload（_raw_README.md:38-164）

该库实现了 Claude Code **全部 13 个 hook 事件**，每个事件对应 `.claude/hooks/` 下一个脚本，并把事件 JSON 记录到 `logs/`。README 用 Mermaid 图给出生命周期：Session（Setup → SessionStart → … → SessionEnd）→ 主循环（UserPromptSubmit → PreToolUse → PermissionRequest → 工具执行 → PostToolUse/PostToolUseFailure → Stop）→ Subagent（SubagentStart → SubagentStop）→ PreCompact。

| # | Hook | 触发时机 | Payload 关键字段 | 增强能力（本库实现） |
|---|---|---|---|---|
| 1 | UserPromptSubmit | 用户提交 prompt 后、Claude 处理前 | `prompt`、`session_id`、时间戳 | 校验、日志、上下文注入、安全过滤 |
| 2 | PreToolUse | 任何工具执行前 | `tool_name`、`tool_input` | 阻断危险命令（`rm -rf`、访问 `.env`） |
| 3 | PostToolUse | 工具成功完成后 | `tool_name`、`tool_input`、`tool_response` | 日志、transcript 转 JSON |
| 4 | Notification | Claude Code 发通知（等待输入等） | `message` | TTS 播报（30% 概率带工程师名字） |
| 5 | Stop | Claude 完成响应时 | `stop_hook_active` 布尔 | AI 生成完成播报 + TTS（LLM 优先级：OpenAI > Anthropic > Ollama > 随机） |
| 6 | SubagentStop | 子代理（Task 工具）完成时 | `stop_hook_active` | TTS "Subagent Complete" |
| 7 | PreCompact | 压缩（compaction）前 | `trigger`（"manual"/"auto"）、`custom_instructions`、会话信息 | transcript 备份 |
| 8 | SessionStart | 新会话启动或恢复 | `source`（"startup"/"resume"/"clear"） | 加载 git 状态、近期 issue、上下文文件 |
| 9 | SessionEnd | 会话结束（exit/sigint/error） | `session_id`、`transcript_path`、`cwd`、`permission_mode`、`reason` | 会话日志 + 临时文件清理 |
| 10 | PermissionRequest | 弹权限对话框时 | `tool_name`、`tool_input`、`tool_use_id` | 权限审计；只读操作（Read/Glob/Grep/安全 Bash）自动放行 |
| 11 | PostToolUseFailure | 工具执行失败时 | `tool_name`、`tool_input`、`tool_use_id`、`error` | 结构化错误日志 |
| 12 | SubagentStart | 子代理（Task 工具）启动时 | `agent_id`、`agent_type` | 启动日志 + 可选 TTS |
| 13 | Setup | 进入仓库（init）或周期性（maintenance） | `trigger`（"init"/"maintenance"） | 经 `CLAUDE_ENV_FILE` 持久化环境、`additionalContext` 注入 |

**架构（UV 单文件脚本）**：所有 hook 是 `.claude/hooks/` 下的独立 Python 脚本，依赖声明内嵌于脚本头部，由 `uv run` 执行——隔离、可移植、免虚拟环境管理、自包含（_raw_README.md:180-191）。

---

## 4. 配置方法与参数（_raw_README.md:537-559, 901-912）

Hook 在 `.claude/settings.json` 中配置，命令必须用 `$CLAUDE_PROJECT_DIR` 前缀保证跨工作目录的路径解析可靠（README 原文标注 **Important**）：

```json
"UserPromptSubmit": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "uv run $CLAUDE_PROJECT_DIR/.claude/hooks/user_prompt_submit.py --log-only"
      }
    ]
  }
]
```

`user_prompt_submit.py` 的三个命令行参数：
- `--log-only`：仅记录 prompt（默认）
- `--validate`：启用安全校验
- `--context`：向 prompt 注入项目上下文

状态栏在 settings.json 中以 `statusLine` 键配置：

```json
{
  "statusLine": {
    "type": "command",
    "command": "uv run $CLAUDE_PROJECT_DIR/.claude/status_lines/status_line_v3.py"
  }
}
```

**Hook 执行环境**（_raw_README.md:461-468）：每个 hook **60 秒超时**；同事件的所有匹配 hook **并行**执行；继承 Claude Code 环境变量；在当前项目目录运行；输入为 **stdin 传入的 JSON**；输出走 stdout/stderr + 退出码。

---

## 5. 退出码与流控（_raw_README.md:290-459）

### 退出码语义

| 退出码 | 行为 | 说明 |
|---|---|---|
| **0** | 成功 | stdout 在 transcript 模式（Ctrl-R）中展示给用户 |
| **2** | **阻断错误** | **关键**：stderr 自动反馈给 Claude |
| 其他 | 非阻断错误 | stderr 展示给用户，执行继续 |

### 各 hook 的阻断能力

| Hook | 能否阻断 | 说明 |
|---|---|---|
| UserPromptSubmit | **能**（阻断 prompt）+ 可加上下文 | 退出码 2 = 整个 prompt 不被 Claude 看到 |
| PreToolUse | **能**（阻断工具调用） | 退出码 2 = 工具不执行，错误给 Claude |
| PostToolUse | **不能** | 工具已执行、无法撤销；退出码 2 仅把错误给 Claude |
| Notification | 不能 | 纯信息性 |
| Stop | **能阻断"停止"** | 强制 Claude 继续；**小心无限循环** |
| SubagentStop | 能阻断子代理停止 | 确保子代理任务完成 |
| PreCompact / SessionStart / SessionEnd | 不能 | stderr 仅给用户 |

### 结构化 JSON 输出控制

所有 hook 通用字段：

```json
{
  "continue": true,
  "stopReason": "string",
  "suppressOutput": true
}
```

- PreToolUse 决策：`"decision": "approve" | "block" | undefined` —— `approve` 绕过权限系统（reason 给用户）；`block` 阻止执行（reason 给 Claude）；`undefined` 走正常权限流。
- PostToolUse 决策：`"decision": "block" | undefined` —— `block` 自动以 reason 重新提示 Claude。
- Stop 决策：`"decision": "block"` 时**必须提供 reason**（告诉 Claude 如何继续）。

**优先级**（_raw_README.md:410-417）：`"continue": false` > `"decision": "block"` > 退出码 2 > 其他退出码。

---

## 6. 示例（README 原文代码，_raw_README.md:320-325, 419-459）

**PreToolUse 阻断危险命令：**

```python
# Block dangerous commands
if is_dangerous_rm_command(command):
    print("BLOCKED: Dangerous rm command detected", file=sys.stderr)
    sys.exit(2)  # Blocks tool call, shows error to Claude
```

**PreToolUse 正则安全过滤：**

```python
dangerous_patterns = [
    r'rm\s+.*-[rf]',           # rm -rf variants
    r'sudo\s+rm',              # sudo rm commands
    r'chmod\s+777',            # Dangerous permissions
    r'>\s*/etc/',              # Writing to system directories
]
```

**PostToolUse 结果校验（JSON 决策阻断）：**

```python
if tool_name == "Write" and not tool_response.get("success"):
    output = {"decision": "block", "reason": "File write operation failed, please check permissions and retry"}
    print(json.dumps(output))
    sys.exit(0)
```

**Stop 完成校验（测试不过不许停）：**

```python
if not all_tests_passed():
    output = {"decision": "block", "reason": "Tests are failing. Please fix failing tests before completing."}
    print(json.dumps(output))
    sys.exit(0)
```

**上下文注入效果**（UserPromptSubmit）：用户输入 `"Write a new API endpoint"`，hook 在 stdout 打印项目标准（REST/OpenAPI 3.0 等），Claude 实际看到「注入的上下文 + 原 prompt」。

**体验命令**（_raw_README.md:532-535）：`cat logs/user_prompt_submit.json | jq '.'`

---

## 7. 子代理（Sub-Agents）（_raw_README.md:571-704）

- **头号误解**（README 加粗原文）：`.claude/agents/*.md` 里写的是**系统提示词（system prompt）**，不是用户提示词。
- **信息流**：`You → Primary Agent → Sub-Agent → Primary Agent → You`。子代理**永不与用户直接对话**、每次**全新上下文**启动、响应的是主代理的 prompt；`description` 字段告诉主代理**何时**派发该子代理（建议写 "use PROACTIVELY" 或触发词）。
- **存储层级**：项目级 `.claude/agents/`（优先）> 用户级 `~/.claude/agents/`；格式为带 YAML frontmatter 的 Markdown：

```yaml
---
name: agent-name
description: When to use this agent (critical for automatic delegation)
tools: Tool1, Tool2, Tool3  # 可选，省略则继承全部工具
color: Cyan
model: opus # 可选 haiku|sonnet|opus，默认 sonnet
---
```

- **Meta-Agent**（`.claude/agents/meta-agent.md`）：生成其他子代理的子代理（"Build the thing that builds the thing"）；直接用自然语言描述想要的代理，主代理自动委派 meta-agent 产出规范 agent 文件。
- **代理链**：可智能串联多个子代理（如 debugger → code-reviewer）。

---

## 8. 团队化验证系统 `/plan_w_team`（_raw_README.md:706-820）

三要素：
1. **自验证**：命令 frontmatter 内嵌 stop hooks（`validate_new_file.py specs/*.md`、`validate_file_contains.py`），产出不合格则反馈给 agent 继续干，直到达标。
2. **代理编排**：基于 Claude Code 任务系统 `TaskCreate` / `TaskUpdate` / `TaskList` / `TaskGet`——任务可并行、可依赖阻塞、依赖完成自动解锁；无需 bash sleep 轮询。
3. **模板化**：生成固定格式的计划（PLAN_NAME / Task / Objective / Team Orchestration / Step-by-Step Tasks）。

**双代理组合**：

| 代理 | 文件 | 工具 | 自验证 | 职责 |
|---|---|---|---|---|
| Builder | `team/builder.md` | 全部工具 | .py 文件过 Ruff + Ty | 执行实现任务 |
| Validator | `team/validator.md` | 只读（无 Write/Edit） | 无 | 验收 Builder 产出 |

**代码质量 validator**（PostToolUse）：`ruff_validator.py`（Write/Edit .py 时 lint 错误即阻断）、`ty_validator.py`（类型错误即阻断）；规则在 `ruff.toml` / `ty.toml`。

**工作流示例**：`/plan_w_team`（生成带编排的计划）→ `/build`（并行执行，Builder 实现、Validator 验收、任务系统协调）。

---

## 9. 输出样式与状态栏（_raw_README.md:822-927）

**输出样式**（`.claude/output-styles/`，用法 `/output-style [name]`）：genui（⭐HTML 内嵌样式）、table-based、yaml-structured、bullet-points、ultra-concise、html-structured、markdown-focused、tts-summary。项目级放 `.claude/output-styles/`，全局放 `~/.claude/output-styles/`。

**状态栏**（`.claude/status_lines/`，v1–v9）：v1 基础 git 信息 → v5 成本跟踪 → v6 上下文窗口用量条 → v7 会话计时 → v8 token/缓存统计 → v9 powerline 极简风。会话数据存 `.claude/data/sessions/<session_id>.json`（prompts、agent_name、extras）。代理自动命名经 `--name-agent` 启用（命名 LLM 优先级 Ollama → Anthropic → OpenAI → 兜底词库）。自定义元数据用 `/update_status_line <session_id> key value`。刷新节流 300ms；v2/v3 按任务类型着色（🔍紫=分析、💡绿=创建、🔧黄=修复、🗑️红=删除、❓蓝=提问）。

---

## 10. 关键文件地图（_raw_README.md:193-275）

```
.claude/settings.json      # hook 配置 + 权限
.claude/hooks/             # 13 个 hook 的 UV 单文件脚本（user_prompt_submit.py 等）
.claude/hooks/validators/  # ruff_validator.py、ty_validator.py（PostToolUse 质量门）
.claude/hooks/utils/       # tts/（ElevenLabs、OpenAI、pyttsx3、tts_queue.py 防重叠）、llm/（task_summarizer.py）
.claude/status_lines/      # status_line.py ~ v9
.claude/output-styles/     # 8 种输出样式
.claude/commands/          # prime.md、plan_w_team.md、crypto_research.md、cook.md、update_status_line.md
.claude/agents/            # crypto/、team/{builder,validator}.md、meta-agent.md、hello-world-agent.md 等
logs/                      # 每种事件一个 JSON 日志 + chat.json（可读会话转录）
ai_docs/                   # 内置 Anthropic hooks/子代理/状态栏/斜杠命令文档与 UV 脚本文档
ruff.toml / ty.toml        # linter 与类型检查配置
```

---

## 11. 限制与注意事项（README 原文明确标注）

1. **Stop hook 无限循环风险**：Stop/SubagentStop 可阻断停止强制继续，不受控会死循环；务必检查 `stop_hook_active` 标志（_raw_README.md:343, 568）。
2. **PostToolUse 不能撤销已执行的工具**：它在校验结果层面起作用，不能阻止执行（_raw_README.md:327-331）。
3. **`chat.json` 只保留最近一次会话**：每次新会话整体覆盖旧内容，不像其他日志那样追加（README 原文 Warning，_raw_README.md:178）。
4. **测试覆盖**：写作时 13 个 hook 中 11 个经自动化测试验证（"11/13 validated via automated testing"，_raw_README.md:169）。
5. **60 秒超时**：单个 hook 执行上限（_raw_README.md:463）。
6. **hook 路径必须用 `$CLAUDE_PROJECT_DIR` 前缀**，否则跨工作目录解析不可靠（_raw_README.md:554）。
7. **最佳实践清单**（_raw_README.md:561-569）：UserPromptSubmit 做早期干预；PreToolUse 做预防；PostToolUse 做结果校验；Stop 做完成保障；错误信息要清晰；防无限循环；先在安全环境充分测试。

---

## 12. 相关资源（README 原文引用的链接）

- Anthropic 官方 Hooks 文档：https://docs.anthropic.com/en/docs/claude-code/hooks
- YouTube 走查：子代理 https://youtu.be/7B2HJr0Y68g ；团队工作流 https://youtu.be/4_2j5wgt_ds ；输出样式与状态栏 https://youtu.be/mJhsWrEv-Go
- 作者课程 Tactical Agentic Coding（agenticengineer.com）与 IndyDevDan 频道
- 本库 `ai_docs/` 目录自带 Anthropic hooks 完整文档副本（`ai_docs/claude_code_hooks_docs.md`、`claude_code_hooks_getting_started.md` 等）

---

*本文档由抓取任务于 2026-09-29 生成；所有内容忠实整理自 README.md 原文（`_raw_README.md`，935 行），元数据经 GitHub API 实测核实。*
