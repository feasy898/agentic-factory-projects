# OUT.md — AB5 确定性与交付自评 A/B 对照报告（arm-a / rep2）

- 任务（golden.json `ab5-determinism-layout-selfeval`）：让被测技能以 `package/scripts/gen_doc.py` 为**唯一入口**，对 `oracle/inputs/会议通知/case1.json` 同一输入**连续运行两遍到同一 outdir**（`package/out/会议通知/case1`，覆盖复写），再运行 `python eval/runner.py package/out oracle/out` 做确定性评测；与参照实现（同输入连跑两遍）对照产物确定性，判定**被测是否满足可分发资产的确定性交付要求（spec D1）**。
- 日期：2026-09-30（全部命令本次实跑）
- 环境：Windows x64 / Python 3.12.10 / python-docx 1.2.0（`python --version`、`python -c "import docx; print(docx.__version__)"` 实查，与 spec.md 附录 A 实测环境一致）
- 工作目录：`skillfactory/v3/assets/office-templates/`
- 依据文件（本次完整读过）：`package/SKILL.md`、`package/references/{周报,请示函,会议通知,工作总结}.md`、`spec.md`、`contract.md`、`package/scripts/gen_doc.py`、`eval/runner.py`、`eval/golden.json`、`oracle/{oracle.py,verify.py,README.md}`、`oracle/inputs/会议通知/case1.json`

---

## 0. 结论（先行）

**判定：被测满足可分发资产的确定性交付要求（spec D1）——PASS。**

| 判据（spec D1 / rubric） | 结果 | 证据 |
|---|---|---|
| 同输入连跑两遍，`fields.json`（除 outputs 键外）逐字节一致 | **成立** | 两遍 md5 全等 `596379276c096786b4329c0b998f49e9`（含 outputs 的全文件亦逐字节相等——同一 outdir 使 outputs 路径相同）；去 outputs 规范化哈希亦相等 |
| 同输入连跑两遍，docx 解析后段落文本/对齐/缩进/字体/行距/页边距完全一致 | **成立** | 语义签名 SHA-256 两遍全等 `f1010146…02bd1`（页面几何 + 12 段 × 文本/对齐/firstLineChars/右缩进/行距+lineRule/首 run 字体字号粗体）；仅 zip 条目时间戳不同（D1 明文允许） |
| 参照实现同输入连跑两遍（对照组）确定性 | **成立** | oracle 两遍 fields md5 全等 `02e344be…`；docx 语义签名 SHA-256 全等 `3e959317…`；仅 zip 时间戳不同 |
| runner 确定性评测 | **pass** | `python eval/runner.py package/out oracle/out` → `ok=true`、exit 0、68 项检查全过、字段一致率 100.0%（66/66）；连跑两遍输出逐字节相同（`cmp` 相等） |
| runner 自校验红绿双向 | **成立** | 绿 `oracle/out oracle/out` → exit 0 全过；红 `<空目录> oracle/out` → exit 1、`units_found` 失败 |
| package 三件套 + 入口可用 | **成立** | 三文件齐全；`py_compile` 通过；contract §2 命令行两遍实跑均 exit 0 |

补充（非 D1 判据）：被测与参照的 docx **不是同一份文档**（成文结构差异位于 spec 未冻结的自由区，详见 §5），但两者的 fields 台账去 `outputs` 后**逐字节相等**，且被测两遍内部语义签名与参照两遍内部语义签名各自全等——确定性维度上被测与参照行为同级。

---

## 1. 执行记录（命令原样，exit 实测）

### 1.1 被测技能（唯一入口 `package/scripts/gen_doc.py`，同一 outdir 覆盖复写两遍）

```bash
# Run 1（覆盖既有单元，该单元此前为同日 05:04 旧产物，md5 先行留底）
python package/scripts/gen_doc.py --template 会议通知 --data oracle/inputs/会议通知/case1.json --outdir package/out/会议通知/case1
# → exit=0；stdout：已生成：package\out\会议通知\case1\文书.docx（模板=会议通知，标题=关于召开三季度质量评审会的通知，字段 filled/total=11/11，必填缺失=无，模板外键=无）

# Run 2（同一命令，覆盖复写）
python package/scripts/gen_doc.py --template 会议通知 --data oracle/inputs/会议通知/case1.json --outdir package/out/会议通知/case1
# → exit=0；stdout 与 Run 1 逐字相同
```

