# PreToolUse 安全防护：挂载 `pre_tool_use.py` 与行为链（hooks-mastery t1）

> 依据：`disler/claude-code-hooks-mastery` 教学库 README 原文（本目录存证 `_raw_README.md`，935 行，ASSET-DOC 记录 2026-09-29 刷新核验与上游逐字节一致）+ 上游真实 `.claude/settings.json` 与 `.claude/hooks/pre_tool_use.py`（本会话经 `curl -sL https://raw.githubusercontent.com/disler/claude-code-hooks-mastery/main/...` 实际抓取）+ 本会话对真实脚本的实测运行记录（见文末验证表）。

---

## (a) `.claude/settings.json` 配置 JSON 片段（完整、可直接粘贴）

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "uv run $CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py"
          }
        ]
      }
    ]
  }
}
```

要点说明：

- **结构**：顶层 `"hooks"` → 事件键 `"PreToolUse"`（值为数组）→ 数组元素含 `"matcher"` 与 `"hooks"` 数组 → hook 对象必须含 `"type": "command"` 与 `"command"` 两个字段。若 `settings.json` 已有其他配置（如 `permissions`、`statusLine`），把整个 `"PreToolUse": [...]` 键并入现有 `"hooks"` 对象即可，不要再写一个重复的顶层 `"hooks"`。该片段与上游仓库 `.claude/settings.json` 中 PreToolUse 条目逐字一致（本会话抓取实测）。
- **`$CLAUDE_PROJECT_DIR` 前缀是硬要求**：README 原文标注 **Important**（`_raw_README.md:554`）——hook 命令必须用 `$CLAUDE_PROJECT_DIR` 前缀，否则 Claude 在子目录工作时相对路径解析不到脚本、hook 静默失效；写死绝对路径则换机器/移动仓库即失效。
- **`uv run`**：脚本是依赖内嵌的 UV 单文件脚本（PEP 723 元数据），`uv run` 负责隔离解析依赖并执行，无需虚拟环境。
- **`"matcher": ""`**（上游原库写法）表示对所有工具触发。推荐保持空 matcher，因为真实脚本除拦截 Bash 危险命令外，还保护 Read/Edit/MultiEdit/Write 对 `.env` 敏感文件的访问（`pre_tool_use.py` 的 `is_env_file_access`）；若只想过滤 shell 命令，可窄化为 `"matcher": "Bash"`。
- hook 执行环境（`_raw_README.md:461-468`）：单 hook 60 秒超时；同一事件的所有匹配 hook 并行执行；继承 Claude Code 环境变量；在当前项目目录运行；输入为 **stdin 传入的 JSON**（含 `session_id`、`tool_name`、`tool_input`）。

---

## (b) Claude 试图执行 `rm -rf /tmp/build` 时的完整行为链

1. **发起调用**：Claude 创建 Bash 工具调用，`tool_input.command = "rm -rf /tmp/build"`。
2. **触发时机**：Claude Code 在**工具执行之前**触发 PreToolUse hook（生命周期：UserPromptSubmit → **PreToolUse** → PermissionRequest → 工具执行 → PostToolUse），即在权限流程之前先过安全钩子。
3. **执行 hook 命令**：`uv run $CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py`；Claude Code 通过 **stdin** 传入 JSON payload：`{"session_id": "...", "tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/build"}}`；hook 在当前项目目录运行、继承环境变量、限时 60 秒。
4. **脚本判定**：脚本 `json.load(sys.stdin)` 后发现 `tool_name == "Bash"`，提取 `command`，调用 `is_dangerous_rm_command("rm -rf /tmp/build")`：命令小写归一化后，模式 `r'\brm\s+.*-[a-z]*r[a-z]*f'` 命中 `-rf` → 判定危险（README 教学版简化正则 `r'rm\s+.*-[rf]'` 同样命中，本会话均已实测）。
5. **脚本输出与退出码**：向 **stderr** 打印 `BLOCKED: Dangerous rm command detected and prevented`（README 教学版简写为 `BLOCKED: Dangerous rm command detected`），然后 `sys.exit(2)`（`_raw_README.md:320-325` 原文示例）。
6. **退出码 2 = 阻断错误**：Claude Code 看到退出码 2 后，**该工具调用被完全阻断，`rm -rf /tmp/build` 不会被执行**（`_raw_README.md:314-318`："Blocks the tool call entirely"）。
7. **stderr 去向**：退出码 2 时 **stderr 被自动反馈给 Claude**（`_raw_README.md:301`："**Critical**: stderr is fed back to Claude automatically"）——Claude 收到 "BLOCKED: Dangerous rm command detected …"，明白调用因安全策略被拒，可改用其他方案；用户在界面上看到的是被拒绝的工具调用。此路径下脚本在写日志之前即退出，`logs/pre_tool_use.json` **不新增记录**。

本会话对上游真实脚本的实测（临时目录运行）：

```text
$ printf '%s' '{"session_id":"test-sess","tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/build"}}' | uv run cc_pre_tool_use.py
exit_code=2
stdout: （空）
stderr: BLOCKED: Dangerous rm command detected and prevented
```

---

## (c) 安全命令正常放行时的行为（如 `ls -la`）

1. PreToolUse 同样触发、同样经 stdin 收到 JSON payload。
2. 脚本解析后**无任何危险模式命中**（README 教学版 4 条正则与真实脚本 `is_dangerous_rm_command` 均不命中，本会话实测确认）。
3. 脚本把本次事件追加写入 `<项目目录>/logs/pre_tool_use.json`（其输出副作用是日志文件，不是 stdout），然后 `sys.exit(0)`；即使 stdin 非法或内部异常也优雅地 `exit(0)`，绝不误伤正常工具。
4. **退出码 0 = 成功**（`_raw_README.md:300`）：hook 未输出 `decision` JSON、退出码为 0，不产生任何阻断或修改，**工具调用照常继续执行**（此后仍走 Claude Code 正常权限流程）。
5. **stdout 可见性**：退出码 0 时，stdout 仅在 **transcript 模式（Ctrl-R）中展示给用户**，不会进入 Claude 的上下文，也不会主动弹给用户；且该脚本成功路径本就不向 stdout 打印任何内容，所以正常会话界面上用户与 Claude 都看不到 hook 的任何输出。

本会话对上游真实脚本的实测：

```text
$ printf '%s' '{"session_id":"test-sess","tool_name":"Bash","tool_input":{"command":"ls -la"}}' | uv run cc_pre_tool_use.py
exit_code=0
stdout: （空）  stderr: （空）
logs/pre_tool_use.json => 新增 {"session_id":"test-sess","tool_name":"Bash","tool_input":{"command":"ls -la"}}
```

---

## 附：退出码速查（README 原文，`_raw_README.md:298-302`）

| 退出码 | 行为 | 说明 |
|---|---|---|
| **0** | 成功 | stdout 仅在 transcript 模式（Ctrl-R）中展示给用户 |
| **2** | **阻断错误** | stderr 自动反馈给 Claude；PreToolUse 下 = 工具调用不执行 |
| 其他 | 非阻断错误 | stderr 展示给用户，执行继续 |

---

## 验证记录（全部为本会话实际执行）

| # | 检查 | 命令 | 结果 |
|---|---|---|---|
| 1 | 抓取上游真实配置与脚本 | `curl -sL https://raw.githubusercontent.com/disler/claude-code-hooks-mastery/main/.claude/settings.json` 与 `.../main/.claude/hooks/pre_tool_use.py` | 均成功；PreToolUse 条目即 (a) 片段；脚本逻辑（stdin JSON → 匹配 → stderr+exit 2 / 写日志+exit 0）与 ASSET-DOC §4/§6 一致 |
| 2 | 危险命令阻断 | `printf '%s' '{"tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/build"}}' \| uv run cc_pre_tool_use.py` | `exit_code=2`，stdout 空，stderr=`BLOCKED: Dangerous rm command detected and prevented` |
| 3 | 安全命令放行 | 同上，command 换为 `ls -la` | `exit_code=0`，stdout/stderr 均空，`logs/pre_tool_use.json` 新增该事件 |
| 4 | README 教学版正则 | `python -c "import re; ..."`（对 `rm -rf /tmp/build`、`ls -la`、`echo hello` 逐一匹配 4 条 `dangerous_patterns`） | `rm -rf /tmp/build` 命中 `rm\s+.*-[rf]`；两个安全命令均不命中 |

