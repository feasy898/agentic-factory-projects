# PreToolUse 安全防护：配置与行为链（hooks-mastery · t1 · arm-b · rep1）

> 依据材料：任务给出的脚本核心逻辑（`dangerous_patterns` 四条正则、`is_dangerous_rm_command` 阻断分支、`sys.exit(2)`）与 README 原文事实——hook 配置于 `.claude/settings.json`；hook 命令必须以 `$CLAUDE_PROJECT_DIR` 为前缀（README 标注 Important）；退出码语义 **0=成功（stdout 仅在 transcript 模式 Ctrl-R 中展示给用户）、2=阻断错误（stderr 自动反馈给 Claude，阻止工具调用）、其他=非阻断错误（stderr 展示给用户，执行继续）**。脚本为依赖内嵌的 uv 单文件 Python 脚本，由 `uv run` 执行。

---

## (a) `.claude/settings.json` 配置片段（完整、可直接粘贴）

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "uv run \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/pre_tool_use.py"
          }
        ]
      }
    ]
  }
}
```

逐字段说明：

| 字段 | 作用 |
|---|---|
| `hooks.PreToolUse` | 注册到 PreToolUse 事件——在工具调用**执行之前**触发 |
| `matcher: "Bash"` | 只对 Bash 工具调用运行本 hook。本脚本解析的是 `tool_input.command`（shell 命令），对其他工具无意义。matcher 是对工具名的正则；如需扩面可写 `"Bash\|Read\|Write"`，省略则匹配全部工具 |
| `type: "command"` | hook 类型为 shell 命令 |
| `command` 的 `uv run` | 脚本是带内嵌依赖声明（PEP 723 inline script metadata）的 uv 单文件脚本，必须经 `uv run` 启动才能自动建环境并解析依赖。首次运行会解析依赖、稍慢，可另加可选字段 `"timeout": 60`（秒）放宽 |
| `command` 的 `$CLAUDE_PROJECT_DIR` | README 标注 **Important**：用该环境变量锚定项目根，保证 Claude 无论当前工作目录在哪个子目录，hook 都能可靠解析到 `.claude/hooks/pre_tool_use.py`；变量整体加引号，防路径含空格 |

运行机制：Claude Code 启动该命令，并把工具调用上下文以 JSON 写入 hook 进程的 **stdin**（含 `session_id`、`tool_name`、`tool_input.command` 等）；脚本读 stdin、做判断，用**退出码**表达裁决（0 放行 / 2 阻断）。

---

## (b) Claude 试图执行 `rm -rf /tmp/build` 时的完整行为链（被阻断）

1. **触发**：Claude 发起 Bash 工具调用，`command="rm -rf /tmp/build"`。Claude Code 在真正执行该命令**之前**触发 PreToolUse hook。
2. **执行脚本**：以 `uv run "$CLAUDE_PROJECT_DIR"/.claude/hooks/pre_tool_use.py` 启动脚本，其 stdin 收到 JSON：`{"tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/build", ...}, ...}`。
3. **命中规则**：脚本取出 command，`is_dangerous_rm_command("rm -rf /tmp/build")` 返回 **True**——命中第一条正则 `rm\s+.*-[rf]`（`rm` + 至少一个空白 + 任意内容 + 紧跟 `-` 的 `r` 或 `f`；`-rf` 中 `-r` 即满足）。实测验证见文末检查记录。
4. **脚本反应**：向 **stderr** 打印 `BLOCKED: Dangerous rm command detected`，随后 `sys.exit(2)`。
5. **退出码 2 的语义（阻断错误；README 原文：Blocks tool call, shows error to Claude）**：
   - stderr 里的 BLOCKED 消息**不展示给用户**，而是**自动反馈给 Claude**——Claude 在对话上下文中看到阻断原因，可以改用安全命令或向用户求助；
   - 该次工具调用被**取消**：`rm -rf /tmp/build` **不会被执行**，shell 不产生任何副作用（`/tmp/build` 不受影响）。

一句话：脚本退出码 2 → stderr「BLOCKED: …」自动回给 Claude → 工具调用不执行。

---

## (c) 安全命令正常放行时的行为

以 `ls -la /tmp/build`（或任何不命中四条 `dangerous_patterns` 的命令）为例：

1. **检查**：四条正则均不命中 → 不进入阻断分支 → 脚本自然走完，**退出码 0**。
2. **放行**：退出码 0 = 成功，PreToolUse 裁决为允许，Bash 工具调用**照常执行**。
3. **stdout 可见性**：脚本若有 stdout 输出，默认**不进入对话上下文**（Claude 看不到、用户正常界面也看不到），仅当用户进入 transcript 模式（**Ctrl-R**）回看时才可见——对正常工作流完全无感。

---

## 附：退出码语义速查（README 原文）

| 退出码 | 含义 | stderr 去向 | stdout 去向 | 工具是否执行 |
|---|---|---|---|---|
| 0 | 成功 | — | 仅 transcript 模式（Ctrl-R）展示给用户 | 执行 |
| 2 | 阻断错误 | **自动反馈给 Claude** | — | **不执行** |
| 其他 | 非阻断错误 | 展示给用户 | — | 执行（不阻断） |

**已知边界**（由正则本身决定）：`rm file.txt` 这类不带 `-r/-f` 旗标的 rm 不命中 `rm\s+.*-[rf]`，会被放行——该脚本防护面以「带旗标的危险 rm」为主。

---

## 检查记录（本次交付前实际运行）

环境：win32，`python --version`（本机 Python）。运行命令：`python "D:\workspace\zcode研究\_hook_check_tmp.py"`（临时校验脚本，校验后已删除），原始输出：

```text
'rm -rf /tmp/build'            -> hits: ['rm\\s+.*-[rf]']
'sudo rm -rf /tmp/build'       -> hits: ['rm\\s+.*-[rf]', 'sudo\\s+rm']
'ls -la /tmp/build'            -> hits: []
'mkdir -p /tmp/build'          -> hits: []
'rm /tmp/build/log.txt'        -> hits: []
JSON parse: OK
shell-received hook command: uv run "$CLAUDE_PROJECT_DIR"/.claude/hooks/pre_tool_use.py
uses $CLAUDE_PROJECT_DIR: True
invoked via uv run: True
```

结论：(a) 片段为合法 JSON、命令含 `$CLAUDE_PROJECT_DIR` 且经 `uv run` 启动；(b) 的命中判断与 (c) 的放行判断经正则实测确认。

**未运行项**：本环境未启动 Claude Code 会话，故未实测 hook 在 Claude Code 内的端到端触发；(b)(c) 中退出码语义、stderr/stdout 去向、是否执行均引自任务提供的 README 原文，非本次实测。
