# PreToolUse 安全防护：防危险命令 Hook 的配置与行为链

> **材料来源**：任务给定的教学库 README 摘录（`pre_tool_use.py` 核心逻辑、退出码语义、`$CLAUDE_PROJECT_DIR` Important 要求）。
> 本文中标注「实测」的结论均来自本次会话实际运行的命令（见文末「验证记录」）；受任务公平性约束，未读取 `skillfactory/` 下任何文件（包括 `pre_tool_use.py` 原文与该库的真实 `settings.json`），对脚本行为的描述一律以任务提供的 README 摘录为准。

---

## (a) `.claude/settings.json` 配置片段（完整、可直接粘贴）

若 `.claude/settings.json` 已有其他配置（如 `permissions`），把下面的 `hooks` 键合并进现有 JSON 顶层即可，不要整文件覆盖。

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
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

逐键说明：

| 键 | 值 | 作用 |
|---|---|---|
| `hooks` | 对象 | settings.json 中 hook 配置的顶层容器，按事件名分组 |
| `PreToolUse` | 数组 | 挂到 **PreToolUse** 事件——每次工具调用**执行之前**触发 |
| `matcher` | `"Bash"` | 只对 Bash 工具调用触发本 hook（危险命令检测只针对 shell 命令）。matcher 是大小写敏感的工具名匹配，支持 `"Bash\|Write"` 这类写法；省略或 `"*"` 则匹配所有工具。若确认该脚本还守护文件工具，可扩成 `"Bash\|Read\|Write\|Edit"` |
| `hooks[].type` | `"command"` | 命令型 hook：起一个 shell 进程执行 `command`，工具调用的 JSON 从 **stdin** 传入 |
| `hooks[].command` | `uv run $CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py` | 该脚本是 **uv 单文件脚本（依赖内嵌）**，必须用 `uv run` 执行；路径必须加 `$CLAUDE_PROJECT_DIR` 前缀——README 标注 **Important**，因为 Claude 可能从任意工作目录发起工具调用，前缀保证路径始终解析到会话启动时的项目根，不依赖当前目录 |

两个可选补充（均不写也能工作）：

- 官方文档还支持在命令条目上加 `"timeout": <秒>`（超时的 PreToolUse hook 不阻断，调用走正常权限流程）；不写则用默认值。
- 官方文档的 shell 形式示例把占位符包在双引号里（`"${CLAUDE_PROJECT_DIR}/..."`）以防路径含空格；本片段沿用教学库 README 的裸 `$CLAUDE_PROJECT_DIR` 前缀写法，两者语义相同。

---

## (b) Claude 试图执行 `rm -rf /tmp/build` 时的完整行为链（阻断）

按时间顺序：

1. **触发**：Claude 发起 Bash 工具调用（`tool_input.command = "rm -rf /tmp/build"`）。因为 (a) 中配置了 `PreToolUse` + `matcher: "Bash"`，Claude Code 在**该命令执行之前**启动 hook 进程：`uv run $CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py`。
2. **输入**：hook 从 **stdin** 收到本次工具调用的 JSON（含 `hook_event_name: "PreToolUse"`、`tool_name: "Bash"`、`tool_input.command` 等字段）。脚本从中取出命令字符串 `command`。
3. **检测命中**：脚本用 README 摘录中的四条正则逐一匹配，`rm -rf /tmp/build` 命中 `rm\s+.*-[rf]`（`rm` + 空白 + 任意内容 + `-r` 或 `-f`）。
   - 实测（用摘录正则原样跑 `re.search`）：`'rm -rf /tmp/build' -> MATCH (pattern 'rm\\s+.*-[rf]', matched 'rm -r')`。
4. **退出**：进入摘录中的阻断分支——向 **stderr** 打印 `BLOCKED: Dangerous rm command detected`，然后 `sys.exit(2)`。
5. **退出码 2 的语义**（README 原文，任务材料）：**阻断错误（blocking error）**，stderr 内容**自动反馈给 Claude**。官方文档同样注明：对 PreToolUse，退出码 2 一律拦截该工具调用，无论是否打印 JSON 决策。
6. **最终结果**：
   - **该工具调用不会执行**——`/tmp/build` 不会被删除，`rm` 进程根本没有被启动；
   - Claude 收到 stderr 里的 `BLOCKED: Dangerous rm command detected`，能理解被拒原因，并据此换用安全命令（例如去掉 `-rf`）；
   - 用户在界面上会看到这条 Bash 调用被 hook 阻止。

