# spec.md — 单位热词表管理器（hotwords）

- 资产路径：`skillfactory/v5/assets/hotwords/`
- 版本：1.0（2026-09-30 固化）
- oracle 参照：`oracle/hotwords.py` + `oracle/run_all.py` + `oracle/fixtures/`（本 spec 全部规则均锚定其**实跑行为**，验证命令见 §7）
- 接口契约（冻结）：见同目录 `contract.md`
- 评测器：`eval/runner.py`（确定性，规则见 §4.3）

---

## 1. 定位与目标

本资产是「单位热词表管理器」：管理一份热词库（词 + 类别 + 备注 + 权重），支持增删查与
FunASR / 纯文本导出，作为**可分发、可复刻的 CLI 工具资产**——任何按本契约重新实现该
工具的产物，都必须产出与 oracle 参照**逐字节一致**的操作序列快照，并通过 `eval/runner.py`
的确定性评测。

目标（逐条可判定，与 runner 四项检查一一对应）：

| # | 目标 | 判定方法 |
|---|---|---|
| G1 | 操作序列每步快照与期望一致（10 步 id/expect/exit_code/快照文件） | runner 检查 `script_sequence_consistent` |
| G2 | 重复 add 报错（exit=2、stderr 中文、stdout 空、库不变；连带 remove 缺失词报错） | runner 检查 `duplicate_add_rejected` |
| G3 | export funasr 行格式正确（「词+空格+权重」，缺省 20；stdout 导出一致；plain 每行一词） | runner 检查 `funasr_export_format` |
| G4 | 与参照产物一致率 100%（逐文件，cmd.txt 归一化后比对） | runner 检查 `consistency_with_reference_100` |

## 2. 术语与产物结构

- **被测实现（package）**：重新实现的 `hotwords.py` + `run_all.py` + 字节一致的 `fixtures/`
  （布局见 contract.md §2）。
- **产物根**：`run_all.py` 产出的 `out/` 目录——含 `manifest.json`、10 个步骤快照目录
  `out/<序号>_<id>/`（序号两位从 01 起）与工作库 `out/_work/store.json`。
- **步骤快照**：`out/<NN>_<id>/` 下恰含 5 个 meta 文件 `cmd.txt / exit_code.txt / stdout.txt /
  stderr.txt / store.json`，export 步骤另含导出产物（`hotwords_funasr.txt` / `hotwords_plain.txt`）。
- **产物根解析**（runner，contract.md §4）：`<root>/manifest.json` 存在 → direct；
  否则单层回退 `<root>/out/manifest.json`（`resolved_via=parent-out` 留痕）；均无 → 全部
  相关检查判红（前置失败）。
- **参照产物根**：`oracle/out/`（由 `cd oracle && python run_all.py` 产出，规范源）。

## 3. 输入 / 输出

**输入**：两个产物根目录；命令行 `python skillfactory/v5/assets/hotwords/eval/runner.py <被测产物根> <参照产物根> [--out <path>]`。

**输出**（runner）：stdout 逐项 `[PASS]/[FAIL] <name>: <detail>` + JSON 报告（`ok / summary /
checks[4]`，形状见 contract.md §4）+ 汇总行；给了 `--out` 则另写报告文件。
**退出码**：0 = 4 项检查全过；1 = 任一失败（失败时仍打印完整 JSON，`ok=false`）；2 = 命令行
用法错误（argparse）。输出**不含时间戳**，同参数重复运行 stdout 逐字节一致。

## 4. 行为规则（逐条可判定）

### 4.1 hotwords.py CLI 行为规则（源自 `oracle/hotwords.py`，括号内为代码行号）

- **R1 全局选项**：`python hotwords.py [--store <json>] <add|list|remove|export> [参数...]`；
  `--store` 须写在子命令之前，默认 `./store.json`（hotwords.py:196-197）。
- **R2 库结构与落盘**：`{"version": 1, "words": [{"word","category","note","weight"}, ...]}`；
  落盘 `indent=2 + ensure_ascii=False + 末尾换行`、UTF-8 无 BOM、`\n` 行尾（hotwords.py:100-107）；
  读取容忍 BOM（hotwords.py:58）；词条保持**插入序**。
