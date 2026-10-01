# T5 评审报告：Stop hook「测试不过不许停」——版本 A 为何失效、版本 B 机制、最小修复与防死循环

> 评审对象：同事写的 `.claude/hooks/stop_check.py` 两版核心实现（任务书给出）。
> 依据材料：任务书原文及其引用的 README 原文依据；`skillfactory/v2/evalbench-v02/hooks-mastery/ASSET-DOC.md`（下称 ASSET-DOC）及其存证原文 `_raw_README.md`（935 行，下称「原文」，行号均指该文件）。
> 验证方式：本机 Python 实际运行两版实现及修复版（`all_tests_passed()` 模拟为 False），喂入样例 stdin payload，实测退出码与 stdout/stderr 流向。全部命令与输出见第五节。

## 结论速览

| 问题 | 结论 |
|---|---|
| (a) 版本 A 为何不阻断 | `sys.exit(1)` 落入「其他退出码 = 非阻断错误」分支：stderr 只展示给用户、执行照常继续，对 Stop 事件零阻断；且消息打在 stdout，本就不会反馈给 Claude（实测 exit=1） |
| (b) 版本 B 为何有效 | 退出码 0 + stdout 结构化 JSON：`"decision": "block"` 阻止停止；`reason` 是把「如何继续」传给 Claude 的唯一通道，原文标注 "Must be provided when blocking Claude from stopping"（原文 403 行）。该写法即原文 449–457 行的官方示例 |
| (c) 版本 A 最小修复 | 改两处：`print(..., file=sys.stderr)` + `sys.exit(2)`（实测 exit=2、消息在 stderr） |
| (d) 死循环成因与防护 | 测试一直不过时「停止→block→被迫继续→再停止→再 block」无限循环；防护 = 解析 stdin payload，`stop_hook_active` 为 true 时直接放行 `sys.exit(0)`（实测三场景通过） |

---

## (a) 版本 A 为什么不能阻止 Claude 停止

**根因：退出码 1 不是阻断码。**

原文「Exit Code Behavior」表（原文 294–302 行）定义了三条退出码语义：

| 退出码 | 行为 | 说明 |
|---|---|---|
| 0 | 成功 | stdout 在 transcript 模式（Ctrl-R）展示给用户 |
| 2 | **阻断错误** | **Critical**：stderr 自动反馈给 Claude |
| 其他 | **非阻断错误** | stderr 展示给用户，**执行继续正常进行** |

版本 A 的失败路径是 `sys.exit(1)`，落入「其他」分支——非阻断错误。对 Stop 事件而言，只有「退出码 2（stderr 反馈）」或「结构化 JSON `decision: block`」两条路能拦住停止；退出码 1 对 Claude Code 来说只是「这个 hook 出了个非致命错误」，处理方式是**把错误信息展示给终端用户、然后照常放行停止**。这正是测试现象：Claude 正常结束回答，报错只出现在用户终端。

原文 Stop Hook 一节（原文 339–343 行）写明阻断停止的正确姿势：

> `- **Exit Code 2 Behavior**: Blocks stoppage, shows error to Claude (forces continuation)`（原文 341 行）
> `- **Caution**: Can cause infinite loops if not properly controlled`（原文 343 行）

版本 A 没有用上这条唯一的退出码阻断通道——它差一个数字（1 ≠ 2）。

**附加缺陷：消息走错了流。** 版本 A 用 `print(...)` 把消息打到 **stdout**。按原文表格，stdout 只有在退出码 0 时才会「在 transcript 模式展示给用户」；而能反馈给 Claude 的是退出码 2 时的 **stderr**。所以即便有人把版本 A 的退出码改成 2 却不改输出流，Claude 也收不到那条消息。版本 A 同时错在两处：**退出码（1，应为 2）与输出流（stdout，应为 stderr）**。

> 对测试现象的一个细节澄清：给出的版本 A 代码把消息 `print` 到 stdout，而现象描述说「stderr 的报错只在终端展示给用户」。二者不矛盾——退出码 1 之下无论 stdout 还是 stderr 都不会喂给 Claude；用户在终端看到的是 Claude Code 对非阻断 hook 错误的展示，这正是「其他退出码：stderr 展示给用户，执行继续」分支的既定行为。核心结论不因此改变。

## (b) 版本 B 起作用的机制，以及 reason 为什么必须提供

**机制：退出码 0 + stdout 结构化 JSON 决策，是独立于退出码语义的第二条控制通道。**