覆盖复写实证：单元目录 mtime 由 05:04 变为 07:11（run1）/07:13:59（run2）；目录内**恰 2 个文件** `文书.docx` + `fields.json`（`ls -la` 实查）。

两遍产物快照（供比对，不影响 `package/out` 交付位）：

| 快照 | `fields.json` md5 | `文书.docx` md5 |
|---|---|---|
| 覆写前旧产物（留底） | `596379276c096786b4329c0b998f49e9` | `8b409d27c4a6bfcf547573891cf8283b` |
| `_work/run1/会议通知/case1` | `596379276c096786b4329c0b998f49e9` | `c98151eb40bf81b12c4a201851490463` |
| `_work/run2/会议通知/case1` | `596379276c096786b4329c0b998f49e9` | `67f2e7972384ee24c1fcce13716ac550` |

### 1.2 参照实现（对照组，oracle 同输入连跑两遍到同一 outdir 覆盖复写）

```bash
python oracle/oracle.py --template 会议通知 --data oracle/inputs/会议通知/case1.json --outdir tests/ab/ab5-determinism-layout-selfeval/arm-a/rep2/_work/oracle/会议通知/case1
# Run 1 → exit=0；Run 2（同一命令覆盖）→ exit=0；两遍 stdout 逐字相同（OK template=会议通知 … filled=11 missing=0 missing_required=0）
```

对照组输出落在 `_work/oracle`（未触碰 `oracle/out` 基线），两遍快照于 `_work/oracle-run{1,2}/`：

| 快照 | `fields.json` md5 | `文书.docx` md5 |
|---|---|---|
| `_work/oracle-run1/会议通知/case1` | `02e344be79577433f0c509429add93d2` | `7d221022e53c43d8451299c96037f0c0` |
| `_work/oracle-run2/会议通知/case1` | `02e344be79577433f0c509429add93d2` | `01872b7c7c461743bb8740dd1e753cca` |

### 1.3 确定性评测与自校验

```bash
python eval/runner.py package/out oracle/out          # run1：ok=true，exit=0
python eval/runner.py package/out oracle/out          # run2：ok=true，exit=0；与 run1 输出 cmp 逐字节相等
python eval/runner.py oracle/out oracle/out           # 绿：ok=true，exit=0（68 项检查全过）
python eval/runner.py <_work/emptydir> oracle/out     # 红：ok=false，exit=1
```

---

## 2. 确定性比对（D1 核心，脚本 `_work/det_compare.py`）

比对维度：fields.json 原始字节；去 `outputs` 键后的规范化 JSON（`ensure_ascii=false, indent=2`）；
docx 语义签名 = 页面几何（宽/高/四边距 cm）+ 每段 {text, 对齐, firstLineChars, 右缩进 twips,
w:line + lineRule, 首 run 的 eastAsia/ascii/hAnsi/字号/粗体}；zip 条目名表与时间戳。

### 2.1 被测：run1 vs run2（`_work/det_tested_run1_vs_run2.json`）

| 维度 | 结果 |
|---|---|
| `fields.json` 原始字节 | **逐字节一致**（sha256 全等；本例同一 outdir 连 `outputs` 键亦同路径） |
| `fields.json` 去 `outputs` | **逐字节一致** |
| docx 语义签名（12 段 + 页面几何） | **全等**：两侧 SHA-256 = `f101014658b30c93ddb9bf94c53d1b5815c4ee8dfee44d86ca8f4ead44a02bd1` |
| zip 条目名表 | 一致 |
| zip 条目时间戳 | 不同（D1 明文允许）；故 docx 原始字节 md5 不同（`c98151eb…` vs `67f2e797…`） |

签名内容抽查（run2，与 run1 全等）：页面 21.001×29.7 cm、边距 上3.701/下3.5/左2.799/右2.6；段序 = 标题（居中/黑体/22pt）→ 称谓 `各部门、各项目组：`（顶格）→ 会议时间/地点/参会人员/议题 4 个标签行（firstLineChars=200、仿宋/TNR/16pt、w:line=560 exact）→ 节头 `一、会议要求`（黑体）→ 条目 `1．/2．` → 联系行 → 落款两行（RIGHT、右缩进 640 twips=32pt）。

