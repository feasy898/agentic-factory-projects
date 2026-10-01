# 安全护栏 Hook：禁止 AI 对 .env / .env.* 做任何写操作（Write / Edit 全拦）

> 需求（原文）：『禁止 Claude 对 .env 文件做任何写操作（Write/Edit 工具都算），命中时向用户说明原因并阻断本次工具调用；.env 的变体文件（如 .env.local、.env.production）也要拦。』
>
> 方法依据：`skillfactory/v2/evalbench/hooks-mastery/ASSET-DOC.md`（disler/claude-code-hooks-mastery 实战教学库）。要点映射：
> - 预防性拦截用 **PreToolUse**：`退出码 2 = 工具不执行，错误给 Claude`（ASSET-DOC.md §5，`:112`）；PreToolUse 的经典用途就是"阻断危险命令（rm -rf、访问 .env）"（ASSET-DOC.md §3 `:43`）。
> - Hook 输入为 **stdin 传入的 JSON**，关键字段 `tool_name`、`tool_input`（ASSET-DOC.md §3 `:43`、§4 `:93`）。
> - 命令必须以 `$CLAUDE_PROJECT_DIR` 前缀，否则跨工作目录路径解析不可靠（ASSET-DOC.md §4 `:62`、§11 `:259`）。
> - 脚本采用该库的 **UV 单文件风格**：仅标准库、无第三方依赖、`uv run` 直接执行（ASSET-DOC.md §3 `:56`）。
>
> 本目录交付物：`OUT.md`（本文）、`env_guard.py`（hook 脚本实体）、`run_tests.py`（测试执行器）。全部结论均在本机实测（详见 §4）。

---

## 1. Hooks 配置 JSON（写入目标项目的 `.claude/settings.json`）

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "uv run $CLAUDE_PROJECT_DIR/.claude/hooks/env_guard.py"
          }
        ]
      }
    ]
  }
}
```

配置要点：

| 项 | 说明 |
|---|---|
| 事件 `PreToolUse` | 在**任何工具执行前**触发——此时拦截，工具根本不会执行，`.env` 文件不会被改动（这是 PostToolUse 做不到的：ASSET-DOC.md §5 `:113` 明确 PostToolUse 不能撤销已执行的工具） |
| `matcher: "Write|Edit"` | 只对 Write 与 Edit 两个写类工具生效，命中需求"Write/Edit 工具都算"；其余工具（含 Read/Grep 等读类）不进脚本，零开销 |
| `type: "command"` | 该库唯一 hook 类型：外部命令，输入走 stdin JSON（ASSET-DOC.md §4 `:93`） |
| `$CLAUDE_PROJECT_DIR` 前缀 | **必须**（README 原文 Important）：保证 Claude 在任意子目录工作时报路径都指向项目内的脚本（ASSET-DOC.md §4 `:62`） |
| 无 `uv` 时 | 把 command 换成 `python "$CLAUDE_PROJECT_DIR/.claude/hooks/env_guard.py"` 即可；脚本仅用标准库，两种解释器行为一致（本机两种均已实测，见 §4.3） |
| 超时/并发 | 单 hook 上限 60 秒；本脚本毫秒级返回。同事件多个 hook 并行执行，本配置每事件仅一条，无并发影响 |

## 2. Hook 脚本全文（`.claude/hooks/env_guard.py`）

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
env_guard.py — PreToolUse 安全护栏：禁止 Claude 对 .env / .env.* 文件做任何写操作。

事件   : PreToolUse（任何工具执行前触发；此时拦截 = 工具根本不会执行）
匹配   : matcher "Write|Edit"（配置见 OUT.md）；脚本内再做一次 tool_name 双重校验
输入   : stdin 收到的 hook JSON，取 tool_input.file_path 判断目标文件
命中   : 目标是 .env 或 .env.* 变体（.env.local / .env.production / .env.20260929.bak ...）
         -> stderr 输出原因，退出码 2 = 阻断本次工具调用（stderr 自动反馈给 Claude）
未命中 -> 退出码 0 = 放行，工具正常执行
风格   : 参照 disler/claude-code-hooks-mastery 的 UV 单文件脚本——仅用 Python 标准库，
         无第三方依赖，`uv run` 或任意 python3 均可直接执行。
"""
import json
import sys

# 双重校验：即使配置 matcher 写漏，脚本也只对写类工具生效（读工具不受影响）
GUARDED_TOOLS = {"Write", "Edit"}
# Write / Edit 工具的目标路径字段；notebook_path 顺带覆盖，防御字段改名
PATH_FIELDS = ("file_path", "notebook_path", "path")
# 豁免名单（按需自行放开，例如把 .env.example 视为可写模板）：
# EXEMPT = {".env.example"}
EXEMPT = set()


def basename_of(raw_path: str) -> str:
    """取路径最后一段文件名；统一反斜杠/正斜杠，去空白与引号。"""
    path = raw_path.strip().strip('"').strip("'").replace("\\", "/")
    return path.rstrip("/").split("/")[-1]


def is_env_file(raw_path: str) -> bool:
    """命中规则：文件名 == '.env'，或以 '.env.' 开头的变体。Windows 大小写不敏感，故一律 lower。"""
    name = basename_of(raw_path).lower()
    if name in EXEMPT:
        return False
    return name == ".env" or name.startswith(".env.")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        # 输入损坏时放行（fail-open），但向用户留痕；改成 sys.exit(2) 即为 fail-closed。
        print(f"env_guard: 无法解析 hook 输入（{exc}），本次放行", file=sys.stderr)
        return 0

    tool_name = payload.get("tool_name", "")
    if tool_name not in GUARDED_TOOLS:
        return 0  # 与本护栏无关的工具，直接放行

    tool_input = payload.get("tool_input") or {}
    for field in PATH_FIELDS:
        target = tool_input.get(field)
        if isinstance(target, str) and is_env_file(target):
            print(
                f"BLOCKED: 已拦截对环境变量文件 '{target}' 的 {tool_name} 写操作。"
                f"原因：.env 及其变体（.env.*）通常含密钥/生产凭据，属敏感文件，"
                f"本护栏禁止 AI 直接改写，防止泄露或误改生产配置。"
                f"如确需变更，请由用户手工编辑，或在 env_guard.py 的 EXEMPT 中显式豁免。",
                file=sys.stderr,
            )
            sys.exit(2)  # 阻断工具调用，stderr 原因自动反馈给 Claude

    return 0  # 未命中：放行，工具照常执行


if __name__ == "__main__":
    sys.exit(main())
```