版本 B 的进程行为是「成功退出」（实测 exit=0）。单看退出码它什么都不阻断；起作用的是 Claude Code 对 stdout 上结构化 JSON 的解析。原文「Stop Decision Control」一节（原文 399–407 行）：

```json
{
  "decision": "block" | undefined,
  "reason": "Must be provided when blocking Claude from stopping"
}
```

> `- **"block"**: Prevents Claude from stopping, reason tells Claude how to proceed`（原文 406 行）

即 `decision: "block"` 使 Claude Code **阻止 Claude 停止**，并把 `reason` 作为反馈交给 Claude。两者叠加的优先级在原文「Flow Control Priority」（原文 410–417 行）中排定：

1. `"continue": false` > 2. `"decision": "block"` > 3. 退出码 2 > 4. 其他退出码

结构化决策（优先级第 2）**高于**退出码语义（第 3、4 档），所以「exit 0 + JSON block」的组合表达的是阻断而非放行。值得指出：**版本 B 一字不差就是原文给出的官方示例**——「3. Completion Validation (Stop Hook)」（原文 449–457 行）的代码与同事的版本 B 相同（`if not all_tests_passed():` → 输出 `{"decision": "block", "reason": "Tests are failing. ..."}` → `sys.exit(0)`，见原文 452 行起）。这不是偏方，是 README 的推荐实现。

**reason 为什么必须：它是 block 生效后把「如何继续」传给 Claude 的唯一通道。**

- 原文在 Stop 决策的 schema 里直接把 reason 的值写为 `"Must be provided when blocking Claude from stopping"`（原文 403 行）——阻断停止时**必须**提供；
- block 的目的不是单纯否决「停止」，而是把控制权交回 Claude 强制其继续干活。如果只有 block 没有 reason，Claude 只知道「不许停」，不知道为什么被拦、接下来做什么，等于把它扔回一个没有指令的循环里；
- 版本 B 的 reason 内容「Tests are failing. Please fix failing tests before completing.」正是任务要 Claude 做的事：先修复失败的测试。实测确认其 stdout 是合法 JSON 且 reason 非空（第五节第 2 项）。

## (c) 版本 A 的最小修改修复

改动两处（退出码 1→2；消息 stdout→stderr），其余不动：

```python
if not all_tests_passed():
    print("Tests are failing. Please fix failing tests before completing.", file=sys.stderr)
    sys.exit(2)  # 阻断错误：stderr 自动反馈给 Claude，Stop 事件下 = 强制继续
```

依据：原文 341 行——Stop hook 退出码 2 的行为是 "Blocks stoppage, shows error to Claude (forces continuation)"；原文 301 行——退出码 2 时 stderr 自动反馈给 Claude。实测（第五节第 3 项）：`fix_a.py` 以 exit=2 结束、消息出现在 stderr、stdout 为空，恰好构成「stderr 反馈给 Claude → 阻断停止」的通道。

（等价的另一种可行改法：直接采用版本 B 的 JSON 决策写法，即原文 449–457 行示例本身。任务书允许任一。）

## (d) 死循环风险的成因与正确的防护写法

**成因：Stop hook 在每次「尝试停止」时都会触发，block 会制造下一次触发。**

原文写明 Stop 事件的触发时机是 "When Claude Code finishes responding"（原文 122 行）。于是一旦测试**一直**不通过——修不好、环境坏掉、或 `all_tests_passed()` 判定本身有 bug——就形成闭环：

```
Claude 尝试结束回答 → Stop hook 触发 → 测试不过 → decision:block
→ Claude 被迫继续 → 修不好 → 再次尝试结束回答 → Stop hook 再次触发 → 再次 block → ……
```

会话永不结束，token/费用持续消耗。原文在 Stop Hook 一节明确警告（原文 343 行）："Caution: Can cause infinite loops if not properly controlled"；最佳实践清单第 6 条（原文 568 行）给出解法："**Avoid Infinite Loops**: Check `stop_hook_active` flag in Stop hooks"。该标志是 Stop/SubagentStop payload（stdin 传入的 JSON）中的布尔字段（原文 123、128 行；任务书原文依据同）。

**防护写法：hook 开头解析 payload，`stop_hook_active` 为 true 时放行。**

