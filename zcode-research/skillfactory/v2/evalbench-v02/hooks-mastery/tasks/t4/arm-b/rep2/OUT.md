# t4 排查报告：PreToolUse 危险命令拦截 hook 不触发

> **一句话结论**：`command` 里用了相对路径 `uv run .claude/hooks/pre_tool_use.py`，而 Claude Code 是在**会话当前工作目录**（本案由 `pwd` 证实为 `/home/dev/shop-api/src`）执行 hook 命令的——相对路径在那里被解析成不存在的 `/home/dev/shop-api/src/.claude/hooks/pre_tool_use.py`，hook 命令在脚本运行之前就失败了，所以既不拦截、也没有日志；手动测试通过，只是因为人恰好站在仓库根目录。修复：给命令加 `$CLAUDE_PROJECT_DIR` 前缀。

---

## (a) 最可能的根因，以及为什么两个现象并不矛盾

### 根因

`settings.json` 中的 hook 命令写成了相对路径：

```json
"command": "uv run .claude/hooks/pre_tool_use.py"
```

关键事实（三条证据互相咬合）：

1. **hook 命令的执行 cwd 是"会话当前目录"，不是恒等于仓库根。** 官方文档（code.claude.com/docs/en/hooks，2026-09-29 抓取）原文：*"Handlers run in the current directory with Claude Code's environment."*，并说明该目录失效时才逐级回退到 *"the directory the session started in, the project root, your home directory, or the system temp directory"*；文档同时区分了 `${CLAUDE_PROJECT_DIR}`（*"the project root where the session started"*）与随 Claude 移动的 `cwd` 字段（worktree 场景下 *"the `cwd` input field follows Claude"*）。也就是说：Claude 在会话里 `cd` 到哪，hook 进程的 cwd 就跟到哪。
2. **教学库 README 早就把这一点标成了 Important。** README 原文（本资产库 `_raw_README.md:554`）：*"**Important:** Use `$CLAUDE_PROJECT_DIR` prefix for hook paths in settings.json to ensure reliable path resolution across different working directories."* —— 这句话本身只有在"hook 的 cwd 会漂移"的前提下才有意义。
3. **本案的 `pwd` 是直接物证。** Claude 正在 `/home/dev/shop-api/src` 工作，于是 hook 命令实际等价于 `cd /home/dev/shop-api/src && uv run .claude/hooks/pre_tool_use.py`，uv 去找 `/home/dev/shop-api/src/.claude/hooks/pre_tool_use.py` —— 不存在。

后果链：hook 命令在**脚本第一行都没执行**的情况下失败 → 拦截逻辑从未运行 → `rm -rf ./dist` 不被拦、`logs/` 里也永远不会因为这个 hook 而新增文件（日志是脚本自己在放行路径上写的，见 (d) 的源码依据）。

### 为什么「手动在根目录测试通过」与「Claude 会话中不触发」不矛盾

因为相对路径的解析基准是**执行命令那一刻的进程 cwd**，而两次执行的 cwd 不同：

| | 手动测试 | Claude 会话中的 hook |
|---|---|---|
| 命令字符串 | `uv run .claude/hooks/pre_tool_use.py` | 完全相同 |
| 执行 cwd | `/home/dev/shop-api`（开发者站在仓库根） | `/home/dev/shop-api/src`（会话当前目录） |
| 实际查找路径 | `/home/dev/shop-api/.claude/hooks/pre_tool_use.py` ✅ 存在 | `/home/dev/shop-api/src/.claude/hooks/...` ❌ 不存在 |
| 结果 | BLOCKED，退出码 2 | 命令报错，脚本根本没跑 |

同一个命令字符串，在两个 cwd 下命运相反。这正是本次故障的本质：**这个 hook 是否生效，取决于"Claude 当时恰好在哪个目录干活"这样一个随会话漂移的隐含条件**——这也是 README 把 `$CLAUDE_PROJECT_DIR` 前缀标为 Important 的全部原因。

我在本机对故障做了 1:1 复现（Windows 11 + uv 0.12.15，目录结构完全照搬：`shop-api/{.claude/hooks/pre_tool_use.py, src/}`，脚本用教学库原版 `pre_tool_use.py`，输入用故障同款 JSON）：

```text
=== Test A（现有配置，cwd=仓库根，即开发者的手动测试）===
BLOCKED: Dangerous rm command detected and prevented
EXIT=2

=== Test B（现有配置，cwd=src 子目录，即 Claude 会话中的情形）===
error: Failed to spawn: `.claude/hooks/pre_tool_use.py`
  cause: 系统找不到指定的路径。 (os error 3)
EXIT=2

=== Test B2（两个位置均无任何日志产生）===
logs: No such file or directory；src/logs: No such file or directory
```

