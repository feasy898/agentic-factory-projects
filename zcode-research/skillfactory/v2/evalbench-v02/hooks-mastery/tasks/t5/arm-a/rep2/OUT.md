# T5 评审报告：Stop hook「测试不过不许停」——为什么版本 A 拦不住、版本 B 拦得住，以及死循环怎么防

> 评审对象：同事的两版 `.claude/hooks/stop_check.py`（Stop hook，需求：测试未全部通过时强制 Claude 继续修复）。
> 依据：本资产库 README 原文存证 `_raw_README.md`（935 行，与上游逐字节一致，见 `../ASSET-DOC.md` 第 13 节核实记录）；所有 `:N` 行号均指该文件。
> 交付性质：本文即最终交付物。

---

## 0. 结论速览

| 版本 | 行为 | 判定 |
|---|---|---|
| A（`sys.exit(1)` + `print` 到默认 stdout） | 退出码 1 = **非阻断错误**，stderr 仅给用户、执行继续；对 Stop 事件**零阻断力**，Claude 照常停止 | ❌ 不能满足需求 |
| B（stdout 输出 `{"decision":"block","reason":...}` + `sys.exit(0)`） | 结构化决策 `block` 优先级高于退出码，**阻断停止、把 reason 反馈给 Claude 强制继续** | ✅ 满足需求（这正是 README 的官方示例，`_raw_README.md:449-459`） |
| A 的最小修复 | `print(..., file=sys.stderr)` + `sys.exit(2)`：阻断错误，stderr 自动反馈给 Claude | ✅ 满足需求 |
| B 的死循环顾虑 | 属实：无条件 block 会无限循环；防护 = 读 stdin payload，`stop_hook_active` 为 true 时放行 | ⚠️ 需补防护 |

---

## 1. 证据清单

**题面给定材料**（任务描述本身）：两版代码、五条 README 依据、测试现象（版本 A 时 Claude 正常结束、报错只在终端给用户；版本 B 行为符合预期）。

**README 原文**（本目录 `../../_raw_README.md`，行号经本会话 Read 核实）：

| 编号 | 位置 | 内容 |
|---|---|---|
| [R1] | `_raw_README.md:298-302` | 退出码表：0=成功（stdout 仅在 transcript 模式 Ctrl-R 给用户）；**2=阻断错误（Critical：stderr 自动反馈给 Claude）**；其他=非阻断错误（stderr 展示给用户，**执行继续正常进行**） |
| [R2] | `_raw_README.md:339-343` | Stop hook「CAN BLOCK STOPPING」：退出码 2 才阻断停止并把错误给 Claude（**forces continuation**）；Caution：控制不当会无限循环 |
| [R3] | `_raw_README.md:399-408` | Stop 决策控制：`"block"` 阻止 Claude 停止，**`reason`「Must be provided when blocking Claude from stopping」**，reason 告诉 Claude 如何继续 |
| [R4] | `_raw_README.md:410-417` | 控制优先级：`"continue": false` > `"decision": "block"` > 退出码 2 > 其他退出码 |
| [R5] | `_raw_README.md:449-459` | 官方「Completion Validation (Stop Hook)」示例——**与同事的版本 B 逐字一致** |
| [R6] | `_raw_README.md:123`（SubagentStop 为 `:128`）、`:568` | Stop/SubagentStop 的 payload 含布尔字段 `stop_hook_active`；最佳实践第 6 条：「Avoid Infinite Loops: Check `stop_hook_active` flag in Stop hooks」 |
| [R7] | `_raw_README.md:320-325` | 退出码 2 的配套写法：消息必须打到 **stderr**（`print(..., file=sys.stderr)`），因为反馈给 Claude 的是 stderr |

**本会话实测**（三份可运行最小脚本存于本目录 `verify/`，`all_tests_passed()` 桩固定返回 `False`；命令与原始输出见附录 A）：

