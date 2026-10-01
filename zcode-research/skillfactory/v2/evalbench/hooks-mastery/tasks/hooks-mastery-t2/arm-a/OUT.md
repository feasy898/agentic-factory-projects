# Hooks 配置诊断：拦截 `rm -rf` 的错误分析与修正

**需求原文**：在 Claude 提交 Bash 命令之前进行拦截：如果命令里包含 `rm -rf`，就阻止执行并提示「危险命令，禁止」。

**同事的配置原文**：

```json
{"hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "jq -r '.tool_input.command' | grep -q 'rm -rf' && echo '危险命令，禁止' && exit 2 || true"}]}]}}
```

---

## 一、与需求不符的 2 处错误

### 错误 1：事件挂错 —— `PostToolUse` 应为 `PreToolUse`

- `PostToolUse` 在工具调用**执行成功之后**才触发（官方文档原文："PostToolUse: After a tool call succeeds"；而 "PreToolUse: Before a tool call executes. **Can block it**"）。
- 需求要求的是「提交**之前**拦截、**阻止执行**」。挂在这个事件上，`rm -rf` 早已真实跑完、破坏已经发生；此时即使 `exit 2` 也只是"把 stderr 显示给 Claude"（文档原文对 PostToolUse 的说明："Shows stderr to Claude; **the tool already ran**"），根本不存在"阻止"效果。
- **结论**：要实现事前拦截，事件必须是 `PreToolUse` —— 它在 Claude 生成工具参数之后、命令真正执行之前运行，且唯一拥有"阻断该次工具调用"的权力。

### 错误 2：`matcher` 写错 —— `"Edit"` 应为 `"Bash"`

- `matcher` 按**工具名**匹配（文档："`Bash` matches only the Bash tool"）。写成 `"Edit"` 后，这个 hook **只在 Claude 调用 Edit 工具时触发**；对 Bash 命令一次都不会运行 —— 拦截对象整个落空。
- 更隐蔽的是：即便它被触发，也必然放行。Edit 工具的入参是 `{file_path, old_string, new_string}`，**没有 `command` 字段**，`jq -r '.tool_input.command'` 会输出字符串 `null`（本次实测输出见文末验证记录 [5]），`grep -q 'rm -rf'` 永不命中，最终落到 `|| true` 以 exit 0 放行。也就是说该配置是"双重失效"：对 Bash 零触发，对 Edit 触发了也永远放行。
- **结论**：要拦 Bash 命令，`matcher` 必须写 `"Bash"`。

### 附加修正（保证"提示"送达；不计入上述 2 处，但不改则需求只完成一半）

原命令把提示 `echo` 到 **stdout**，而 exit 2 的阻塞语义是：**stderr 文本作为阻塞原因回传**（文档："The blocking message is the reason from your JSON's blocking decision when it makes one, and **your stderr text** otherwise"；普通 stdout 仅进调试日志，Claude 看不到）。实测（验证记录 [2]）也证实：原命令命中时 exit=2 但 stderr 为空 —— 命令能被拦下，**提示却会丢失**。因此提示必须改写为 `echo '危险命令，禁止' >&2`。另外把兜底的 `|| true` 改成语义更明确的 `|| exit 0`（两者对"未命中即放行"等价，exit 0 = hook 无决策、工具照常走权限流程）。

---