Test A/B 与题面两个现象逐字对应：**同一命令，仅 cwd 不同，一个 BLOCKED、一个 spawn 失败且无日志。**

### 一个如实标注的细节（不改变结论）

本机实测中，`uv run` 对"脚本不存在"的失败**退出码是 2**（Test B）。而按退出码契约（README 与官方文档一致：PreToolUse 下 2 = 阻断工具调用），如果这个失败以退出码 2 浮出水面，现象应当是"**每次工具调用都被这个 spawn 错误阻断**"——比题面报告的现象更响亮。题面报告的是"正常执行、毫无拦截"，说明在出事的那台 Linux 机器上，失败是以**非 2 退出码**浮出的（按契约非阻断：stderr 仅展示给用户、执行继续）。典型分支是 hook 进程的 `PATH` 里没有 `uv`（shell 直接 `command not found`，退出码 127，非阻断——uv 常被装在 `~/.local/bin`，若 Claude Code 从 GUI/IDE 启动而非交互 shell，PATH 可能不带它）；也可能那台机器上的 uv 对 spawn 失败返回别的码。

无论走哪个分支：**根因（相对路径导致 hook 找不到脚本、脚本从未运行）不变，修复不变。** 我曾尝试在本机 WSL（Ubuntu-24.04）安装 uv 复测 Linux 侧退出码，下载停滞未完成，此点**未能核实**，特此如实说明。

---

## (b) 修复后的 command 配置行

```json
"command": "uv run \"$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py\""
```

放回完整 `settings.json`（可直接粘贴）：

```json
{
  "permissions": { "allow": ["Bash(ls:*)"] },
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          { "type": "command", "command": "uv run \"$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py\"" }
        ]
      }
    ]
  }
}
```

三点说明：

- **保留 `uv run`**：这是 uv 单文件脚本（依赖以内嵌元数据声明在脚本头部），`uv run` 负责按需装依赖再执行，是教学库 README 明确的架构（README："所有 hook 是 `.claude/hooks/` 下的独立 Python 脚本，依赖声明内嵌于脚本头部，由 `uv run` 执行"）。要修的只是路径，不是运行器。
- **`$CLAUDE_PROJECT_DIR` 由 Claude Code 在执行 hook 时注入**，值为 *"the project root where the session started"*（官方文档原文），与 cwd 无关，因此会话里无论漂到哪个子目录都解析到仓库根下的同一份脚本。
- **给路径套双引号**（JSON 里写作 `\"`）：官方文档对 shell 形式 hook 的建议是 *"In shell form, wrap each placeholder in double quotes."*，防工程路径带空格时断裂。不带引号的 `uv run $CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py` 在无空格路径下同样可用，但带引号是更稳的写法。

修复有效性已实测（Test C，在复现环境的 `src/` 子目录、设置 `CLAUDE_PROJECT_DIR` 后执行修复命令）：

```text
BLOCKED: Dangerous rm command detected and prevented
EXIT=2
```

---

## (c) 为什么写死绝对路径"能临时解决"但不是好方案

先承认它为什么**能**用：绝对路径与 cwd 无关。实测（Test D，在 `src/` 子目录执行）：

```text
=== uv run ~/hookrepro/shop-api/.claude/hooks/pre_tool_use.py（写死绝对路径，cwd=src）===
BLOCKED: Dangerous rm command detected and prevented
EXIT=2
```

但它**不该**用，四个理由：

1. **绑死机器与仓库位置，复发方式与本次一模一样。** 换台机器、换个用户、仓库移动/改名/克隆到别的路径（包括 CI、同事的 checkout、worktree），这个路径立刻失效——而且失效的姿态和这次故障完全相同：hook 静默失败、不拦截、无日志。等于把同一颗雷重新埋回去。
2. **`.claude/settings.json` 是项目级共享配置。** 它通常随仓库提交，服务全组与 CI。写死 `/home/dev/shop-api/...` 意味着这份配置只在"你这一台机器的这个 checkout"上是正确的；正确的写法必须对"仓库在哪"保持中立，而 `$CLAUDE_PROJECT_DIR` 正是 Claude Code 专门为这个中立性提供的环境变量。
3. **与 README/官方最佳实践相悖。** README 把 `$CLAUDE_PROJECT_DIR` 前缀标注为 **Important**（`_raw_README.md:554`）；官方文档不仅提供该变量，还配套建议对占位符加双引号。用工具为此设计的机制，而不是绕过它。
4. **维护成本。** 绝对路径不可携带、不可评审（评审者无法判断 `/home/dev` 是否对）、还会在项目搬迁后悄悄腐烂；`$CLAUDE_PROJECT_DIR` 的语义由 Claude Code 保证，项目去哪它跟到哪。

