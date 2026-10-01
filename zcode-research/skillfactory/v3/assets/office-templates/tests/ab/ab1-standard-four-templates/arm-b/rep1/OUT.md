# AB1 标准全量生成 A/B 对照报告 — arm-b / rep1

- **日期**：2026-09-30（本机 windev-01，Python 3.12.10 + python-docx 1.2.0）
- **被测方（A）**：office-templates 技能包生成器 `package/scripts/gen_doc.py`
- **参照方/oracle（B）**：`oracle/oracle.py` 及其既有基线产物 `oracle/out/`
- **输入**：`oracle/inputs/{周报,请示函,会议通知,工作总结}/case1.json`（四类各 1 份，字段齐全——运行时双方均报 `filled=all, missing=0, missing_required=0`，实证齐全）
- **产物落位**：A → `package/out/<模板>/case1/`（文书.docx + fields.json）；B 基线 → `oracle/out/<模板>/case1/`，另在沙箱重跑一份用于可复现性核验
- **判定问题**：被测产物可否替代参照交付

## 0. 口径与限制声明（必读）

- 任务限制「禁止读取 skillfactory/ 任何文件」按如下口径执行：**未读取任何 skillfactory 源码/规范/参考文件的内容**（contract.md、spec.md、SKILL.md、gen_doc.py、oracle.py、verify.py、references/\*、README 均未读入）。CLI 接口未读 contract §2 原文，仅凭任务书给定的 `--template/--data/--outdir` 并以执行 `--help` 实证（两个生成器 usage 完全一致，exit=0）。
- 任务同时强制要求「与 oracle/out 逐一对照版式与字段台账」，故对**产物文件**（docx/fields.json）采用**程序化比对**（sha256、zip 结构、XML 规范化解析、语义结构 diff、全文针脚检索）：比对工具的判定输出进入本报告，文件原文未整篇读入对话。contract §2 原文未核（受限未读），接口一致性以 `--help` 实测为准。
- 运行前对既有 `package/out/` 全量快照备份至沙箱 `D:\workspace\zcode研究\_ab1_armb_rep1_scratch\backup_package_out\`；本次重生成对既有 7 份 case1 产物为**内容无变化的等价覆盖**（见 §5），并补齐了原本缺失的 `工作总结/case1`。

## 1. 执行的命令与退出码（contract §2 CLI，实测）

```bash
# 参照方（oracle），fresh 重跑入沙箱：
python oracle/oracle.py --template {周报|请示函|会议通知|工作总结} \
  --data oracle/inputs/<模板>/case1.json --outdir <沙箱>/oracle-fresh/<模板>/case1
# → 4/4 exit=0；输出行：OK … filled=7/8/11/7 missing=0 missing_required=0

# 被测方，按任务书落位 package/out：
python package/scripts/gen_doc.py --template {同上} \
  --data oracle/inputs/<模板>/case1.json --outdir package/out/<模板>/case1
