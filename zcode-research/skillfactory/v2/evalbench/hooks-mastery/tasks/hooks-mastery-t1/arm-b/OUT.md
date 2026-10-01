# Claude Code Hooks 配置：编辑/新建 .py 后自动 `ruff format`（失败不打断）

> 依据：Claude Code 官方 hooks 文档 `https://code.claude.com/docs/en/hooks`（2026-09-29 实读）。
> 文档关键事实（下文反复引用，均出自该页）：
> - **PostToolUse**："fire after a tool has already executed successfully. The input includes both `tool_input`, the arguments sent to the tool, and `tool_response`"；事件表中 PostToolUse 的 **Can block? = No**。
> - 对文件工具，"`tool_input.file_path` is always absolute: Claude Code expands `~` and relative paths before hooks run. On Windows, the path arrives with backslash separators."
> - hook 的 `command` 默认经 shell 执行："sh -c on macOS and Linux, Git Bash on Windows, or PowerShell when Git Bash isn't installed"，可用 `shell` 字段显式指定。
> - 退出码：exit 2 → "Shows stderr to Claude; the tool already ran"（不阻断）；其他非零 → 非阻断错误，"the action proceeds"，transcript 显示 "Failed with non-blocking status code:"；exit 0 → stdout 只进 debug log、不进 transcript。
> - 配置可放 `~/.claude/settings.json`（用户级）、`.claude/settings.json`（项目级、可提交）、`.claude/settings.local.json`（项目级、gitignore）；对 settings 文件的直接编辑"normally picked up automatically by the file watcher"，`/hooks` 菜单是只读查看器。
> - `timeout` 单位为秒，`command` 类默认 600。

---

## 1. 完整配置 JSON（放入 settings 文件的 `hooks` 键下）

推荐放 `~/.claude/settings.json`（对全部项目生效）或项目 `.claude/settings.json`。以下即 `hooks` 键下的完整内容（若文件已有其他键，合并同级即可）：

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "f=$(jq -r '.tool_input.file_path // empty'); case \"$f\" in *.py) ruff format \"$f\" || true;; esac",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

三要素逐条说明：

| 要素 | 值 | 为什么 |
|---|---|---|
| 事件 | `PostToolUse` | 工具**成功执行完毕后**触发——此时 Write/Edit/MultiEdit 已把新内容落盘，格式化的才是刚写入的文件。`PreToolUse` 在写盘之前触发，格式化的是旧内容，语义不对。 |
| matcher | `Write|Edit|MultiEdit` | 覆盖 Claude Code 全部三个文本文件编辑类工具。纯"字母+竖线"形式按官方语义是**精确枚举列表**（不是正则），不会误命中 `NotebookEdit`（它编辑 `.ipynb`，本就与 .py 无关）。 |
| 命令 | 见上 | 从 stdin 的 JSON 提取路径、只对 `.py` 执行 ruff、失败不传播（细节见 §2、§3）。 |

`timeout: 30` 可省略（command 类默认 600 秒）；设小一点只为避免卡顿感。超时的 hook 被取消后同样不会打断会话。

**Windows 且未安装 Git Bash 时的等价配置**（此时 hook 默认以 PowerShell 执行；也可用 `shell` 字段显式指定）：

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "shell": "powershell",
            "command": "$p=[Console]::In.ReadToEnd()|ConvertFrom-Json; $f=$p.tool_input.file_path; if($f -and $f.EndsWith('.py')){ ruff format $f }; exit 0",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

前置依赖：`ruff` 在 PATH（`pip install ruff`）；POSIX 命令还需 `jq` 在 PATH（jq 二进制单文件即可，本机实测用 jq-1.7.1 官方 release 的 `jq-windows-amd64.exe`）。

---

## 2. 路径提取方式（要求 2）

**机制**：PostToolUse 触发时，Claude Code 把一个 JSON 对象写进 hook 的 stdin，字段包括 `hook_event_name`、`tool_name`、`tool_input`（即发给工具的参数对象）和 `tool_response`。对 `Write`/`Edit`/`MultiEdit`，参数对象里的路径字段就是 **`file_path`**，且文档保证其为**绝对路径**（Windows 下为反斜杠分隔，如 `D:\proj\a.py`）。

**提取**：`jq -r '.tool_input.file_path // empty'` —— 用的 jq 路径是 **`.tool_input.file_path`**；`// empty` 让字段缺失或为 null 时输出空串（而不是字符串 `"null"`），保证后续判断拿到干净的空值。

**过滤**：POSIX 命令用 `case "$f" in *.py)` 通配——**仅当路径以 `.py` 结尾**才执行 `ruff format "$f"`；`.txt`/`.js`/`.json` 等一律不执行任何命令，空值同样跳过。变量一律加双引号（官方安全清单原话："Always quote shell variables: use `\"$VAR\"` not `$VAR`"）。PowerShell 变体用 `$f.EndsWith('.py')` 同义。

**实测证据**（本机 2026-09-29，Git Bash 即 hook 默认 shell；`sh -c "<命令原文>"` 完整复现执行方式，payload 按 stdin 喂入）：

