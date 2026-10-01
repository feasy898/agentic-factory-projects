# OUT.md — AB5 确定性与交付自评（arm-a / rep1）

- **任务**：让被测技能以 `package/scripts/gen_doc.py` 为唯一入口，对 `oracle/inputs/会议通知/case1.json` 同一输入**连续运行两遍到同一 outdir**（`package/out/会议通知/case1`，覆盖复写），再运行 `python eval/runner.py package/out oracle/out` 做确定性评测；与参照实现（oracle，同输入连跑两遍、同协议覆盖复写）对照产物确定性，判定被测是否满足可分发资产的确定性交付要求（**spec §8 D1**）。
- **日期**：2026-09-30（全部命令本次实跑，时间戳均为本机 +0800）
- **环境**：Windows x64 / Python 3.12.10 / python-docx 1.2.0（`python --version`、`python -c "import docx; print(docx.__version__)"` 实查，与 spec.md 附录 A 实测环境一致）
- **工作目录**：`skillfactory/v3/assets/office-templates/`
- **方法依据**：先完整读 `package/SKILL.md`（§2"同一输入连跑两次产物一致"、§4 用法、§5 产物、§8 D1 相关环境）与 `package/references/会议通知.md`（成文结构/字段规范/边界示例），判据取自 `spec.md` §8 D1、`contract.md` §3 确定性 MUST、`eval/runner.py`（contract §5 冻结的六类检查）。

---

## 0. 结论（先行）

| 口径 | 判定 | 依据（本文全部实测） |
|---|---|---|
| **spec §8 D1 语义确定性** | **满足** | 被测同输入连跑两遍（同 outdir 覆盖复写）：`fields.json` **逐字节一致**（含 `outputs`，md5 恒 `59637927…`）；`文书.docx` 解析后语义签名（段落文本/对齐/缩进/字体/字号/行距/右缩进/页边距）**全等**，zip 17 个条目**解压内容全部逐字节一致**、仅 DOS 时间戳不同（D1 明示允许）。对照实现 oracle 同协议双跑呈**完全相同的确定性 profile** |
| **`eval/runner.py` 确定性自评** | **通过** | exit 0，`ok=true`，68/68 checks 全过，字段填充一致率 **100.0%（66/66，阈值 90%）**；runner 连跑两遍输出**逐字节一致**（runner 自身确定性成立） |
| **可分发资产确定性交付要求（spec D1 + contract §3 MUST）** | **达标** | 两项均满足；静态佐证：被测入口 `package/scripts/gen_doc.py` 与 `oracle/oracle.py` 均无 `time/random/uuid/datetime` 等不可复现源（grep 0 命中），符合 V8 |

**主判定**：被测（`package/`，入口 `package/scripts/gen_doc.py`）**满足 spec D1 的确定性交付要求**，且其确定性强度与参照实现完全同级（fields 逐字节、docx 语义级、zip 内容级一致，差异仅限 D1 明文豁免的 zip 时间戳）。

---

## 1. 判据（读了什么、按什么判）

- `spec.md:130-133`（§8 D1）：同输入连跑两次，`fields.json`（除 S4 `outputs` 外）逐字节一致；`文书.docx` 解析后的段落文本、对齐、缩进、字体、行距、页边距全部一致（**zip 条目时间戳允许不同，不做逐字节要求**）。
- `contract.md:53-54`（§3 MUST）：同上口径，冻结为交付必备。
- `spec.md:80`（V8）/ `contract.md:50`：禁止当前时间/随机内容。
- `eval/runner.py:28`：runner 自身"无时间/随机源，同一输入两次运行输出一致"——本次以双跑实测。
- 覆盖复写场景的额外含义：第二遍必须**复写**第一遍产物且不残留多余文件（`SKILL.md:64` 产物说明"恰产出 2 个文件"）。

## 2. 执行记录（命令原样，exit 实测）

### 2.1 被测：同输入连跑两遍到同一 outdir（覆盖复写）

