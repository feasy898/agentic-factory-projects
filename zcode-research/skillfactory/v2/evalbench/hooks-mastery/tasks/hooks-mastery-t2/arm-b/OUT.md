# Hooks 配置诊断：Bash 危险命令（`rm -rf`）执行前拦截

需求原文：**在 Claude 提交 Bash 命令之前进行拦截：如果命令里包含 `rm -rf`，就阻止执行并提示「危险命令，禁止」。**

同事的配置（照录）：

```json
{"hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "jq -r '.tool_input.command' | grep -q 'rm -rf' && echo '危险命令，禁止' && exit 2 || true"}]}]}}
```

判定依据：`disler/claude-code-hooks-mastery` 资产文档（`ASSET-DOC.md`）及其原文存证 `_raw_README.md`（下文行号均指该文件）。

---

## 一、两处与需求不符的错误

### 错误 1：事件用错 —— `PostToolUse` 应为 `PreToolUse`

需求要求**在命令执行之前**拦截；而 `PostToolUse` 的触发时机是**工具成功完成之后**（`_raw_README.md:113`："Fires: After successful tool completion"，payload 还多了 `tool_response` 字段，:114）。该库 README 对此有明确的能力定性：

> `PostToolUse Hook - CANNOT BLOCK (Tool Already Executed)` …
> **Limitation**: Cannot prevent tool execution since it fires after completion（`_raw_README.md:327, 331`）

也就是说，这条链路下 `rm -rf` **已经真实执行完毕**，hook 才被调用；此时 hook 即便返回退出码 2，也只是"向 Claude 显示一条错误（工具已运行，无法撤销）"（`_raw_README.md:328-329`），起不到任何"阻止执行"的作用——文件已经删了。能"在工具执行前拦截"的只有 `PreToolUse`：

> `PreToolUse Hook - CAN BLOCK TOOL EXECUTION`
> - Intercepts tool calls **before** they execute
> - Exit Code 2 Behavior: **Blocks the tool call entirely**, shows error message to Claude（`_raw_README.md:315-316`）

该库自己的 `rm -rf` 防护示例也正是放在 PreToolUse 里（`_raw_README.md:320-325`）。生命周期顺序同样是 `PreToolUse → 权限 → 工具执行 → PostToolUse`（`_raw_README.md:59-66`），PostToolUse 在时序上根本不可能"事前拦截"。

### 错误 2：matcher 用错 —— `"Edit"` 应为 `"Bash"`

`matcher` 字段决定这条 hook **匹配哪些工具**才会触发。写 `"Edit"` 意味着这条 hook 只在 Claude 调用 **Edit（编辑文件）工具**时才会运行；需求针对的是 **Bash 命令**，而 Bash 工具调用根本不匹配 `Edit`，hook 主体（jq/grep/exit 2）**从头到尾不会被触发**——拦截逻辑等于从未上线。改为 `"Bash"` 后，任何 Bash 工具调用在执行前都会带着 `tool_input.command` 进入本 hook。

旁证（说明为什么恰好是这两个字段都错了）：Edit 工具的 `tool_input` 里只有 `file_path`/`old_string`/`new_string`，**没有 `command` 字段**，所以即使它偶然被 Edit 触发，`jq -r '.tool_input.command'` 取到的是 `null`，grep 也永远匹配不上——原配置是一处"双重错位"，事件错了、作用对象也错了。

### 附带缺陷（题面问两处，此为修正确认项）：提示写到了 stdout 而非 stderr

原命令 `echo '危险命令，禁止'`（未加 `>&2`）把提示打到 **stdout**。而退出码 2 的交付规则是：**只有 stderr 会自动反馈给 Claude**（`_raw_README.md:301`："**2** | Blocking Error | **Critical**: `stderr` is fed back to Claude automatically"）。本机实测也复现了这一点（见第三节）：stderr 被丢弃时消息仍出现在 stdout——即消息永远到不了 Claude/用户面前。修正版必须写成 `echo '危险命令，禁止' >&2`。

---

