# T4 排查报告：PreToolUse hook「rm -rf 拦截」在 Claude 会话中不触发

> 对象：`/home/dev/shop-api`（`.claude/settings.json` + `.claude/hooks/pre_tool_use.py`，uv 单文件脚本）
> 交付性质：本文即最终交付物（排查结论 + 修复配置 + 验证方案）。

---

## 0. 结论速览

- **根因**：hook 的 `command` 用了**相对路径** `uv run .claude/hooks/pre_tool_use.py`。hook 命令在**执行那一刻的当前工作目录（cwd）**下解析路径，而 Claude 会话的 cwd 已持久地变成 `/home/dev/shop-api/src`，于是路径被解析成 `/home/dev/shop-api/src/.claude/hooks/pre_tool_use.py`——一个不存在的文件。**脚本从未被执行**，所以无拦截、`logs/` 零新增日志。
- **修复**（一行）：

  ```json
  "command": "uv run \"$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py\""
  ```

---

## 1. 题面证据清单（下文用 [E*] 引用）

| 编号 | 证据 | 来源 |
|---|---|---|
| [E1] | 危险命令 `rm -rf ./dist` 被 Claude 正常执行，无任何拦截；`logs/` 无新日志 | 题面·故障现象 |
| [E2] | 开发者在**仓库根目录**手动 `echo '{"tool_name":"Bash",...}' \| uv run .claude/hooks/pre_tool_use.py` → 输出 BLOCKED、退出码 2 | 题面·故障现象 |
| [E3] | 同一会话中 Claude 执行 `pwd` 显示其正工作在 `/home/dev/shop-api/src` | 题面·故障现象 |
| [E4] | README（标注 Important）：hook 命令必须用 `$CLAUDE_PROJECT_DIR` 前缀，保证**跨工作目录**的路径解析可靠；hook 继承 Claude Code 环境变量、在当前目录运行、stdin 传 JSON | 题面·README 依据 |
| [E5] | `settings.json` 中 `PreToolUse` 条目**省略了 `matcher` 字段**；命令为 `uv run .claude/hooks/pre_tool_use.py` | 题面·配置 |

---

## 2. (a) 根因分析

### 2.1 机制：hook 命令按「执行时的 cwd」解析相对路径

官方 hooks 文档明确：

> "**Handlers run in the current directory** with Claude Code's environment."（hook 在当前目录、以 Claude Code 的环境执行）
> — https://code.claude.com/docs/en/hooks

Bash 工具的工作目录在**同一会话内是持久的**：Claude 在干活过程中 `cd` 进过 `src/`（或被要求在其中工作）之后，后续所有 Bash 调用——以及由工具调用触发的 PreToolUse hook 命令——都继承这个 cwd。这与 [E3] 的 `pwd` 输出完全吻合。

### 2.2 故障链条（逐步）

1. Claude 准备执行 `rm -rf ./dist` → PreToolUse hook **确实被触发**（配置有效，见 2.4）；
2. hook 命令 `uv run .claude/hooks/pre_tool_use.py` 在 cwd = `/home/dev/shop-api/src` 下启动；
3. 相对路径解析为 `/home/dev/shop-api/src/.claude/hooks/pre_tool_use.py` → **文件不存在**；
4. `uv run` 以报错结束（本机双平台实测：`error: Failed to spawn: '.claude/hooks/pre_tool_use.py'`，见附录 A），**mock 脚本的 BLOCKED / exit 2 / 写日志一行都没发生**；
5. 于是 [E1]：工具调用未被拦截（或仅收到与预期不符的 uv 报错）、`logs/` 无新日志。

所以「hook 不触发」是一处**误诊**：hook 本身每次都触发了，是 hook 的 **command 在错误的目录里找不到脚本**。这也解释了为什么故障对 cwd 敏感、而对脚本逻辑无关。

### 2.3 为什么「手动在根目录测试通过」与「会话内不触发」并不矛盾

两条通路**唯一的差别是执行命令时的 cwd**，而相对路径的解析结果正取决于 cwd：