---

## 依据引用

- `_raw_README.md:298-302` 退出码语义表；`:314-318` PreToolUse CAN BLOCK TOOL EXECUTION；`:320-325` 阻断代码示例（`print(..., file=sys.stderr)` + `sys.exit(2)`）；`:424-428` `dangerous_patterns` 四条正则；`:410-417` 流控优先级（`continue:false` > `decision:block` > 退出码 2 > 其他）；`:461-468` 执行环境（60s 超时 / 并行 / stdin JSON / 项目目录运行）；`:537-554` 配置方法与 **Important** 的 `$CLAUDE_PROJECT_DIR` 前缀要求。
- `ASSET-DOC.md` §4（配置方法）、§5（退出码与各 hook 阻断能力）、§6（示例）、§13（2026-09-29 刷新核验，上游无变化）。
- 上游真实文件（本会话抓取）：`.claude/settings.json` 的 PreToolUse 条目、`.claude/hooks/pre_tool_use.py`（`is_dangerous_rm_command`、`is_env_file_access`、`main()`）。

## 任务与资产说明的冲突注明

**无实质冲突。** 唯一差异：任务引文是 README 的教学版片段（4 条简化正则 + 消息 `"BLOCKED: Dangerous rm command detected"`），而上游真实 `pre_tool_use.py` 使用更丰富的 `is_dangerous_rm_command` 多模式判定 + 消息 `"BLOCKED: Dangerous rm command detected and prevented"`；对 `rm -rf /tmp/build` 而言两版判定结果、退出码与阻断行为完全一致（上表 #2/#4 均已实测）。本文两版并陈，(a)(b)(c) 结论不受影响。按要求在此注明。