---

## (d) 修复后验证 hook 已生效的两个具体办法

### 办法 1：离线管道复测——从"案发子目录"证明命令在任何 cwd 都能找到脚本

不依赖 Claude，直接复刻 hook 的调用方式，但**故意站在当初出故障的 `src/` 子目录**（这正是原故障与手动测试的差异点）：

```bash
cd /home/dev/shop-api/src                      # 故意站在子目录
export CLAUDE_PROJECT_DIR=/home/dev/shop-api   # 模拟 Claude Code 注入的环境变量
printf '%s' '{"tool_name":"Bash","tool_input":{"command":"rm -rf ./dist"}}' \
  | uv run "$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py"
echo "exit=$?"
```

**期望**：stderr 打印 `BLOCKED: Dangerous rm command detected and prevented`，`exit=2`。（本机 Test C 的等价实测结果与此完全一致。）

注意要先用 `export` 再展开：写成单行前缀形式 `CLAUDE_PROJECT_DIR=/x uv run "$CLAUDE_PROJECT_DIR/..."` 是错的——POSIX shell 先做参数展开、后应用临时赋值，`$CLAUDE_PROJECT_DIR` 会展开成空串。

**反向对照**（确认修的正是原故障）：同一命令去掉 `$CLAUDE_PROJECT_DIR` 前缀、站在 `src/` 下执行，必须复现 `Failed to spawn` 报错（本机 Test B 实测即此表现）。修复后这条对照应不再出现。

### 办法 2：Claude 会话端到端验证 + 查日志

修改 `settings.json` 后**重启 Claude Code 会话**（hook 配置变更需重启或经 `/hooks` 菜单审查后才加载生效），然后：

1. 让 Claude 尝试一条危险的 `rm -rf`（如 `rm -rf ./dist`，或对准一个可丢弃的探针目录如 `/tmp/hook-probe`）。
   **期望**：该工具调用**不被执行**，Claude 收到 hook 的 stderr 反馈（`BLOCKED: Dangerous rm command detected and prevented`）并改道或向你报告被拦。辅助观察：用 `claude --debug` 启动可在输出中看到每次 hook 的执行与 stderr；也可先用 `/hooks` 菜单确认 PreToolUse 下该命令已注册。
2. 再让 Claude 跑一条**安全**命令（如 `pwd`），然后查日志文件有新记录。
   **期望**：`logs/pre_tool_use.json` 出现本次调用的 JSON 记录。

**日志落点与"为什么用安全命令查日志"的精确依据**（读教学库原版脚本源码 + 本机 Test E 实测）：该脚本的日志写在 `Path.cwd() / 'logs' / 'pre_tool_use.json'`（`pre_tool_use.py:108-110`），即 **hook 进程 cwd（= 会话当前目录）**下的 `logs/`——若会话在 `src/`，日志在 `src/logs/` 而非仓库根；且日志只记录**放行**的调用（命中危险命令时在写日志之前就 `sys.exit(2)` 了，`pre_tool_use.py:104-105`），所以验证日志要用安全命令触发，而非被拦的命令。本机 Test E 实测：从 `src/` 下以修复命令跑安全 payload，退出码 0，日志落在 `src/logs/pre_tool_use.json`：

```json
[
  {
    "tool_name": "Bash",
    "tool_input": { "command": "pwd" }
  }
]
```

（办法 1 的命令与期望输出是本机等价复现实测；办法 2 是在出事机器上的操作程序——本机无该 Linux 会话，未执行，其机制依据为官方文档的阻断语义与本机 Test E 的日志落点实测。）

**顺带的改进建议（超出本题、一句话）**：脚本自身的日志路径也是 cwd 相对写入的（`:108`），若希望日志稳定落在仓库根，应把脚本里的 `Path.cwd()` 改为从 `CLAUDE_PROJECT_DIR` 环境变量取根。

---

## 附：本机复现记录汇总（全部实测于 2026-09-29，Windows 11 x64 + uv 0.12.15；脚本为教学库原版 `.claude/hooks/pre_tool_use.py` 逐字副本，输入为题面同款 JSON）