| | 手动测试 [E2] | Claude 会话 [E1][E3] |
|---|---|---|
| cwd | `/home/dev/shop-api`（仓库根） | `/home/dev/shop-api/src` |
| `.claude/hooks/pre_tool_use.py` 解析为 | `<根>/.claude/hooks/pre_tool_use.py` ✔ 存在 | `<根>/src/.claude/hooks/pre_tool_use.py` ✘ 不存在 |
| 结果 | 脚本运行 → BLOCKED + exit 2 | uv 报错 → 脚本未运行 → 无拦截、无日志 |

换言之，开发者手动测试只验证了「**脚本逻辑**是对的」，没有复现「**Claude 实际执行 hook 命令时的目录环境**」。两现象不仅不矛盾，反而是同一根因在不同 cwd 下的两种必然表现；这也正是 README [E4] 把「必须用 `$CLAUDE_PROJECT_DIR`」标为 Important 的原因。

### 2.4 排除其他假设

- **不是 matcher 写错**：[E5] 虽省略 `matcher`，但官方文档明确 `"*", ""或省略 matcher` 均为 "Match all"，即该 hook 对每次工具调用都会触发。
- **不是配置未加载**：官方文档："Direct edits to hooks in settings files are normally picked up automatically by the file watcher."（对 settings 的直接修改通常会被文件监视器自动拾取。）
- **不是脚本坏了**：[E2] 手动运行脚本行为正确（BLOCKED + exit 2）。
- **不是 uv 缺失**：题面明示该机已装 uv，且手动测试用的就是同一条 `uv run`。

### 2.5 实测注记（诚实披露一个细节，不影响结论）

我在本机对「`uv run` 指向不存在的脚本」做了双平台实测（Windows + Linux/WSL1，附录 A）：**uv 此时的退出码是 2**（不是 1 或 127）。按官方语义，exit 2 本应「Blocks the tool call」并把 stderr 反馈给 Claude；其他非零码才是非阻断（"the action proceeds"）。据此把会话内的失败通路严格分为两种，两者**共同点是脚本从未运行**（→ 无拦截、无日志，与 [E1] 一致），且都由同一条命令的写法导致：

- **通路 A**：hook 环境中 `uv` 可用 → uv 找不到脚本 → exit 2 → 工具调用被挡下，但反馈给 Claude 的是 uv 的 `Failed to spawn` 报错而非脚本的 BLOCKED 拦截——对外观感仍是「安全检查形同虚设」（且 Claude 可能在报错后换路径重试，最终把 `dist` 删掉）。
- **通路 B**：hook 进程的 PATH 里没有 `uv`（claude 的启动环境与开发者交互 shell 不同）→ shell 报 command not found → exit 127 → 完全非阻断、默认不可见，工具照常执行——与题面「没有任何拦截」的表述完全一致。

区分二者只需在 (d) 中看一眼 debug 日志里 hook 的 exit code（2 vs 127）。无论哪条通路，根因层级相同：**这条命令的解析依赖「在哪个目录、什么环境下执行」，这正是不允许的**，修复与验证方法也完全一致。

---

## 3. (b) 修复后的配置

只需替换 `command` 一行（其余配置不动）：

```json
{
  "permissions": { "allow": ["Bash(ls:*)"] },
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run \"$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py\""
          }
        ]
      }
    ]
  }
}
```

要点：

- `$CLAUDE_PROJECT_DIR` 由 Claude Code 在执行 hook 时注入，值是「**会话启动时的项目根**」（官方文档：`${CLAUDE_PROJECT_DIR}` 指 "the project root where the session started"，在 worktree 等场景下也 "stays put"）。它与 cwd 解耦，任何子目录里触发都能命中仓库内的脚本——这就是 README [E4] 标 Important 要求的写法。
- 路径整体加引号（JSON 里转义为 `\"`），防止项目路径含空格时被 shell 拆词；`"$VAR"/...` 与 `"$VAR/..."` 两种引法皆可。
- 对 PEP 723 单文件脚本，`uv run <脚本路径>` 依据**脚本自身内联元数据**构建运行环境，与 cwd 无关——所以把路径修对即可，无需 `--directory` 之类补救。
- （可选，新版写法）官方现推荐「路径占位符用 exec 形式」：`"command": ["uv", "run", "$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py"]`，可彻底绕开 shell 引号问题；上面的 shell 形式与题面 README 一致，同样正确。