一句话链路：**PreToolUse 触发 → stdin 收到命令 JSON → 正则命中 → stderr 写 BLOCKED → exit(2) → 工具调用被取消，stderr 作为反馈送达 Claude。**

---

## (c) 安全命令正常放行时的行为

以 `ls -la`（同理 `echo hello`、`git status`）为例：

1. PreToolUse 同样触发，hook 进程同样收到 stdin JSON——**每条 Bash 命令都会过一遍这个检测**，安全与否对流程无差别。
2. 四条危险正则全部不命中（实测：`'ls -la' / 'echo hello' / 'git status' -> no-match`）。
3. 脚本不进阻断分支，直接正常结束，**退出码 0**。
4. 退出码 0 的语义（README 原文，任务材料）：成功；此时脚本若有 **stdout** 输出，**仅在 transcript 模式（Ctrl-R 回看）中展示给用户**——Claude 看不到它，正常界面也不显示。（对照：官方现行文档把 exit-0 的 stdout 描述为记入调试日志/transcript，仅在少数几个事件中作为上下文可见，PreToolUse 不在其中——与 README 语义一致：安全命令的 stdout 对 Claude 不可见。）
5. **最终结果**：该工具调用**照常执行**，对 Claude 和用户完全透明无感。

三种情形对照表：

| 场景 | 退出码 | stderr 去向 | stdout 去向 | 工具是否执行 |
|---|---|---|---|---|
| `rm -rf /tmp/build`（命中危险正则） | 2 | 自动反馈给 Claude（附阻断原因） | ——（脚本只写 stderr） | **否，被阻断** |
| 安全命令（不命中） | 0 | ——（无输出） | 仅 transcript 模式 Ctrl-R 对用户可见，Claude 不可见 | **是，正常执行** |
| （对照）其他非 0 非 2 退出码 | 如 1 | 展示给用户，**非阻断** | 同 exit 0 | 是，执行继续 |

---

## 本次验证记录（均为本会话实际运行）

| # | 检查 | 命令 | 结果 |
|---|---|---|---|
| 1 | 危险命令命中摘录正则、安全命令不命中 | `python _tmp_hook_check.py`（模式取自任务摘录的 4 条正则，逐条 `re.search`） | `rm -rf /tmp/build`、`sudo rm -rf /var`、`chmod 777 /etc/passwd`、`echo x > /etc/hosts` → MATCH；`ls -la`、`echo hello`、`git status` → no-match |
| 2 | 摘录阻断分支的退出码/stderr 机制 | 同上脚本（`subprocess` 模拟：stderr 打 BLOCKED 后 `sys.exit(2)`；安全分支 `sys.exit(0)`） | blocked: `returncode = 2, stderr = 'BLOCKED: Dangerous rm command detected'`；safe: `returncode = 0, stdout = '', stderr = ''` |
| 3 | (a) 配置片段是合法 JSON | `python -m json.tool _tmp_hook_settings.json`（内容与 (a) 片段逐字一致） | 退出码 0，输出 `JSON_VALID` |
| 4 | 官方文档交叉核对 schema / 退出码 / `$CLAUDE_PROJECT_DIR` / stdin JSON | WebFetch `https://code.claude.com/docs/en/hooks` | 证实：`hooks → PreToolUse → [{matcher, hooks:[{type:"command", command}]}]` 结构、exit 2 对 PreToolUse 一律拦截、`$CLAUDE_PROJECT_DIR` 为"会话启动时的项目根"用于跨工作目录解析路径、命令 hook 经 stdin 收到含 `tool_name`/`tool_input` 的 JSON |

**未做/不能做的**：未读取、未运行 `skillfactory/` 下的任何文件（含 `pre_tool_use.py` 本体与该库真实 `settings.json`）——任务公平性约束所限；因此第 1、2 项是对**任务摘录逻辑**的忠实重放，不是对脚本原件的执行。
