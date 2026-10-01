# OUT.md — AB1 标准全量生成对照（arm-a / rep2）：被测 package vs 参照 oracle，四模板 case1

- 日期：2026-09-30（本机实跑，Windows x64 / Python 3.12.10 / python-docx 1.2.0，与 spec.md 附录 A 同环境）
- 资产根：`skillfactory/v3/assets/office-templates/`
- 任务：让被测技能（`package/scripts/gen_doc.py`）与参照实现（`oracle/oracle.py`）分别处理
  `oracle/inputs/` 下四类模板的 case1 输入（周报 / 请示函 / 会议通知 / 工作总结，各 1 份、字段全部齐全），
  以 contract §2 命令行（`--template/--data/--outdir`）生成 `文书.docx` + `fields.json` 到
  `package/out/<模板>/case1/`，与 `oracle/out/<模板>/case1/` 逐一对照**版式**与**字段台账**，
  判定被测产物可否替代参照交付。
- 依据材料（本 ask 先完整读过的）：`package/SKILL.md`（全文 133 行）、`package/references/{周报,请示函,会议通知,工作总结}.md`（全文）、
  `contract.md`、`spec.md`、`oracle/README.md`、`oracle/oracle.py`、`oracle/verify.py`、`eval/runner.py`、`package/scripts/gen_doc.py`、
  `oracle/inputs/*/case1.json`（4 份输入，字段齐全性已逐一核对：与 spec §3.3 字段表 7/8/11/7 项一一对应，无缺失、无模板外键）。

---

## 0. 结论速览

| 单元（case1） | fields.json 台账 | 文书.docx 正文文本 | 文书.docx 版式（spec §4 口径） | **可否替代参照交付** |
|---|---|---|---|---|
| 周报 | 剔除 outputs 后逐字节相等；7/7 字段一致 | **不一致**（基本信息行少"部门"、对齐不同） | runner 版式 4 项全过；A4/版心两侧完全相等 | **不可替代** |
| 请示函 | 同上；8/8 一致 | **不一致**（缺 2 句公文固定句，段数 7 vs 9） | 同上（全过） | **不可替代** |
| 会议通知 | 同上；11/11 一致 | **不一致**（无引语/结束语/编号体系不同，段数同为 12 但 9 段文本不同） | 同上（全过） | **不可替代** |
| 工作总结 | 同上；7/7 一致 | **逐字全等**（15 段全同） | 同上（全过）；残差仅 XML 属性级（渲染语义等价） | **可替代** |

- **总判定：不可（整体）替代参照交付。** 字段台账 4/4 单元与参照完全相等（33/33 字段，spec §10 一致率 100%）；
  但 4 份文书中 3 份（周报 / 请示函 / 会议通知）的正文段落构成与参照**实质性不同**——同一输入会交付出
  内容不同的两份 docx，最终收文方看到的是两份不一样的文书。仅"工作总结"模板可逐字替代。
- 官方 eval 口径对照（供参考）：`python eval/runner.py package/out oracle/out` → `"ok": true`、exit 0、
  字段填充一致率 100.0%（66/66，含 case2）——即**按 eval/contract 的验收标准是通过的**；runner 只查
  "版式要素存在性 + fields 台账一致率 ≥90%"，**不比较两版 docx 的段落文本**，因此通过≠可逐字替代。
  两个结论不矛盾，口径不同，均已如实列出。

---

## 1. 执行记录（全部命令与结果，均为本 ask 实跑）

### 1.1 环境

```
$ python --version                 → Python 3.12.10
$ python -c "import docx; print(docx.__version__)"   → 1.2.0
$ python -c "import sys; print(sys.executable)"      → C:\Program Files\Python312\python.exe
```
与 spec.md 头部"实测环境 Windows x64 / Python 3.12.10 / python-docx 1.2.0"一致。

### 1.2 被测技能生成（contract §2 命令行，逐条 exit=0）

```
$ python package/scripts/gen_doc.py --template 周报   --data oracle/inputs/周报/case1.json   --outdir package/out/周报/case1
已生成：package\out\周报\case1\文书.docx（模板=周报，标题=研发部工作周报，字段 filled/total=7/7，必填缺失=无，模板外键=无）  exit=0
$ python package/scripts/gen_doc.py --template 请示函 --data oracle/inputs/请示函/case1.json --outdir package/out/请示函/case1
已生成：…（标题=关于采购评测用 GPU 服务器的请示，filled/total=8/8）  exit=0
$ python package/scripts/gen_doc.py --template 会议通知 --data oracle/inputs/会议通知/case1.json --outdir package/out/会议通知/case1
已生成：…（标题=关于召开三季度质量评审会的通知，filled/total=11/11）  exit=0
$ python package/scripts/gen_doc.py --template 工作总结 --data oracle/inputs/工作总结/case1.json --outdir package/out/工作总结/case1
已生成：…（标题=评测技术部2026年第三季度工作总结，filled/total=7/7）  exit=0
```
4 个标题均与 spec §9 期望表一致；每单元恰产出 `文书.docx` + `fields.json` 两个文件。