| 编号 | 脚本 | 实测结果 |
|---|---|---|
| [V1] | `verify/a_snip.py`（版本 A 原文） | 退出码 **1**；消息在 **stdout**；stderr 为空 |
| [V2] | `verify/b_snip.py`（版本 B 原文） | 退出码 **0**；stdout 为一行合法 JSON `{"decision": "block", "reason": "Tests are failing. ..."}` |
| [V3] | `verify/a2_snip.py`（修复版） | 退出码 **2**；消息在 **stderr**；stdout 为空 |

---

## 2. (a) 版本 A 为什么拦不住 Claude 停止

**一句话：`sys.exit(1)` 落在优先级链的最底层——「其他退出码 = 非阻断错误」，它对 Stop 事件根本不产生任何阻断语义，Claude Code 收到非阻断错误后照常放行停止。**

逐步拆解：

1. **退出码 1 不在阻断通道里。** 依据 [R1]/[R4]：能让 Stop「阻断停止」的只有两件事——结构化 `"decision": "block"`（优先级 2）和退出码 2（优先级 3）；而退出码 1 属于「Other = Non-blocking Error」，语义被明确定义为「stderr 展示给用户，**执行继续正常进行**」（`_raw_README.md:302`）。所谓「执行继续」在 Stop 场景下就意味着：**停止动作照常完成**。
2. **报错信息走的是用户通道，不是 Claude 通道。** 非阻断错误的 stderr「仅展示给用户」（[R1]）；只有退出码 2 的 stderr 才会被「自动反馈给 Claude」（`_raw_README.md:301` 标注 Critical）。所以测试现象中「报错只在终端展示给用户、Claude 没有继续修复」正是 [R1] 预期的行为，不是偶发 bug。
3. **消息甚至不在 stderr 上。** 版本 A 用的是裸 `print(...)`，默认输出到 stdout——[V1] 实测：退出码 1、stdout 有消息、stderr 为空。而 stdout 按约定只在 transcript 模式（Ctrl-R）给用户看（`_raw_README.md:300`）。无论落在 stdout 还是 stderr，两条通道都**到不了 Claude**； Claude 根本不知道有测试失败这回事。
4. **对照：Stop 事件要阻断，退出码必须是 2。** [R2] 明确写着 Stop 的「Exit Code 2 Behavior: Blocks stoppage, shows error to Claude (forces continuation)」。版本 A 唯一的错误就是选错了退出码：**1 和 2 之间，一个放行、一个阻断**。

> 这也解释了为什么这个坑很常见：在普通 shell 脚本习惯里 `exit 1` 表示「出错」，但 hooks 协议里退出码被赋予了流控语义——1 不再是「错误就拦下」，而是「出错了但继续」。

---

## 3. (b) 版本 B 起作用的机制，以及 reason 为什么必须提供

### 3.1 机制

版本 B 就是 README 官方示例 [R5]（`_raw_README.md:449-459`）的逐字实现，它走的是**结构化 JSON 决策**通道，与退出码通道并行且优先级更高：

1. 脚本以 `sys.exit(0)` 干净退出（[V2] 实测退出码 0），Claude Code 于是**解析 stdout 的 JSON**；
2. 解析到 `"decision": "block"`，命中 Stop 决策控制 [R3]：「**Prevents Claude from stopping**」——停止动作被否决，Claude 被拉回对话循环；
3. `reason` 字段作为**反馈内容喂给 Claude**（[R3]：「reason tells Claude how to proceed」），于是 Claude 收到「Tests are failing. Please fix failing tests before completing.」这条可执行的指令，去继续修测试；
4. 依据 [R4]，`"decision": "block"` 的优先级高于退出码 2——在退出码 0 的前提下它本来就是唯一生效的控制信号。

一句话：**版本 A 试图用「进程退出码」说话但说错了频道；版本 B 用「结构化决策」在正确的频道上说话，所以 Claude 真的收到了「不许停 + 怎么办」。**

### 3.2 reason 为什么必须提供

