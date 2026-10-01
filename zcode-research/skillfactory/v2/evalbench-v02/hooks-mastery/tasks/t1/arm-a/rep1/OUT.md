# T1：PreToolUse 安全防护——配置与行为链（arm-a / rep1）

> 依据：任务给定的 README 核心逻辑（`dangerous_patterns` + `sys.exit(2)` 代码）、disler/claude-code-hooks-mastery 原文存证 `_raw_README.md`（935 行，本目录上一级，行号引用格式 `_raw_README.md:<行号>`）、ASSET-DOC.md。关键结论均经本机实测复现（见文末「验证记录」）。

---

## (a) `.claude/settings.json` 配置（完整、可直接粘贴）

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run $CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py"
          }
        ]
      }
    ]
  }
}
```

**说明**

- 结构与 README 原文示例完全同构（`_raw_README.md:541-552`，UserPromptSubmit 示例）：hook 配置在 `.claude/settings.json` 中；`PreToolUse` 是 `hooks` 对象下的顶层键，其值为**数组**，数组元素含 `hooks` 数组，hook 对象含 `"type": "command"` 与 `"command"` 两个字段。
- **`$CLAUDE_PROJECT_DIR` 前缀不可省**：README 原文标注 **Important**——"Use `$CLAUDE_PROJECT_DIR` prefix for hook paths in settings.json to ensure reliable path resolution across different working directories."（`_raw_README.md:554`）。缺了它，Claude 在子目录里工作时相对路径解析不到脚本，hook 会静默失效。
- `uv run` 直接执行 uv 单文件脚本（依赖内嵌于脚本头部的 PEP 723 元数据块，无需虚拟环境；`_raw_README.md:180-191`）。
- 若项目已有 `settings.json`：把 `"PreToolUse": [...]` 整条并入现有顶层 `"hooks"` 对象即可，其余键保持不动。
- 本脚本的阻断走**退出码 2** 通道（无命令行参数）；README 中 `--log-only` 等参数属于 `user_prompt_submit.py`，勿混用。

---

## (b) `rm -rf /tmp/build` 的完整行为链（阻断）

前提：Claude 准备调用 **Bash** 工具执行 `rm -rf /tmp/build`，PreToolUse 在**任何工具执行前**触发（`_raw_README.md:314-316`：PreToolUse "Intercepts tool calls before they execute"）。

1. **触发与传参**：Claude Code 把 payload 以 **stdin JSON** 传给 hook（含 `tool_name: "Bash"`、`tool_input: {"command": "rm -rf /tmp/build"}`；执行环境见 `_raw_README.md:461-468`：单 hook 60 秒超时、同事件多个匹配 hook 并行、继承环境变量、在当前项目目录运行）。
2. **命中危险模式**：脚本取出 `tool_input.command`，与 `dangerous_patterns` 逐一 `re.search`——`r"rm\s+.*-[rf]"` 命中 `rm -rf /tmp/build`（`rm` + 空白 + 任意字符 + `-rf`）。**实测确认 MATCH**（见验证记录 #2）。
3. **脚本输出与退出码**：执行 `print("BLOCKED: Dangerous rm command detected", file=sys.stderr)` 后 `sys.exit(2)`。**退出码 2 = 阻断错误**（`_raw_README.md:301`）。
4. **工具调用是否执行**：**不执行**。`rm -rf /tmp/build` 这条命令根本不会跑，`/tmp/build` 不会被删除。PreToolUse 的退出码 2 语义即 "Blocks the tool call entirely, shows error message to Claude"（`_raw_README.md:316`；README 同节原文示例正是 "Our `pre_tool_use.py` blocks `rm -rf` commands with exit code 2"，`_raw_README.md:318`）。
5. **stderr 去向**：stderr 的 `BLOCKED: Dangerous rm command detected` **自动反馈给 Claude**（`_raw_README.md:301` "**Critical**: `stderr` is fed back to Claude automatically"）。Claude 随即在对话中看到该报错，可以据此调整（换安全命令/向用户说明），用户则在界面上看到这次工具调用被 hook 拦截。
6. **控制优先级**：本脚本走的是简单的「退出码 2」通道；按优先级 `"continue": false` > `"decision": "block"`（结构化 JSON）> 退出码 2 > 其他退出码（`_raw_README.md:410-417`），退出码 2 已足以完成阻断。

一句话链路：**Bash 调用发起 → hook 收 stdin JSON → 正则命中 `rm\s+.*-[rf]` → stderr 打印 BLOCKED → 退出码 2 → 工具调用被整体阻断（命令不执行）→ stderr 报错自动回给 Claude。**

---

## (c) 安全命令正常放行的行为

以 `ls -la`（不在任何 dangerous pattern 内，实测 NO MATCH）为例：

1. **判定**：四个模式均不命中，脚本不进阻断分支，走放行路径。
2. **退出码**：**0 = 成功**（`_raw_README.md:300`）。对 PreToolUse 而言，退出码 0 不产生任何阻断或特殊决策，工具调用**照常执行**。
3. **stdout 在哪里可见**：hook 的 stdout **不会给 Claude**，也不进主聊天流——只在 **transcript 模式（Ctrl-R）中展示给用户**（`_raw_README.md:300`："`stdout` shown to user in transcript mode (Ctrl-R)"）。所以放行路径上脚本若打印信息，只有用户主动翻 transcript 才看得到。
4. **工具是否执行**：**执行**。`ls -la` 正常运行、结果正常返回给 Claude，Claude 和用户都感知不到 hook 存在（除非翻 transcript）。
5. **补充（上游实机行为，实测）**：上游真实 `pre_tool_use.py` 在放行路径上 stdout 为空，而是把本次事件追加写入 `logs/pre_tool_use.json` 后 `sys.exit(0)`（脚本 `main()` 第 108-129 行；实测放行后 `logs/` 下出现 `pre_tool_use.json`，内容为本次 `tool_name`/`tool_input`）——即教学库宣传的 "Tool use events with security blocking" 日志能力（`_raw_README.md:254`）。

---

## 验证记录（本 ask 期间实际执行）

| # | 检查 | 命令 | 结果 |
|---|---|---|---|
| 1 | (a) 配置 JSON 合法性与结构 | 上述 JSON 经 `python -c json.loads` 解析（stdin 传入） | `JSON_VALID`；`hooks.PreToolUse` 为 list；hook 对象 `type=command`，`command=uv run $CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py` |
| 2 | (b) 正则命中 / (c) 安全命令不命中 | `re.search` 逐一测试任务给定的 4 个 pattern（`re.IGNORECASE`） | `rm -rf /tmp/build` → **MATCH** `rm\s+.*-[rf]`；`ls -la`、`git status` → NO MATCH |
| 3 | (b)(c) 端到端行为 | `curl -sL https://raw.githubusercontent.com/disler/claude-code-hooks-mastery/main/.claude/hooks/pre_tool_use.py`（exit 0，138 行）取回**上游真实脚本**，在临时目录中以生产同款方式执行：<br>`echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/build"}}' \| uv run -q pre_tool_use.py` | **exit_code=2**，stdout 空，stderr=`BLOCKED: Dangerous rm command detected and prevented` → 对应阻断：工具调用不执行、报错回给 Claude（`_raw_README.md:316`） |
| 4 | (c) 放行路径实机行为 | 同上脚本，payload 换为 `{"tool_name":"Bash","tool_input":{"command":"ls -la"}}` | **exit_code=0**，stdout/stderr 均空；`logs/pre_tool_use.json` 被写入本次事件 → 工具正常执行，stdout（此处为空）即便有也仅在 transcript Ctrl-R 中给用户看 |

