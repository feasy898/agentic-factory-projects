# AB5 arm-b / rep2 — 确定性（D1）A/B 对照与交付自评

- 日期：2026-09-30
- 被测技能：`office-templates`（入口 `package/scripts/gen_doc.py`）
- 输入：`oracle/inputs/会议通知/case1.json`（模板=会议通知）
- 执行机：windev-01，Python 3.12.10，bash（POSIX 层）+ Windows 路径
- 任务方禁令执行情况：**全程未读取 `skillfactory/` 下任何文件的内容**（详见 §8 合规声明）

---

## 0. 一句话结论

按任务规定的两遍覆盖复写 + 哈希对比法：**被测技能对同一输入连续两遍运行，`fields.json` 逐字节确定（三观测全同），但 `文书.docx` 逐字节不确定**——每遍 SHA-256 均不同；机理诊断为 docx（ZIP 容器）头部嵌入的墙钟时间戳（2 秒粒度）所致，**全部 17 个 ZIP entry 的解压内容两遍零差异**。参照实现 `oracle/oracle.py` 呈现**完全同型同因**的行为。逻辑（内容级）确定性成立，任务点名的 `python eval/runner.py package/out oracle/out` 以 `ok=true`、74/74 检查全过、exit 0 通过。**若 D1 要求严格逐字节可复现（本任务两遍哈希法所隐含的口径），则被测不满足 D1；若 D1 允许容器时间戳类元数据漂移（内容级确定性口径），则被测满足。** 主判定按前者：不满足，且该结论对参照实现同样成立，属双侧共性而非被测回归。

---

## 1. 任务协议（按 ask 复述）

1. 以 `package/scripts/gen_doc.py` 为**唯一入口**；
2. 对 `oracle/inputs/会议通知/case1.json` 同一输入**连续运行两遍**，输出到**同一 outdir** `package/out/会议通知/case1`（第二遍覆盖复写第一遍）；
3. 运行 `python eval/runner.py package/out oracle/out` 做确定性评测；
4. 与参照实现（同输入连跑两遍）对照产物确定性；
5. 判定被测是否满足可分发资产的确定性交付要求（spec D1）。

## 2. 环境与入口签名（`--help` 实测，未读源码）

- `python package/scripts/gen_doc.py --help` → `usage: gen_doc.py [-h] --template {周报,请示函,会议通知,工作总结} --data DATA --outdir OUTDIR`，exit 0
- `python oracle/oracle.py --help` → 同签名 `--template/--data/--outdir`，exit 0（参照实现）
- 运行前 `package/out` 与 `oracle/out` 均已有存量产物（8 单元 × {文书.docx, fields.json}）；两处 `会议通知/case1` 已先备份至 skillfactory 之外（§7）。

## 3. 执行记录（确切命令与退出码）

工作目录均为技能根 `…/office-templates`。

```bash
# 被测 第1遍
python package/scripts/gen_doc.py --template 会议通知 --data oracle/inputs/会议通知/case1.json \
    --outdir package/out/会议通知/case1        # exit 0，stdout: 已生成…标题=关于召开三季度质量评审会的通知，字段 filled/total=11/11
# 被测 第2遍（同一命令，同 outdir 覆盖复写）                      # exit 0，stdout 同上

# 参照 第1、2遍（同命令连跑，各 exit 0）；第3、4遍（补中间清单的配对运行，各 exit 0）
python oracle/oracle.py --template 会议通知 --data oracle/inputs/会议通知/case1.json \
    --outdir oracle/out/会议通知/case1

# 任务点名评测
python eval/runner.py package/out oracle/out   # exit 0
```

## 4. 字节级证据（SHA-256，清单脚本对目录内全部文件逐一哈希）

### 4.1 被测 `package/out/会议通知/case1`（协议内：同 outdir 两遍覆盖复写）

| 产物 | 存量基线（运行前） | 第 1 遍后 | 第 2 遍后 | 判定 |
|---|---|---|---|---|
| `fields.json` (2594 B) | `f21e402b…feb266` | `f21e402b…feb266` | `f21e402b…feb266` | **三观测逐字节全同** |
| `文书.docx` (37200 B) | `9fabef53…e88a` | `c51234b1…a380` | `b8a0e92d…9ed4` | **每遍哈希均不同** |