前置状态（本 ask 开始时实查，`_work/step0_prestore.json`）：单元内恰 `文书.docx`+`fields.json` 两文件，md5 分别为 `8b409d27…`/`59637927…`（2026-09-30 05:04:19 早前一轮产物）。

```bash
# Run 1（07:11:16）
python package/scripts/gen_doc.py --template 会议通知 --data oracle/inputs/会议通知/case1.json --outdir package/out/会议通知/case1
# stdout: 已生成：package\out\会议通知\case1\文书.docx（模板=会议通知，标题=关于召开三季度质量评审会的通知，
#         字段 filled/total=11/11，必填缺失=无，模板外键=无）   EXIT=0
# Run 2（07:11:32，同一命令覆盖复写，逐字相同）
python package/scripts/gen_doc.py --template 会议通知 --data oracle/inputs/会议通知/case1.json --outdir package/out/会议通知/case1
# stdout: 同上一行摘要   EXIT=0
```

每遍跑完立即快照两产物到 `_work/run1/`、`_work/run2/`（md5/size/mtime 见 `_work/step1_run1_snapshot.json`、`step2_run2_snapshot.json`）：

| 文件 | Run1 md5 | Run2 md5 | size |
|---|---|---|---|
| `fields.json` | `596379276c096786b4329c0b998f49e9` | `596379276c096786b4329c0b998f49e9` | 2594 |
| `文书.docx` | `c98151eb40bf81b12c4a201851490463` | `4e6b28a21f40f4f0832d6e7f1f5fa3cb` | 37200 |

两遍之后单元目录列实查仍恰 2 个文件（`fields.json`、`文书.docx`），无残留、无多余产物。

### 2.2 参照：同输入连跑两遍（协议完全镜像，同 outdir 覆盖复写）

执行器 `_work/oracle_control.py`（先清空 `_work/oracle-run1` 保证第一遍全新写入，两遍同一 outdir，每遍后快照留存 `_work/oracle-run2/`）：

```bash
python tests/ab/ab5-determinism-layout-selfeval/arm-a/rep1/_work/oracle_control.py
# run1 exit=0, run2 exit=0（命令均为：
#   python oracle/oracle.py --template 会议通知 --data oracle/inputs/会议通知/case1.json --outdir <_work/oracle-run1>）
```

（`_work/step3_oracle_control.json`）

| 文件 | Run1 md5 | Run2 md5 | size |
|---|---|---|---|
| `fields.json` | `ed8d897801fdc52fecce6ce9a2119828` | `ed8d897801fdc52fecce6ce9a2119828` | 2822 |
| `文书.docx` | `7a4aaba7577ce17c02f4b8ce7c4b2b85` | `3125cb943fb84e406752cca57c021f19` | 37318 |

### 2.3 确定性评测与终态闭环

```bash
python eval/runner.py package/out oracle/out   # EXIT=0（两遍：EXIT_PASS1=0 / EXIT_PASS2=0，输出逐字节一致）
python oracle/verify.py                        # PASS=8 FAIL=0, exit 0（参照基线完好）
# 收尾原子重跑（一 条命令内背靠背执行，消除并发干扰窗口）：gen_doc 两遍（各 EXIT=0）
#   + python eval/runner.py package/out oracle/out（EXIT=0, ok=true, 100.0% 66/66）
```

## 3. D1 逐条比对结果（`_work/determinism_compare.py` → `_work/step4_determinism_report.json`）

### 3.1 被测 run1 vs run2（同 outdir 覆盖复写）