- **R3 add**：`add <词> [--category 类别] [--note 备注] [--weight N]`。词 strip 后须非空；
  类别默认「默认」、备注默认空、权重默认 20（hotwords.py:36-37,110-129）；与库内既有词
  **完全同字**即重复 → 退出码 2、**库不变**、stderr 中文报错（hotwords.py:116-118）；
  库不存在自动新建（hotwords.py:111）。
- **R4 list**：类别按**字典序**排序、类别内保持插入序；输出格式
  `[类别]（N 词）` / `  - 词  权重W  备注`（无备注时省略尾段）/ 末行 `共 N 词，M 类`；
  空库输出 `（空库：共 0 词）`（hotwords.py:132-150）。
- **R5 remove**：`remove <词>` 按词删除；不存在 → 退出码 2、库不变（hotwords.py:153-164）。
- **R6 export**：`export --format <funasr|plain> [--out 文件]`，`--format` 必填；funasr 每行
  `词 权重`（**权重缺省 20**），plain 每行一词；省略 `--out` 写标准输出，且 stdout 内容与
  `--out` 产物逐字节一致；`--format` 非法 → 退出码 2 中文报错（hotwords.py:167-188）。
- **R7 退出码与报错语言**：`0` 成功 / `2` 失败（重复、不存在、库缺失或损坏、format 非法、
  参数语法错误——argparse 报英文、业务错误 stderr 中文，前缀 `错误：`）（hotwords.py:221-233）。
- **R8 规整规则**（load 时 normalize，hotwords.py:65-97）：word 非空 str 否则报错；
  category 空/缺 → 「默认」；note 非 str → `""`；weight 非 int（bool 除外）→ 20；
  `version != 1` → 退出码 2；顶层非对象 / words 非数组 / 词条非对象 → 退出码 2。
- **R9 确定性**：无时间戳、无随机数、无网络——同输入连跑两次所有输出逐字节一致。

### 4.2 run_all.py 行为规则（源自 `oracle/run_all.py`，括号内为代码行号）

- **A1 工作库**：清空重建 `out/`；`fixtures/base.json` 复制为 `out/_work/store.json`，跨步延续
  （run_all.py:56-62）。
- **A2 真实子进程**：逐步执行 `fixtures/script.json` 的 steps，argv =
  `[python, hotwords.py, --store <工作库>] + step.args`，子进程 **cwd = 该步快照目录**
  （相对 `--out` 产物直接落入快照）（run_all.py:66-71）。
- **A3 快照文件**：每步写 `cmd.txt`（`subprocess.list2cmdline` 全命令行）、`exit_code.txt`
  （`"%d\n"`）、`stdout.txt`、`stderr.txt`，并把工作库复制为该步 `store.json`（run_all.py:76-80）。
- **A4 manifest**：`out/manifest.json` 含 `script / base_store / steps[{step, desc, expect,
  exit_code, pass, stdout_first_line, stderr_first_line, artifacts}] / all_pass`（run_all.py:85-107）。
- **A5 判定**：`expect=ok` 要求退出码 0，`expect=fail` 要求退出码非 0（业务报错同样是参照
  行为）；任一不符整体退出码 1，否则 0（run_all.py:72-74, 109-112）。

### 4.3 eval/runner.py 行为规则（本 spec 冻结，runner 内同值写死）

- **E1 CLI 与输出**：`python skillfactory/v5/assets/hotwords/eval/runner.py <被测产物根> <参照产物根> [--out <path>]`。
  stdout 打印 JSON：`{tool, asset, candidate, reference, candidate_resolved(_via),
  reference_resolved(_via), self_eval, ok, summary, checks[4]}`；`checks[]` 每项
  `{name, passed, detail[, 审计字段]}`，消费方只应依赖 `name/passed/detail`。退出码 0 = 4 项
  全过 / 1 = 任一失败（`ok=false` 仍打印完整 JSON）/ 2 = 用法错误。产物根解析见 §2。
- **E2 `script_sequence_consistent`**（G1）：manifest.json 可解析且 `all_pass=true`、恰 10 步且
  `step` 名与冻结序列一致；每步目录存在、5 个 meta 文件齐备；`exit_code.txt` 可解析且
  **expect=ok → 0、expect=fail → 2**（契约 R7）；manifest 登记的 `expect/pass/exit_code` 与
  冻结序列、与 exit_code.txt 三方一致；export 步骤导出产物存在且非空。