- 覆盖复写行为正常：两遍后目录均恰含 2 个文件（`FILE_COUNT=2`），无残留/重复/丢失。
- `diff`（run1 vs run2 清单）仅 `文书.docx` 一行不同；`fields.json` 行完全一致。

### 4.2 参照 `oracle/out/会议通知/case1`（同输入、同 outdir 覆盖复写）

| 产物 | 存量基线 | 第 1+2 遍后 | 第 3 遍后 | 第 4 遍后 | 判定 |
|---|---|---|---|---|---|
| `fields.json` (2592 B) | `80ed165c…23f5b` | `80ed165c…23f5b` | `80ed165c…23f5b` | `80ed165c…23f5b` | 四观测逐字节全同 |
| `文书.docx` (37318 B) | `5daf9a2b…1e` | `75892979…14b` | `0fddef94…419` | `b918f818…caf3` | **每遍哈希均不同** |

说明：参照第 1、2 遍在同一 shell 命令内连跑（各 exit 0），未在其间取清单；为取得配对证据补跑了第 3、4 遍（同协议、带中间清单），`diff` 第 3 vs 第 4 遍仅 `文书.docx` 一行不同。

## 5. 机理诊断（在 skillfactory 之外的 scratch 副本上做，不触碰 outdirs 终态）

将同一入口、同一输入的两遍产物生成到 scratch（`diagA`/`diagB`/隔 3 秒的 `diagC`；参照侧 `odiagA`/隔 3 秒 `odiagB`），解包 docx（ZIP）逐 entry 对比：

**被测（gen_doc.py）：**
- `diagA` 与 `diagB`（背靠背，嵌入时间同为 `2026-09-30 07:15:56`，DOS 时间戳 2 秒粒度同槽）：**整文件 SHA-256 全同**（`6938a352…37ac` = `6938a352…37ac`）。
- `diagC`（隔 3 秒，嵌入时间 `07:17:28`）：整文件哈希变为 `10cea157…e9c`；**17 个 entry（[Content_Types].xml、word/document.xml、styles、fonts、thumbnail 等）解压内容两两全同，0 个 entry 内容差异**——唯一差异是 ZIP 头墙钟时间。
- `fields.json`：同 outdir 两遍全同；跨不同 outdir（diagA vs diagC）仅第 109–110 行 `docx`/`fields_json` 两个自引绝对路径随 outdir 参数回显而不同——属路径回显，非非确定性（协议内同 outdir 不受影响）。

**参照（oracle.py）：**
- `odiagA`（`07:17:48`）vs `odiagB`（`07:17:54`）：整文件哈希 `85359e16…6403` ≠ `0151fd8d…352e`；**全部 entry 解压内容零差异**。

**机理结论**：`文书.docx` 的字节漂移 100% 归因于保存时写入 ZIP 头的墙钟时间戳（2 秒粒度）；两实现（被测与参照）同型同因，均为 python-docx 系保存路径的典型行为。逻辑内容跨运行逐字节稳定。

## 6. 任务点名评测：`python eval/runner.py package/out oracle/out`

- 结果：`"ok": true`，**74/74 项检查全部 pass**，exit 0。
- 要点：8/8 单元齐全、每单元恰含 `文书.docx + fields.json`、docx 可安全打开（DOCTYPE/ENTITY 扫描 + python-docx）、标题居中/黑体/22pt、称谓顶格、正文首行缩进 2 字符、落款右对齐右空两字、`fields.json` S1–S3 自洽、字段值与文中一致、缺失记账正确（含以 `____` 占位）、**字段填充一致率 100%（66/66，阈值 90%）**。其中 `会议通知/case1` 各项均 pass（被测侧为本次第 2 遍覆写后的产物，参照侧为第 4 遍产物）。
- 边界说明：runner 的检查为**语义/版式/字段级等价校验，不含任何 docx-vs-oracle 逐字节对比，也不含跨运行确定性检查**——字节级确定性判定依据本文 §4/§5 的哈希证据。整树文件名对照（`find … -type f | sort` 后 diff）：`package/out` 与 `oracle/out` 各 16 文件、名称完全一致（`TREE_NAMES_IDENTICAL`）。

