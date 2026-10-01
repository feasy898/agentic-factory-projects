# Claude Code Hooks 配置：文件编辑类工具改动 .py 后自动执行 `ruff format`（失败不打断会话）

> 任务：每次 Claude 用文件编辑类工具修改或新建 `.py` 文件后，自动对该文件执行 `ruff format`；格式化失败时不要打断会话。
> 方法依据：`D:\workspace\zcode研究\skillfactory\v2\evalbench\hooks-mastery\ASSET-DOC.md`（disler/claude-code-hooks-mastery 教学库说明）；退出码/配置 schema 另经官方文档 https://code.claude.com/docs/en/hooks 核对；本机全部实测（ruff 0.16.9 + jq 1.7.1 + Git Bash 5.3.15，Windows）。

---

## 1. 完整 hooks 配置 JSON（settings 文件中的 `hooks` 键下）

放置位置：项目级 `.claude/settings.json`（或用户级 `~/.claude/settings.json`；ASSET-DOC.md:62 亦确认 hook 配置位于 settings.json）。

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "f=$(jq -r '.tool_input.file_path // empty'); case \"$f\" in *.py) ruff format \"$f\" || true;; esac; exit 0"
          }
        ]
      }
    ]
  }
}
```

要点：
- **事件 = `PostToolUse`**：文件编辑类工具成功执行后触发，payload 含 `tool_name`、`tool_input`（ASSET-DOC.md:43-44）。这是唯一能在"文件已被写入"之后对其加工的事件（PreToolUse 时文件还没写出来）。
- **`matcher` = `Write|Edit|MultiEdit|NotebookEdit`**：按官方 schema，matcher 是以 `|` 分隔的工具名精确匹配列表（官方文档，code.claude.com/docs/en/hooks）。覆盖 Claude Code 全部文件写入/编辑工具。
- **结构** = 事件名 → matcher 组数组 → 每组内 `hooks` 数组 → `{"type": "command", "command": ...}`，与官方示例同构（官方文档同页示例 `"matcher": "Edit|Write"`）。
- 该 JSON 已用 `jq` 实测解析通过，命令串转义无损（`jq -c` 读回 matcher/type/command 全部正确）。

## 2. 路径提取方式：stdin JSON + jq 路径 `.tool_input.file_path`

**机制**：Claude Code 以 **stdin JSON** 调用 hook 命令（ASSET-DOC.md:93「输入为 stdin 传入的 JSON」）。PostToolUse 事件下，被编辑文件的路径就在 `tool_input.file_path`——官方文档的 MCP hook 示例正是引用 `${tool_input.file_path}` 这一字段。

hook 收到的 stdin 形如（实测所用样例）：

```json
{
  "session_id": "t1", "cwd": "...", "hook_event_name": "PostToolUse",
  "tool_name": "Write",
  "tool_input": { "file_path": "C:/path/to/demo.py", "content": "..." },
  "tool_response": { "success": true }
}
```

**提取与守卫（逐段解释命令）**：

```sh
f=$(jq -r '.tool_input.file_path // empty')   # 从 stdin JSON 提取路径；缺字段时得空串
case "$f" in *.py) ruff format "$f" || true;; esac   # 仅当路径以 .py 结尾才执行 ruff format
exit 0                                         # 无论前两步发生什么，hook 一律退出 0
```

- jq 程序为 `.tool_input.file_path // empty`：取到路径输出（`-r` 裸串）；`Edit`/`Write`/`MultiEdit` 的文件参数键同名，通吃；`NotebookEdit` 的键是 `notebook_path` 且产出 `.ipynb`——此时 `f` 为空，`case` 不匹配，安全空转。
- `*.py` 为严格后缀匹配，`.txt` 等其他文件不触碰；`ruff format "$f"` 只格式化**被编辑的那一个文件**，不扫全仓。
- `|| true` + 末尾 `exit 0`：ruff 的任何失败（文件不存在、语法损坏等）都被吸收，见第 3 节实测。

**实测证据（本机运行，非纸面推断）**：构造 4 个真实形状的 PostToolUse payload 逐一通过 stdin 喂给上面这条命令（`bash -c '<命令>' < payload.json`，命令与 JSON 中逐字节一致）：