该标志为 true 表示**本次停止尝试已处于一次 Stop-hook 阻断所触发的继续回合中**（即 Claude 已经因这个 hook 被强制继续过、现在又一次要停）。此时若再 block 就构成循环，所以必须直接 `sys.exit(0)` 放行。完整实现：

```python
import sys
import json


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # payload 解析失败时放行（fail-open），不因 hook 自身故障卡死会话

    # 防无限循环：stop_hook_active=True 说明本次停止已是一次阻断后的继续回合，放行
    if payload.get("stop_hook_active"):
        sys.exit(0)

    if not all_tests_passed():
        output = {"decision": "block",
                  "reason": "Tests are failing. Please fix failing tests before completing."}
        print(json.dumps(output))
        sys.exit(0)


main()
```

实测三个场景（第五节第 4 项）：

| stdin payload | 实测结果 | 含义 |
|---|---|---|
| `{"stop_hook_active": false}` | exit=0，stdout 输出 block JSON | 首次停止、测试失败 → 正常阻断 |
| `{"stop_hook_active": true}` | exit=0，stdout/stderr 均空 | 已强制继续过一次后再停 → **放行，打破循环** |
| 非 JSON 输入 | exit=0，无输出 | 容错：hook 自身异常时不阻断 |

**权衡说明（如实陈述）**：`stop_hook_active` 防护的语义是「每次停止链最多强制继续一次」——Claude 被拦一次、继续干活后若测试仍未通过，第二次停止会被放行。这是 README 推荐做法的标准代价：宁可在边界上放行，也不冒无限循环的风险。若业务上需要更强硬的多轮拦截，可在 hook 外部状态里对连续 block 次数设上限（如最多 N 次，超限放行并附提示），但 README 原文给出的防护就是检查 `stop_hook_active`（原文 343、568 行）。

---

## 五、实测记录（本机运行，命令与输出原样）

验证脚本为临时文件（已运行并清理），`all_tests_passed()` 一律模拟返回 False（测试失败）；stdin payload 模拟 Claude Code 传入的 Stop 事件 JSON。

| # | 命令 | 实测输出 |
|---|---|---|
| 1 | `echo '{"session_id":"s1","stop_hook_active":false}' \| python version_a.py`（版本 A 原文） | `exit=1`；stdout=`Tests are failing. Please fix failing tests before completing.`；stderr=空 → 消息不进 stderr、退出码非阻断，(a) 得证 |
| 2 | `echo '{"session_id":"s1","stop_hook_active":false}' \| python version_b.py`（版本 B 原文） | `exit=0`；stdout=`{"decision": "block", "reason": "Tests are failing. Please fix failing tests before completing."}`；随后 `json.loads` 校验通过，`decision=='block'` 且 reason 非空 → (b) 得证 |
| 3 | `echo '{"session_id":"s1","stop_hook_active":false}' \| python fix_a.py`（(c) 修复版） | `exit=2`；stdout=空；stderr=`Tests are failing. Please fix failing tests before completing.` → 消息进入「自动反馈给 Claude」的 stderr 通道，(c) 得证 |
| 4a | `echo '{"stop_hook_active":false}' \| python guarded_b.py` | `exit=0`，stdout 输出 block JSON → 首次停止正常阻断 |
| 4b | `echo '{"stop_hook_active":true}' \| python guarded_b.py` | `exit=0`，stdout/stderr 均空 → 防循环放行生效，(d) 得证 |
| 4c | `echo 'not-json' \| python guarded_b.py` | `exit=0`，无输出 → 容错路径不误伤 |

**未能运行的检查（如实声明）**：本环境没有运行中的 Claude Code 主循环，无法端到端复现「Stop hook 阻断后 Claude 继续修复」的真实会话行为。退出码语义与 `decision: block` 的阻断效果以原文条文（原文 300–302、339–343、399–417、449–457 行）及任务书给出的 README 原文依据为准；任务书描述的测试现象（A 失效、B 符合预期）与上述条文及本机实测推断完全一致。

## 六、产物要求声明

本任务按要求先完整读取 `ASSET-DOC.md` 并按其方法执行：所有 README 论据均核对同目录存证原文 `_raw_README.md`（935 行）并标注行号（294–302 退出码表、122–123 与 127–128 payload、339–343 Stop 阻断与循环警告、399–417 Stop 决策与优先级、449–457 官方示例、568 最佳实践）。ASSET-DOC 的方法（忠实引用 README 原文 + 标注验证方式）与任务书无实质冲突；若有个别表述差异，以任务书为准（特此注明）。