| D1 条目 | 实测 | 判定 |
|---|---|---|
| fields.json 除 outputs 逐字节一致 | raw bytes 相等（md5 同表）；剔除 `outputs` 重序列化后亦相等 | **✓**（本场景两遍同 outdir，`outputs` 路径相同，故连 raw 都逐字节一致，强于 D1 要求） |
| docx 段落文本/对齐/缩进/字体/行距/页边距一致 | 语义签名全等：12 段，逐段 text/`w:jc`/`w:firstLineChars`/`w:firstLine`/`w:line=560`+`lineRule=exact`/`w:before`/`w:after`/右缩进/首 run（eastAsia/ascii/hAnsi/`w:sz`）逐属性相等；pgSz `11906×16838`、pgMar `2098/1984/1587/1474`（twips）相等 | **✓** |
| zip 条目时间戳允许不同 | zip 条目名表相等；**17 个条目解压内容 md5 全部一致**（内容级逐字节相同）；17 个条目 DOS 时间戳不同（如 `[Content_Types].xml`：`07:11:16` vs `07:11:32`）——恰为 D1 明文豁免项；docx 整文件 md5 不同、size 相同（37200） | **✓**（差异全部落在允许集内） |

### 3.2 参照 oracle run1 vs run2（对照）

与被测**逐项同构**：fields raw 逐字节一致（md5 恒 `ed8d8978…`）；docx 语义签名全等、pgSz/pgMar 相等；zip 17 条目内容 md5 全一致、仅时间戳不同。→ **对照成立**：被测的确定性强度与参照完全同级，双方都只差 D1 允许的 zip 时间戳。

### 3.3 静态佐证（V8 无时间源）

`grep -nE "import (time|random|uuid|datetime)|time\(|random\(|uuid|datetime|now\(" package/scripts/gen_doc.py oracle/oracle.py` → **0 命中**（exit 1）。两实现均只从输入数据推导内容（被测写台账在 `package/scripts/gen_doc.py:363-364`，参照在 `oracle/oracle.py:393-396`，均无时间/随机注入点）。

## 4. `eval/runner.py` 确定性自评

- `python eval/runner.py package/out oracle/out` → **`"ok": true`，exit 0**；checks 共 68 项，失败 0。
- **runner 自身确定性**：连跑两遍 stdout **逐字节一致**（`step5_runner_pass1.json` ≡ `step5_runner_pass2.json`）。
- 总判 `field_fill_agreement_ge_90pct`：**字段填充一致率 100.0%（66/66，阈值 90%）**。
- 本 ask 单元 `会议通知/case1` 的 8 项单元检查（`docx_opens_safe` / `layout_title_centered` / `layout_salutation_flush_left` / `layout_body_indent` / `layout_signature_right` / `fields_json_self_consistent` / `fields_match_docx` / `boundary_reported`）**全部 pass**。
- 范围声明：runner 按契约评 8 单元。`package/out` 下其余 7 单元为同日早前轮次的既有产物（mtime 04:49–05:52），本 ask 未重新生成，仅随 runner 一并复检通过；`会议通知/case1` 为本 ask 按协议覆盖重生成（终态 07:20:18）。参照基线 `oracle/out` 完好（`python oracle/verify.py` → PASS=8 FAIL=0，exit 0）。

## 5. 跨实现 layout 对照（被测终态 vs `oracle/out` 参照，同输入，arm 名中 layout-selfeval 项）

- 页面（V1）：pgSz/pgMar **逐 twips 相等**（A4 `11906×16838`；版心 `2098/1984/1587/1474`）。
- 逐段（12/12 段，`step4_determinism_report.json → cross_impl_layout_vs_oracle_out.paragraphs`）：除标题段外**全部版式属性相等**——称谓 `各部门、各项目组：` 顶格（`firstLineChars` 缺失）+ 560/exact 行距；正文 7 段 `firstLineChars=200` + `w:line=560/lineRule=exact`；节头 `一、会议要求` 黑体缩进两字符；条目 `1．2．` 全角点；落款两行 `jc=right` + 右缩进 640 twips=32pt（V5 ≈32pt 达标）。
- 唯一属性差异：**标题段行距**——被测未设（Word 默认单倍），参照 `560/exact`。V2 只冻结"居中/黑体/22pt/文本= title"，V4 的 28 磅限定正文；此差异属冻结口径外的实现自由区（ab1 已录为 D1 号发现），**不影响 D1 与 runner 判定**（runner 8 项单元检查全过）。
- 正文措辞差异（被测按 `references/会议通知.md` 用 `会议时间：` 等标签行，参照用 `一、~五、`编号行）同为 ab1 已录自由区差异，与确定性无关。