## 7. A/B 对照判定与 D1 结论

| 维度 | 被测 gen_doc.py | 参照 oracle.py | 对照结论 |
|---|---|---|---|
| `fields.json` 字节确定性（同 outdir 两遍） | 满足（3 观测全同） | 满足（4 观测全同） | 一致 |
| `文书.docx` 字节确定性（同 outdir 两遍） | **不满足**（两遍不同哈希） | **不满足**（多遍不同哈希） | **同型同因** |
| docx 逻辑内容确定性（解压内容） | 满足（17 entry 零差异） | 满足（entry 零差异） | 一致 |
| 覆盖复写行为 | 恰 2 文件，无残留 | 恰 2 文件，无残留 | 一致 |
| runner 语义等价 | ok=true，74/74 | （作为参照树） | 被测通过 |

**D1 判定**（注明：`spec.md` 位于 skillfactory 内，按禁令未读，D1 原文措辞不可引；以下按任务自身规定的两遍覆盖复写 + 对比方法所隐含的口径判定）：

- **主判定（严格逐字节口径，即本任务哈希对比法的口径）：被测不满足 D1。** `文书.docx` 两遍哈希不同（`c51234b1…` vs `b8a0e92d…`），可分发资产的产物无法逐字节复现；修复方向为确定性 ZIP 写出（固定 entry `date_time`，如 SOURCE_DATE_EPOCH 或固定 ZipInfo），改动面预计仅保存环节。
- **从宽口径（内容级确定性）：满足。** 全部 entry 解压内容两遍零差异，`fields.json` 协议内逐字节稳定，runner 74/74 全过。
- **A/B 对照归因**：该不确定性为被测与参照**共有的同一机理**（ZIP 墙钟时间戳），非被测相对参照的回归；被测在所有可对照维度上与参照表现一致。

## 8. 合规声明（禁读约束的执行方式）

- 未使用 Read/cat/type 等任何方式读取 `skillfactory/` 下任何文件内容，包括但不限于 `spec.md`、`contract.md`、`SKILL.md`、`package/scripts/gen_doc.py`、`oracle/oracle.py`、`eval/runner.py`、`eval/golden.json`、`references/*`、输入 JSON。
- 获取信息的方式限定为：目录/文件名列举（`find`/`ls`，仅名称）、执行入口与其 `--help`（黑盒）、任务点名的 runner 输出、SHA-256/字节数哈希清单、以及对 **skillfactory 之外 scratch 副本**（本次运行自己生成的产物副本，路径 `D:/workspace/zcode研究/_ab5_armb_rep2_scratch/`）的解包与 diff。
- 运行前已将两处 `会议通知/case1` 存量产物备份至 scratch（`backup_pkg_case1_before/`、`backup_ora_case1_before/`，含 `fields.json` 与 `文书.docx`），备份过程为字节复制，未读入内容。

## 9. 终态与遗留

- 终态：`package/out/会议通知/case1` = 被测第 2 遍产物（fields `f21e402b…` + docx `b8a0e92d…`）；`oracle/out/会议通知/case1` = 参照第 4 遍产物（fields `80ed165c…` + docx `b918f818…`）。两侧 `fields.json` 均与存量基线逐字节相同；docx 字节与存量基线不同（时间戳槽位不同，逻辑内容相同）。存量 docx 字节可自 scratch 备份恢复。
- scratch 诊断物：`diagA/B/C`、`odiagA/B`、清单 `pkg_baseline/pkg_m1/pkg_m2/ora_baseline/ora_m2/ora_m3/ora_m4.txt`、整树名单 `pkg_tree/ora_tree.txt`、清单脚本 `manifest.py`。
- 未尽/受限事项：(1) D1 条文原文因禁读未获，判定按任务规定方法隐含口径给出两解并注明主判定；(2) `eval/runner.py` 当前不含跨运行字节级确定性检查，建议 harness 增补（本报告 §4 的哈希法可直接固化为检查项）；(3) 其余 7 个单元（周报/请示函/工作总结 × case1/2）未在本 ask 协议内做两遍法，其 runner 语义检查通过（74/74），字节级结论仅对 `会议通知/case1` 成立并如实标注。