## 二、修正后的完整配置 JSON

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "jq -r '.tool_input.command' | grep -q 'rm -rf' && { echo '危险命令，禁止' >&2; exit 2; } || exit 0"
          }
        ]
      }
    ]
  }
}
```

逐段对应需求：

| 片段 | 作用 |
|---|---|
| `"PreToolUse"` | 在工具执行**前**触发，满足"提交之前拦截" |
| `"matcher": "Bash"` | 只对 Bash 工具调用生效 |
| `jq -r '.tool_input.command'` | 从 stdin 的 hook 入参 JSON 中提取 Bash 的命令字段 |
| `grep -q 'rm -rf'` | 命令包含 `rm -rf` 即命中 |
| `echo '危险命令，禁止' >&2; exit 2` | 提示写到 stderr + exit 2 阻止本次工具调用 |
| `\|\| exit 0` | 未命中时以 0 退出，命令正常放行 |

> 等价替代写法（效果相同）：改用结构化 JSON 输出，让 stdout 以 `{` 开头被解析为决策，如 `jq -n '{decision:"block", reason:"危险命令，禁止"}'`；`reason` 同样会作为阻塞原因送达。二选一即可。
> 该命令假定 hook 运行环境有 `jq` 与 `grep`（POSIX shell 语义）；Windows 下需保证二者在 PATH 中（例如随 Git 附带的工具）。

---

## 三、修正后：拦截发生的时间点与提示信息的到达路径

**时间点**：Claude 生成 Bash 工具调用的参数之后、命令真正执行之前，Claude Code 先运行该 `PreToolUse` hook 并把调用入参 JSON 从 stdin 传入。若命中（命令含 `rm -rf`），hook 以 exit 2 退出，**该次 Bash 调用被直接取消 —— 命令一行都不会执行**；这就是需求中"提交之前拦截/阻止执行"的实现点。

**提示信息的到达路径**（exit 2 的阻塞语义）：

1. **到达 Claude**：stderr 中的「危险命令，禁止」被自动作为阻塞原因回传给 Claude，Claude 会明确看到命令因 hook 被拒以及原因，从而不会再原样重试。
2. **到达用户**：界面上这次工具调用显示为被 hook 阻止，阻塞原因（即 stderr 文本）随调用一并展示给用户，用户在交互界面直接看到「危险命令，禁止」。
3. **关键前提是 `>&2`**：若提示仍写在 stdout（如原配置），exit 2 场景下 stdout 不会作为消息送达 —— 拦截仍然生效，但提示会丢失（实测 [2] stderr 为空）。

---

## 验证记录（本会话实际执行）

**官方文档核验**：WebFetch `https://code.claude.com/docs/en/hooks`（Claude Code Hooks 官方参考），关键原文：

- "PreToolUse: Before a tool call executes. Can block it"；"PostToolUse: After a tool call succeeds"
- "`Bash` matches only the Bash tool"
- "Exit 2 means a blocking error"、PreToolUse 下 "Blocks the tool call"、消息来源 "the reason from your JSON's blocking decision when it makes one, and your stderr text otherwise"
- PostToolUse："Shows stderr to Claude; the tool already ran"
- stdin 入参含 `"tool_name": "Bash", "tool_input": { "command": ... }`

**命令实测**（WSL `sh` + `jq-1.7`，脚本与样本输入均由本会话构造；运行 `wsl -e sh -c "sh /mnt/c/Users/Administrator/AppData/Local/Temp/hook-t2-test/test_hook.sh"`）：

| # | 场景 | exit | stdout | stderr |
|---|---|---|---|---|
| [1] | 原配置命令 + Edit 入参（原配置真实场景） | 0 | 空 | 空（静默放行） |
| [2] | 原配置命令 + Bash 命中 `rm -rf` | 2 | 危险命令，禁止 | **空**（提示丢失） |
| [3] | 修正命令 + Bash 命中 `rm -rf` | 2 | 空 | 危险命令，禁止（拦截且提示送达） |
| [4] | 修正命令 + Bash 未命中 | 0 | 空 | 空（正常放行） |
| [5] | `jq -r '.tool_input.command'` 处理 Edit 入参 | — | `null` | — （证明错误 2 中 grep 永不命中） |

**修正配置 JSON 校验**（`jq -e . config.json`）：输出 `CONFIG_JSON_VALID`（合法）；`jq -r '.hooks.PreToolUse[0].hooks[0].command'` 提取出的命令串与上表实测命令逐字节一致（`diff` 输出 `COMMAND_STRING_MATCHES`）。

**局限说明**：本机 Git Bash 无 `jq`，故命令实测在 WSL 的 `sh` + `jq 1.7` 中完成；hook 运行时平台（Claude Code 自身的 shell 调度、UI 展示细节）无法在本机端到端复现，事件时序与 exit 2 语义以官方文档为准。