| payload | tool_name | file_path | 提取结果（`jq -r '.tool_input.file_path // empty'`） | 结果 |
|---|---|---|---|---|
| p1 | Write | `…/proj/demo.py` | 提取成功 | `1 file reformatted`，文件内容 `x = {"a": 1,  "b":   2}` / `y=[1,2,3]` 被格式化为 `x = {"a": 1, "b": 2}` / `y = [1, 2, 3]`，**hook exit=0** |
| p2 | Edit | `…/proj/demo.py` | 提取成功 | `1 file left unchanged`，**hook exit=0** |
| p3 | Write | `…/proj/note.txt` | 提取成功 | ruff **未被调用**，note.txt 原样，**hook exit=0** |
| p4 | Edit | `…/proj/ghost.py`（不存在） | 提取成功 | ruff 报错（见下），**hook exit=0** |

## 3. 「格式化失败不打断」：非零退出码行为 + 方案证明

**事件下非零退出码的官方语义**（ASSET-DOC.md:99-113 退出码表 + 阻断能力表；官方文档同义）：

- 退出码 **0**：成功，stdout 仅在转录模式（Ctrl-R）展示；
- 退出码 **2**：阻断错误，stderr 自动反馈给 Claude——但 **PostToolUse 本就不能阻断**（工具已执行、无法撤销），此处 exit 2 的效果只是"把 stderr 给 Claude"；
- **其他非零**：非阻断错误，stderr 展示给用户，**执行继续**。

**为什么本方案满足「失败不打断」（双重保险）**：

1. 结构上，`PostToolUse` 本就是不可阻断事件：即使 hook 非零退出，也无法打断/撤销已完成的编辑（ASSET-DOC.md:113）。
2. 本命令再叠加 `|| true` + 末尾 `exit 0`：**无论 ruff 成败，hook 恒定退出 0**，既不会触发 exit 2 的"stderr 反馈给 Claude"，也不会产生任何 `"decision": "block"` JSON 输出（本命令从不向 stdout 写 JSON）——Claude 与会话对格式化失败完全无感。

**实测证明（p4 场景）**：对不存在的 `ghost.py`，裸命令与 hook 命令对照：

```text
$ ruff format …/proj/ghost.py ; echo $?
error: Failed to format …/proj/ghost.py: 系统找不到指定的文件。 (os error 2)
raw ruff exit=2                                    ← ruff 原始失败码 2

$ <hook 命令> < p4_missing_py.json ; echo $?
error: Failed to format …/proj/ghost.py: … (os error 2)
hook exit=0                                        ← 同一失败，hook 退出 0，会话不受影响
```

另附边界说明：hook 有 60 秒超时（ASSET-DOC.md:93、258）；单文件 `ruff format` 毫秒级，无风险。命令仅调用 PATH 上的 `jq`/`ruff`，不含脚本路径，故无需 `$CLAUDE_PROJECT_DIR` 前缀（该前缀用于 settings 中引用项目内脚本，ASSET-DOC.md:62、259）；前置条件是 `jq` 与 `ruff` 在 PATH 上（`pip install ruff` 或 `uv tool install ruff`）。Windows 下 Claude Code 经 Git Bash 执行 shell 形式的 hook 命令（官方文档；本机已验证 Git Bash 5.3.15 可用）。

## 4. 人工验证步骤（1 条）

1. 把第 1 节 JSON 放入项目的 `.claude/settings.json`，在该项目目录启动 `claude`，输入：「用 Write 工具新建文件 messy.py，内容为 `x = {"a": 1,  "b":   2}` 和 `y=[1,2,3]` 两行；再用 Write 工具新建 note.txt，内容随意」。Claude 两次工具调用完成后，**另开终端检查**：`cat messy.py note.txt`——预期 `messy.py` 已被自动重排为 `x = {"a": 1, "b": 2}` / `y = [1, 2, 3]`（等价地 `ruff format --check messy.py` 显示 would be reformatted 消失/通过），而 `note.txt` 保持原样；且会话中无任何 hook 报错提示、Claude 正常继续对话（不打断）。

---

### 与 ASSET-DOC 的关系说明

ASSET-DOC 与任务无冲突：其最佳实践清单明确「PostToolUse 做结果校验」（ASSET-DOC.md:260），与"编辑后自动格式化"同一事件位；差异仅在于该库自带的 `ruff_validator.py` 走 lint 阻断路线，而本任务要求的是"格式化 + 失败不打断"，故按任务采用恒定 `exit 0` 的非阻断设计。