检查 #3/#4 说明：任务给定的「核心逻辑」是 README 教学摘录（阻断文案为 `BLOCKED: Dangerous rm command detected`）；上游真实脚本对 `rm -rf` 的判定更完备（含 `rm -fr`/`--recursive --force` 变体与危险路径启发式），且另有 `.env` 访问防护与日志写入，但对 `rm -rf /tmp/build` 的行为链与摘录**完全一致**：命中 → stderr BLOCKED → exit 2（阻断）/ 不命中 → 写日志 → exit 0（放行）。两版差异不影响 (a)(b)(c) 任何结论。

## 资料引用

- 任务 ask 自带材料：`dangerous_patterns` 四条正则 + `is_dangerous_rm_command` → `sys.exit(2)` 代码块；退出码语义（0 / 2 / 其他）与 `$CLAUDE_PROJECT_DIR` Important 说明。
- `_raw_README.md`（935 行原文存证）：退出码表 `:298-302`；PreToolUse 阻断语义与示例 `:314-325`；安全过滤正则 `:421-435`；执行环境 `:461-468`；优先级 `:410-417`；配置示例与 Important `:537-554`；uv 单文件架构 `:180-191`；日志 `:254`。
- ASSET-DOC.md：§3 事件表（PreToolUse=阻断工具调用）、§4 配置方法、§5 退出码与各 hook 阻断能力、§6 示例。

## ASSET-DOC 与任务的冲突说明

无实质冲突：ASSET-DOC 对配置方法、退出码语义、PreToolUse 阻断能力的记载与任务给定材料一致，本文按任务要求以 ask 给出的脚本核心逻辑与退出码语义为准作答。仅存在一处表述差异（非冲突）：任务引用的 README 教学摘录中阻断文案为 "BLOCKED: Dangerous rm command detected"、正则为简化版 `rm\s+.*-[rf]`，而上游仓库实际脚本（本次实测取回并运行）文案多 "and prevented"、判定更严格并附带 `.env` 防护与日志——已在「验证记录」#3/#4 注明，按任务口径以摘录为准，实机结果作旁证。
