# AB4 非法输入拒绝 A/B 对照报告 — arm-b / rep1

- **日期**：2026-09-30（本机 windev-01，Python 3.12.10 + python-docx 1.2.0，与 SKILL.md §8 实测版本一致）
- **判定问题**：对 4 组非法输入（①--template 模板名非法 ②--data 文件不存在 ③--data 非 JSON ④--data 顶层非对象）
  及 1 组合法对照（`oracle/inputs/周报/case1.json`），被测 CLI 契约（contract §2 / spec §7 C1–C2）与参照实现是否一致：
  非法 → 退出码 2 + stderr 中文报错 + **不产生产物、不建产物目录**；合法 → 退出码 0 + stdout 摘要 + 恰 2 产物
- **被测方（A）**：office-templates 技能包生成器 `package/scripts/gen_doc.py`（SKILL.md §4 冻结 CLI）
- **参照方/oracle（B）**：`oracle/oracle.py`
- **输入**：G1/G0 用 `oracle/inputs/周报/case1.json`（全字段合法，隔离模板名单一变量）；
  G2 用不存在的 `…/_work/inputs/ghost_404.json`；G3/G4 用本次自造的 `_work/inputs/not-json.json`
  （内容 `这不是一段合法的JSON文本！！`）与 `_work/inputs/array-top.json`（内容 `["数组", "非对象"]`）
- **产物落位**：本 rep1 目录 `_work/` 下，A → `_work/a/`，B → `_work/b/`（对称沙箱，全程未写入
  `package/out` 与 `oracle/out`，两者 sha256 前后清点零改动，见 §5）
- **方法依据**：先完整读 `package/SKILL.md` 全文与 `package/references/` 全部 4 篇（周报/请示函/会议通知/工作总结），
  按 SKILL.md §4（退出码 0/2 语义）、§7（四种非法输入表）执行；判定基准为 `contract.md` §2 冻结 CLI
  与 `spec.md` §7（C1–C3）——G1 的机制 SKILL.md §7-1/spec §7 C2-1 明确指定为 "argparse choice 报错"

## 1. 执行的命令与退出码（10 次实跑，driver=Python subprocess，cwd=资产根）

每组同一命令模板，逐组实测（完整原文见 `_work/ab4_results.json` 与 `_work/logs_ab4_run.txt`）：

```bash
# A（被测）：python package/scripts/gen_doc.py  --template <T> --data <D> --outdir <O>
# B（参照）：python oracle/oracle.py           --template <T> --data <D> --outdir <O>
```

| 组 | 输入 | A 退出码 | B 退出码 | A stdout | B stdout |
|---|---|---|---|---|---|
| G1 模板名非法 | `--template 证书`（data=case1 合法） | **2** | **2** | 空 | 空 |
| G2 data 不存在 | `ghost_404.json`（事先确认不存在） | **2** | **2** | 空 | 空 |
| G3 非 JSON | `not-json.json` | **2** | **2** | 空 | 空 |
| G4 顶层非对象 | `array-top.json`（`["数组", "非对象"]`） | **2** | **2** | 空 | 空 |
| G0 合法对照 | `oracle/inputs/周报/case1.json` | **0** | **0** | 1 行摘要 | 1 行摘要 |

**退出码全集 = {0, 2}**（10 次实跑程序化归并，`ab4_results.json`）——满足 contract §2 "不允许其他退出码语义"、
SKILL.md §7 "除 0/2 外不应出现其他退出码"；全程 **0 个未捕获 traceback**（程序化检测 `Traceback` 字样=无）。

## 2. stderr 对照（逐组原文）