- **协议层面是硬性要求**：[R3] 原文把 `reason` 标注为「**Must be provided when blocking Claude from stopping**」（`_raw_README.md:403`）。缺了它，block 决策不完整。
- **功能层面：reason 就是「强制继续」的唯一载体。** 阻断停止只是把 Claude 拦回来；拦回来之后 Claude 凭什么知道该干什么？全靠 reason。对 Stop 事件而言，block 的语义是「用 reason 重新提示 Claude」（与 PostToolUse 的 block 同构，`_raw_README.md:396`）。如果 block 而无 reason，Claude 被迫继续却没有得到任何方向——最可能的反应是**立刻再次尝试停止**，既没解决问题，又平白多触发一轮 hook（这正是 (d) 的死循环温床）。
- **工程层面：reason 决定了这轮「强制继续」是否有产出。** 好的 reason 应含可行动信息（本项目即「哪些测试在失败、去修复它们」），让下一轮工作直奔目标。

---

## 4. (c) 版本 A 的最小修改修复

**改法（推荐，改动最小、语义最直接）：把消息改到 stderr、退出码 1 改成 2。**

```python
# .claude/hooks/stop_check.py —— 修复版（阻断错误通道）
import sys

if not all_tests_passed():
    print("Tests are failing. Please fix failing tests before completing.", file=sys.stderr)  # ① 消息进 stderr
    sys.exit(2)                                                                                # ② 1 → 2
```

为什么是这两处：

- **`exit 2`**：对 Stop 事件，退出码 2 的定义就是「Blocks stoppage, shows error to Claude (forces continuation)」（[R2]），满足需求；
- **`file=sys.stderr`**：退出码 2 时被自动反馈给 Claude 的是 **stderr**（[R1]/[R7]）。若保留原 `print`（stdout），阻断会发生，但 Claude 收到的是一条**空的** stderr——强制了继续却没给原因，等于退化为「无 reason 的 block」。

**等效改法（改完即版本 B，同样是合法答案）**：按 README 官方示例 [R5] 输出 JSON 决策：

```python
import sys, json

if not all_tests_passed():
    print(json.dumps({
        "decision": "block",
        "reason": "Tests are failing. Please fix failing tests before completing."
    }))
    sys.exit(0)
```

两者实测均通过：`verify/a2_snip.py` 退出码 2、stderr 含消息（[V3]）；`verify/b_snip.py` 退出码 0、stdout 含决策 JSON（[V2]）。若采用退出码 2 方案，注意同会话内不要再混用 JSON 决策输出，避免两种通道语义叠加造成排查困难（[R4] 的优先级规则虽能兜底，但可读性差）。

---

## 5. (d) 死循环风险的成因与正确防护

### 5.1 成因：Stop hook 的阻断是「可重复触发」的

把时间线摊开：

```
Claude 想停止 → Stop hook 触发 → 测试失败 → block 强制继续
→ Claude 继续干活（可能没修好）→ Claude 再次想停止
→ Stop hook 再次触发 → 测试仍失败 → 再次 block → ……
```

README 对 Stop 的原始警告就是这句（[R2]，`_raw_README.md:343`）：「**Can cause infinite loops if not properly controlled**」。风险在两个条件下叠加成立：

1. **判定条件持续为假**：`all_tests_passed()` 一直不过（测试真的修不动、或判定函数本身有 bug——比如环境没装依赖导致永远 fail）；
2. **hook 无条件 block**：脚本不看任何历史状态，每次触发都阻断。两个条件都满足时，Claude 被永远钉在「继续 → 想停 → 被拦 → 继续」的循环里，烧 token 且无法自行退出。

### 5.2 正确防护：检查 payload 的 `stop_hook_active` 标志

`stop_hook_active` 是 Stop/SubagentStop 事件 payload 里的布尔字段（[R6]，`_raw_README.md:123`；hook 输入经 stdin 传入）。它的语义：当本次停止请求**本身就是上一轮「Stop hook 强制继续」之后的再次停止**时，该标志为 `true`。最佳实践第 6 条给出对应守则（[R6]，`_raw_README.md:568`）：「Avoid Infinite Loops: Check `stop_hook_active` flag in Stop hooks」。

