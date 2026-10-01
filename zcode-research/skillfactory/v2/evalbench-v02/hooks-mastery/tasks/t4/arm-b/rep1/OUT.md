# T4 排查报告：PreToolUse hook（rm -rf 拦截）不触发

> 项目：`/home/dev/shop-api` ｜ 症状：`rm -rf ./dist` 未被拦截、`logs/` 无新日志、根目录手动测试脚本正常、Claude 会话工作目录为 `src/` 子目录
>
> **TL;DR**：根因是 hook 命令用了**相对路径**且缺少 `$CLAUDE_PROJECT_DIR` 前缀。Claude Code 执行 hook 命令时的工作目录跟随会话的**当前工作目录**（本例 Claude 已进入 `/home/dev/shop-api/src`），于是 hook 实际去找 `src/.claude/hooks/pre_tool_use.py` —— 不存在，`uv run` 直接报 "Failed to spawn" 退出，**Python 脚本一行都没执行**。根目录手动测试通过只是因为那里相对路径恰好解析正确。修复：命令改为 `uv run $CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py`。

---

## (a) 最可能的根因，以及两个现象为何不矛盾

### 根因

`settings.json` 里的 hook 命令写成了相对路径：

```json
"command": "uv run .claude/hooks/pre_tool_use.py"
```

这直接违反 README 用加粗 **Important** 标注的规则：

> **Important:** Use `$CLAUDE_PROJECT_DIR` prefix for hook paths in settings.json to ensure reliable path resolution across different working directories.
> （`_raw_README.md:554`，本会话已读原文）

结合 hook 执行环境事实（`_raw_README.md:461-468`：hook 继承 Claude Code 环境变量、**在当前工作目录运行**、输入为 stdin 传入的 JSON、单 hook 60 秒超时），完整故障链条是：

1. 配置 JSON 结构本身与 README 官方示例（`_raw_README.md:541-552`）逐字段同构，PreToolUse 事件注册与触发没有问题——问题出在**触发之后命令解析失败**；
2. Claude 会话中 `pwd` 显示在 `/home/dev/shop-api/src` → hook 命令从 `src/` 目录启动；
3. `.claude/hooks/pre_tool_use.py` 相对 `src/` 解析为 `/home/dev/shop-api/src/.claude/hooks/pre_tool_use.py` —— 该文件不存在；
4. `uv run` 找不到脚本立即报错退出，**hook 脚本从未运行**；
5. 脚本没运行 ⇒ 不会打印 BLOCKED、不会 `sys.exit(2)`、也不会写日志——`logs/` 下的日志是各 hook 脚本自己写入的（`_raw_README.md:288`："Run any Claude Code command to see hooks in action via the `logs/` files"）。**"没有拦截"和"没有新日志"两个症状由同一个原因同时解释。**

### 为什么"根目录手动测试通过"与"会话中不触发"不矛盾

两次执行**唯一的差别是启动命令时的工作目录**，而不是脚本本身：

| 场景 | 工作目录 | `.claude/hooks/pre_tool_use.py` 解析结果 | 脚本是否运行 | 结果 |
|---|---|---|---|---|
| 开发者根目录手动测试 | `/home/dev/shop-api`（仓库根） | 正确命中脚本 | ✅ 运行 | BLOCKED + 退出码 2 |
| Claude 会话内 hook | `/home/dev/shop-api/src`（会话 cwd） | 指向不存在的 `src/.claude/hooks/...` | ❌ 从未运行 | 无拦截、无日志 |

手动测试无意中只复现了"路径恰好正确"的那条分支——它验证了**脚本逻辑**没问题，但没有验证"hook 在**任意工作目录**下都能找到脚本"。这正是 README 用 Important 强调、并要求 `$CLAUDE_PROJECT_DIR` 前缀的原因（该环境变量由 Claude Code 在派发 hook 时注入，始终指向项目根的绝对路径，与当前 cwd 无关）。

### 细节与诚实说明（不改变根因与修法）

本机（Windows + uv 0.12.15）复现时发现：`uv run` 找不到脚本文件时**自身也以退出码 2 结束**（`error: Failed to spawn: ...`，见附录 T2）。按 README 退出码表（`_raw_README.md:298-302`）退出码 2 属"阻断错误"，理论上会把 uv 的报错反馈给 Claude 并拦下工具；而事故中工具被放行了。最可能的解释是该环境的这次失败按**非阻断错误**处理（`_raw_README.md:302`："Other: Non-blocking Error — stderr shown to user, execution continues normally"，错误只进 transcript、极易被忽略；也不排除 dev 机 uv 版本对 spawn 失败返回非 2 退出码）。dev 机器不可达，此子现象无法在其上复核——但无论这次失败表现为阻断还是非阻断，**脚本都没运行、根因与修复方式完全相同**。