- **E3 `duplicate_add_rejected`**（G2）：对两个 expect=fail 步骤（03_add_duplicate、
  06_remove_missing）逐项要求：退出码恰为 2；stdout 为空；stderr 非空中文且命中冻结关键词
  （03：「悟空客服」「已存在」；06：「不存在」）；该步 `store.json` 与**上一步** `store.json`
  逐字节一致（失败操作库不变）。
- **E4 `funasr_export_format`**（G3）：从 08 步 `store.json` 推导期望产物（按插入序
  `词 + 空格 + 权重` 每行，与 oracle `cmd_export` 同口径：行间 `\n`、非空时末尾 `\n`）：
  ① `hotwords_funasr.txt` 与期望**逐字节一致**；② 每行匹配冻结正则 `^.+ \d+$` 且行数 =
  词条数；③ 含行 `灵犀大模型 20`（02 步未给 `--weight`，验证缺省权重 20）；④ 09 步
  `hotwords_plain.txt` 与推导的「每行一词」逐字节一致；⑤ 10 步 stdout 与 funasr 产物逐字节
  一致（省略 `--out` 写 stdout）。
- **E5 `consistency_with_reference_100`**（G4）：对被测与参照 `out/` 树做**并集文件清单**
  （递归、不排除任何文件），逐相对路径比对：`*/cmd.txt` 按 **A-7 归一化规则**（附录 A.7）
  比对（剔除 python 解释器/脚本绝对路径与 `--store <工作库路径>`——机器相关，不参与），
  其余文件**逐字节**比对；一致率 = 一致文件数 / 并集文件数，**恰 100% 判过**（缺失、多出、
  不一致均拉低一致率）。不一致/缺失/多出清单写入审计字段。
- **E6 确定性**：无时间戳、无随机、无网络、目录遍历排序；同参数重复运行 stdout 逐字节一致。
  全部检查为纯文件比对与推导，无模型调用，天然确定。
- **E7 短路补位**：被测产物根无法解析时，4 项检查仍**齐全出现**于 `checks`，均置
  `passed=false`、detail 注明「前置失败」；仅参照不可解析时仅第 4 项前置失败，前 3 项照常评测。

## 5. 质量基线（oracle 实测，2026-09-30 本会话测得）

| 指标 | 实测值 |
|---|---|
| `run_all.py` | 10/10 步 OK、`manifest.all_pass=true`、整体退出码 0（03/06 步按预期 exit=2） |
| 产物规模 | `out/` 共 **54 个文件**（10 步快照 + `_work/store.json` + `manifest.json`） |
| 确定性 | 连跑两次 `run_all.py`，`out/` 全树 sha256 逐文件一致（本次会话 diff 为空） |
| 绿侧自评 | runner 4/4 PASS、一致率 1.0（54/54）、exit 0 |
| 手工边界（oracle notes 记录） | add 自动建库 exit 0；list 空库；remove 于缺失库 exit 2；`--format yaml` exit 2 中文；坏 JSON 库 exit 2 |

## 6. 边界与非目标

- **不接 FunASR 运行时**：只产出 FunASR 热词**文件格式**（每行「词 权重」），不调用任何
  ASR 引擎。
- **不做** pytest 单测（沿用 oracle 交付口径）；评测即回归。
- **不做**语义/模糊判分：全部检查为逐字节比对与结构推导，无模型调用。
- **不修改 oracle**：`oracle/` 为参照实现，只读；演进 = 在新 package 根按 contract 重新实现并过 runner。
- **eval 只增不删**：`eval/` 下检查项只允许新增或收紧，不允许删除/放松既有 4 项检查与 100% 阈值。
- 已知局限：第 4 项检查要求**可见行为逐字节复刻**（含全部用户可见文案），这使重实现
  等价于行为级克隆——是本资产的有意设计（可复刻、可验收），文案全文见附录 A.3。

## 7. 验证方式（本会话实跑记录）

以下命令均于 2026-09-30 在本机实际执行（工作区根 = `D:\workspace\zcode研究`）：