**防护写法（完整可用的 Stop hook 骨架）：**

```python
# .claude/hooks/stop_check.py —— 带防死循环防护的完整版
import json
import sys


def all_tests_passed() -> bool:
    ...  # 项目自有测试判定逻辑


def main() -> None:
    payload = json.load(sys.stdin)          # hook 输入：JSON via stdin

    # 防护：这已经是"被强制继续之后"的第二次停止请求了。
    # 若测试仍不过，说明继续强压也已无效——放行停止，把问题交还给用户，
    # 而不是把 Claude 永远钉在循环里。
    if payload.get("stop_hook_active"):
        sys.exit(0)

    if not all_tests_passed():
        print(json.dumps({
            "decision": "block",
            "reason": "Tests are failing. Please fix failing tests before completing."
        }))
        sys.exit(0)


if __name__ == "__main__":
    main()
```

要点：

- **`stop_hook_active` 为 true 时必须放行（`exit 0`、无 block）**——这是打破循环的那一刀。效果：每轮强制继续后**最多再拦一次**，循环深度有界；
- 放行的取舍要向同事讲清楚：这不是放弃质量门，而是承认「无限强压」不是解法——第一轮 block 给了 Claude 一次完整修复机会，若仍不过，人工介入比死循环便宜得多。若想多给几轮机会，可以自行记录已 block 次数（如写入临时状态文件）设上限，但**标准做法就是查 `stop_hook_active`**（[R6]）；
- 同理适用于 SubagentStop（payload 同样带 `stop_hook_active`，`_raw_README.md:128`）。

### 5.3 给同事的最终建议

采用版本 B（它就是官方示例 [R5]），**但必须加上 5.2 的 `stop_hook_active` 防护**再上线；README 最佳实践第 7 条同时提醒（`_raw_README.md:569`）：先在安全环境充分测试——建议先用一个必定失败的测试验证 block 生效，再用「二次停止」路径验证 `stop_hook_active` 放行生效，两条都过才算验收。

---

## 附录 A：本会话实测记录

工作目录：`skillfactory/v2/evalbench-v02/hooks-mastery/tasks/t5/arm-a/rep2/verify/`。
三个脚本均为题面代码的最小可运行化：补上 `import sys`/`import sys, json` 与 `all_tests_passed()` 桩（固定返回 `False`），核心判断逻辑逐字保留。

执行命令（bash，逐段执行）：

```
python a_snip.py  >a.out  2>a.err; echo "exit=$?"
python b_snip.py  >b.out  2>b.err; echo "exit=$?"
python a2_snip.py >a2.out 2>a2.err; echo "exit=$?"
```

原始输出：

```
== Version A ==
exit=1
stdout: [Tests are failing. Please fix failing tests before completing.]
stderr: []
== Version B ==
exit=0
stdout: [{"decision": "block", "reason": "Tests are failing. Please fix failing tests before completing."}]
stderr: []
== Version A fixed (exit 2) ==
exit=2
stdout: []
stderr: [Tests are failing. Please fix failing tests before completing.]
```

说明：实测运行的是 **Python 脚本本身的退出码与 stdout/stderr 分流**（[V1][V2][V3]）；「Claude Code 收到退出码 2 / decision block 后阻断停止」这一环是对 README [R1][R2][R3][R4] 的引用结论，本次未在真实 Claude Code 会话中端到端复现（未执行端到端验证），题面给出的测试现象（版本 A 放行、版本 B 阻断生效）与该结论一致。

---

## 附注：ASSET-DOC 与本任务的关系

已按要求先完整读取 `ASSET-DOC.md` 并按其方法执行——本文全部结论均落在本资产库 README 原文存证 `_raw_README.md` 的具体行号上（[R1]–[R7]），并辅以本会话实测。ASSET-DOC 与任务无实质冲突（其第 5、11 节正是本任务的答案来源）；如个别表述以任务题面为准之处，均已在正文中按题面材料转述并标明来源。