本配置的 JSON 合法性已实测验证：`json.load` 解析通过，取回的 command 值为 `uv run "$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py"`（附录 A 第 4 项）。

---

## 4. (c) 为什么写死绝对路径「能临时解决但不是好方案」

`uv run /home/dev/shop-api/.claude/hooks/pre_tool_use.py` 的确能让路径与 cwd 无关，故障立即消失——但它是把「这台机器、这个用户、这个克隆位置」硬编码进了配置：

1. **不可移植**：`.claude/settings.json` 是项目级共享配置（通常入库）。换一台机器、换一个用户、换一个克隆路径（别的同事 `/home/alice/`、CI 容器 `/workspace/`），配置即失效，且是**静默失效**——对一个安全护栏来说，失效而不报错是最坏的失败模式。
2. **多克隆互踩**：机器上若存在两个 checkout（如主仓 + worktree），硬编码路径会让其中一个会话执行**另一份 checkout 里的脚本**——护栏可能跑的是错误版本的拦截逻辑，比不跑更具迷惑性。
3. **仓库迁移即碎**：仓库改名、挪目录、迁入容器/沙箱后，同样静默断链。
4. **信息泄露与一致性**：向所有拿到该配置的人暴露本机目录结构与用户名；团队里人人各改各的，无法作为统一约定 review。
5. **官方机制就是为此设计的**：`$CLAUDE_PROJECT_DIR` 是 Claude Code 提供的「自定位」变量（README Important [E4]、docs 明说用于 "regardless of the working directory when the hook runs"），一行配置即可与任何克隆位置解耦。绝对路径只应存在于**个人本机调试**（如 `settings.local.json` 临时试验），不应作为正式修复。

---

## 5. (d) 修复后验证 hook 已生效的两个具体办法

### 办法一：会话内端到端复现（验证真实链路）

1. 保存新配置后**重启 claude 会话**（当前版本 file watcher 会自动拾取 settings 修改；旧版本在启动时快照 hooks 配置，重启最稳妥），并执行 `/hooks` 菜单确认 PreToolUse 下已挂上该 command。
2. 造一个无害演练目标，并**故意在子目录里**触发（复刻故障条件）：
   ```bash
   mkdir -p /home/dev/shop-api/src/__hook_selftest__
   # 然后让 Claude 执行：cd /home/dev/shop-api/src && rm -rf ./__hook_selftest__
   ```
3. **通过判据**：该次 Bash 调用被阻断（目录仍在、Claude 收到 BLOCKED 反馈），且 `/home/dev/shop-api/logs/` 出现新日志行。目录被删 = 未生效。
4. （顺带确诊）用 `claude --debug` 启动会话：debug 日志会打印每次 hook 的 command、exit code 与 stderr——若看到 `Failed to spawn` + exit 2，说明路径仍未修对；若看到 command not found + exit 127，则是 uv 不在 hook 的 PATH，需要另行处理 PATH。

### 办法二：脱离会话的最小复现 + 退出码断言（验证跨目录解析，不依赖 Claude）

```bash
# 刻意复刻 Claude 当时的故障工作目录
cd /home/dev/shop-api/src

# 修复后的命令（模拟 Claude Code 注入 CLAUDE_PROJECT_DIR）
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf ./dist"}}' \
  | CLAUDE_PROJECT_DIR=/home/dev/shop-api sh -c \
    'uv run "$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py"'
echo "exit=$?"
# 期望：stderr 输出 BLOCKED ...，且 exit=2
```

并做**对照组**：同在 `src/` 下把管道命令换回修复前的 `uv run .claude/hooks/pre_tool_use.py`——应复现失败（本机实测为 `error: Failed to spawn: '.claude/hooks/pre_tool_use.py'`）。一过一败、唯一变量是路径写法，即直接证明原故障由 cwd 决定、修复消除了这种依赖。