| # | 命令（cwd） | 输出 | 退出码 | 对应论点 |
|---|---|---|---|---|
| A | `printf '%s' '{"tool_name":"Bash","tool_input":{"command":"rm -rf ./dist"}}' \| uv run .claude/hooks/pre_tool_use.py`（仓库根） | `BLOCKED: Dangerous rm command detected and prevented` | 2 | 手动测试通过的现象与机理 |
| B | 同上（`src/` 子目录） | `error: Failed to spawn: '.claude/hooks/pre_tool_use.py'`（os error 3，路径不存在） | 2 | 根因：cwd 漂移导致相对路径解析失败；无日志产生 |
| C | `export CLAUDE_PROJECT_DIR=…; … \| uv run "$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py"`（`src/` 子目录） | `BLOCKED: …` | 2 | (b) 修复命令在子目录下生效 |
| D | `… \| uv run <绝对路径>/pre_tool_use.py`（`src/` 子目录） | `BLOCKED: …` | 2 | (c) 绝对路径"临时可用"属实 |
| E | 修复命令 + 安全 payload `{"tool_name":"Bash","tool_input":{"command":"pwd"}}`（`src/` 子目录） | 无 stderr；`src/logs/pre_tool_use.json` 新增该记录 | 0 | (d) 办法 2 的日志验证与日志落点 |

未做/未核实（如实声明）：出事机器上的真实 Claude Code 会话端到端复现（本机无该环境）；Linux 下 uv 对缺失脚本的退出码（WSL1 安装尝试因下载停滞中止）。

## 引用与依据清单

- **题面材料**：`.claude/settings.json` 原文配置；三条故障现象；`pwd` = `/home/dev/shop-api/src`；README 依据转述（Important 前缀、60 秒超时、stdin JSON、继承环境变量）。
- **README 原文存证** `_raw_README.md`（与 ASSET-DOC.md 同目录，935 行，逐字节对应上游）：
  - `:554` —— *"**Important:** Use `$CLAUDE_PROJECT_DIR` prefix for hook paths in settings.json to ensure reliable path resolution across different working directories."*
  - `:461-468` —— Hook Execution Environment（`:466` "Working Directory: Runs in current project directory"，其措辞问题见文末注明）。
  - `:180-191` —— uv 单文件脚本架构（依赖内嵌、`uv run` 执行）。
- **Claude Code 官方文档**（https://code.claude.com/docs/en/hooks ，2026-09-29 抓取）：
  - *"Handlers run in the current directory with Claude Code's environment."*（及失效回退链：session 启动目录 → 项目根 → 家目录 → 系统临时目录）
  - *"${CLAUDE_PROJECT_DIR}: the project root where the session started"*；worktree 场景 *"the `cwd` input field follows Claude"*
  - 退出码：*"Exit 2 means a blocking error"*（PreToolUse 下 *"Blocks the tool call"*）；*"Any other exit code doesn't block on its own for most hook events."*
  - *"In shell form, wrap each placeholder in double quotes."*；命令型 hook 输入 *"arrives on stdin"*。
- **教学库原版脚本** `.claude/hooks/pre_tool_use.py`（disler/claude-code-hooks-mastery@main，本机副本 `C:\Users\Administrator\hookrepro\shop-api\.claude\hooks\pre_tool_use.py`）：`:103-105` 命中危险命令→stderr BLOCKED→`sys.exit(2)`；`:108-110` 日志写 `Path.cwd()/logs/pre_tool_use.json`；`:107-129` 日志仅出现在放行路径。

## 与能力资产说明（ASSET-DOC）的关系及冲突处理

已按任务要求先完整读取 `ASSET-DOC.md` 并按其方法执行：全文以 README 原文存证（`_raw_README.md`，带行号）与可复现实测为依据组织结论，退出码语义、60 秒超时、stdin JSON、uv 单文件架构等均直接采用 ASSET-DOC §4/§5 的整理。**发现一处措辞冲突并按任务指示以任务为准、在此注明**：ASSET-DOC §4（转述 `_raw_README.md:466`）称 hook "在当前项目目录运行"（"Runs in current project directory"），若按字面理解则相对路径应始终可解析、本案故障不可能发生；经官方文档原文（"Handlers run in the current directory…"）与题面 `pwd` 证据、本机 Test B 复现三方印证，**操作语义是"hook 在会话当前工作目录执行"**——README `:466` 是该教学库 README 的不严谨措辞，且与其自身 `:554` 的 Important 条款（"across different working directories"）互为印证。本报告以此修正后的语义为准。
