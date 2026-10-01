# PreToolUse Hook 不触发：根因分析与修复

> 场景：仓库 `/home/dev/shop-api`，`.claude/hooks/pre_tool_use.py`（uv 单文件脚本，命中危险命令时 `sys.exit(2)` 阻断）。
> 现象：`rm -rf ./dist` 在 Claude 会话中被正常放行、`logs/` 无新日志；但开发者在仓库根目录手动管道测试同一脚本，输出 BLOCKED 且退出码 2。

---

## (a) 最可能的根因，以及为什么两个现象不矛盾

### 根因：hook 命令用了相对路径，而 hook 实际执行时的工作目录不是仓库根目录

`settings.json`（任务材料原文）中 hook 命令是：

```
uv run .claude/hooks/pre_tool_use.py
```

这是一个**相对路径**。任务材料给出的 README 摘录恰好点明了要害——hook 命令必须用 `$CLAUDE_PROJECT_DIR` 前缀，「保证**跨工作目录**的路径解析可靠」（README 标注 Important）。这句话存在的原因是：hook 命令执行时继承 Claude 会话当时的当前工作目录，而会话的工作目录是会变的。

本例中会话证据显示 Claude 正在 `/home/dev/shop-api/src` 子目录里工作（`pwd` 输出）。于是 hook 触发时，实际执行的是：

```
uv run /home/dev/shop-api/src/.claude/hooks/pre_tool_use.py
```

`src/` 下并不存在 `.claude/hooks/pre_tool_use.py`，`uv run` 找不到目标脚本，直接报错退出——**脚本一行都没有执行**。三条现象因此全部自洽：

1. **`rm -rf ./dist` 被放行**：PreToolUse hook 的语义是退出码 2 才阻断工具调用；其它失败属非阻断错误，Claude Code 继续执行工具。脚本没跑成，自然没有"拦截"发生。
2. **`logs/` 无新日志**：日志由脚本自己写，脚本从未启动，当然没有日志。
3. **失败是"静默"的**：非阻断的 hook 失败其 stderr 只在 verbose/debug 输出里可见，会话照常进行。（反过来讲：如果这次失败产生了退出码 2，Claude 会被阻断并看到"文件不存在"的报错，而不是正常执行 `rm`——这与观测现象矛盾，可排除。）

顺带排除：`permissions.allow: ["Bash(ls:*)"]` 与本故障无关——它只管 `ls` 的权限放行，既不涉及 `rm`，也不影响 hook 的执行。

### 为什么「手动在根目录通过」与「会话内不触发」并不矛盾

开发者的手动测试是在 `/home/dev/shop-api` 根目录下运行的，此时相对路径 `.claude/hooks/pre_tool_use.py` 恰好能解析到真实脚本，于是得到 BLOCKED + 退出码 2。会话中 hook 触发时，起跑目录是 `/home/dev/shop-api/src`，同一条命令字符串解析到不存在的文件。

**两个测试的命令相同，但工作目录不同，解析结果一个成功、一个失败。** 手动测试无意中满足了「cwd = 仓库根」这个隐含前提，而这个前提在真实会话中（Claude 会 `cd` 进子目录干活）不成立。所以两个现象不但不矛盾，合在一起恰好把根因钉死在「相对路径 + 会话工作目录漂移」上。

---

## (b) 修复后的 command 配置行

用 `$CLAUDE_PROJECT_DIR`（Claude Code 在执行 hook 命令前注入的环境变量，值为项目根目录绝对路径）锚定脚本位置：

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

两个细节：

- JSON 字符串内的双引号必须写成 `\"`，否则整个 `settings.json` 解析失败（hook 会整体不加载，又是静默失败）。
- 给路径加引号是防路径含空格被 shell 拆词；README 的官方示例同样是给 `$CLAUDE_PROJECT_DIR` 整体加引号的写法（`"$CLAUDE_PROJECT_DIR"/.claude/hooks/check.sh` 形式），两种写法等价。

这样无论 Claude 当时在哪个子目录，`$CLAUDE_PROJECT_DIR` 都展开为仓库根的绝对路径，脚本总能被找到。

---

## (c) 为什么写死绝对路径是"能跑但不好"

`uv run /home/dev/shop-api/.claude/hooks/pre_tool_use.py` 确实能临时解决——绝对路径不依赖 cwd，Claude 在任何子目录下 hook 都能启动。但它：