| 组 | A（被测）stderr | B（参照）stderr | 语义一致？ |
|---|---|---|---|
| G1 | `usage: gen_doc.py [-h] --template {周报,请示函,会议通知,工作总结} …`（3 行）+ `error: argument --template: invalid choice: '证书' (choose from 周报, 请示函, 会议通知, 工作总结)` | 同构 3 行，仅程序名换 `oracle.py` | ✅ 逐字同构（argparse choice 报错，双方机制与四选一名单完全一致，符合 SKILL.md §7-1 指定机制） |
| G2 | `错误：数据文件不存在：tests/ab/…/ghost_404.json` | `[oracle] 数据文件不存在: tests\ab\…\ghost_404.json` | ✅ 同为中文、同名报错类别，均含出错路径；前缀/路径分隔符属格式自由 |
| G3 | `错误：数据文件不是合法 JSON：tests/ab/…/not-json.json（Expecting value: line 1 column 1 (char 0)）` | `[oracle] JSON 解析失败: Expecting value: line 1 column 1 (char 0)` | ✅ 同为中文报错；均带底层解析器定位（同一 JSONDecodeError 文案）；A 逐字命中 SKILL.md §7-3 "数据文件不是合法 JSON"，B 为同义表述 |
| G4 | `错误：数据 JSON 顶层必须是对象（键值对），实际为 list` | `[oracle] 数据必须是 JSON 对象（键值对）` | ✅ 同为中文报错、同一判定类别；A 逐字命中 SKILL.md §7-4 "顶层必须是对象"，B 为同义表述 |

G1 注记：argparse choice 报错为英文 usage 文案，**A/B 完全同构**且是 contract/SKILL/spec 三处共同指定的机制
（spec §7 C2-1 原文 "argparse choice 报错"），不构成双方分歧，也不违反 "stderr 中文报错" 的契约意图；
G2–G4 双方均为中文。contract §2 未冻结错误文案的具体措辞（"stderr 打印中文错误信息"，格式自由）。

## 3. 产物残留（contract §2 硬约束：不写任何产物文件、不建产物目录）

程序化三重核对（每次运行前快照沙箱树、运行后 diff；并检查 outdir 及其父目录存在性）：

| 组 | A：outdir 存在 | A：父目录存在 | A：沙箱树新增 | B：outdir 存在 | B：父目录存在 | B：沙箱树新增 |
|---|---|---|---|---|---|---|
| G1 | False | False | **无** | False | False | **无** |
| G2 | False | False | **无** | False | False | **无** |
| G3 | False | False | **无** | False | False | **无** |
| G4 | False | False | **无** | False | False | **无** |
| G0 | True | True | 恰 `control/周报/case1/{文书.docx, fields.json}` | True | True | 恰同 2 文件 |

- 4 组非法输入下 **8/8 零残留**：outdir 连同其父目录都未被创建（G1–G4 的 `_work/<臂>/g<N>/` 至本次报告写就时仍不存在，`find` 实证 `_work/a`、`_work/b` 下只有 `control/`）；stdout/stderr 之外无任何新文件。
- G2 的幽灵输入文件 `ghost_404.json` 运行后仍未被任何一方创建（防"读文件反手建文件"式副作用）。
- 对照组 8/8：两臂 outdir 均恰含 `文书.docx + fields.json` 两个文件（清单 `['fields.json','文书.docx']` 程序化比对）。
- 实现层印证（读码）：A 的全部输入校验位于 `gen_doc.py:330-346`，先于 `outdir.mkdir`（`gen_doc.py:361`）；
  B 同构（`oracle.py:370-381` 校验先于 `oracle.py:389` mkdir）——"先校验后触盘" 双方一致，与实测零残留互证。

## 4. 合法对照组（G0）产物质量核验——对照建立在可信基线上

- **fields.json 三方深度 diff**（忽略 `$.outputs.*` 自引用路径，`_work/ab4_control_check.py`）：
  `A vs B = 0 差异`、`A vs 基线 oracle/out/周报/case1 = 0 差异`、`B vs 基线 = 0 差异`——台账逐键一致，
  两臂顶层恰 7 键、summary 恰 6 键（S1 口径，程序化打印）。
- **docx 段落文本**：A 11 段 vs B 11 段，唯一差异为 B 基本信息行多 `　　部门：研发部`（AB1 已定性的
  参照方结构差异；`references/周报.md` §1 基本信息行公式为 `填报人：{填报人}　　周期：{周期}`，**A 与
  references 逐字一致，B 超出 references**）。属文书结构项，与本次判定的 CLI 契约（§2）无关，录以备考。
