# Stop Hook 评审：版本 A 为何拦不住、版本 B 的机制与防死循环写法

- **评审对象**：`.claude/hooks/stop_check.py` 两版核心实现（即本任务给到的版本 A / 版本 B 代码原文）。
- **评审依据**：任务给到的 README 原文依据五条——①退出码语义（0=成功，stdout 仅 transcript 模式给用户；2=阻断错误，stderr 自动反馈给 Claude；其他=非阻断错误，stderr 展示给用户、执行继续）；②Stop hook 可阻断「停止」强制 Claude 继续，但小心无限循环；③Stop 的结构化输出 `"decision": "block"` 必须提供 reason（告诉 Claude 如何继续）；④控制优先级 `"continue": false` > `"decision": "block"` > 退出码 2 > 其他退出码；⑤Stop/SubagentStop 务必检查 payload 中的 `stop_hook_active` 布尔标志防无限循环。另附本机对等价脚本的实际运行验证（见附录）。

## 结论速览

| 问题 | 结论 |
|---|---|
| (a) A 为何无效 | `sys.exit(1)` 落在「其他退出码=非阻断」档：既不是退出码 2，也没有 `"decision": "block"`，两条阻断通道都没用上；按 README 语义「执行继续」＝放行 Claude 停止，报错只到用户终端，Claude 一无所知。 |
| (b) B 为何有效 | 退出 0 + stdout JSON `{"decision":"block","reason":...}`：结构化输出走第二优先级通道，Stop 语义为「拒绝停止、强制继续」；reason 是唯一被注入回 Claude 的指令文本，README 规定必填。 |
| (c) A 的最小修复 | 消息改打 stderr 并 `sys.exit(2)`（退出码 2 = 阻断，stderr 自动反馈给 Claude）。 |
| (d) 死循环与防护 | block → 继续 → 再停 → 再 block 无限循环；必须读 stdin 输入 JSON，`stop_hook_active` 为 true 时直接放行 `sys.exit(0)`。 |

---

## (a) 版本 A 为什么不能阻止 Claude 停止

版本 A（任务原文）：

```python
if not all_tests_passed():
    print("Tests are failing. Please fix failing tests before completing.")
    sys.exit(1)
```

按 README 的退出码语义，Stop hook 只有两条通道能「阻断停止」：

1. 结构化输出 `"decision": "block"`（优先级第二）；
2. 退出码 2（优先级第三）。

`sys.exit(1)` 属于「其他退出码 = 非阻断错误」档：README 明确该档的行为是「stderr 展示给用户，**执行继续**」——对 Stop hook 而言「执行继续」就意味着放行 Claude 停止。在 README 给出的控制优先级链（`"continue": false` > `"decision": "block"` > 退出码 2 > 其他退出码）里，1 排在最末档，没有任何阻断效力。

消息通道也选错了：

- `print(...)` 写的是 **stdout**。README 中 stdout 只在「退出 0 = 成功」的场景下于 transcript 模式展示给用户；退出 1 时这条消息对 Claude 完全不可见；
- **stderr 什么都没写**，Claude 侧收到的反馈为空。

所以测试现象与语义完全吻合：终端（用户侧）出现 hook 报错，Claude 侧什么也没收到，照常结束回答。一句话诊断：**A 的判断条件是对的，但用了一个「只通知人、不影响控制流」的退出码——报告发给了没有权限拦人的一方，Claude 从头到尾不知道测试挂了。**

## (b) 版本 B 起作用的机制，以及 reason 为什么必须提供

版本 B（任务原文）：

```python
if not all_tests_passed():
    output = {"decision": "block", "reason": "Tests are failing. Please fix failing tests before completing."}
    print(json.dumps(output))
    sys.exit(0)
```

机制分两步：

1. `sys.exit(0)` 声明 hook 本身执行成功，Claude Code 随即把 stdout 上的 JSON 解析为**结构化控制输出**；
2. `"decision": "block"` 在 README 的控制优先级里仅次于 `"continue": false`、高于退出码 2。对 Stop hook，它的语义就是「拒绝本次停止，强制 Claude 继续工作」——恰好是需求要的行为。这也解释了测试现象：B 一上，Claude 就被按回去继续修。

reason 为什么必须提供：

- `block` 只表达了「不许停」，是一条否定性指令；Claude 被按回去之后要干活，需要知道**为什么被拦、下一步做什么**。reason 是整个交互里唯一会被注入回 Claude 的文本通道——README 明文规定：Stop 的 `"decision": "block"` 必须提供 reason（告诉 Claude 如何继续）；
- 落到效果上：Claude 下一轮上下文里能看到的就是 reason 这句话。B 的 reason「Tests are failing. Please fix failing tests before completing.」本身就是可执行指令，所以行为符合预期；若缺失，Claude 被拦下却拿不到任何指引，阻断等于白拦。

