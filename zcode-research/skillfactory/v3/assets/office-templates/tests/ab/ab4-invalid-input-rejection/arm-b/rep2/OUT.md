# ab4-invalid-input-rejection · arm-b · rep2 — 完整成果（OUT.md）

- 日期：2026-09-30
- 任务：A/B 对照**非法输入拒绝**——让被测技能（A = `package/scripts/gen_doc.py`）与参照实现
  （B = `oracle/oracle.py`）分别接受四组非法输入（① `--template 证书`；② `--data` 指向不存在文件；
  ③ `--data` 内容不是 JSON；④ `--data` 内容为 `["数组","非对象"]` 顶层数组），另以
  `oracle/inputs/周报/case1.json` 作合法对照；逐组记录退出码、stderr 与产物残留，
  判定被测 CLI 契约（contract §2）与参照是否一致。
- 执行者：ZCode 子代理（dynamic workflow actor），本机 windev-01。
- scratch 现场：`D:\workspace\zcode研究\_ab4_armb_rep2_work\`（跑批器、后续脚本、10 份日志、汇总 JSON、产物）。

---

## 0. 方法依据（先读后做，全部实际读取）

按任务要求先完整阅读以下文件，按其方法执行：

| 文件 | 取用的方法点 |
|---|---|
| `package/SKILL.md`（全文 133 行） | §4 用法/退出码表（0 成功 / 2 非法输入拒绝）；§7 四种非法输入行为表（第 1 行明写 "argparse choice 报错，exit 2"；第 2–4 行报"数据文件不存在 / 不是合法 JSON / 顶层必须是对象"）；"退出码 2 ⇒ stderr 中文报错、**不写任何产物文件、不建产物目录**"；"除 0/2 外不应出现其他退出码" |
| `package/references/周报.md`（及另 3 篇 references 全文） | 合法对照组的标题公式核对（周报标题 = `{部门}工作周报`）；确认 references 只涉版式/字段语义，不涉拒绝行为 |
| `contract.md` §2（CLI 契约，冻结） | 判定基准：exit 2 条件恰为四条（模板非法/文件不存在/JSON 解析失败/顶层非对象）；"stderr 打印中文错误信息，不产生产物、不建产物目录"；"不允许其他退出码语义" |
| `spec.md` §7 C2 + 附录 A-3 | 验证方法：4 条负路径各 exit=2，产物残留计数=0（附录 A-3 用 `find ... -name 文书.docx -o -name fields.json` 计数法，本轮 step2 同法复刻） |
| `oracle/README.md` | 参照实现自述的退出码语义（2 = 模板名非法/数据文件缺失/JSON 非法/数据非对象），与 contract §2 同口径 |

---

## 1. 环境与输入（实测）

环境：Python 3.12.10 / python-docx 1.2.0 / Windows x64——与 spec.md 文首声明的实测环境一致。

非法输入 ③④ 由本轮在 scratch 内新造；② 的不存在路径经 `os.path` 核实；① 与对照组复用合法输入：

| # | 输入 | 路径 | 事实（实测） |
|---|---|---|---|
| ① | 模板名非法 | `--template 证书`，`--data` = `oracle/inputs/周报/case1.json`（456B，sha256[:16]=`3e775488b6a95bf9`） | 数据合法，非法性仅在模板名 |
| ② | 文件不存在 | `_ab4_armb_rep2_work/inputs/no_such_file.json` | `exists=False`（断言通过） |
| ③ | 不是 JSON | `_ab4_armb_rep2_work/inputs/notjson.json` | 内容恰为字面 `不是JSON`（10B，sha16=`c1a17738a1776922`） |
| ④ | 顶层非对象 | `_ab4_armb_rep2_work/inputs/toplist.json` | 内容恰为 `["数组","非对象"]`（22B，sha16=`3560a9786452326f`） |
| C | 合法对照 | `oracle/inputs/周报/case1.json` | 顶层对象、周报 7 字段全填 |

两入口存在性核实：`package/scripts/gen_doc.py` 与 `oracle/oracle.py` 均 `is_file()=True`。

---

## 2. 执行记录（本轮实测的检查 = 任务点名的检查：2 实现 × 5 组 = 10 次生成）

统一 CLI（contract §2 口径）：`python <script> --template <T> --data <D> --outdir <O>`，cwd=scratch，
每个案例的 outdir 在运行前断言不存在（保证"是否建目录"可判定）。运行器：
`python _ab4_armb_rep2_work/run_ab4.py`；原始 stdout/stderr 存档 `_ab4_armb_rep2_work\logs\{A,B}_{n1..n4,C}.log`。

### 2.1 退出码总表（10/10 实测）

| 组 | A 被测 gen_doc.py | B 参照 oracle.py | contract §2 期望 |
|---|---|---|---|
| ① `--template 证书` | **2** | **2** | 2 |
| ② data 不存在 | **2** | **2** | 2 |
| ③ 不是合法 JSON | **2** | **2** | 2 |
| ④ 顶层数组 | **2** | **2** | 2 |
| C 合法对照 | **0** | **0** | 0 |

全程仅出现 0/2 两种退出码 → 满足 SKILL.md §7 "除 0/2 外不应出现其他退出码"、contract §2 "不允许其他退出码语义"。

### 2.2 stderr / stdout / 产物残留逐组明细（stderr 为原文摘录）

| 组 | 实现 | stderr（原文） | stdout | outdir 被创建？ | 产物残留 |
|---|---|---|---|---|---|
| ① | A | `usage: gen_doc.py …` + `gen_doc.py: error: argument --template: invalid choice: '证书' (choose from 周报, 请示函, 会议通知, 工作总结)` | 空 | **否** | 0 |
| ① | B | `usage: oracle.py …` + `oracle.py: error: argument --template: invalid choice: '证书' (choose from 周报, 请示函, 会议通知, 工作总结)` | 空 | **否** | 0 |
| ② | A | `错误：数据文件不存在：D:\…\inputs\no_such_file.json` | 空 | **否** | 0 |
| ② | B | `[oracle] 数据文件不存在: D:\…\inputs\no_such_file.json` | 空 | **否** | 0 |
| ③ | A | `错误：数据文件不是合法 JSON：D:\…\inputs\notjson.json（Expecting value: line 1 column 1 (char 0)）` | 空 | **否** | 0 |
| ③ | B | `[oracle] JSON 解析失败: Expecting value: line 1 column 1 (char 0)` | 空 | **否** | 0 |
| ④ | A | `错误：数据 JSON 顶层必须是对象（键值对），实际为 list` | 空 | **否** | 0 |
| ④ | B | `[oracle] 数据必须是 JSON 对象（键值对）` | 空 | **否** | 0 |
| C | A | 空 | `已生成：…\out\A\C\文书.docx（模板=周报，标题=研发部工作周报，字段 filled/total=7/7，必填缺失=无，模板外键=无）` | 是 | 恰 `文书.docx` + `fields.json` |
| C | B | 空 | `OK template=周报 docx=… filled=7 missing=0 missing_required=0` | 是 | 恰 `文书.docx` + `fields.json` |

### 2.3 产物残留专项扫描（spec 附录 A-3 同法，step2 复刻）

`python _ab4_armb_rep2_work/step2_residual_and_paras.py`：全新子树 `neg_only/`，**只跑 8 条阴性命令**
（2 实现 × 4 组），随后全子树扫描 `文书.docx` / `fields.json`：

- 8 条命令退出码全为 **2**（`negative_exit_all_2: true`）；
- 残留计数 = **0**（`residual_count_文书_docx_plus_fields_json: 0`，`residual_paths: []`）；
- `neg_only/` 全树文件清单仅剩 2 个输入文件——**8 个 outdir 一个都没被创建**（无任何 `out/` 目录）。

⇒ contract §2 "exit 2 ⇒ 不产生产物、不建产物目录"在两实现上均成立，且**逐组可判**
（主跑批器对每次运行都有前置断言 `outdir 不存在` + 后置检查 `outdir_created=false, listing=[]`）。

---

## 3. 逐组一致性判定（对照 contract §2 / SKILL.md §7）

| 组 | 退出码 | stderr 语义 | 残留 | 判定 |
|---|---|---|---|---|
| ① 模板名非法 | A=B=2 | 均为 argparse choice 报错，报文除 prog 名（gen_doc.py/oracle.py）与 usage 缩进外**逐字同构**；均列出四个合法名 | 双方均 0 | ✅ **一致** |
| ② 文件不存在 | A=B=2 | 中文报错，同一短语 **"数据文件不存在"**，均附 offending 路径（措辞前缀 `错误：` vs `[oracle]` 属实现自由） | 双方均 0 | ✅ **一致** |
| ③ 不是合法 JSON | A=B=2 | 中文报错，均附同一底层解析器信息 `Expecting value: line 1 column 1 (char 0)`；A 的短语"数据文件不是合法 JSON"恰为 SKILL.md §7 第 3 行的原文措辞，B 为"JSON 解析失败"（spec 附录 A-3 同措辞）——语义等价 | 双方均 0 | ✅ **一致** |
| ④ 顶层数组 | A=B=2 | 中文报错，均点明"必须是（JSON）对象（键值对）"；A 额外注明实际类型 `list`（增量信息，不构成语义分歧） | 双方均 0 | ✅ **一致** |
| C 合法对照 | A=B=0 | 双方 stderr 均空；stdout 各打一行人读摘要（格式自由，contract §2 明示） | 双方均恰 2 文件 | ✅ **一致** |

**结论：被测 CLI 契约（contract §2）与参照实现完全一致——四组非法输入全部按"exit 2 + 报错 + 零产物、
零目录"拒绝，合法对照全部按"exit 0 + 摘要 + 恰 2 产物"放行；无任何一组出现 A/B 行为分歧。**

两点如实说明（不构成分歧）：

1. **组① 的 stderr 是英文 argparse 报文**。这不是被测偏离：SKILL.md §7 第 1 行对本组的**规定行为**就是
   "argparse choice 报错，exit 2"，参照实现同样如此；"stderr 打印中文错误信息"的中文要求落在第 2–4 行
   （②③④），两实现均以中文报错满足。A/B 在本组互相一致、且都与 SKILL.md 规定的机制一致。
2. **跑批器一处标记瑕疵（已核实不影响结论）**：`ab4_summary.json` 中 `residual_after_negative_cases_only`
   键的扫描实际发生在全部 10 次运行之后（命名不准）。其内容仍证明全 scratch 无 stray 产物（仅两个对照
   outdir 各 2 文件）；而"阴性后零残留"的权威证据由 §2.3 的专项干净扫描（neg_only，只跑 8 条阴性）独立给出。

---

## 4. 合法对照组的产物实质核对（补充证据）

对照输入 `周报/case1.json`（7 字段全填）：

- **fields.json**：A/B **深度等价**——去掉 `$.outputs`（路径写法随实现，spec S4/contract §6 明示不比较）
  后完全相等（`fields_equal_minus_outputs: true`）；字节级哈希不同仅因 outputs 内路径不同
  （A sha16=`75372739b0f09680`，B=`e18a002d2c19091c`）。
- **docx 段落**：A/B 均 11 段，标题同为 `研发部工作周报`（与 references/周报.md 标题公式 `{部门}工作周报`
  一致）；**仅第 2 段（基本信息行）1 处文字差异**：
  - A：`填报人：王小明　　周期：2026-09-21 至 2026-09-27`
  - B：`填报人：王小明　　部门：研发部　　周期：2026-09-21 至 2026-09-27`
  - 定位：`oracle/oracle.py:177` 信息行含 `部门：{dept}`，`package/scripts/gen_doc.py:265` 信息行不含部门
    （gen_doc 的信息行口径与其自身 `references/周报.md` §1 的公式一致）。
    **这是 ab1/ab3 轮已存档的既知 D1 分歧**（周报信息行是否含部门），属成文内容层、**不在 contract §2
    CLI 契约范畴**，本轮如实复现记录，不重复计为新手发现。
- **XML 安全**（contract §3 安全 MUST，顺带核验）：两份对照 docx 的 zip 内 XML 条目抽查头部无
  `<!DOCTYPE`/`<!ENTITY`（step2 的 `paras()` 内置断言，未触发）。
- docx 字节级 A≠B（A sha16=`478fa614d3332419`，B=`aa6c058cbae7e968`）——与 ab1/ab3 结论相同，为样式表级
  差异，非本轮范畴。

---

## 5. 结论（arm-b/rep2 判定）

1. **四组非法输入，A（被测 gen_doc.py）与 B（参照 oracle.py）行为完全一致**：全部 exit=2、stderr 报错
   （① argparse 报文逐字同构；②③④ 中文短语语义相同）、stdout 全空、**不建产物目录、零产物残留**
   （逐组即时核验 + 干净子树专项扫描双重证实，残留计数 0/8×2）。
2. **合法对照完全一致**：双方 exit=0、stderr 空、stdout 一行人读摘要、outdir 内恰 `文书.docx` + `fields.json`
   两文件；fields.json 去 `$.outputs` 后深度相等。
3. **退出码域**：10 次运行只出现 0 与 2，无第三种退出码、无未捕获崩溃——满足 contract §2/SKILL.md §7。
4. 被测的 CLI 契约（contract §2）判定为**与参照一致**；唯一记录在案的文字差异（③④ 的中文措辞、报错前缀
   `错误：` vs `[oracle]`、④ 附带实际类型名）均属 contract §6"实现自由区"（stderr 措辞未冻结）。
5. 合法路径上的既知内容分歧（周报信息行是否含 `部门`）本轮再次复现，已如实记录于 §4，属成文内容层、
   不影响本轮 CLI 拒绝契约的一致性判定。

---

## 6. 检查与证据清单（本轮实际执行）

| 检查 | 命令（实际运行） | 结果 |
|---|---|---|
| 任务点名检查：10 次生成（2 实现 × 4 非法组 + 1 合法对照），逐组记录退出码/stderr/残留 | `python _ab4_armb_rep2_work/run_ab4.py` | §2 全部数据；汇总 `_ab4_armb_rep2_work\ab4_summary.json`；原始日志 `logs\{A,B}_{n1..n4,C}.log` |
| 产物残留专项（spec 附录 A-3 同法） | `python _ab4_armb_rep2_work/step2_residual_and_paras.py` | 8 阴性全 exit=2、残留=0、无 outdir 被创建（§2.3） |
| 对照组产物实质核对（fields 深度 diff、docx 逐段、XML 安全、标题公式） | 同上 step2 脚本（内置于 `paras()`/diff 逻辑） | §4 全部数据；明细 `_ab4_armb_rep2_work\step2_report.json` |
| 方法依据阅读 | Read `package/SKILL.md`、`package/references/{周报,请示函,会议通知,工作总结}.md`、`contract.md`、`spec.md`、`oracle/README.md`、`oracle/oracle.py`、`package/scripts/gen_doc.py` | §0 取用点 |

**未做 / 不适用**：未做同输入双跑确定性验证（D1，任务未要求，ab1 轮已覆盖）；非法输入仅在 `周报` 模板与
对照组数据上施测（任务点名的四组输入即此范围；组① 因 argparse 前置拒绝，任何合法 --data 下行为相同）；
未做真实渲染目检（SKILL.md §8 明示不做）。

**产物与现场**：scratch 全套（跑批器、step2 脚本、10 份日志、2 份 JSON 汇总、对照组产物）留存于
`D:\workspace\zcode研究\_ab4_armb_rep2_work\`。本文件即交付物本体。