- **oracle 自带 verify.py 版式不变量**（标题居中/称谓顶格/firstLineChars=200/落款右对齐/台账自洽）：
  `verify.py _work/a/control` → PASS=1 FAIL=0 exit 0；`_work/b/control` → PASS=1 FAIL=0 exit 0（4/4 项全过）。
- G0 stdout 摘要：A `已生成：…（模板=周报，标题=研发部工作周报，字段 filled/total=7/7，必填缺失=无，模板外键=无）`；
  B `OK template=周报 … filled=7 missing=0 missing_required=0`——双方如实（7/7 全填，与台账一致）。

## 5. 共享状态零改动（卫生核验）

`package/out` 与 `oracle/out` 全部文件 sha256 前后两次全量清点：**两棵树均逐字节不变**
（`ab4_results.json: shared_state_unchanged = {package/out: true, oracle/out: true}`）。

## 6. 判定结论：**被测 CLI 契约（contract §2）与参照完全一致 ✅（8/8 拒绝路径 + 2/2 对照路径全对齐）**

1. **退出码语义一致**：4 组非法输入 A/B 均 exit 2，合法对照均 exit 0；全程退出码集合恰为 {0,2}，无第三种退出码、无崩溃（contract §2 退出码表逐格命中）。
2. **报错行为一致**：G2–G4 双方均为 stderr 中文报错、均指向同一错误类别（不存在/非 JSON/顶层非对象），A 更进一步逐字命中 SKILL.md §7 的报错措辞并附出错路径与解析定位；G1 双方为同构的 argparse choice 报错（contract 指定机制，四选一名单完全一致）。
3. **零残留一致**：8/8 非法路径双方均不写产物、不建产物目录（连父目录都未创建），且无任何沙箱外副作用（幽灵输入未被创建、共享产物树逐字节不变）——"先校验后触盘" 的实现顺序双方同构（`gen_doc.py:330-346` vs `oracle.py:370-389`）。
4. **合法路径质量对齐**：对照组 fields.json 三方 0 差异、verify.py 双双 PASS、stdout 摘要如实——对照锚定在可信基线上，A/B 分工仅余 AB1 已定性的参照方多文案结构差异（B 信息行多 `部门：`，与 references 公式不符的反而是 B），不影响本判定。
5. **微差备案（均属 contract 格式自由区）**：错误前缀（A `错误：` / B `[oracle]`）、G3 是否回显输入路径、路径分隔符写法——双方均满足"stderr 中文报错"的冻结要求，不构成契约分歧。

## 7. 证据与工件索引

- 本目录 `_work/`：
  - `ab4_run.py`（驱动：造非法输入 → 10 次 subprocess 实跑 → 退出码/stderr/树 diff/共享状态清点）、`ab4_results.json`（逐次原始记录）、`logs_ab4_run.txt`（控制台原文）
  - `ab4_control_check.py`（对照组核验：清单/三方 diff/段落 dump/verify.py/sha256）、`ab4_control_check.json`、`logs_ab4_control_check.txt`
  - `inputs/not-json.json`、`inputs/array-top.json`（自造非法输入）；`a/control/周报/case1/`、`b/control/周报/case1/`（两臂对照产物）
- §1–§5 全部数字与引文均出自本次实跑输出（`tee` 落盘的 logs 与 results JSON），stderr 原文可在 `ab4_results.json` 逐字节复查。
- sha256（前 16 位）：A 对照 docx=`87460c161f2aa6ef`/fields=`0a3fdbf289e05b78`；B 对照 docx=`00144f34e9f7b912`/fields=`99e6829aa765b82b`；基线 docx=`f0d11dc26c79961f`/fields=`3f657d4347b6f017`（docx 哈希不同仅因 zip 内嵌时间戳，段落文本/台账语义层已比对）。
- **未做事项**：G1 以外的模板名（仅测 `证书` 这一个非法名，四合法名逐一通过性属 AB1 范围）；非 UTF-8 编码文件（SKILL.md §7 表外情形，A 有独立报错分支 `gen_doc.py:339` 但不在本任务四组之内）；docx 渲染级目检未做（SKILL.md §8 明示不做）。