1. **基线重跑**：`cd skillfactory/v5/assets/hotwords/oracle && python run_all.py` → 10/10 步
   OK、`EXIT=0`；全树 `find out -type f | xargs sha256sum` 与重跑前存档 **diff 为空**（确定性）。
2. **绿（自评，主案例）**：`python skillfactory/v5/assets/hotwords/eval/runner.py
   skillfactory/v5/assets/hotwords/oracle/out skillfactory/v5/assets/hotwords/oracle/out
   --out .../eval/out/runner-green-self.json` → `[PASS]×4`、`ALL GREEN ✓（4/4）`、**exit 0**、
   `self_eval=true`、54 文件一致率 100%。
3. **绿（异地拷贝，验证 cmd.txt 归一化跨路径成立）**：oracle/out 拷至系统临时目录后
   `runner.py <临时>/out oracle/out --out .../runner-green-copy.json` → 4/4 PASS、**exit 0**。
4. **红（主案例，空目录）**：`runner.py <空目录> oracle/out --out .../runner-red-empty.json`
   → 4 项全部「前置失败」判红、**exit 1**。
5. **定向负例（验证各项检查"有牙"，报告存档 eval/out/）**：
   - 08 步 funasr 产物权重 `灵犀引擎 25→26` → 仅 `funasr_export_format`（与库快照推导不符）
     与 `consistency_with_reference_100`（一致率 98.1%，指出 08_export_funasr/hotwords_funasr.txt）
     判红，exit 1；
   - 03 步 `exit_code.txt` 改 `0` → `script_sequence_consistent`（expect=fail 但 exit=0、与
     manifest 不符）、`duplicate_add_rejected`（退出码 0 != 2）、`consistency_with_reference_100`
     三项精确判红，`funasr_export_format` 保持绿，exit 1。
6. **确定性**：绿侧同参数连续两次运行，stdout 经 `cmp` **逐字节一致**，退出码均 0。

---

## 附录 A（增补条款 A-1：逐字节比对常量全文）

> 凡 eval 逐字节比对的常量，全文列于本附录。除 A.7（归一化规则）外，以下内容任何变更
> 都须先改 spec.md/contract.md 并升版本号。

### A.1 fixtures/base.json（全文，632 字节）

```json
{
  "version": 1,
  "words": [
    {"word": "悟空客服", "category": "产品", "note": "智能客服机器人", "weight": 20},
    {"word": "灵犀引擎", "category": "产品", "note": "自研推理引擎", "weight": 25},
    {"word": "七天无理由退换", "category": "售后", "note": "售后服务承诺", "weight": 20},
    {"word": "闪修服务", "category": "售后", "note": "48小时上门快修", "weight": 20},
    {"word": "618大促", "category": "营销", "note": "年中大促活动名", "weight": 30},
    {"word": "会员积分翻倍", "category": "营销", "note": "大促期间权益", "weight": 20}
  ]
}
```

### A.2 fixtures/script.json（全文，1728 字节）

```json
{
  "description": "单位热词表管理器演示操作序列：由 run_all.py 逐步以真实 CLI 子进程执行，--store 由 run_all 注入（指向从 base.json 复制的工作库，跨步延续）",
  "steps": [
    {"id": "list_initial", "args": ["list"], "expect": "ok", "desc": "初始演示库按类别分组列出"},
    {"id": "add_ok", "args": ["add", "灵犀大模型", "--category", "产品", "--note", "公司旗舰大模型"], "expect": "ok", "desc": "追加新词条"},
    {"id": "add_duplicate", "args": ["add", "悟空客服", "--category", "产品", "--note", "与既有词重复应报错"], "expect": "fail", "desc": "重复词条报错（退出码 2，库不变）"},
    {"id": "add_with_weight", "args": ["add", "通义听悟", "--category", "产品", "--note", "转写工具", "--weight", "30"], "expect": "ok", "desc": "带自定义权重追加"},
    {"id": "remove_ok", "args": ["remove", "闪修服务"], "expect": "ok", "desc": "按词删除既有词条"},
    {"id": "remove_missing", "args": ["remove", "不存在的词"], "expect": "fail", "desc": "删除不存在的词报错（退出码 2）"},
    {"id": "list_final", "args": ["list"], "expect": "ok", "desc": "增删后的库按类别分组列出"},
    {"id": "export_funasr", "args": ["export", "--format", "funasr", "--out", "hotwords_funasr.txt"], "expect": "ok", "desc": "导出 FunASR 热词文件（词 权重）"},
    {"id": "export_plain", "args": ["export", "--format", "plain", "--out", "hotwords_plain.txt"], "expect": "ok", "desc": "导出纯文本热词文件（每行一词）"},
    {"id": "export_stdout", "args": ["export", "--format", "funasr"], "expect": "ok", "desc": "省略 --out 时导出到标准输出"}
  ]
}
```