# → 4/4 exit=0；输出行：已生成…（字段 filled/total=7/7、8/8、11/11、7/7，必填缺失=无，模板外键=无）
```

两边 CLI usage 逐项一致（`--template {周报,请示函,会议通知,工作总结} --data DATA --outdir OUTDIR`）。

## 2. 参照基线可复现性核验（先决检查）

沙箱 fresh 重跑 vs 既有 `oracle/out/`，四模板逐一比对：**16/16 个 XML part 规范化后全部一致**（唯一 sha 差异来自 docx core.xml 内嵌时间戳，规范化后消除）；正文语义结构（段落/表格/字体/字号/对齐/页设置）**全部 IDENTICAL**；fields.json 仅 `$.outputs.docx / $.outputs.fields_json` 两个自引用路径随输出目录不同，其余全同。
**结论：oracle/out 是可信、可复现的参照基线。**

## 3. 字段台账对照（fields.json）— 4/4 完全等价 ✅

四模板 A vs B 深度 diff：**除 `$.outputs.*` 两个路径字段（输出位置固有差异）外 0 差异**。台账要点（两侧一致）：

| 模板 | 字段数(filled/total) | 字段清单 | missing |
|---|---|---|---|
| 周报 | 7/7 | 部门、填报人、周期、本周工作内容、下周工作计划、问题与需协调事项、报送日期 | [] |
| 请示函 | 8/8 | 请示事由、主送机关、请示缘由、请示事项、请示单位、联系人、联系电话、成文日期 | [] |
| 会议通知 | 11/11 | 会议名称、召开单位、主送对象、会议时间、会议地点、参会人员、会议议题、会议要求、联系人、联系电话、发文日期 | [] |
| 工作总结 | 7/7 | 总结主体、总结时段、工作回顾、主要成绩、存在问题、下一步工作打算、成文日期 | [] |

required 标记、kind（text/list）、status、value 全部一致。**台账层面被测产物可无损替代参照。**

## 4. 版式对照（文书.docx）— 4/4 非逐字节等价；内容差异 3 份

zip 均 17 个 part、集合一致；**sectPr 页面设置（4/4）规范化一致**。差异两类：

### 4.1 系统性版式差异（四模板共有，可见）

| # | 差异 | A（被测） | B（参照） |
|---|---|---|---|
| L1 | styles.xml docDefaults | 缺少文档默认字体块 | 含 `rFonts ascii/hAnsi=Times New Roman, eastAsia=仿宋; sz=32`(三号16pt)——**四模板唯一 styles.xml 差异** |
| L2 | 正文首行缩进 | 正文段无 `firstLine=640`（顶格） | 正文段一律首行缩进 2 字符 |
| L3 | 标题行距 | 未设置 | `spacing line=560 lineRule=exact`（固定 28pt） |
| L4 | 标题/小标题西文字体 | ascii/hAnsi=`黑体` | `Times New Roman`（含拉丁字符处可见，如请示函标题 "GPU"） |
| L5 | run 序列化 | 省略 bold 属性 | 显式 `b w:val="0"`（语义等价：均不加粗，**不可见**） |

### 4.2 各模板内容/结构差异（全文针脚检索 + 块级 diff 实证）

| 模板 | 块数 A/B | 内容差异（A 相对 B） | 定性 |
|---|---|---|---|
| 工作总结 | 16/16 | **无内容差异**，仅 §4.1 版式差异 | 内容等价 ✅ |
| 周报 | 12/12 | 信息行漏排 `部门：研发部`（in-A=False / in-B=True）——**台账中有此字段值，docx 未渲染**；且该行 A 首行缩进而 B 居中 | 字段渲染缺失 ❌ |
| 请示函 | 8/**10** | 缺 `现就有关事项请示如下：`（过渡句）与 `妥否，请批示。`（请示结语）——公文要素性固定文案缺失（检索均 in-A=False / in-B=True） | 结构缺失 ❌ |
| 会议通知 | 13/13 | 缺引言 `经研究，决定召开…通知如下：`、结语 `特此通知。`；五项事项未按 `一、…五、` 统一编号（A 将时间/地点/人员/议题排为无编号条目行，另设「一、会议要求」+ 1．2．子目）——结构与参照不同 | 结构偏离 ❌ |

**docx sha256（前 16 位）**：A=周报 `db05b138be924afe`、请示函 `02b170b5799cc7ce`、会议通知 `b4e3f9603585ff78`、工作总结 `1120fcfe4835c3ad`；B=`f0d11dc26c79961f` / `1005b9a471f468bd` / `5daf9a2bc4c68783` / `081bfb2631584a38`。四对均非逐字节相同（时间戳 + 上述内容/版式差异）。

## 5. 交叉验证与确定性

- **oracle 自带验收器**：`python oracle/verify.py package/out` → **PASS 8/8（exit=0）**；`oracle/out` 同样 PASS 8/8。注：verify.py 不接受单 case 目录（传 case1 路径或 `--help` 均 FAIL「未找到任何产物目录」exit=1），需传 `out` 父目录。被测产物**通过参照方自设验收门槛**。
- **被测方确定性**：重生成 vs 运行前备份（周报/请示函/会议通知 3 份既有 case1）：16/16 XML part 规范化一致、语义结构 IDENTICAL、fields.json 逐字节相同 → 覆盖为等价操作；`工作总结/case1` 为本次新补齐（备份中不存在）。

## 6. 判定结论：**被测产物不能无条件整体替代参照交付（有条件部分替代）**

1. **fields.json 台账：可替代**（4/4 除输出路径外完全等价）。
2. **文书.docx：整体不可作等价替代**。四模板均非逐字节/逐版式一致；其中仅**工作总结**内容完全等价（可在接受 §4.1 排版偏差——正文无首行缩进、无固定标题行距、docDefaults 字体块缺失——的前提下替代）；**周报**（docx 漏渲染「部门」字段值）、**请示函**（缺过渡句与「妥否，请批示。」）、**会议通知**（缺引言/结语/统一编号）存在**内容级缺失**，直接交付将劣于参照。
3. 缓解事实：被测 8 份产物全部通过 oracle 自带 verify.py 验收（PASS 8/8）——若验收标准即 verify.py 门槛，则可替代；若验收标准为「与参照逐项一致」，则不可。
4. 修复指向（供 arm 汇总）：正文首行缩进 2 字符、标题固定行距、docDefaults 字体块（Times New Roman/仿宋/三号）、周报信息行补「部门」、请示函补过渡句与结语、会议通知补引言/「特此通知。」/一至五统一编号。

## 7. 证据与工件索引

- 比对脚本（沙箱）：`D:\workspace\zcode研究\_ab1_armb_rep1_scratch\{abcompare.py, probe2.py}`
- oracle fresh 重跑产物：`…_ab1_armb_rep1_scratch\oracle-fresh\<模板>\case1\`
- 运行前 package/out 备份：`…_ab1_armb_rep1_scratch\backup_package_out\`
- 主要命令及输出已逐条收录于上文 §1/§2/§5；比对器原始输出（REPRO/AB/DETERMINISM 三组、四模板全文）见会话执行记录。
- 未做事项：未读取 contract.md/spec.md 及任何实现源码（受任务限制）；contract §2 原文一致性未核，仅以 `--help` 实证接口；docx 渲染级（打开 Word 目测）验证未执行，判定基于 OOXML 结构/语义层比对。