### 2.2 对照组：oracle run1 vs run2（`_work/det_oracle_run1_vs_run2.json`）

| 维度 | 结果 |
|---|---|
| `fields.json` 原始字节 | **逐字节一致**（md5 `02e344be…` 两遍全等） |
| docx 语义签名 | **全等**：两侧 SHA-256 = `3e959317ab914492d167b3d046c491881077e8667bdb6820147b867d7210ee88` |
| zip 时间戳 / docx 原始字节 | 不同（同为 zip 时间戳维度，D1 允许） |

→ **A/B 同判**：两臂各自"同输入连跑两遍"内部确定性行为一致；被测的确定性不弱于参照，D1 成立。

### 2.3 交叉对照（信息性，非 D1 判据；`_work/det_tested_vs_oracle_baseline.json`）

- fields 台账：原始字节不同**仅因 `outputs` 路径**（`package\out\…` vs `oracle\out\…`，spec §6 S4 明示"路径写法随实现，评测不比较此键"）；去 `outputs` 后**逐字节相等**。
- docx 语义签名不同（`f1010146…` vs `3e959317…`）：两者均 12 段、页面几何完全相等，差异全部在 spec V1–V8 未冻结的成文自由区（被测按 `references/会议通知.md` 结构：标签行不编号 + `一、会议要求` 独立小节；oracle：`经研究…`/`特此通知。` 套语 + `一、~五、` 编号事项行）——与 ab1 报告发现 D4 一致。D1 约束的是**同实现同输入的可复现性**（§2.1/§2.2 已证），不要求跨实现 docx 同文；runner 六类冻结检查对被测产物全过（§3）。

---

## 3. runner 确定性评测（`python eval/runner.py package/out oracle/out`）

- **run1**：`"ok": true`，exit 0，68 项检查（3 项全局 + 8 单元 × 8 项 + 1 项总判）**全部 pass**；
  总判 `field_fill_agreement_ge_90pct` = **字段填充一致率 100.0%（66/66，阈值 90%）**。
- **run2**：输出与 run1 **逐字节相等**（`cmp` 无差异）→ runner 自述"无时间/随机源"实测成立。
- 本 ask 重生成的 `会议通知/case1` 单元 8 项检查明细：`docx_opens_safe`（DOCTYPE/ENTITY 扫描通过）、
  `layout_title_centered`（`关于召开三季度质量评审会的通知` 居中/黑体/22pt/与 title 相等）、
  `layout_salutation_flush_left`（`各部门、各项目组：` 顶格全角冒号）、`layout_body_indent`
  （firstLineChars=200 段 8 个，含仿宋/TNR/16pt/28 磅 exact）、`layout_signature_right`
  （`2026年9月28日` 右对齐 + 32pt）、`fields_json_self_consistent`（11 字段与字段表一致）、
  `fields_match_docx`、`boundary_reported`（无缺失）——全 pass。
- **范围声明**：runner 按契约评测 8 单元；仅 `会议通知/case1` 为本 ask 双跑重生成，其余 7 单元为同日更早轮次的既有产物，本次未重生成、仅随 runner 复检并全部通过（与 ab1 rep1 报告的范围声明同口径）。

### 3.1 runner 自校验红绿双向（rubric 第 4 条）

| 向 | 命令 | 实测 |
|---|---|---|
| 绿 | `python eval/runner.py oracle/out oracle/out` | `ok=true`，exit 0，68 项全过，一致率 100.0%（66/66） |
| 红 | `python eval/runner.py tests/ab/ab5-determinism-layout-selfeval/arm-a/rep2/_work/emptydir oracle/out` | `ok=false`，exit 1；`units_found` **失败**（缺全部 8 期望单元）；`field_fill_agreement_ge_90pct` 0.0%（0/66）失败（红向预期连带） |

---

## 4. 可分发资产交付检查（rubric 第 5 条 + V8）

- **三件套齐全**：`package/SKILL.md`（9911 B）、`package/scripts/gen_doc.py`（17286 B）、
  `package/requirements.txt`（内容 `python-docx>=1.1`，17 B）。
