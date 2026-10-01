# T5 评审：Stop hook 能否强制 Claude 继续修测试（版本 A vs 版本 B）

## 0. 评审依据与范围声明

- 被评审代码：任务描述中给出的版本 A / 版本 B 两段 `stop_check.py` 核心实现（原文引自任务描述）。
- README 依据：任务描述给出的 5 条 README 摘录（退出码语义、Stop 可阻断、`decision: "block"` 须带 reason、控制优先级、`stop_hook_active` 防护）。
- **范围声明**：按公平性要求，本次评审未读取 `skillfactory/` 目录下任何文件；文中所有 README 引用均以**任务描述中的摘录原文**为准，未对照 skillfactory 内 README 全文核实。
- **验证声明**：见文末附录——对 (c)(d) 的代码片段做了真实运行的控制流/语法验证（桩替换 `all_tests_passed`，Python 3.12.10）；**未**在真实 Claude Code Stop hook 环境中做端到端验证（本评审环境无法启动该环境），(a)(b) 的结论基于任务描述给出的 README 语义与测试现象推断。

---

## (a) 版本 A 为什么不能阻止 Claude 停止

版本 A 的关键两行：

```python
print("Tests are failing. Please fix failing tests before completing.")   # stdout
sys.exit(1)                                                               # 退出码 1
```

对照 README 退出码语义：**0=成功（stdout 在 transcript 模式展示给用户）；2=阻断错误（stderr 自动反馈给 Claude）；其他=非阻断错误（stderr 展示给用户，执行继续）**。

版本 A 三处都不占：

1. **退出码走错档**：`sys.exit(1)` 落在"其他"档 = 非阻断错误。README 明确这一档"执行继续"——对 Stop hook 来说就是放行本次停止。能阻断停止的退出码只有 2。
2. **消息走错流**：消息 `print` 到 **stdout**，而"反馈给 Claude"的唯一文件描述符是退出码 2 档的 **stderr**。stdout 只在退出码 0 成功时才以 transcript 模式给用户看；退出码 1 时它连用户都不一定看到，更不会进入 Claude 的上下文。
3. **结论与现象吻合**：Claude 从未收到任何阻断信号与报错内容，于是照常结束回合；终端上用户看到的报错只是 hook 非阻断错误的外围展示。这正是测试现象"测试失败后 Claude 仍然正常结束回答，stderr 的报错只在终端展示给用户，Claude 没有继续修复"的成因。

一句话总结：**阻断"停止"只有两条通道——退出码 2（stderr 自动反馈给 Claude）或结构化 JSON `"decision": "block"`。版本 A 两条都没走，所以完全无法阻止停止。**

---

## (b) 版本 B 起作用的机制，以及 reason 为什么必须提供

### 机制

版本 B 以**退出码 0（成功）**结束，但在 stdout 输出结构化 JSON：

```json
{"decision": "block", "reason": "Tests are failing. Please fix failing tests before completing."}
```

harness 解析到 `"decision": "block"` 后，按 README 的控制优先级——**`"continue": false` > `"decision": "block"` > 退出码 2 > 其他退出码**——这一结构化决策优先于任何退出码通道生效：本次"停止"被否决，Claude 被强制进入下一轮继续工作。也就是说，版本 B 用的是"成功退出 + stdout 携带决策"这条结构化通道，而不是版本 A 试图用的退出码通道；这也解释了为什么两版只差几行，行为却完全不同。

### reason 为什么必须提供

两个层面：

1. **协议要求**：README 明确规定 Stop 的 `"decision": "block"` 必须提供 reason。
2. **功能要求**：reason 是阻断后反馈给 Claude 的**继续指令**——它告诉 Claude"为什么不许停、接下来怎么做"（这里就是：测试失败，先修复失败的测试再结束）。被阻断的 Claude 需要靠这个字段知道下一步目标；缺了 reason，Claude 只知道"被拦了"，不知道该干什么，阻断失去意义，还更容易引发无方向的空转重试。这正是 README 把 reason 定为该决策必填项的原因。

---

## (c) 版本 A 的最小修改修复

最小改法 = 把退出码 1 改成 **2**，并把消息从 stdout 改到 **stderr**（共改两处）：

```python
import sys

if not all_tests_passed():
    print("Tests are failing. Please fix failing tests before completing.", file=sys.stderr)
    sys.exit(2)
```

原理：退出码 2 是"阻断错误"，其 **stderr 会被自动反馈给 Claude**，从而拦下本次停止，且 Claude 能直接读到修复指令。这是利用退出码 2 通道的最小改动（对版本 A 原文只动两个参数/值）。

等价替代改法（同样是可行解，改动量略大）：直接换成版本 B 的结构化输出——`print(json.dumps({"decision": "block", "reason": "..."})); sys.exit(0)`。两者任选其一即可；注意**无论采用哪种，都必须叠加 (d) 的死循环防护**。

---

## (d) 死循环风险的成因与正确防护

### 成因

Stop hook 在 Claude **每次尝试停止时都会触发**。版本 B 拦下一次停止 → Claude 继续干活 → 再次尝试停止 → hook 再次触发。只要"测试未全部通过"这个条件持续成立，这个循环就没有天然的出口。而条件持续成立非常容易发生：

