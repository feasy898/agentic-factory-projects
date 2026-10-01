# CHANGELOG — meeting-minutes 资产

所有对冻结物（contract / golden.json / runner.py）的变更逐条记录于此。格式参照 contract.md §4 冻结规则。

## 2026-09-29 — specfix-meeting-minutes（重生成连续 2 轮失败后的资产修订）

**失败定性（证据）**：两轮重生成的确定性评测均为 15 项检查全红，detail 逐字为
「被测用例目录不存在: …package/out\caseN」——被测产物目录从未产出。根因是**交付流程矛盾**：
重生成实现者的任务指令写明样例输入在 `<资产根>/inputs/`（该目录当时不存在），同时禁止读取
`oracle/`（黄金转写稿当时唯一在 `oracle/inputs/`）。实现方无法在不违反禁令的情况下取得黄金
输入，`package/out/<case>` 自然无法产出。行为规则本身可满足（见下"验证"）。

### 变更清单

| 文件 | 变更 | 性质 |
|---|---|---|
| `eval/golden.json` | **只增**：`eval_inputs` 追加 `case4`（全噪声转写稿，决议/待办/风险全 0 边界，固化 spec §8 与 R3.6 全零口径）；case1–3 与 `ab_tasks` 逐字未动 | 增补（收紧覆盖面，无断言放宽） |
| `oracle/inputs/case4.txt` | 新建规范源输入（11 关键词零命中自检通过） | 黄金输入增补 |
| `oracle/out/case4/` | 运行 oracle 补跑参照产物（contract §1 授权"参照产物若缺则补跑"） | 参照产物增补 |
| `inputs/`（新建） | `case1..4.txt` 资产根副本，与 `oracle/inputs/` 字节一致（`cmp` 验证）；化解实现者"样例输入位置"矛盾 | 布局增补（contract 升 1.1） |
| `spec.md` | 追加 §9「交付物与验收流程（DoD）」；§8 边界指向 case4；R5.3 澄清后缀集「之前/前/以前/底」与「本周/下周/这周」前缀不进提取结果；验证记录移 §10 并追加本轮实证 | 澄清歧义 |
| `contract.md` | 升版本 1.1：布局图加 `inputs/`；新增输入样例注记（实现者用 `inputs/`，规范源仍 `oracle/inputs/`，参照目录恒为 `oracle/out`） | 契约注记（按其自身变更协议） |
| `eval/archive/`（新建） | 归档 `golden-v1.0-20260929.json`（3 例，修订前）与 `golden-v1.1-20260929.json`（4 例，现行） | 冻结规则要求 |

### 未变更（红线核对）

- `eval/runner.py`：零改动（mtime 2026-09-29 01:55 未动），既有检查项、容差、判红逻辑全部保留。
- `golden.json` case1–3 条目与全部 `ab_tasks`：逐字未动（未为通过评测放宽任何断言）。
- `oracle/oracle.py` 与既有参照产物 case1–3：零改动。

### 修订后验证（本会话实际运行）

| 验证 | 命令 | 结果 |
|---|---|---|
| spec 可满足性（独立实现） | 仅依据 spec.md 在临时目录写独立实现（未读 oracle.py），对 `inputs/case1..4.txt` 各跑一次，`python eval/runner.py <临时out> oracle/out` | **exit 0，20/20 检查通过** |
| oracle 自校验 | `python eval/runner.py oracle/out oracle/out` | exit 0，20/20 |
| 失败模式同型复现 | 对崩溃中的中间态实现（存在并发施工）评测 | 与上报失败逐字同型（被测目录不存在→全红），证实原失败在交付流程 |
| 字节一致性 | `cmp oracle/inputs/caseN.txt inputs/caseN.txt`（N=1..4） | 4/4 一致 |