顺带说明：退出码 2（见 (c)）同样能阻断，差别只在通道与文本形态；两者同时出现时按优先级 `"decision": "block"` > 退出码 2 取前者。

## (c) 版本 A 的最小修改

改动两点：输出通道 stdout → stderr，退出码 1 → 2：

```python
if not all_tests_passed():
    print("Tests are failing. Please fix failing tests before completing.", file=sys.stderr)
    sys.exit(2)
```

依据 README：退出码 2 = 阻断错误，**stderr 自动反馈给 Claude**，Stop hook 场景下即「阻止停止、让 Claude 继续」。这是行数最少的可行改法。（任务只要求一种改法，另一条等价路线是直接采用版本 B 的 JSON 结构化输出。）

选型建议：若后续要叠加 (d) 的防死循环，建议直接用 B 的骨架改——因为防死循环需要从 stdin 读输入 payload，JSON 路线更顺（见下）。

## (d) 死循环风险的成因与正确的防护写法

**成因**：Stop hook 阻断成功后，Claude 继续工作一轮，然后再次尝试结束回答 → Stop hook **再次运行** → 若测试仍未通过（修复无效、环境问题、或 `all_tests_passed()` 本身永远返回 False），就再次 block → 「停—拦—干—停」无限循环，token 持续燃烧。README 对此有明确警告：Stop hook 可阻断停止，但小心无限循环。同事的担心是对的——版本 B 原样上线就带着这个风险。

**正确防护**：Stop/SubagentStop 的输入 payload（hook 启动时从 **stdin** 读入的 JSON）里有布尔字段 `stop_hook_active`——当本次「停止」本身就是上一次 stop hook 强制继续之后的结果时，它为 true。README 的要求是「务必检查该标志」。写法：为 true 时直接放行（exit 0，不再输出 block）。

完整正确版（B 骨架 + 防护）：

```python
import json
import sys

def all_tests_passed():
    ...  # 同事已有实现

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    # 防死循环：本次停止已是“被本 hook 强制继续之后”的延续，放行
    if isinstance(data, dict) and data.get("stop_hook_active"):
        sys.exit(0)

    if not all_tests_passed():
        print(json.dumps({
            "decision": "block",
            "reason": "Tests are failing. Please fix failing tests before completing.",
        }, ensure_ascii=False))
    sys.exit(0)

main()
```

要点：

- 版本 A / B 原文都**没读 stdin**；`stop_hook_active` 在输入 payload 里，不读 stdin 就永远用不上这个防护——这是两版共同的遗漏；
- 该防护的语义是「强制继续至多一轮」。若业务上想要有限多次重试，可在 hook 外部（状态文件/环境变量）自维护计数后再放行，但 README 指定的标准防护就是检查 `stop_hook_active`；
- (c) 的退出码 2 路线同样可加防护：从 stdin 读 payload，`stop_hook_active` 为 true 时 `sys.exit(0)`。

---

## 附录：本机实际运行验证

> 说明：以下验证的是脚本本身的行为（退出码、输出流向、防护分支）；「退出码 2 / `"decision": "block"` 能阻断 Stop」这层语义来自任务给到的 README，未在本环境真实挂载 Claude Code 复现，特此声明。验证在系统临时目录进行，未读取 skillfactory/ 下任何文件。

**命令**：`python "C:\Users\Administrator\AppData\Local\Temp\t5_hook_test\runner.py"`（Python 3.12.10；runner 依次以不同 stdin 运行 4 个场景，capture stdout/stderr/exit code）。

**输出**：

```text
[a.py] stdin=
  exit=1
  stdout='Tests are failing. Please fix failing tests before completing.'
  stderr=''
[fix2.py] stdin=
  exit=2
  stdout=''
  stderr='Tests are failing. Please fix failing tests before completing.'
[fixed_guard.py] stdin={"stop_hook_active": false}
  exit=0
  stdout='{"decision": "block", "reason": "Tests are failing. Please fix failing tests before completing."}'
  stderr=''
[fixed_guard.py] stdin={"stop_hook_active": true}
  exit=0
  stdout=''
  stderr=''
```

**对应结论**：

| 场景 | 实测 | 印证 |
|---|---|---|
| 版本 A 等价脚本 | 退出 1，消息在 stdout，stderr 为空 | 1 = 非阻断档；消息走的还是一条该档下对 Claude 不可见的通道 → 拦不住 |
| (c) 最小修复版 | 退出 2，消息在 stderr | 2 = 阻断档，stderr 自动反馈给 Claude → 能拦 |
| 防护版，`stop_hook_active: false` | 退出 0，stdout 输出 block JSON | 正常拦截路径（= 版本 B 行为） |
| 防护版，`stop_hook_active: true` | 退出 0，无任何输出 | 防护生效：被强制继续后的第二次停止直接放行 → 无死循环 |