- 修复真的没成功，测试持续失败；
- hook 自身有 bug 或环境问题导致测试**永远被判为不通过**（测试命令路径写错、依赖缺失、超时、`all_tests_passed()` 实现有误等）——此时哪怕 Claude 干得再好也永远被拦。

结果就是"停止 → 阻断 → 继续 → 停止 → …"的无限循环，不停烧 token 且停不下来。README 也因此专门提醒：Stop hook 可以阻断"停止"强制 Claude 继续，但**小心无限循环**。

### 正确防护：检查 `stop_hook_active`

README 指定：**Stop/SubagentStop 务必检查 payload 中的 `stop_hook_active` 布尔标志**以防无限循环。该标志在"本次停止正是被 Stop hook 上次阻断后的延续"时为 `true`。防护规则：

- `stop_hook_active == true` → **放行**（退出码 0、不输出 block），把是否继续的决定权交还模型/用户；
- `stop_hook_active == false`（或字段缺失）→ 正常执行测试检查，失败则 block。

### 推荐完整写法（版本 B + 防护）

```python
import json
import sys


def all_tests_passed():
    # 真实实现：运行测试套件并返回布尔结果（此处省略）
    ...


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    # 防死循环：本次停止是被本 hook 上次阻断后的延续时，放行
    if data.get("stop_hook_active"):
        sys.exit(0)

    if not all_tests_passed():
        print(json.dumps({
            "decision": "block",
            "reason": "Tests are failing. Please fix failing tests before completing.",
        }))
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
```

三个要点：

1. `stop_hook_active` 的判断必须放在**阻断判断之前**，为 true 时一律放行退出 0——这是 README 指定的防护位；
2. payload 缺失/解析失败时按"非延续"处理走正常检查，避免解析故障导致防护被意外绕过；
3. reason 写成可执行的继续指令（"先修复失败的测试再结束"），让被阻断后的下一轮有明确目标，减少空转。

已知代价（同事的担心在防护之后仍然部分成立）：加了防护后，被阻断延续的那一轮若测试仍未通过，hook 会放行停止——即防护是用"放弃第 N+1 次强制"换"不死循环"，这是 README 认可的取舍；若业务上需要多轮重试，应在 hook 内自行计数/加超时，而不是去掉 `stop_hook_active` 检查。

---

## 结论速览

| 版本 | 行为 | 根因 |
|---|---|---|
| A（`print` + `exit 1`） | **无效**，Claude 照常停止 | 退出码 1 属"其他"非阻断档；消息在 stdout，永不进 Claude 上下文 |
| B（JSON block + `exit 0`） | **有效**，Claude 被强制继续 | 走 `"decision": "block"` 结构化通道，优先级高于退出码 2；reason 是协议必填的继续指令 |
| A 的最小修复 | `print(..., file=sys.stderr)` + `sys.exit(2)` | 走退出码 2 通道，stderr 自动反馈给 Claude |
| 死循环防护 | 先读 stdin JSON，`stop_hook_active` 为 true 即放行退出 0 | README 指定的 Stop/SubagentStop 防护位 |

---

## 附录：本次评审实际运行的验证

**验证 1 —— (d) 推荐写法的控制流（桩替换 `all_tests_passed`，4 用例）**

命令（在临时目录 `.tmp_t5_check/` 下，含 `tests_gate.py` 桩、`hook_snippet.py`、`driver.py`，验证后已删除）：

```
cd "/d/workspace/zcode研究/.tmp_t5_check" && python driver.py
```

输出：

```
CASE: stop_hook_active=true（延续性停止，测试失败）
  expect : 放行：exit 0 且无 block 输出
  exit   : 0
  stdout : ''

CASE: stop_hook_active=false（全新停止，测试失败）
  expect : 阻断：exit 0 且输出 decision=block + reason
  exit   : 0
  stdout : '{"decision": "block", "reason": "Tests are failing. Please fix failing tests before completing."}'
  parsed : decision='block' reason='Tests are failing. Please fix failing tests before completing.'

CASE: payload 无该字段（测试失败）
  expect : 阻断：字段缺失视为非延续，输出 block
  exit   : 0
  stdout : '{"decision": "block", "reason": "Tests are failing. Please fix failing tests before completing."}'
  parsed : decision='block' reason='Tests are failing. Please fix failing tests before completing.'

CASE: stop_hook_active=false（测试通过）
  expect : 放行：exit 0 且无 block 输出
  exit   : 0
  stdout : ''
```

4/4 用例符合预期：防护位放行延续性停止、阻断全新停止、block JSON 含必填 reason、测试通过时放行。

**验证 2 —— (c) 最小修复片段语法可编译性**

命令：

```
python - <<'EOF'  （compile 版本A修复片段，见下方脚本内容）
snippet = '''import sys
if not all_tests_passed():
    print("Tests are failing. Please fix failing tests before completing.", file=sys.stderr)
    sys.exit(2)
'''
compile(snippet, "fix_a.py", "exec")
print("fix-A snippet: syntax OK")
EOF
```

输出：

```
fix-A snippet: syntax OK
```

**未做/不能做的验证**：未在真实 Claude Code Stop hook 环境中端到端复现 (a) 的失败现象与 (b) 的阻断行为（本评审环境无法启动该运行时）；(a)(b) 的结论依据是任务描述给出的 README 语义摘录与任务描述记录的测试现象，两者相互吻合。`all_tests_passed()` 的真实测试套件实现不在本次评审范围内。