1. **不可移植，且随仓库泄漏给所有人**。`.claude/settings.json` 通常随仓库提交。写死 `/home/dev/shop-api` 后，任何其他检出位置——同事的机器、CI 容器、另一块盘上的 clone、`git worktree` 工作树——拿到的都是一条指向不存在路径的 hook，在那台机器上**以和本次完全相同的方式静默失效**。
2. **仓库一动就坏，坏得无声**。目录一旦改名/搬移/重建，配置指向旧路径，hook 变成 no-op，没有任何报错提示你——正是本次排障最难的部分：没有日志、没有报错、只有"没拦住"。
3. **可能执行到错误的脚本副本**。若机器上残留旧目录或存在多个检出，写死的路径可能命中另一份过期脚本：你以为在跑新版拦截逻辑，实际在执行旧版——这种"hook 生效但行为不对"的问题排查成本极高。
4. **背弃官方契约**。`$CLAUDE_PROJECT_DIR` 就是 Claude Code 为这个场景提供的受支持机制（README 把它标为 Important）。写死路径等于用脆弱的机器特定配置替代官方保证，属于把故障"推迟"而不是修复。

---

## (d) 修复后验证 hook 已生效的两个具体办法

### 办法一：会话内实弹验证（端到端，最直接）

保持 Claude 在子目录工作状态（如 `/home/dev/shop-api/src`），先建一个一次性牺牲目录，再让它执行删除：

```bash
mkdir -p ./hook-canary        # 由开发者普通 shell 执行
# 然后在 Claude 会话里让它执行：
rm -rf ./hook-canary
```

**预期**：该工具调用被拒绝，Claude 的回复里带有 hook 的 stderr（BLOCKED…），且 `logs/` 出现新日志条目。与修复前的基线（放行 + 无日志）对照，即可确认 hook 在"子目录工作"这一原故障条件下已生效。用一次性目录可避免真拿 `dist` 或其他真实产物冒险。

### 办法二：无 Claude 复现故障条件，定点验证"cwd 无关性"

在原故障现场（子目录）分别跑旧命令和新命令，构成阴性/阳性对照：

```bash
# 1) 阴性对照：复现原始故障（在 src/ 下用旧相对路径，应失败）
cd /home/dev/shop-api/src
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf ./dist"}}' \
  | uv run .claude/hooks/pre_tool_use.py; echo "exit=$?"
#   → uv 报找不到文件，无 BLOCKED，退出码非 2。这就是线上症状的根。

# 2) 阳性验证：同一子目录下改用 $CLAUDE_PROJECT_DIR（应通过）
cd /home/shop-api/src 2>/dev/null || cd /home/dev/shop-api/src
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf ./dist"}}' \
  | CLAUDE_PROJECT_DIR=/home/dev/shop-api \
    uv run "$CLAUDE_PROJECT_DIR/.claude/hooks/pre_tool_use.py"; echo "exit=$?"
#   → 输出 BLOCKED，exit=2，logs/ 有新日志。证明路径解析不再依赖 cwd。
```

辅助手段：会话内输入 `/hooks` 可查看当前实际注册生效的 hook 列表（排除配置未被加载的情况）；用 `claude --debug` 启动可在输出中观察每次 hook 的执行细节（命令、实际 cwd、退出码、stderr），适合最终确认。

---

## 附：本次排查的依据与边界

- **结论依据**（全部来自任务材料本身）：① `.claude/settings.json` 原文（相对路径命令）；② 三条故障现象（放行 / 无日志 / 根目录手动测试通过 + 会话 `pwd` 显示在 `src/`）；③ README 摘录（`$CLAUDE_PROJECT_DIR` 的 Important 注记；hook 继承会话环境变量、60 秒超时、stdin JSON 输入、退出码 2 = 阻断）。
- **未运行声明**：场景仓库位于另一台机器的 `/home/dev/shop-api`，本环境无法访问，上述 (d) 的命令是交付给该机器执行的操作步骤，本次**未实际运行**；(a)–(c) 的推断链完全由给定材料支撑，其中「非阻断失败路径」的判断由现象反推（若失败产生退出码 2，`rm` 会被阻断并回显报错，与观测矛盾）。
