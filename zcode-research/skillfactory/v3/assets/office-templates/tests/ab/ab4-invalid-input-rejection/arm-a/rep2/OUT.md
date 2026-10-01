# AB-4 非法输入拒绝 · A/B 对照报告 — arm A（被测实现）· rep2

| 项 | 值 |
|---|---|
| 测试 | ab4-invalid-input-rejection（CLI 契约 §2：非法输入拒绝） |
| 臂 / 复测 | arm-a / rep2 |
| 被测实现（A） | `package/scripts/gen_doc.py`（office-templates skill 包内脚本） |
| 参照实现（B） | `oracle/oracle.py` |
| ROOT（两 CLI 的 cwd） | `D:\workspace\zcode研究\skillfactory\v3\assets\office-templates` |
| 日期 / 环境 | 2026-09-30 · windev-01 · Python 3.12.10（locale/FS 编码均 utf-8）· Git Bash |
| 调用方式来源 | skillfactory 之外的历史脚本 `_ab3_arma_rep2_scratch/step1_run.py`（第 22–24 行）：`python <script> --template <名> --data <json> --outdir <目录>`，`cwd=ROOT`，捕获 stdout/stderr |
| 运行轮次 | 每用例×每实现各跑 2 轮（pass1 / pass2），结果完全一致（确定性成立） |
| scratch（本测工作区，skillfactory 之外） | `D:\workspace\zcode研究\_ab4_arma_rep2_scratch\`（runner=`run_ab4.py`，原始记录=`ab4_runs.json`，fixtures=`fixtures\`，产物=`out\`） |

---

## 一、总判定

**被测 `gen_doc.py` 与参照 `oracle.py` 在全部四组非法输入及合法对照上的 CLI 行为一致（4/4 组通过 + 对照通过）。**

一致点：
1. **退出码逐一相同**：四组非法输入双方均 `exit=2`；合法对照双方均 `exit=0`。
2. **错误只走 stderr**：16 次拒绝运行（4 组 × 2 臂 × 2 轮）的 stdout 全部为空字符串（程序化核验，见 §四）。
3. **拒绝即零产物**：所有拒绝运行均**不创建** `--outdir` 目录（更无任何文件残留），`outdir_created=False` 且目录不存在。
4. **拒绝语义逐组对应**：T1 同为 argparse `invalid choice` 并列出同一组合法模板；T2 同为「数据文件不存在」并回显同一绝对路径；T3 同为 JSON 解析失败且给出同一解析器定位 `Expecting value: line 1 column 1 (char 0)`；T4 同为「顶层必须是 JSON 对象」校验。
5. **合法对照双双成功**：均产出 `文书.docx` + `fields.json`，且字段填充一致（filled=7/7，必填缺失=0）。

差异（均为**非语义**的措辞/格式差异，不构成契约分歧，详见 §五）：错误消息前缀不同（`错误：` vs `[oracle] `）；package 在 T3 中额外回显数据文件路径、在 T4 中额外标注实际类型 `list`；usage 文本中程序名不同（`gen_doc.py` vs `oracle.py`）。

---

## 二、方法

- 命令模板（A/B 完全同参，仅脚本路径不同）：
  ```
  python <ROOT>\package\scripts\gen_doc.py --template <T> --data <F> --outdir <OUT>   # 被测（arm A）
  python <ROOT>\oracle\oracle.py           --template <T> --data <F> --outdir <OUT>   # 参照
  ```
  `cwd=ROOT`；`subprocess.run(capture_output=True, timeout=180s)`；产物目录按 `pass{1,2}/<impl>/<case>` 独立新建。
- 用例与输入（5 组 × 2 实现 × 2 轮 = 20 次运行）：

| 组 | --template | --data | 非法点 |
|---|---|---|---|
| T1 | `证书` | `oracle\inputs\周报\case1.json`（合法数据） | 模板名不在合法集 {周报, 请示函, 会议通知, 工作总结} |
| T2 | `周报` | `_ab4_arma_rep2_scratch\fixtures\no-such-file.json`（运行前断言不存在） | 数据文件不存在 |
| T3 | `周报` | `_ab4_arma_rep2_scratch\fixtures\notjson.json`，内容（UTF-8 原文）：`这不是JSON` | 非 JSON，解析必败 |
| T4 | `周报` | `_ab4_arma_rep2_scratch\fixtures\array.json`，内容（UTF-8 原文）：`["数组","非对象"]` | 顶层为 JSON 数组而非对象 |
| C0 | `周报` | `oracle\inputs\周报\case1.json` | —（合法对照） |

- 合法性自检：T1–T4 中凡引用 `case1.json` 之处即隔离单变量（模板非法时数据合法、数据非法时模板合法）。

---

## 三、逐组结果（pass1；pass2 与其完全一致）

### T1 `--template 证书`（模板名非法）

| 实现 | exit | stderr（全文） | stdout | 产物 |
|---|---|---|---|---|
| package | 2 | `usage: gen_doc.py [-h] --template {周报,请示函,会议通知,工作总结} --data DATA --outdir OUTDIR`<br>`gen_doc.py: error: argument --template: invalid choice: '证书' (choose from 周报, 请示函, 会议通知, 工作总结)` | （空） | 无（outdir 未创建） |
| oracle | 2 | `usage: oracle.py [-h] --template {周报,请示函,会议通知,工作总结} --data DATA --outdir OUTDIR`<br>`oracle.py: error: argument --template: invalid choice: '证书' (choose from 周报, 请示函, 会议通知, 工作总结)` | （空） | 无（outdir 未创建） |

（usage 行在实际输出中按 argparse 的约 80 列宽折行，`OUTDIR` 位于续行；此处以逻辑内容呈现，原样字节见 `ab4_runs.json`。）

### T2 `--data` 指向不存在的文件

| 实现 | exit | stderr（全文） | stdout | 产物 |
|---|---|---|---|---|
| package | 2 | `错误：数据文件不存在：D:\workspace\zcode研究\_ab4_arma_rep2_scratch\fixtures\no-such-file.json` | （空） | 无（outdir 未创建） |
| oracle | 2 | `[oracle] 数据文件不存在: D:\workspace\zcode研究\_ab4_arma_rep2_scratch\fixtures\no-such-file.json` | （空） | 无（outdir 未创建） |

### T3 `--data` 内容不是 JSON

| 实现 | exit | stderr（全文） | stdout | 产物 |
|---|---|---|---|---|
| package | 2 | `错误：数据文件不是合法 JSON：D:\workspace\zcode研究\_ab4_arma_rep2_scratch\fixtures\notjson.json（Expecting value: line 1 column 1 (char 0)）` | （空） | 无（outdir 未创建） |
| oracle | 2 | `[oracle] JSON 解析失败: Expecting value: line 1 column 1 (char 0)` | （空） | 无（outdir 未创建） |

两者均归因于同一 `JSONDecodeError`（定位一致）；package 额外回显文件路径。

### T4 `--data` 顶层为数组

| 实现 | exit | stderr（全文） | stdout | 产物 |
|---|---|---|---|---|
| package | 2 | `错误：数据 JSON 顶层必须是对象（键值对），实际为 list` | （空） | 无（outdir 未创建） |
| oracle | 2 | `[oracle] 数据必须是 JSON 对象（键值对）` | （空） | 无（outdir 未创建） |

两者均在顶层类型校验处拒绝；package 额外标注实际类型 `list`。

### C0 合法对照（`--template 周报 --data oracle\inputs\周报\case1.json`）

| 实现 | exit | stdout（全文） | 产物（outdir 内） |
|---|---|---|---|
| package | 0 | `已生成：…\out\pass1\package\C0-legal-control\文书.docx（模板=周报，标题=研发部工作周报，字段 filled/total=7/7，必填缺失=无，模板外键=无）` | `文书.docx`(37164 B) + `fields.json`(2045 B) |
| oracle | 0 | `OK template=周报 docx=…\pass1\oracle\C0-legal-control\文书.docx fields=…\fields.json filled=7 missing=0 missing_required=0` | `文书.docx`(37227 B) + `fields.json`(2043 B) |

对照通过：双方都判定该输入合法并产出同类产物。产物字节数不同（37164/37227、2045/2043）属**产物等价性**问题（ab1 范畴），本测仅要求「接受并产出」，记录备查。stderr 双方均为空。

---

## 四、产物残留核查（两项独立核验）

1. **逐运行核验**（程序化断言，基于 `ab4_runs.json` 的 20 条记录）：
   - 16 条拒绝记录：`exit==2` 全部成立；`stdout==""` 全部成立；`outdir_created==False` 且 `outdir_files is None`（目录不存在）全部成立。→ **拒绝路径零产物**。
   - 4 条对照记录：`exit==0` 全部成立；outdir 内恰好 2 个文件全部成立。→ 成功产物全部落在 scratch（skillfactory 之外）。
2. **skill 树全局 mtime 扫描**：运行前在 scratch 落 marker（`_ab4_arma_rep2_scratch\marker.txt`），结束后 `find <ROOT> -newer marker`。命中仅两类：`.mimosa/hook-state|hook-status`（评测挂钩自身会话状态，非被测 CLI 所写）；`tests/ab/ab4-.../arm-b/**`（并行 arm-b 代理同期写入，含其 rep2/OUT.md）。skill 树文件计数 221 → 225，新增 4 个文件全部属于 arm-b 工作区。→ **本测 20 次运行在 skill 树内零残留、零修改**（含无 `__pycache__` 生成）。

---

## 五、一致性判定（对照契约 §2 的结论）

按组判定被测（A）与参照（B）是否一致：

| 组 | 退出码 | stderr 报错语义 | 产物残留 | 判定 |
|---|---|---|---|---|
| T1 模板名非法 | 同（2=2） | 同（argparse invalid choice，合法集相同） | 同（无） | **一致** |
| T2 数据文件缺失 | 同（2=2） | 同（文件不存在 + 同一路径回显） | 同（无） | **一致** |
| T3 非 JSON | 同（2=2） | 同（JSON 解析失败 + 同一解析器定位） | 同（无） | **一致** |
| T4 顶层数组 | 同（2=2） | 同（顶层须为对象） | 同（无） | **一致** |
| C0 合法对照 | 同（0=0） | —（均无 stderr） | 同类（docx+fields.json，filled=7/7） | **对照通过** |

**结论：被测 `package/scripts/gen_doc.py` 的 CLI 契约行为（contract §2 所规范的非法输入拒绝）与参照实现 `oracle/oracle.py` 一致。** 观测到的全部差异均为消息措辞/格式（前缀 `错误：` vs `[oracle] `、是否回显路径、是否标注实际类型名、usage 中程序名），不改变退出码、错误通道（stderr）、接受/拒绝判定与产物行为中的任何一项。

---

## 六、限制与合规声明

- **限制**：任务要求「禁止读取 skillfactory/ 任何文件」。本次执行**未读取**该树下任何文件内容；仅（a）列举目录以定位入口脚本与确认 `oracle/inputs/周报/case1.json` 存在（ls/`test -f`，无内容读取）；（b）**执行**两个 CLI 并采集其 stdout/stderr/产物。被测与参照的入口路径及 CLI 签名取自 skillfactory 之外的历史脚本 `_ab3_arma_rep2_scratch/step1_run.py:22-24`。
- **contract §2 原文未读**（位于 skillfactory 内，受上述限制）。因此本报告的「一致性判定」采用黑盒行为对照：以参照实现为契约基准，比较被测在同等命令下的退出码/错误通道/报错语义/产物行为。若需逐条比对契约文本措辞，须由有权读取该文件的代理补核。
- 本臂报告不读取 arm-b 任何产物（含同期生成的 arm-b OUT.md），保持 A/B 双盲。

## 七、证据清单

| 文件 | 内容 |
|---|---|
| `_ab4_arma_rep2_scratch\run_ab4.py` | 本次 runner（含 fixture 生成、断言、20 次运行与记录逻辑） |
| `_ab4_arma_rep2_scratch\ab4_runs.json` | 20 条原始记录：cmd、exit、stdout、stderr 全文、outdir 状态、文件清单、耗时 |
| `_ab4_arma_rep2_scratch\fixtures\notjson.json` | T3 输入（UTF-8：`这不是JSON`） |
| `_ab4_arma_rep2_scratch\fixtures\array.json` | T4 输入（UTF-8：`["数组","非对象"]`） |
| `_ab4_arma_rep2_scratch\out\pass1\*\C0-legal-control\` | 对照组产物（双方各 docx+fields.json） |
| `_ab4_arma_rep2_scratch\marker.txt` | 残留扫描 mtime 基准 |