### A.3 十步快照 stdout/stderr 全文（逐字节；`\n` 行尾；expect=fail 步 stdout 为 0 字节，expect=ok 步 stderr 为 0 字节）

| 步骤 | stdout / stderr（全文） |
|---|---|
| 01_list_initial（stdout） | `[产品]（2 词）⏎␣␣- 悟空客服␣␣权重20␣␣智能客服机器人⏎␣␣- 灵犀引擎␣␣权重25␣␣自研推理引擎⏎[售后]（2 词）⏎␣␣- 七天无理由退换␣␣权重20␣␣售后服务承诺⏎␣␣- 闪修服务␣␣权重20␣␣48小时上门快修⏎[营销]（2 词）⏎␣␣- 618大促␣␣权重30␣␣年中大促活动名⏎␣␣- 会员积分翻倍␣␣权重20␣␣大促期间权益⏎共 6 词，3 类⏎` |
| 02_add_ok（stdout） | `已添加：灵犀大模型（类别：产品，权重：20） 备注：公司旗舰大模型⏎` |
| 03_add_duplicate（stderr） | `错误：热词「悟空客服」已存在（类别：产品），不可重复添加⏎` |
| 04_add_with_weight（stdout） | `已添加：通义听悟（类别：产品，权重：30） 备注：转写工具⏎` |
| 05_remove_ok（stdout） | `已删除：闪修服务（类别：售后）⏎` |
| 06_remove_missing（stderr） | `错误：热词「不存在的词」不存在，无法删除⏎` |
| 07_list_final（stdout） | `[产品]（4 词）⏎␣␣- 悟空客服␣␣权重20␣␣智能客服机器人⏎␣␣- 灵犀引擎␣␣权重25␣␣自研推理引擎⏎␣␣- 灵犀大模型␣␣权重20␣␣公司旗舰大模型⏎␣␣- 通义听悟␣␣权重30␣␣转写工具⏎[售后]（1 词）⏎␣␣- 七天无理由退换␣␣权重20␣␣售后服务承诺⏎[营销]（2 词）⏎␣␣- 618大促␣␣权重30␣␣年中大促活动名⏎␣␣- 会员积分翻倍␣␣权重20␣␣大促期间权益⏎共 7 词，3 类⏎` |
| 08_export_funasr（stdout） | `已导出 7 条热词 → hotwords_funasr.txt（格式 funasr）⏎` |
| 09_export_plain（stdout） | `已导出 7 条热词 → hotwords_plain.txt（格式 plain）⏎` |
| 10_export_stdout（stdout） | 与 08 步产物 `hotwords_funasr.txt` 全文逐字节一致（见 A.4） |

文案模板（hotwords.py 冻结，`⏎`=换行，`␣`=空格）：add 成功 `已添加：{词}（类别：{类别}，权重：{权重}）`＋有备注时尾缀 ` 备注：{备注}`；remove 成功 `已删除：{词}（类别：{类别}）`；export 成功 `已导出 {N} 条热词 → {路径}（格式 {格式}）`；list 组头 `[{类别}]（{N} 词）`、条目 `  - {词}  权重{W}`＋有备注时尾缀 `  {备注}`、汇总 `共 {N} 词，{M} 类`、空库 `（空库：共 0 词）`；业务错误前缀 `错误：`。

### A.4 导出产物全文（`\n` 行尾、非空时末尾含换行）

`hotwords_funasr.txt`（127 字节；每行「词 空格 权重」，顺序 = 库插入序）：