---

## (b) 修复后的 command 配置行

```json
"command": "uv run $CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py"
```

放回完整 `settings.json`（与原配置唯一的差异就是这一行）：

```json
{
  "permissions": { "allow": ["Bash(ls:*)"] },
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          { "type": "command", "command": "uv run $CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py" }
        ]
      }
    ]
  }
}
```

说明：

- 与 README 官方示例完全同构（`_raw_README.md:547`：`"command": "uv run $CLAUDE_PROJECT_DIR/.claude/hooks/user_prompt_submit.py --log-only"`），只是换成 pre_tool_use 脚本；
- 若项目路径可能含空格，应给路径加引号（JSON 内需转义）：`"command": "uv run \"$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py\""`。本例 `/home/dev/shop-api` 无空格，两种写法等价，推荐与 README 一致的不带引号形式；
- 修复后的整份 JSON 已实测可通过解析（本会话用 `uv run python -c "import json; json.load(...)"` 校验，输出 `JSON OK`）。

---

## (c) 为什么写死绝对路径只是临时方案

`uv run /home/dev/shop-api/.claude/hooks/pre_tool_use.py` 确实能立刻恢复拦截——因为它和 `$CLAUDE_PROJECT_DIR` 一样消除了对 cwd 的依赖。但它把**本机、本次检出的物理路径**固化进了配置文件，缺点是结构性的：

1. **绑死机器与仓库位置**：仓库移动、改名、换目录重新 clone、或以 git worktree 等方式在别路径检出后，路径失配，hook 静默失效——本案例已经证明 hook 失效是静默的（无报错感知、无日志），比报错更危险；
2. **不可移植、不可共享**：`.claude/settings.json` 是随仓库分发的配置（hooks-mastery 教学库本身就是把 `.claude/` 整体入库的，`_raw_README.md:237` 文件地图）。写死 `/home/dev/shop-api` 后，其他开发者、其他机器、CI/容器上全部失效，还把个人目录结构泄漏进版本库；
3. **背离官方明确标注的最佳实践**：`$CLAUDE_PROJECT_DIR` 这个变量就是 Claude Code 为解决"跨工作目录可靠解析"而提供的机制（`_raw_README.md:554` Important 注记；README 所有配置示例均用它，如 `:547`）。两种写法改动成本相同，一个在任何机器任何 cwd 都正确，另一个只在一台机器的一个路径下正确——没有任何理由选后者。

---

## (d) 修复后验证 hook 已生效的两个具体办法

### 办法 1：会话内端到端复测（把原故障的两个阴性指标翻正）

在 Claude Code 会话中：先让 Claude 进入子目录工作（复现原故障条件，如 `cd src`），再让它执行一次会被拦截的危险命令（安全替身：对可重建的空目录执行 `rm -rf ./dist`，或临时往脚本拦截名单加一条无害模式）。**修复生效的三个信号**：

1. 工具调用被**阻断**，`rm -rf` 没有真正执行；
2. Claude 收到 stderr 反馈 "BLOCKED: Dangerous rm command detected"（退出码 2 = stderr 自动反馈给 Claude，`_raw_README.md:301,316`）；
3. `logs/` 下出现新日志：`cat logs/pre_tool_use.json | jq '.'`（README 同款体验命令，`_raw_README.md:532-535`）能看到新增记录。

补充：若 `settings.json` 是会话中途修改的，先用 `/hooks` 菜单确认 PreToolUse 已注册并经审查生效（Claude Code 对会话中途的 hooks 变更要求确认）。

### 办法 2：从子目录用 stdin 管道手动复测（直接验证"任意 cwd 都能找到脚本"）

```bash
cd /home/dev/shop-api/src
export CLAUDE_PROJECT_DIR=/home/dev/shop-api   # Claude Code 派发 hook 时会注入该变量；手动模拟时自己设置
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf ./dist"}}' | uv run "$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py"
echo "exit=$?"
```

预期：输出 `BLOCKED: Dangerous rm command detected` 且 `exit=2`。这与原手动测试的唯一差别是 cwd 在子目录，等价于模拟了会话内 hook 的启动条件，能直接证明根因（cwd 依赖）已消除。

> ⚠️ 不要写成单行前缀形式 `CLAUDE_PROJECT_DIR=/home/dev/shop-api uv run "$CLAUDE_PROJECT_DIR/..."`——`$CLAUDE_PROJECT_DIR` 会在**当前 shell**（该变量尚为空）展开后再执行命令，路径会碎掉。本会话已实测对比：单行前缀形式报 `error: Failed to spawn: .../.claude/hooks/pre_tool_use.py`，export 形式正常输出 BLOCKED + exit 2（见附录 T4）。
>
> 本机沙盒中已完整执行过该办法的等价流程（从子目录 `src/`、export 变量、stdin 管道 JSON），结果 BLOCKED + 退出码 2，日志新增一条（附录 T3）。