---

## 附录 A：本次实测记录（命令与输出原文）

> 说明：题面场景机 `/home/dev/shop-api` 是题述环境，本机不可达，未做任何实地操作；以下为本机对同一故障机制的**忠实复现**（mock 脚本与题面脚本行为一致：stdin 读 JSON，命中 `rm -rf` → stderr 输出 BLOCKED、`sys.exit(2)`），目录结构相同（`proj/.claude/hooks/pre_tool_use.py` + `proj/src/`）。

**环境**：Windows Server 2022（uv 0.12.15）+ WSL1 Ubuntu 24.04（uv 0.12.20, x86_64-unknown-linux-gnu，经 pip 安装）；mock 脚本与 input.json 同源共用。

1. **Windows，仓库根（复刻 [E2]）**——`cd <tmp>/hookdemo/proj && uv run .claude/hooks/pre_tool_use.py < src/input.json`：
   ```
   BLOCKED: refusing dangerous command: rm -rf ./dist
   EXITCODE=2
   ```
2. **Windows，src 子目录（复刻 [E1][E3] 故障条件）**——同命令、cwd 改为 `.../proj/src`：
   ```
   error: Failed to spawn: `.claude/hooks/pre_tool_use.py`
     cause: 系统找不到指定的路径。 (os error 3)
   EXITCODE=2
   ```
3. **Linux/WSL1，脚本化三组对照**（`bash /tmp/linux_run.sh`，结果写 `linux-results.log` 后整读，规避 wsl.exe 的输出/退出码传输失真；sanity 组 `false` → `EXITCODE=1` 证明退出码捕获可靠）：
   ```
   == case 1: from project root (mirrors manual test) ==
   BLOCKED: refusing dangerous command: rm -rf ./dist
   EXITCODE=2

   == case 2: from src subdirectory (mirrors Claude session cwd, relative path) ==
   error: Failed to spawn: `.claude/hooks/pre_tool_use.py`
     cause: No such file or directory (os error 2)
   EXITCODE=2

   == case 3: from src with CLAUDE_PROJECT_DIR (the fix) ==
   BLOCKED: refusing dangerous command: rm -rf ./dist
   EXITCODE=2
   ```
   （case 3 命令：`export CLAUDE_PROJECT_DIR=<proj>; uv run "$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py" < input.json`。）
4. **修复配置 JSON 校验**——`python -c "import json; d=json.load(open('fixed-settings.json', encoding='utf-8')); ..."`：
   ```
   PARSED OK
   command = uv run "$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py"
   ```

**未做的事**：未能（也无法）在题面机器 `/home/dev/shop-api` 上实际执行任何命令；无法确认该机故障属于 2.5 节通路 A 还是通路 B——该区分依赖该机 `claude --debug` 日志，已写入 (d) 办法一第 4 步作为现场确诊手段。上述结论对该细节不敏感（两条通路根因与修复一致）。

## 附录 B：引用来源

- 题面：故障现象、settings.json 原文、README 依据摘录（[E1]–[E5]）。
- 官方 hooks 文档，https://code.claude.com/docs/en/hooks （2026-09-29 经 WebFetch 两次定向摘引）：
  - "Handlers run in the current directory with Claude Code's environment."
  - `${CLAUDE_PROJECT_DIR}` = "the project root where the session started"；占位符用于 "reference hook scripts relative to the project … regardless of the working directory when the hook runs"；"Prefer exec form for any hook that references a path placeholder."
  - "Exit 2 means a blocking error"（PreToolUse：Blocks the tool call）；其他非零码为非阻断、"the action proceeds"，transcript 显示 `Failed with non-blocking status code:`；官方告诫 "If your hook is meant to enforce a policy, use `exit 2`."
  - matcher `"*", "", or omitted` 均 "Match all"。
  - "Direct edits to hooks in settings files are normally picked up automatically by the file watcher."
- 本机实测：附录 A 第 1–4 项（Windows + Linux/WSL1 双平台，命令与输出如原文所录）。