| 用例 | payload 的 `tool_input.file_path` | 结果 |
|---|---|---|
| A1 Write `.py`（正斜杠路径） | `C:/Users/Administrator/AppData/Local/Temp/hookt/ok.py` | stdout `1 file reformatted`，hook-exit=0，文件内容由 `x=1;y=2` 变为 `x = 1` / `y = 2` |
| A2 Write `.py`（反斜杠路径，真实 Windows payload 形态，JSON 转义 `\\`） | `C:\\Users\\...\\hookt\\ok2.py` | stdout `1 file reformatted`，hook-exit=0，内容由 `z = [1,2,3]` 变为 `z = [1, 2, 3]` |
| B Write `.txt` | `.../note.txt` | 无任何输出，hook-exit=0，文件原样 → **ruff 未执行** |
| C 无 `file_path` 的工具（Bash） | （无该字段） | 无输出，hook-exit=0 → 空转 |

---

## 3. 非零退出码行为：为什么"失败不打断"（要求 3）

按官方文档对该事件的定义，逐档列出：

1. **PostToolUse 的 "Can block?" = No**。它在工具**已经执行成功之后**才运行，所以无论 hook 退出码是什么，都不可能阻断、回滚或打断任何东西——能"阻断"的只有 `PreToolUse` 的 exit 2（拦下尚未执行的工具调用）和 `Stop` 的 exit 2（拦下停止），PostToolUse 不具备该能力。这是结构性保证，与命令写法无关。
2. **exit 2**："Shows stderr to Claude; the tool already ran"——stderr 反馈给 Claude，但工具不会重跑、会话不中断。
3. **其他非零**：非阻断错误，"the action proceeds"，仅 transcript 显示 "Failed with non-blocking status code:" 加 stderr 首行。
4. **exit 0**：成功；stdout 只进 debug log（正常会话里连 ruff 的 "1 file reformatted" 都看不见，零噪音）。

**方案内的双保险**：命令尾部 `|| true` 使 hook 自身**恒以 0 退出**——ruff 因语法错误解析失败、文件不存在、甚至 `ruff` 命令不存在（shell 127）都被吞掉，连第 2 档的 stderr 回传都不会发生，Claude 与会话零感知。PowerShell 变体同理，以 `; exit 0` 收尾。

**实测证据**（同一测试序列）：

- **D：对含语法错误的 `.py` 触发**（`bad.py` 内容 `def f(:`）：
  ```
  error: Failed to parse C:/Users/Administrator/AppData/Local/Temp/hookt/bad.py:1:7: Expected a parameter or the end of the parameter list
  hook-exit=0          ← ruff 失败，hook 仍以 0 退出（|| true 生效）
  raw-ruff-exit=2      ← 对照：不经 || true 时 ruff format 的原始退出码
  ```
- **附加韧性**：给 jq 喂一段转义损坏的坏 payload（jq 自身报 `parse error: Invalid escape`），hook 仍 hook-exit=0——连"payload 异常"也不传播。
- PowerShell 变体实测：`1 file reformatted`，ps-exit=0，`ok3.py` 由 `a=1;b=2` 变为 `a = 1` / `b = 2`。
- 超时（30 秒）按文档同样只是取消该 hook、丢弃输出，不打断会话。

> 若希望 ruff 的失败"让 Claude 知道"（比如让它顺手修语法），把 `|| true` 去掉即可：ruff 的 exit 2 会把 stderr 回传给 Claude，但依然不会打断会话——两种语义都安全，本任务按"不打断"取 `|| true`。

---

## 4. 人工验证步骤（要求 4，1 条）

1. 把 §1 的 JSON 合并进 `~/.claude/settings.json`（或项目 `.claude/settings.json`），启动 `claude` 并输入 **`/hooks`**，确认 PostToolUse 分组下已列出 matcher `Write|Edit|MultiEdit` 和该命令；然后对 Claude 说：**"新建 demo_hook_check.py，内容是 `x=1;y=2`"**——等它写完后在终端执行 **`ruff format --check demo_hook_check.py`**：hook 生效时该命令**无输出、退出码 0**（文件已被自动重排为 `x = 1`、`y = 2` 两行；若 hook 未生效，`--check` 会报 `1 file would be reformatted` 且退出码 1）。反向抽查：再让它建一个 `demo_hook_check.txt`，确认其内容保持原样（ruff 未被触发）。

> 配置改动由 settings 文件监视器自动拾取（文档："normally picked up automatically by the file watcher"）；`/hooks` 菜单为只读查看器，用于人工确认登记结果。

---

## 附：本机实测环境与命令（可复现）

- 机器：windev-01（Windows Server 2022，Git for Windows 2.55 → hook 默认 shell 为 Git Bash `sh -c`）；jq 1.7.1（`jq-windows-amd64.exe`，置于 PATH）；ruff 0.16.9（pip 安装）。
- 复现命令（夹具：`ok.py` 内容 `x=1;y=2`、`bad.py` 内容 `def f(:`、`note.txt` 内容 `hello`）：

  ```bash
  CMD='f=$(jq -r '"'"'.tool_input.file_path // empty'"'"'); case "$f" in *.py) ruff format "$f" || true;; esac'
  printf '{"hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":"C:/tmp/hookt/ok.py","content":"x=1;y=2"}}' | sh -c "$CMD"; echo "hook-exit=$?"
  ```

- 全部 7 个用例（A1/A2/B/C/D/坏payload/PS变体）于 2026-09-29 实跑通过，输出摘录见 §2、§3 表格与代码块。