```
悟空客服 20
灵犀引擎 25
七天无理由退换 20
618大促 30
会员积分翻倍 20
灵犀大模型 20
通义听悟 30
```

`hotwords_plain.txt`（106 字节；每行一词）：

```
悟空客服
灵犀引擎
七天无理由退换
618大促
会员积分翻倍
灵犀大模型
通义听悟
```

### A.5 热词库 JSON 布局与快照推导

- 布局（冻结）：`{"version": 1, "words": [...]}`，落盘 `indent=2`、`ensure_ascii=False`、
  UTF-8 无 BOM、`\n` 行尾、**末尾一个换行**；词条键序 `word, category, note, weight`；
  保持插入序。
- 各步 `store.json` 快照 = base.json（A.1）经 A.2 序列在上述布局下的确定性推导，
  eval 不内嵌其字节、而由参照产物运行期提供；终态（07 步起，936 字节）全文如下：

```json
{
  "version": 1,
  "words": [
    {
      "word": "悟空客服",
      "category": "产品",
      "note": "智能客服机器人",
      "weight": 20
    },
    {
      "word": "灵犀引擎",
      "category": "产品",
      "note": "自研推理引擎",
      "weight": 25
    },
    {
      "word": "七天无理由退换",
      "category": "售后",
      "note": "售后服务承诺",
      "weight": 20
    },
    {
      "word": "618大促",
      "category": "营销",
      "note": "年中大促活动名",
      "weight": 30
    },
    {
      "word": "会员积分翻倍",
      "category": "营销",
      "note": "大促期间权益",
      "weight": 20
    },
    {
      "word": "灵犀大模型",
      "category": "产品",
      "note": "公司旗舰大模型",
      "weight": 20
    },
    {
      "word": "通义听悟",
      "category": "产品",
      "note": "转写工具",
      "weight": 30
    }
  ]
}
```

### A.6 runner 内嵌冻结常量

| 常量 | 值 |
|---|---|
| 步骤序列（id, expect） | list_initial/ok, add_ok/ok, add_duplicate/fail, add_with_weight/ok, remove_ok/ok, remove_missing/fail, list_final/ok, export_funasr/ok, export_plain/ok, export_stdout/ok（快照目录名 `%02d_%s`，序号从 01 起） |
| meta 文件 | `cmd.txt, exit_code.txt, stdout.txt, stderr.txt, store.json` |
| 导出产物名 | export_funasr → `hotwords_funasr.txt`；export_plain → `hotwords_plain.txt` |
| fail 步 stderr 关键词 | 03：`悟空客服`、`已存在`；06：`不存在` |
| funasr 行正则 | `^.+ \d+$` |
| 缺省权重锚 | 行 `灵犀大模型 20`（词 `灵犀大模型`，DEFAULT_WEIGHT=20） |
| 库版本 / 失败退出码 | STORE_VERSION=1；expect=fail 步 exit_code 恰为 2 |
| exit_code.txt 格式 | `"%d\n"` |

### A.7 cmd.txt 归一化规则（第 4 项检查专用）

`cmd.txt` 中的 python 解释器绝对路径、hotwords.py 脚本绝对路径、`--store` 选项及其后的
**工作库绝对路径**随机器/检出位置而变，不参与比对。归一化 = 用正则
`--store\s+(?:"[^"]*"|\S+)` 定位 `--store` 及其路径参数，取**其后的剩余字符串并 strip**，
仅比对该参数尾串（即子命令与参数序列本身，如 `list`、`add 灵犀大模型 --category 产品 ...`）。
正则不命中时整行参与比对（视为不一致处理）。

### A.8 manifest.json 结构（第 1 项检查读取的键）

顶层：`script`（="fixtures/script.json"）、`base_store`（="fixtures/base.json"）、
`steps`（数组，10 项）、`all_pass`（bool）。steps 项键：`step`（=`<NN>_<id>`）、`desc`、
`expect`、`exit_code`、`pass`、`stdout_first_line`、`stderr_first_line`、`artifacts`
（导出产物文件名数组，排序；无产物为空数组）。文件以 `indent=2 + ensure_ascii=False +
末尾换行`、UTF-8 无 BOM 落盘。
