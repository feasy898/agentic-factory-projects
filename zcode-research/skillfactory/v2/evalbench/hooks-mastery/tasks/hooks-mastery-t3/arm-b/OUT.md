# 安全护栏 Hook：禁止对 `.env` / `.env.*` 的一切写操作

> 需求原文：『禁止 Claude 对 .env 文件做任何写操作（Write/Edit 工具都算），命中时向用户说明原因并阻断本次工具调用；.env 的变体文件（如 .env.local、.env.production）也要拦。』
>
> 本文包含：① hooks 配置 JSON；② hook 脚本全文；③ 退出码语义说明；④ 测试用例与**本机实测结果**（Python 3.12.10 / Windows）。
> 设计依据：Claude Code Hooks Reference（code.claude.com/docs/en/hooks）——PreToolUse 事件、退出码 0/2 语义、stdin 输入结构 `tool_name` / `tool_input.file_path` 均按该文档实现。

---

## 1. 方案概览

- **事件**：`PreToolUse`（工具调用执行前触发，是唯一能"阻断本次工具调用"的同步拦截点）。
- **matcher**：`Write|Edit|MultiEdit`（需求要求 Write/Edit；MultiEdit 同为文件写工具，一并防御，可按需删减）。
- **脚本**：Python 3 脚本，从 stdin 读 hook 输入 JSON，取 `tool_input.file_path` 的 basename 判断是否为 `.env` 或 `.env.*` 变体（大小写不敏感，兼容 `\` 与 `/`，含子目录情形）。
- **命中 → 退出码 2**，原因写 stderr：PreToolUse 下退出码 2 会**取消本次工具调用**，且 stderr **自动回传给 Claude 并展示给用户**（文档原文："PreToolUse… Blocks the tool call… Shows stderr to Claude"）——正好满足"说明原因并阻断"。
- **未命中 → 退出码 0** 放行，工具调用正常继续。

---

## 2. hooks 配置 JSON

放入项目根的 `.claude/settings.json`（随仓库共享），或 `.claude/settings.local.json`（仅本机生效），或 `~/.claude/settings.json`（对本机所有项目生效）：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PROJECT_DIR}/.claude/hooks/deny-env-write.py\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

**Windows 原生（cmd/powershell shell）变体**——若你的 hook 默认 shell 不展开 `${CLAUDE_PROJECT_DIR}`，把 `command` 换成：

```json
"command": "python \"%CLAUDE_PROJECT_DIR%/.claude/hooks/deny-env-write.py\""
```

（`${CLAUDE_PROJECT_DIR}` 是 Claude Code 注入的项目根环境变量；`matcher` 为 `|` 分隔的精确工具名列表，`timeout` 单位为秒。）

---

## 3. hook 脚本全文

保存为项目内 `.claude/hooks/deny-env-write.py`：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deny-env-write.py — PreToolUse 安全护栏 hook

禁止 Claude 用 Write / Edit 工具对 .env 及其变体文件（.env.local、.env.production 等）
做任何写操作。命中即以退出码 2 阻断本次工具调用，并在 stderr 输出原因
（PreToolUse 退出码 2 时，stderr 会回传给 Claude 并展示给用户）。

用法（由 hooks 配置自动调用，无需手动运行）:
    python deny-env-write.py    # 工具调用 JSON 从标准输入读入

退出码:
    0 = 放行，工具调用正常继续
    2 = 阻断本次工具调用，stderr 内容回传给 Claude
"""
import json
import os
import sys

# 拦截的写类工具：Write / Edit 为需求明确要求；MultiEdit 属同类写操作，一并防御。
BLOCKED_TOOLS = {"Write", "Edit", "MultiEdit"}

BLOCK_TMPL = (
    "[HOOK-BLOCKED] 已拦截对 {path} 的写操作（{tool} 工具）。\n"
    "原因：{name} 是 .env 环境变量文件（或其变体）。此类文件通常保存 API key、"
    "数据库密码等敏感凭据，禁止 AI 直接写入，以防止凭据泄露或被意外覆盖。\n"
    "替代做法：请用户手动编辑该文件；如需新增配置项，可写入 .env.example 模板供用户同步。"
)


def is_env_file(path):
    """判断目标路径的文件名是否为 .env 或 .env.* 变体。

    兼容正反斜杠、末尾空白；按文件名（basename）判断；大小写不敏感
    （Windows 文件系统不区分大小写，.ENV 与 .env 是同一文件）。
    """
    if not path:
        return False
    name = os.path.basename(path.replace("\\", "/").strip()).lower()
    return name == ".env" or name.startswith(".env.")


def main():
    # 1. 从 stdin 读取 hook 输入 JSON
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # 输入不是合法 JSON：无法判定目标文件，选择放行（fail-open），
        # 避免契约异常导致所有写操作被误杀。正常 hooks 流程不会走到这里。
        return 0

    # 2. 只检查写类工具（双保险：matcher 已过滤，脚本自身再兜底一次）
    tool = payload.get("tool_name", "")
    if tool not in BLOCKED_TOOLS:
        return 0

    # 3. 取目标文件路径（Write/Edit/MultiEdit 均为 tool_input.file_path）
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""

    # 4. 命中 .env / .env.* → 退出码 2 阻断，原因写 stderr
    if is_env_file(path):
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
        name = os.path.basename(path.replace("\\", "/").strip())
        print(BLOCK_TMPL.format(path=path, tool=tool, name=name), file=sys.stderr)
        return 2

    # 5. 未命中 → 退出码 0 放行
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## 4. 退出码语义（PreToolUse / command 类型 hook）

| 退出码 | 含义 | 对本次工具调用的效果 | stderr 去向 |
|---|---|---|---|
| **0** | 成功/放行 | **不阻断**，工具调用正常继续 | 调试日志（不会出现在会话中） |
| **2** | **阻断错误（blocking error）** | **取消本次工具调用**，Claude 看到拒绝原因并可调整行为 | **自动回传给 Claude**（并展示给用户）——本方案用它传递"为什么拦" |
| 其它非零（如 1） | 非阻断错误 | **不阻断**，动作照常执行 | 仅在转录中给用户显示非阻断错误提示 |

**关键陷阱**：误用退出码 1 想拦截是无效的——文档明确对 exit 1 "proceeds with the action"，并提示 *"If your hook is meant to enforce a policy, use `exit 2`"*。所以本护栏的阻断码必须是 **2**，放行码必须是 **0**。

> 备选写法：退出码 0 的同时向 stdout 输出结构化 JSON `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}`，效果同为阻断且原因可控。本方案采用更简单的纯退出码方式（需求点名"以正确的退出码阻断"）。

---

## 5. 测试用例与实测结果

**测试方式**：把脚本按 Claude Code 的真实调用方式执行——子进程运行 hook、向 stdin 喂 hook 输入 JSON、读取退出码与 stdout/stderr。实测环境：Windows（win32）+ Python 3.12.10。

### 用例 1【应拦】编辑 `.env.local`

stdin 输入：

```json
{
  "session_id": "test-session-001",
  "transcript_path": "/tmp/transcript.jsonl",
  "cwd": "D:\\workspace\\demo",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "tool_use_id": "toolu_01TEST",
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "D:\\workspace\\demo\\.env.local",
    "old_string": "DEBUG=false",
    "new_string": "DEBUG=true"
  }
}
```

执行：`python deny-env-write.py < case1.json`

**预期结果**：退出码 `2`；stderr 输出阻断原因（回传给 Claude/用户）；`.env.local` 不被修改。
**实测结果**：✅ `实际退出码=2`，stderr 为：

```
[HOOK-BLOCKED] 已拦截对 D:\workspace\demo\.env.local 的写操作（Edit 工具）。
原因：.env.local 是 .env 环境变量文件（或其变体）。此类文件通常保存 API key、数据库密码等敏感凭据，禁止 AI 直接写入，以防止凭据泄露或被意外覆盖。
替代做法：请用户手动编辑该文件；如需新增配置项，可写入 .env.example 模板供用户同步。
```

### 用例 2【应放】编辑 `src/app.py`

stdin 输入：

```json
{
  "session_id": "test-session-001",
  "transcript_path": "/tmp/transcript.jsonl",
  "cwd": "D:\\workspace\\demo",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "tool_use_id": "toolu_01TEST",
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "D:\\workspace\\demo\\src\\app.py",
    "old_string": "x = 1",
    "new_string": "x = 2"
  }
}
```

执行：`python deny-env-write.py < case2.json`

**预期结果**：退出码 `0`；无 stderr 输出；工具调用正常放行。
**实测结果**：✅ `实际退出码=0`，stdout/stderr 均为空。

### 补充边界用例（同一测试架实测，全部通过）

| # | 场景 | 期望 | 实测 |
|---|---|---|---|
| 补充A | `Write` 工具写 `.env` 正主文件 | 拦，退出码 2 | ✅ 2，stderr 带原因 |
| 补充B | `Edit` 子目录变体 `config/.env.production`（正斜杠路径） | 拦，退出码 2 | ✅ 2 |
| 补充C | `Write` 大写 `.ENV`（Windows 大小写不敏感） | 拦，退出码 2 | ✅ 2 |
| 补充D | `Read` 工具读 `.env`（护栏只拦写，不拦读） | 放，退出码 0 | ✅ 0 |
| 补充E | 名字相近但非 `.env` 的 `src/env_utils.py` | 放，退出码 0 | ✅ 0 |
| 补充F | stdin 非法 JSON | fail-open 放行，退出码 0 | ✅ 0 |
| — | 第 2 节配置 JSON 用 `json.loads` 校验 | 合法 | ✅ OK |

**汇总**：2 个需求用例 + 6 项补充（含配置校验）全部通过（测试架输出 `all_pass = True`）。测试架源码按 Claude Code 真实协议构造：`subprocess.run([python, deny-env-write.py], input=payload_bytes)` 后断言返回码。

---

## 6. 安装与验证步骤

1. 把第 3 节脚本存到项目内 `.claude/hooks/deny-env-write.py`；
2. 把第 2 节 JSON 合入 `.claude/settings.json`（已有 hooks 时并入 `hooks.PreToolUse` 数组，不要整体覆盖）；
3. 重启会话或执行 `/hooks` 确认 hook 已加载；
4. 让 Claude 尝试 Edit `.env.local` → 应看到 "[HOOK-BLOCKED]…" 原因且写操作未执行；再让它 Edit 一个普通 `.py` 文件 → 应正常执行。

## 7. 设计取舍备注

- **fail-open**：stdin 非法 JSON 时放行（补充F 实测），避免 hook 契约异常导致所有写操作被误杀；若你的场景要求 fail-closed，把 `main()` 里 parse 异常分支改为输出提示并 `return 2`。
- **`.env.example` 白名单**：当前按需求字面拦截一切 `.env.*`（含无密钥的 `.env.example`）。若想放行模板文件，在 `is_env_file` 中加 `if name in (".env.example",): return False`。
- **双保险**：配置层 `matcher` 与脚本内 `BLOCKED_TOOLS` 各拦一道；即使只装脚本不装配置，直接手动调用脚本也同样生效，便于 CI 单测。