- **入口可编译**：`python -m py_compile package/scripts/gen_doc.py` → OK（编译缓存已清理，不留残渣）。
- **入口按 contract §2 直接运行成功**：即 §1.1 两条命令，exit 0 × 2，stdout 单行人读摘要。
- **V8 无时间源**：`grep -n -E "import (time|random|datetime|uuid)|from (time|random|datetime|uuid)|now\(|today\(|randint|random\(" package/scripts/gen_doc.py` → **零命中**（grep exit=1）；参照 `oracle/oracle.py` 同审计零命中。两臂产物确定性来源一致：内容全部由输入 JSON 推导。

---

## 5. 附加发现（不影响判定，如实记录）

- **F1（run 期间基线文件被并行会话覆写）**：`oracle/out/会议通知/case1/文书.docx` 于本次 run 期间
  （07:15:16）被**非本会话命令**改写（本会话全部写操作仅指向 `package/out` 与 `_work/`；mtime 实查；
  疑为同一 workflow 并行臂会话复跑 oracle 所致）。核验：改写后 `verify.py` PASS=8 FAIL=0；其 docx
  语义签名 = `3e959317…`，与本次全新 oracle 双跑全等；`fields.json` md5（`2b93c52f…`）自 run 前留底
  起全程未变。改写仅落在 D1 允许的 zip 时间戳维度，**本报告全部判定不受影响**（被测确定性结论基于
  `_work` 双跑快照，runner 判定基于未变的 fields 与语义全等的 docx）。
- **F2（stdout 亦确定）**：被测两遍、参照两遍的 stdout 摘要均逐字相同——可分发资产的"可复现"不限于产物文件。
- **F3（嵌套无涉）**：`fields.json` 顶层恰 7 键、`summary` 恰 6 键、filled/missing 计数自洽（11/0/11），
  与 spec §6 S1–S3 一致；`title` 与文书首段逐字相等（V2/S1 双重成立）。

---

## 6. 判定

**被测（package/scripts/gen_doc.py 唯一入口）满足可分发资产的确定性交付要求（spec D1）**：

1. 同输入连跑两遍到同一 outdir（覆盖复写）：`fields.json` 除 outputs 外逐字节一致（本例全文件亦逐字节一致）；`文书.docx` 解析后的段落文本/对齐/缩进/字体/行距/页边距经语义签名全等验证一致，唯一差异为 zip 条目时间戳（D1 明文豁免维度）；
2. 与参照实现对照：oracle 同流程双跑内部确定性同级成立，A/B 同判，无被测独有不确定性；
3. `python eval/runner.py package/out oracle/out` → `ok=true`、exit 0、68 项检查全过、一致率 100.0%，且 runner 连跑两遍输出逐字节相同；红绿自校验双向成立；
4. 交付布局正确：`package/out/会议通知/case1` 恰含两产物、相对名与 `oracle/out/会议通知/case1` 配对；package 三件套齐全、入口可 py_compile 并按 contract §2 实跑成功；无当前时间/随机源（V8）。

**保留意见**：被测 docx 与参照 docx 不是同一份文档（成文结构自由区差异，§2.3）；若交付方额外要求"跨实现逐段同文"，需另行对齐——该口径未被 spec/contract/golden 任何冻结文件要求，且与 D1 无涉。

---

## 7. 证据与产物清单

- 本报告：`tests/ab/ab5-determinism-layout-selfeval/arm-a/rep2/OUT.md`
- 比对脚本：`_work/det_compare.py`（fields 字节/去 outputs/docx 语义签名/zip 表提取与 diff）
- 机读结果：`_work/det_tested_run1_vs_run2.json`、`_work/det_oracle_run1_vs_run2.json`、
  `_work/det_tested_vs_oracle_baseline.json`、`_work/det_oracle_baseline_vs_refresh.json`（F1 核验）、
  `_work/runner_pkg_vs_oracle_run{1,2}.json`（两次逐字节相等）、`_work/runner_selfcheck_green.json`、
  `_work/runner_selfcheck_red.json`、`_work/tested_run{1,2}.stdout.txt`
- 双跑快照：`_work/run{1,2}/会议通知/case1/`（被测）、`_work/oracle-run{1,2}/会议通知/case1/`（参照）、
  `_work/oracle/`（参照运行 outdir）、`_work/emptydir/`（红检空目录）
- 交付位产物（本次覆盖复写后）：`package/out/会议通知/case1/{文书.docx, fields.json}`；
  `oracle/out` 基线未由本会话改写（`verify.py` PASS=8 FAIL=0 复核）