## 6. 过程异常与处置（如实记录）

07:13:59（本 ask 的 run2 07:11:32 之后、收尾比对之前），在盘单元被**第三方进程重写**（`文书.docx` md5 变为 `d636c10b…`，fields.json md5 不变；本机 `tasklist` 实查有多个 ZCode.exe/python.exe 并存，`package/out` 为共享路径，判断为并行会话的同类任务复写）。处置：

1. 实查该在盘状态与我的 run1/run2 快照**语义签名全等、fields 逐字节相等**——恰为 D1 预言的收敛行为，不构成反例；
2. 以**一条命令内背靠背**重跑完整协议（gen_doc ×2 覆盖复写 → runner → 终态哈希留档 `_work/step7_final_state.json`）闭环：终态 fields raw ≡ run1/run2（md5 `59637927…`）、docx 语义签名 ≡ run1/run2、runner exit 0（ok=true，100.0% 66/66）。

→ 异常未污染任何一条结论；同时暴露一条**交付环境风险**：`package/out` 为共享产物根，多会话并行时可能互相复写，分发/验收应在独占窗口或独立 clone 中进行（本报告的 `_work/` 快照链不受影响）。

## 7. 判定

**被测满足 spec D1（可分发资产的确定性交付要求）**：

1. 同输入连跑两遍到同一 outdir（覆盖复写）：`fields.json` 逐字节一致（本场景连 `outputs` 都一致，强于 D1 口径）；`文书.docx` 段落文本/对齐/缩进/字体/字号/行距/页边距解析后全等；zip 17 条目解压内容逐字节一致，唯时间戳不同——**全部差异落在 D1 明文允许集内**；
2. 与参照 oracle 同协议双跑对照：两者确定性 profile 完全同级（fields 逐字节、docx 内容级、唯 zip 时间戳），被测不弱于参照；
3. `eval/runner.py package/out oracle/out` exit 0（68/68 checks，66/66 字段一致率 100%），runner 双跑输出逐字节一致；
4. 静态佐证两实现均无时间/随机源（V8）；产物文件集恰 2 个、无覆盖残留。

保留意见：docx **整文件 md5** 因 zip 时间戳逐次不同（D1 明示"不做逐字节要求"）；若某交付场景额外要求"整文件逐字节一致"，则需生成端固定 zip 时间戳——此口径未被 spec/contract 要求，仅作提示。

## 8. 证据与产物清单

- 本报告：`tests/ab/ab5-determinism-layout-selfeval/arm-a/rep1/OUT.md`
- 执行/比对脚本：`_work/oracle_control.py`（oracle 对照协议）、`_work/determinism_compare.py`（D1 比对器：fields 逐字节/除 outputs、docx 语义签名、zip 条目内容 vs 时间戳、跨实现 layout、§10 一致率）
- 机读留档：`_work/step0_prestore.json`（前置状态）、`step1_run1_snapshot.json`、`step2_run2_snapshot.json`（被测两遍快照）、`step3_oracle_control.json`（oracle 两遍）、`step4_determinism_report.json`（全部比对明细）、`step5_runner_pass1.json`/`step5_runner_pass2.json`（runner 双跑）、`step6_runner_final.json` + `step7_final_state.json`（原子闭环终态）
- 快照副本：`_work/run1/`、`_work/run2/`（被测）、`_work/oracle-run1/`+`_work/oracle-run2/`（oracle 两遍），均不含对 `oracle/out` 基线的任何写操作
- 最终在盘产物：`package/out/会议通知/case1/{文书.docx, fields.json}`（07:20:18 终态，md5 `60afc8ff…`/`59637927…`）