### 1.3 参照实现同输入新跑（复核参照可复现性，避免拿陈旧参照比对）

```
$ python oracle/oracle.py --template <t> --data oracle/inputs/<t>/case1.json --outdir <scratch>/oracle-rerun/<t>/case1   （t=四模板，各 exit=0）
```
与预置 `oracle/out/<t>/case1/` 对照（对照脚本 PART 1）：
**4 个单元全部 docx 语义签名相等 + fields.json 剔除 outputs 后逐字节相等（7/7、8/8、11/11、7/7）。**
即预置参照确为当前 `oracle/oracle.py` 的可复现产物，以下主对照以 `oracle/out` 为准成立。

### 1.4 附加检查

| 检查 | 命令 | 结果 |
|---|---|---|
| 官方评测 runner | `python eval/runner.py package/out oracle/out` | `"ok": true`，exit 0；8 单元全部 checks 通过；`field_fill_agreement_ge_90pct` = 100.0%（66/66） |
| 参照自校验 | `python oracle/verify.py` | `共 8 份产物: PASS=8 FAIL=0`，exit 0（参照根完好） |
| 被测确定性（双跑） | 同输入连跑两次到两个临时目录，比对 zip | 条目名相等、**全部条目 CRC 相等**，仅 17 个条目的 zip 时间戳不同——符合 contract §3"zip 条目时间戳允许不同" |
| 被测重生成稳定性 | 重生成前后 sha256 快照 | 4 份 `fields.json` **前后逐字节相同**；`文书.docx` 字节变化（同上，zip 时间戳所致） |

注意（范围声明）：runner 检查 8 个单元；case2 的 4 个单元属早前运行遗留（mtime 04:49，先于本 ask），
本 ask 按任务范围只重新生成了 4 个 case1 单元（其 fields.json 前后哈希相同，证明历史 case1 产物亦出自同一实现）。
上述 runner 结论中 case2 部分不代表本 ask 的重跑结果。

---

## 2. 字段台账对照（fields.json）——4/4 全等

方法：对每单元 (1) 原始字节 unified-diff；(2) 剔除 `outputs` 键后按 `ensure_ascii=false, indent=2`
规范化再比字节（spec D1 口径）；(3) 按 spec §10 逐字段比 `status` 与 filled 时的 `value`。

原始字节 diff 结果（4 个单元完全同构，仅 `outputs` 内两条路径前缀不同，spec §4 S4 明示"路径写法随实现，评测不比较此键"）：

```diff
--- oracle/out/周报/case1/fields.json
+++ package/out/周报/case1/fields.json
-    "docx": "oracle\\out\\周报\\case1\\文书.docx",
-    "fields_json": "oracle\\out\\周报\\case1\\fields.json"
+    "docx": "package\\out\\周报\\case1\\文书.docx",
+    "fields_json": "package\\out\\周报\\case1\\fields.json"
```
（请示函 / 会议通知 / 工作总结 三个单元的 diff 各仅此 2 行路径替换，其余 0 差异。）

| 单元 | 剔除 outputs 后逐字节相等 | spec §10 字段一致 | title | summary | filled/missing 清单 |
|---|---|---|---|---|---|
| 周报/case1 | ✅ | 7/7 | 相等（研发部工作周报） | 相等（7,7,0,0,[],[]） | 相等 |
| 请示函/case1 | ✅ | 8/8 | 相等（关于采购评测用 GPU 服务器的请示） | 相等（8,8,0,0,[],[]） | 相等 |
| 会议通知/case1 | ✅ | 11/11 | 相等（关于召开三季度质量评审会的通知） | 相等（11,11,0,0,[],[]） | 相等 |
| 工作总结/case1 | ✅ | 7/7 | 相等（评测技术部2026年第三季度工作总结） | 相等（7,7,0,0,[],[]） | 相等 |

**合计 33/33 = 100%。字段台账层面，被测产物与参照完全可互换**（含 `fields` 明细的
`name/required/kind/status/value` 逐项、S1–S3 键集合与计数）。

---

## 3. 版式与正文对照（文书.docx）——逐段签名比对

方法：对照脚本（本 ask 实跑，脚本全文见 §5）对两侧 docx 先做 DOCTYPE/ENTITY 安全扫描（均通过），
再逐段提取签名：`text / 对齐 / w:ind@firstLineChars / w:ind@firstLine / 右缩进(pt) / 行距 / 段前段后 /
首 run 的 eastAsia·ascii·hAnsi·字号·加粗`，另比节属性（页面宽高 + 四边距）。页面/边距 **4 个单元全部相等**
（A4 21.0×29.7cm；上 3.7 / 下 3.5 / 左 2.8 / 右 2.6cm——V1 完全一致，无差异行输出）。