## 二、修正后的完整配置

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "jq -r '.tool_input.command' | grep -q 'rm -rf' && echo '危险命令，禁止' >&2 && exit 2 || true"
          }
        ]
      }
    ]
  }
}
```

相对原配置的三处改动：

| 位置 | 原值 | 修正值 | 理由 |
|---|---|---|---|
| 事件 | `PostToolUse` | `PreToolUse` | 只有 PreToolUse 能在工具执行**前**整体拦下调用（`_raw_README.md:315-316`） |
| matcher | `"Edit"` | `"Bash"` | 需求对象是 Bash 命令，matcher 决定 hook 是否被触发 |
| echo | `echo '…'` | `echo '…' >&2` | 退出码 2 时只有 stderr 被反馈给 Claude（`_raw_README.md:301`） |

逻辑保持原样且成立：命令含 `rm -rf` → `grep -q` 命中 → 消息写入 stderr → `exit 2` → 工具调用被整体阻断；不含 → `|| true` 兜底退出码 0 → 放行、无任何输出（退出码 0 的 stdout 仅在 transcript 模式 Ctrl-R 下可见，`_raw_README.md:300`）。

> 备注：README 要求 settings.json 中引用**项目内脚本路径**时用 `$CLAUDE_PROJECT_DIR` 前缀（`_raw_README.md:555-557`）；本命令只依赖系统命令 `jq`/`grep`，不涉及项目内路径，故无需该前缀。若要覆盖 `sudo rm -rf`、`rm  -fr` 等变体，可将 grep 换成正则（该库的安全过滤示例即用 `rm\s+.*-[rf]`，`_raw_README.md:437`），此处按需求字面仅匹配 `rm -rf`。

---

## 三、修正后：拦截发生的时间点与提示信息的到达路径

**时间点**：Claude 每次决定调用 Bash 工具、**在该命令获得执行之前**，Claude Code 触发 `PreToolUse` hook，把事件 JSON（含 `tool_name`、`tool_input`，`_raw_README.md:108-110`）通过 **stdin** 传给 hook 命令，hook 继承环境、在项目目录运行、限时 60 秒（`_raw_README.md:461-468`）。命令含 `rm -rf` 时 hook 以退出码 2 结束——此刻即拦截点：**Bash 命令被整体阻断，永远不执行**，也不会进入权限确认/后续执行流程（"Blocks the tool call entirely"，`_raw_README.md:316`）。不含时退出码 0，命令照常放行。

**提示信息的到达路径**：退出码 2 触发 Claude Code 的固定规则——hook 的 **stderr 被自动反馈给 Claude**（`_raw_README.md:301`）。于是 `危险命令，禁止` 作为该次工具调用被阻断的原因进入对话上下文：Claude 在界面上看到这条阻断错误（通常随之向用户说明/改用安全命令），**用户在 Claude Code 界面中直接看到这条被阻断的 Bash 调用及其反馈信息**。即：hook stderr →（退出码 2 规则）→ Claude → 对话界面呈现给用户。若想完全绕开 shell 退出码、用结构化方式达到同样效果，也可让 hook 输出 `{"decision": "block", "reason": "危险命令，禁止"}` 且退出码 0（`block` 阻止执行、`reason` 给 Claude，`_raw_README.md:419-432` 及 ASSET-DOC §5）；两种写法等效，上文 JSON 采用的是对原配置改动最小的退出码 2 方案。

---

## 四、本机实测验证（2026-09-29，Git Bash 5.3.15 / windev-01）

本机未安装 `jq`（`where jq` 无结果、`jq --version` 返回 127），故将管道前段 `.tool_input.command` 提取用等价 python 一行程序替代，**管道后段（grep 判定、stderr 路由、退出码）与修正后的 hook 命令逐字节一致**进行实测（脚本：本目录 `_hook_logic_test.sh`）：

| 用例 | 输入 payload | 结果 |
|---|---|---|
| 危险命令 | `{"tool_input":{"command":"rm -rf /tmp/x"}}` | stderr 输出「危险命令，禁止」，**exit_code=2** ✅ |
| 复合命令夹带 | `{"tool_input":{"command":"cd /var && rm -rf cache"}}` | stderr 输出「危险命令，禁止」，**exit_code=2** ✅ |
| 安全命令 | `{"tool_input":{"command":"ls -la"}}` | 无任何输出，**exit_code=0**（放行）✅ |
| 原命令 stdout 缺陷复现 | 危险命令 + 丢弃 stderr（`2>/dev/null`） | 消息仍出现在 **stdout**（即到不了 Claude）——证实附带缺陷成立，exit_code=2 |

jq 本体的 JSON 提取语义（`.tool_input.command` 取字段）为 jq 标准用法，未在本机单独验证，特此说明。

---

## 五、依据与冲突说明

- 全部分类学依据来自 `D:\workspace\zcode研究\skillfactory\v2\evalbench\hooks-mastery\ASSET-DOC.md`（§3 生命周期与 payload、§4 配置方法、§5 退出码与流控、§6 官方 rm -rf 示例）及其原文存证 `_raw_README.md`（引用行号：60, 108-114, 300-331, 320-325, 419-432, 437, 461-468, 555-557）。
- 资产说明与任务无冲突，任务按其方法完成，未做取舍。