---

## 附录：本会话实测复现记录

> 环境：Windows Server 2022 + Git Bash + uv 0.12.15（本机无 Claude Code，复现的是"同一条 hook 命令在不同 cwd 下的解析行为"这一机制层；dev 机不可达，事故事实以任务描述为准）。沙盒：`C:\Users\Administrator\AppData\Local\Temp\hooktest\`，内含 `.claude/hooks/pre_tool_use.py`（读 stdin JSON，命中 `rm -rf` 则 stderr 打印 BLOCKED 并 `sys.exit(2)`，同时向 `logs/pre_tool_use.json` 追加一条记录）、`src/`、`logs/`。

| # | 命令（cwd） | 输出 | 退出码 | 对应现实场景 | 结论 |
|---|---|---|---|---|---|
| T1 | `printf '%s' '{"tool_name":"Bash","tool_input":{"command":"rm -rf ./dist"}}' \| uv run .claude/hooks/pre_tool_use.py`（沙盒根目录） | `BLOCKED: Dangerous rm command detected` | 2 | 开发者根目录手动测试 | 脚本逻辑正常，相对路径在根目录可解析 |
| T2 | 同上命令（cwd=沙盒 `src/`） | `error: Failed to spawn: \`.claude/hooks/pre_tool_use.py\`  cause: 系统找不到指定的路径。 (os error 3)` | 2（uv 自身） | **会话内 cwd=src/ 时 hook 实际经历** | 脚本从未运行 → 无 BLOCKED、无日志写入 |
| T3 | `export CLAUDE_PROJECT_DIR=<沙盒根>` 后 `uv run "$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py"`（cwd=沙盒 `src/`） | `BLOCKED: Dangerous rm command detected` | 2 | **修复后的会话内 hook** | 从子目录也能解析，拦截恢复 |
| T4 | 单行前缀形式 `CLAUDE_PROJECT_DIR=<沙盒根> uv run "$CLAUDE_PROJECT_DIR/..."`（cwd=沙盒 `src/`） | `error: Failed to spawn: \`C:/Program Files/Git/.claude/hooks/pre_tool_use.py\`...` | 2 | （d) 中提醒的写法陷阱 | `$VAR` 在当前 shell 先展开，须用 export |

日志核对：沙盒 `logs/pre_tool_use.json` 恰有 2 行（分别来自 T1、T3），**T2 没有留下任何日志**——精确复刻事故中"脚本没跑所以无新日志"的症状。

配置校验：修复后的 `settings.json` 用 `uv run python -c "import json; json.load(open('settings_fixed.json'))"` 解析通过，读回的 command 字段为 `uv run $CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py`。

---

## 证据索引

| 论断 | 依据 |
|---|---|
| hook 路径必须用 `$CLAUDE_PROJECT_DIR` 前缀（README 加粗 Important） | `_raw_README.md:554`（本会话读原文） |
| hook 执行环境：继承环境变量 / 在当前工作目录运行 / stdin JSON / 60s 超时 | `_raw_README.md:461-468` |
| 退出码语义：0=成功；2=阻断错误（stderr 反馈 Claude）；其他=非阻断（stderr 给用户，执行继续） | `_raw_README.md:298-302` |
| PreToolUse 可阻断工具调用 + `rm -rf` 拦截示例（`print(..., file=sys.stderr); sys.exit(2)`） | `_raw_README.md:314-325` |
| 标准配置示例（`uv run $CLAUDE_PROJECT_DIR/.claude/hooks/...`） | `_raw_README.md:541-552`（`:547` 为命令行原文） |
| `logs/` 由 hook 脚本自身写入 | `_raw_README.md:288` |
| 事故事实（根目录测试通过、会话无拦截无日志、pwd=src/、已装 uv） | 任务描述（ask 原文） |
| 不同 cwd 下命令解析行为、日志缺失、export 写法 | 本会话实测 T1–T4 与 JSON 校验（见附录） |

---

*说明（按任务要求注明）：已先完整阅读 `ASSET-DOC.md`（v02，2026-09-29 核验）并按其方法执行——所有 README 论断均引 `_raw_README.md` 行号原文，机制层论断均以本会话实测复核，未核实之处已明确标注。ASSET-DOC 与本任务无实质冲突；唯一以任务为准之处：事故现场（/home/dev/shop-api）不在资产库覆盖范围，事故侧事实以任务描述为据，本机仅复现机制。*