### 3.1 周报 case1（非空段 11 vs 11，差异段 10 —— 1 处实质 + 属性级残差）

**实质差异（段[1]，基本信息行）：**
```
package : 填报人：王小明　　周期：2026-09-21 至 2026-09-27        ← 正文体（firstLineChars=200），无"部门"
oracle  : 填报人：王小明　　部门：研发部　　周期：2026-09-21 至 2026-09-27   ← 居中对齐，含"部门"
```
- 根因（代码层）：`package/scripts/gen_doc.py:264-266` 用 `add_body`（左起、缩进）且文案不含部门；
  `oracle/oracle.py:177` 用 `align=CENTER` 且模板串含 `{dept}`。
- 有趣的口径分裂：`package/references/周报.md:11` 的公式是 `填报人：{填报人}　　周期：{周期}`（与 package 一致、
  与 oracle 不一致）。spec §4 V2/V3/V5 均未规定基本信息行的对齐与是否含部门，属于**参照与被测的
  未钉死口径分歧**——但既然判定标准是"与 oracle/out 逐一对照"，此处计为不一致。

**属性级残差（不影响 spec §4 达标，两侧均合规，但逐字节签名不同）：**
- 标题段（段[0]）：package 未设行距/段前段后（继承 Normal 默认），run 的 ascii/hAnsi=黑体；
  oracle 设 28 磅固定行距、段前段后 0，ascii/hAnsi=Times New Roman（`oracle/oracle.py:123-130` 对所有 run
  一律 `run.font.name = ASCII_FONT`；`package/scripts/gen_doc.py:207-211,189-193` 标题 run 名取 eastAsia 字体）。
  spec V2 只要求"居中、eastAsia=黑体、22pt"，两侧均满足。
- 正文/节头/条目各段：oracle 额外写 `w:firstLine=640`（twips 兜底，`oracle/oracle.py:133-141`），
  package 只写 `w:firstLineChars=200`（`gen_doc.py:196-204`）。两者语义同为"首行缩进两字符"，
  spec V4 判定键（firstLineChars=200）两侧一致；节头 run 的 ascii 字体同理（黑体 vs TNR，spec 只约束 eastAsia=黑体）。

### 3.2 请示函 case1（非空段 7 vs 9 —— 内容缺 2 段）

```
package : 关于…请示 / 公司总经理办公会： / 缘由段 / 事项段 / 联系人行 / 评测技术部 / 2026年9月28日
oracle  : 关于…请示 / 公司总经理办公会： / 缘由段 / 现就有关事项请示如下： / 事项段 / 妥否，请批示。 / 联系人行 / 评测技术部 / 2026年9月28日
```
- oracle 比被测多两句公文固定句：`现就有关事项请示如下：`（`oracle/oracle.py:204`）与 `妥否，请批示。`
  （`oracle/oracle.py:206`）；package 版（`gen_doc.py:276-282`）没有这两句，且 `package/references/请示函.md`
  的结构表（7 段）也未含它们——参照与被测（含其自述文档）在这两句上系统性分歧，spec 未钉死。
- 收文效果：参照版是"引据—事项—结语"完整请示公文体；被测版缺引据语与结语，**作为请示函交付内容不等价**。

### 3.3 会议通知 case1（非空段 12 vs 12，9 段不同 —— 结构体系不同）

```
package : 关于…通知 / 各部门、各项目组： / 会议时间：… / 会议地点：… / 参会人员：… / 会议议题：…
          / 一、会议要求（黑体节头） / 1．会前提交本部门质量简报 / 2．迟到 10 分钟以上按缺席处理
          / 联系人行 / 评测技术部 / 2026年9月28日
oracle  : 关于…通知 / 各部门、各项目组： / 经研究，决定召开三季度质量评审会。现将有关事项通知如下：
          / 一、会议时间：… / 二、会议地点：… / 三、参会人员：… / 四、会议议题：…
          / 五、会议要求：会前提交本部门质量简报；迟到 10 分钟以上按缺席处理。 / 特此通知。
          / 联系人行 / 评测技术部 / 2026年9月28日
```
- oracle：有引语句（`oracle/oracle.py:229`）与结束语 `特此通知。`（:237），事项用 `一、二、…五、` 连续编号，
  会议要求**行内合并**为一句（:234）；package：无引语/结束语，时间地点等不编号，会议要求为
  **独立小节 + `1．2．` 条目**（`gen_doc.py:285-295`）。`package/references/会议通知.md` 的结构表与 package 一致、
  与 oracle 不一致。两侧段数恰同（12），但 9 个段文本不同——**不是同一份通知**。