实现说明：

- **判定规则**：取 `tool_input.file_path` 的**文件名部分**（先统一 `\`→`/`，再取最后一段），命中条件为 `名字 == ".env"` 或 `名字以 ".env." 开头`。相对路径（`.env`）、深层路径（`src/.env.production`）、Windows 反斜杠路径、大写 `.ENV` 全部覆盖；`foo.env`、`environment.yml` 这类**不**命中（不以 `.env` 开头），不会误伤。
- **阻断方式**：仿照该库 PreToolUse 阻断危险命令的原文范例 `print("BLOCKED: ...", file=sys.stderr); sys.exit(2)`（ASSET-DOC.md §6 `:143-148`）——退出码 2 + stderr 原因，语义与需求"说明原因并阻断本次工具调用"严格对应。
- **原因信息**：stderr 消息同时告知"拦了什么、为什么拦（密钥/生产凭据保护）、怎么办（用户手工编辑或显式豁免）"，符合该库最佳实践"错误信息要清晰"（ASSET-DOC.md §11 `:260`）。

## 3. 退出码语义：0 与阻断码 2（ASSET-DOC.md §5，`:99-105`）

| 退出码 | 名称 | 行为 | 对本护栏的含义 |
|---|---|---|---|
| **0** | 成功 | 工具调用**照常执行**；stdout 仅在 transcript 模式（Ctrl-R）中展示给用户 | 未命中 `.env` 规则 → 放行。脚本静默返回 0，不产生任何噪音 |
| **2** | **阻断错误** | **本次工具调用不执行**；stderr **自动反馈给 Claude**（Claude 得知原因并可调整做法） | 命中 `.env` / `.env.*` → 阻断本次 Write/Edit；AI 会收到拦截原因，且文件内容零改动 |
| 其他非零 | 非阻断错误 | stderr 仅展示给用户，**执行继续** | 本脚本不使用；存在即意味着脚本本身出错 |

三点补充（同节，`:107-135`）：

1. **为什么必须用 PreToolUse**：该库阻断能力表中只有 PreToolUse 能真正阻断工具调用；PostToolUse"不能阻断"——工具已执行、无法撤销，届时 `.env` 已被写坏。
2. **结构化 JSON 替代方案**：也可以退出码 0 + stdout 输出 `{"decision": "block", "reason": "..."}` 达到同样阻断效果（reason 给 Claude）。本护栏选择退出码 2 + stderr，更简单且与教学库的危险命令范例一致。优先级：`"continue": false` > `"decision": "block"` > 退出码 2 > 其他。
3. **非零≠阻断**：除 2 以外的非零码只是"非阻断错误"，工具仍会执行——所以阻断必须精确用 2，不能用 1。

## 4. 测试用例与实测结果

### 4.1 必需测试用例

**测试 1（应拦）：Edit `.env.local`**

输入（模拟 Claude Code 经 stdin 传入的 PreToolUse JSON）：

```json
{
  "session_id": "test-session",
  "transcript_path": "/tmp/t.jsonl",
  "cwd": "D:/workspace/demo",
  "hook_event_name": "PreToolUse",
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "D:/workspace/demo/.env.local",
    "old_string": "A=1",
    "new_string": "A=2"
  }
}
```

- **预期**：退出码 **2**（阻断），stderr 含拦截原因，`.env.local` 不被改动。
- **实测**（本机，`uv run` 路径，即配置中的真实命令形态）：

```
$ echo '{"session_id":"t","hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"D:/proj/.env.local","old_string":"A=1","new_string":"A=2"}}' | uv run env_guard.py; echo "exit=$?"
BLOCKED: 已拦截对环境变量文件 'D:/proj/.env.local' 的 Edit 写操作。原因：.env 及其变体（.env.*）通常含密钥/生产凭据，属敏感文件，本护栏禁止 AI 直接改写，防止泄露或误改生产配置。如确需变更，请由用户手工编辑，或在 env_guard.py 的 EXEMPT 中显式豁免。
exit=2
```

→ **结果符合预期：阻断，退出码 2，原因已输出到 stderr。**

**测试 2（应放）：Edit `src/app.py`**

输入：同上结构，`tool_name: "Edit"`，`tool_input.file_path: "D:/workspace/demo/src/app.py"`，`old_string: "pass"`，`new_string: "x = 1"`。

- **预期**：退出码 **0**（放行），无 stderr，Edit 正常执行。
- **实测**（`uv run` 路径）：

```
$ echo '{"session_id":"t","hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"D:/proj/src/app.py","old_string":"pass","new_string":"x=1"}}' | uv run env_guard.py; echo "exit=$?"
exit=0
```

→ **结果符合预期：放行，退出码 0，无任何输出。**

### 4.2 附加边界用例（`python run_tests.py` 实测，7/7 符合预期）

| 用例 | 工具/路径 | 预期 | 实测 |
|---|---|---|---|
| 测试 1 | Edit `.env.local` | 拦(2) | ✅ 拦(2)+原因 |
| 测试 2 | Edit `src/app.py` | 放(0) | ✅ 放(0) |
| 相对路径 | Write `.env` | 拦(2) | ✅ 拦(2) |
| 子目录变体 | Write `src/.env.production` | 拦(2) | ✅ 拦(2) |
| Windows 反斜杠+大写 | Write `D:\workspace\demo\.ENV` | 拦(2) | ✅ 拦(2) |
| 非 `.env` 前缀（防误伤） | Write `config/foo.env` | 放(0) | ✅ 放(0) |
| 读不受限 | Read `.env` | 放(0) | ✅ 放(0) |

`python run_tests.py` 末行输出：`结论: 测试1 阻断(2) / 测试2 放行(0) -> PASS`。

### 4.3 实测环境与命令

- 本机：Windows（win32），Python 3.12.10，uv 0.12.15。
- 实际执行过的命令：
  1. `python run_tests.py`（子进程喂 stdin JSON，断言退出码与 stderr，覆盖上表 7 例）；
  2. `echo '<测试1 JSON>' | uv run env_guard.py; echo "exit=$?"` → `exit=2`；
  3. `echo '<测试2 JSON>' | uv run env_guard.py; echo "exit=$?"` → `exit=0`。
- 两种解释器（`python` 直跑 / `uv run`）行为完全一致，配置中采用 `uv run` 以对齐教学库惯例（ASSET-DOC.md §3 `:56`）。

## 5. 已知边界与可选加固（诚实声明）

1. **覆盖面 = Write/Edit（按需求原文）**：若 Claude 绕道用 **Bash** 写 `.env`（如 `echo K=v > .env`），本配置不拦。如需封死，再加一条 PreToolUse 规则：`"matcher": "Bash"`，脚本内对 `tool_input.command` 用正则（如 `(?i)[>]\s*.*\.env(\.\w+)?\b`、`(?i)\b(tee|cp|mv|sed\s+-i)\b.*\.env\b`）复用同一退出码 2 逻辑——教学库的危险命令正则范式（ASSET-DOC.md §6 `:150-159`）可直接套用。
2. **`.env.example` 默认也在拦截范围**：需求写的是".env 或 .env.* 变体"，故默认全拦；该文件通常无密钥、本可豁免——脚本预留 `EXEMPT = {".env.example"}` 一行开关，按团队约定放开即可。
3. **输入损坏时 fail-open**：stdin JSON 解析失败时放行并留痕 stderr（一行可改为 `sys.exit(2)` 变为 fail-closed）。选择 fail-open 是避免脚本自身故障演变成"所有 Write/Edit 全被拦"的可用性事故；护栏主路径（正常 JSON）已实测确定性强。
4. **不拦读操作**：需求只限"写操作"，Read/Grep 读取 `.env` 不受影响（已实测）。若连读取都要审计，可对 PreToolUse 的 Read matcher 做日志型 hook（退出码 0 + stdout）。

---

*产物说明：本文件为 hooks-mastery-t3 / arm-a 的最终交付物。方法严格遵循同目录上级 `ASSET-DOC.md`（PreToolUse + 退出码 2 + `$CLAUDE_PROJECT_DIR` + UV 单文件脚本）；其说明与任务需求无冲突，无需偏离，故此处无"以任务为准"的例外项——仅第 5 节属任务范围之外的诚实边界声明。所有测试均于 2026-09-29 在本机实际执行，结果如实记录于 §4。*