### 3.4 工作总结 case1（非空段 15 vs 15 —— 文本逐字全等）

- 15 个段落文本**逐字全等**（标题、四个节头、10 条目、落款两行）。差异仅 §3.1 所述属性级残差
  （标题行距/段前段后、`w:firstLine` twips 兜底、标题与节头 run 的 ascii/hAnsi 字体），
  全部落在 spec §4 未约束的属性上，版式语义（V1–V8 各判定键）两侧一致。**可替代。**

### 3.5 runner 官方版式口径（供参考）

`eval/runner.py` 对 4 个 case1 单元的 `layout_title_centered / layout_salutation_flush_left /
layout_body_indent / layout_signature_right / docx_opens_safe / fields_json_self_consistent /
fields_match_docx / boundary_reported` **全部 pass**（JSON 见 §1.4 命令输出）——即两侧在
spec §4 的 V2/V3/V4/V5 判定键上均达标；runner 不做两版段落文本对照，故发现不了 §3.1–§3.3 的内容分歧。

---

## 4. 判定

**按本 ask 的对照口径（与 oracle/out/<模板>/case1/ 逐一对照版式与字段台账，以"可替代参照交付"为标准）：**

1. **fields.json：4/4 单元可替代**——剔除 `outputs`（spec 明示不比较）后逐字节相等，33/33 字段一致。
2. **文书.docx：仅 工作总结 case1 可替代**（文本逐字全等、版式判定键全同）；**周报 / 请示函 / 会议通知
   case1 不可替代**——同一输入下与参照交付物的正文段落构成不同（周报基本信息行缺"部门"且对齐不同；
   请示函缺"现就有关事项请示如下：/妥否，请批示。"两句；会议通知缺引语与"特此通知。"、编号与会议要求
   组织方式不同），收文方拿到的是内容不同的文书。
3. **总判定：被测产物（arm-a 当前实现）不可整体替代参照交付**，替代阻塞点全在 docx 正文文案/结构层，
   不在字段台账层，也不在 GB/T 版式骨架层（V1 页面两侧字节级同参，V2–V5 判定键两侧均达标）。
4. 若改按 eval/contract 的官方验收口径（runner 六类检查、字段一致率 ≥90%），被测为 **通过**（100%；
   `"ok": true, exit 0`）——两个结论并存，取决于交付验收采用"逐字对照"还是"契约达标"。

**修复方向（如需达成逐字可替代）**：`gen_doc.py` 对齐 `oracle.py` 的三处文案结构即可——
周报基本信息行改居中并补"部门"（对齐 `oracle.py:177`）；请示函补两句固定句（`oracle.py:204,206`）；
会议通知补引语/结束语并改用连续编号、会议要求行内合并（`oracle.py:229-237`）。同时建议把这三处
写进 spec §4 或在 spec 声明"以 oracle 交付形态为准"，消除 spec 未钉死口径的分歧空间
（package/references 三份文档与 oracle 行为的分歧即源于此）。

---

## 5. 证据与可复现性

- 对照脚本：`_t_ab1_rep2/compare_ab.py`（本 ask 临时工作区，报告定稿后已清理；核心逻辑如 §3 所述，
  结构化输出 `_t_ab1_rep2/ab_compare_result.json` 已随脚本一并清理，本文档已摘录全部关键差异行）。
- 关键代码引用：
  - `package/scripts/gen_doc.py:264-266`（周报信息行：add_body、不含部门）、`:276-282`（请示函 7 段、无固定句）、
    `:285-295`（会议通知：无引语/结束语、会议要求独立小节）、`:207-211` + `:189-193`（标题 run ascii=黑体、无行距设置）、
    `:196-204`（仅 firstLineChars，无 twips 兜底）
  - `oracle/oracle.py:176-177`（周报居中信息行含部门）、`:204,206`（两句固定句）、`:229-237`（引语/编号/特此通知/会议要求行内合并）、
    `:123-130`（所有 run ascii/hAnsi=TNR）、`:133-141`（firstLine twips 兜底）
  - `package/references/周报.md:11`、`请示函.md:9-15`、`会议通知.md:9-19`（与 package 实现一致、与 oracle 行为分歧的口径源）
  - `contract.md:53-54`（docx 只要求语义一致、zip 时间戳可不同）；`spec.md:150-155`（§10 一致率口径）、`spec.md:160`（S4 路径不比较）
- 本 ask 未做的事（如实声明）：未做 Word/WPS 真实渲染目检（spec §12 非目标，仿宋/黑体为字体声明）；
  未重新生成 case2 单元（不在本 ask 范围）；未修改 package 或 oracle 任何文件——`oracle/out` 在本 ask 前后
  哈希未变（verify.py PASS=8 亦为参照根完好佐证），`package/out` 中 case2 保持原样。
