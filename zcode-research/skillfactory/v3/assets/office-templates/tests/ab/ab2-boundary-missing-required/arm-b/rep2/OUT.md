# AB2 必填缺失边界 A/B 对照报告 — arm-b / rep2

- **日期**：2026-09-30（本机 windev-01，Python 3.12.10 + python-docx 1.2.0）
- **被测方（A/PKG）**：office-templates 技能包生成器 `package/scripts/gen_doc.py`
- **参照方（B/ORC）**：`oracle/oracle.py` 及其既有基线产物 `oracle/out/`
- **输入**（本轮为**数据边界**用例，非全量 case1）：
  - `oracle/inputs/请示函/case2.json` —— 必填「主送机关」键缺失、必填「请示事项」为空字符串、选填「联系电话」「成文日期」键缺失（共 8 字段，实际给 4 个）
  - `oracle/inputs/会议通知/case2.json` —— 必填「会议名称」键缺失、必填「会议地点」空字符串、选填「会议议题/会议要求/联系人/联系电话」缺失、含模板外键「备注」（共 11 字段，实际给 5 个 + 1 个外键）
- **产物落位**：A → `package/out/<模板>/case2/`，B → `oracle/out/<模板>/case2/`（各 `文书.docx` + `fields.json`）
- **判定问题**：两边占位渲染与缺失记账对照后，被测是否做到「**缺数据不编造、如实记账**」（SKILL.md §1/§3.2）
- **方法声明**：按任务要求先完整读 `package/SKILL.md` 与 `references/` 全部四份（周报/请示函/会议通知/工作总结）；对照全部基于**实际运行两侧 CLI + 程序化比对产物**，未读两侧实现源码，判定不依赖源码推断。

---

## 0. 规范预期（先立标尺，全部来自已读文档）

| 边界 | 规范条款 | 预期行为 |
|---|---|---|
| 必填文本缺失（键缺/空串） | SKILL.md §3.2 F1（`SKILL.md:41`）、V7（`SKILL.md:91`） | 文中以字面 `____` 占位；台账 `status="missing"`、`rendered_as="以____占位"` |
| 选填文本缺失 | SKILL.md §3.2 F2（`SKILL.md:42`） | 行内留空、**标签保留**（如 `联系电话：`）；记 `rendered_as="留空（渲染为空字符串）"` |
| 选填列表缺失 | SKILL.md §3.2 F4（`SKILL.md:44`） | 小节整节省略、文中不出现节头；记 `rendered_as="省略该条目/小节"` |
| 模板外键 | SKILL.md §3.2 F6（`SKILL.md:47`） | 仅记入 `summary.unknown_keys`，不影响文书与台账 |
| 必填缺失不是错误 | SKILL.md §3.2 F7/C3（`SKILL.md:48`） | 退出码 0、正常产出 |
| 台账形态 | SKILL.md §5（`SKILL.md:73-79`） | 顶层恰 7 键；summary 恰 6 键；filled+missing=total；missing 项 value=null |
| 请示函 case2 预期 | `references/请示函.md:34-38` | 称谓 `____：`、事项段 `____`、联系行 `联系人：李工　　联系电话：`、落款二空段；filled 4/8，missing_required=[主送机关, 请示事项]，选填 missing=[联系电话, 成文日期] |
| 会议通知 case2 预期 | `references/会议通知.md:39-44` | 标题 `关于召开____的通知`、`会议地点：____`、无"会议要求"节、联系行 `联系人：　　联系电话：`；filled 5/11，missing_required=[会议名称, 会议地点]，unknown_keys=[备注] |

---

## 1. 执行的命令与退出码（4 次运行，全部实测）

工作目录 `D:\workspace\zcode研究\skillfactory\v3\assets\office-templates`，`PYTHONIOENCODING=utf-8`。

```bash
# 被测方（2 次）
python package/scripts/gen_doc.py --template 请示函  --data oracle/inputs/请示函/case2.json  --outdir package/out/请示函/case2    # exit=0
python package/scripts/gen_doc.py --template 会议通知 --data oracle/inputs/会议通知/case2.json --outdir package/out/会议通知/case2 # exit=0
# 参照方（2 次）
python oracle/oracle.py --template 请示函  --data oracle/inputs/请示函/case2.json  --outdir oracle/out/请示函/case2    # exit=0
python oracle/oracle.py --template 会议通知 --data oracle/inputs/会议通知/case2.json --outdir oracle/out/会议通知/case2 # exit=0
```

stdout 实录（两侧均正常退出，**必填缺失未被当作错误**，符合 F7/C3）：

```text
PKG 请示函:   已生成：…请示函\case2\文书.docx（标题=关于延期举办季度评审会的请示，filled/total=4/8，
              必填缺失=['主送机关', '请示事项']，模板外键=无）
PKG 会议通知: 已生成：…会议通知\case2\文书.docx（标题=关于召开____的通知，filled/total=5/11，
              必填缺失=['会议名称', '会议地点']，模板外键=['备注']）
ORC 请示函:   OK … filled=4 missing=4 missing_required=2
ORC 会议通知: OK … filled=5 missing=6 missing_required=2
```

4 个输出目录均恰产出 `文书.docx` + `fields.json` 两个文件（目录清单实测）。

## 2. 缺失记账对照（fields.json）— **两侧 0 差异** ✅

程序化深度 diff（`deep_diff` 递归比较两侧 JSON）：每模板全量差异仅 2 条，均为自指输出路径
`$.outputs.docx` / `$.outputs.fields_json`（A 指 `package\out\...`，B 指 `oracle\out\...`）；
**剔除后差异 = 0**。即逐字段的 `required/kind/status/value/rendered_as` 与全部 summary 计数完全等价。

| 核对项 | 请示函 case2（A=B） | 会议通知 case2（A=B） | 与规范预期 |
|---|---|---|---|
| summary | total=8, filled=4, missing=4, missing_required=2, names=[主送机关, 请示事项], unknown=[] | total=11, filled=5, missing=6, missing_required=2, names=[会议名称, 会议地点], unknown=[备注] | ✅ 与 `references/请示函.md:37`（filled 4/8）、`references/会议通知.md:43-44`（filled 5/11、unknown=[备注]）逐项一致 |
| 必填缺失 rendered_as | 主送机关/请示事项 = `以____占位` | 会议名称/会议地点 = `以____占位` | ✅ F1 |
| 选填缺失 rendered_as | 联系电话/成文日期 = `留空（渲染为空字符串）` | 会议议题/联系人/联系电话 = `留空…`；会议要求(list) = `省略该条目/小节` | ✅ F2/F4 |
| 计数自洽 | filled+missing=total ✅；names=缺失且必填序列 ✅（脚本断言通过） | 同左 ✅ | ✅ SKILL.md §5 |
| 台账形态 | 顶层恰 7 键、summary 恰 6 键、missing 项 value=null、filled 项 value 非 null | 同左 | ✅ SKILL.md §5 |
| 文件格式 | UTF-8、原始汉字（ensure_ascii=false）、2 空格缩进（字节头实测 `{\r\n  "template": "请示函"…`） | 同左 | ✅ SKILL.md §5 |
| 模板外键 | — | `备注` 仅出现在 `summary.unknown_keys`，两侧 `fields[]` 均无此项（11 字段清单实测） | ✅ F6 |

**结论：缺失记账层面，被测与参照完全等价，且逐项命中双方共同声明的 F1/F2/F4/F6 记账口径。**

## 3. 占位渲染对照（文书.docx）— 必填占位两侧一致；选填行渲染策略有 1 处两边分歧（被测更贴规范）

用 python-docx 逐段提取文本/对齐/缩进/字体（`_work/step2_ab_report.txt` 全量段表），要点：

### 3.1 必填缺失占位 — **两侧全部一致出现字面 `____`，无一处编造** ✅

| 模板 | 位置 | A（被测）实测 | B（参照）实测 | 一致 |
|---|---|---|---|---|
| 请示函 | 标题（事由已填） | `关于延期举办季度评审会的请示` 居中黑体22pt | 同 | ✅ |
| 请示函 | 称谓（主送机关缺） | `____：` **顶格**（无首行缩进） | 同 | ✅ |
| 请示函 | 请示事项段（空串） | `____`（首行缩进两字符） | 同（P04） | ✅ |
| 会议通知 | 标题（名称缺） | `关于召开____的通知` 居中黑体22pt | 同 | ✅ |
| 会议通知 | 会议地点（空串） | `会议地点：____` | `二、会议地点：____`（仅编号差异） | ✅ 占位一致 |
| 会议通知 | 引言内（名称缺） | （被测无引言段） | `经研究，决定召开____。现将有关事项通知如下：` | 参照的引言同样以 `____` 代缺失，未编造 |

### 3.2 选填缺失渲染 — 被测严格按其规范；参照在会议通知上把整行省略

| 模板 | 字段 | A（被测） | B（参照） | 规范说 |
|---|---|---|---|---|
| 请示函 | 联系电话缺 | 联系行 `联系人：李工　　联系电话：`（标签保留、值留空） | 同 | F2：标签保留 ✅ 两侧一致 |
| 请示函 | 成文日期缺 | 落款二为**空段**且右对齐（末个非空段=落款一 `评测技术部`，右对齐，两侧实测相同） | 同 | F2/`references/请示函.md:30` ✅ |
| 会议通知 | 会议议题缺 | 保留空值行 `会议议题：` | **整行不出现**（全文检索 in-B=False） | `references/会议通知.md:31` 说「标签保留、值留空」→ **被测符合，参照偏离** |
| 会议通知 | 联系人+联系电话缺 | 联系行 `联系人：　　联系电话：`（双标签保留） | **整行不出现** | `references/会议通知.md:33-34` 同上 |
| 会议通知 | 会议要求缺(list) | 无 `一、会议要求` 节头（检索 in-A=False） | 同（in-B=False） | F4：整节省略 ✅ 两侧一致 |

**关于该分歧的定性**：这是「选填行渲染策略」之差，**不构成编造或记账失实**——两侧该处的值都是空，台账记录（含 `rendered_as="留空（渲染为空字符串）"`）也逐字相同。值得记录的是：参照（ORC）在会议通知 case2 把会议议题行/联系行**整体省略**，但其自身 fields.json 仍记 `rendered_as="留空（渲染为空字符串）"`——**参照的台账措辞与其自家 docx 在此处不对应**；而被测的「标签保留、值留空」与其规范文档（SKILL.md F2、`references/会议通知.md` §2）**逐条吻合**。请示函侧参照又确实保留了空标签 `联系电话：`，说明两侧对 F2 的实现边界在「整行 vs 行内」上不同，本例中被测是更贴文档的一方。

### 3.3 「不编造」负向探针（全文检索，全部通过）✅

- **数字探针**：请示函 case2 输入不含任何数字（无电话、无日期）→ 双方全文正则提取数字：**A=[]，B=[]**。被测没有为缺失的联系电话/成文日期编造任何数字。
- **外键不渲染**：`备注` 的值 `此键不在模板字段内…` 在双方全文均 in-False——被测未把数据外的键渲染进文书。
- **缺失列表节**：`一、会议要求` 双方均未出现——被测没有为缺失的会议要求编造条目。
- **无虚构值**：`联系人：` 后、`会议议题：` 后均无任何非空内容（被测侧）。

### 3.4 非缺失范畴的既有文风差异（记录备查，不参与本判定）

与 ab1 结论一致（`tests/ab/ab1-.../arm-b/rep2/OUT.md` §4）：参照含请示函过渡句/`妥否，请批示。`、会议通知引言/`特此通知。`、正文条目 `一、二、三、` 编号（被测按 `references/会议通知.md` §1 的无编号正文段排布）；缩进上被测只写 `firstLineChars=200`，参照另加 `firstLine=640` twips 兜底（语义同为缩进两字符）。这些属**模板文风/结构**差异，与「缺数据是否编造、缺失是否如实记账」无关。注意：会议通知的引言/结语/编号是**参照自有的固定文案**，属文风而非数据，故不计入「编造」。

## 4. 确定性与验收（先决检查）

- **运行前快照**：`_work/backup/` 存有 4 个 case2 目录重跑前全量副本（8 文件，sha256 见 `_work/backup_manifest.txt`）。
- **被测可复现**：本次 fresh 重跑 vs 快照——`fields.json` 逐字节相同，docx zip 全部 entry 内容哈希逐一相同（差异数=0）。→ 既有 `package/out/.../case2` 基线本就与本次重生成内容一致，覆盖无信息损失。
- **参照可复现**：docx zip 全部 entry 内容哈希相同；`fields.json` 差异**仅** `$.outputs.docx/fields_json` 两条（快照生成时 `--outdir` 记为 `out\...`，本次为 `oracle\out\...`，`_work/step3_followup.py` 实测定位），其余键全同 → 参照基线可信。
- **参照方验收器**：`python oracle/verify.py oracle/out` → **PASS=8 FAIL=0 exit=0**；`python oracle/verify.py package/out` → **PASS=8 FAIL=0 exit=0**。被测两份 case2 边界产物**通过参照方自设验收门槛**。

## 5. 判定结论：**被测做到「缺数据不编造、如实记账」** ✅

| 判定维度 | 结论 | 依据 |
|---|---|---|
| 必填缺失不编造 | ✅ | 4 个必填缺失（主送机关/请示事项/会议名称/会议地点）全部渲染为字面 `____`（称谓/正文/标题/地点行），与参照逐一相同；无任何替代文案 |
| 选填缺失不编造 | ✅ | 联系电话/成文日期/会议议题/联系人→标签保留值留空或空段；会议要求→整节省略；数字探针 0 命中 |
| 模板外键不渗入 | ✅ | `备注` 未渲染、未进 fields[]，仅记 `summary.unknown_keys=["备注"]` |
| 如实记账 | ✅ | fields.json 与参照深度 diff=0（除输出路径）；计数自洽；rendered_as 与文中实际渲染逐条对应（参照反而在会议通知 case2 存在 rendered_as=留空 vs 整行省略的自不一致） |
| 必填缺失非错误 | ✅ | 两侧 4/4 次 exit=0，产物两件套齐全 |
| 可复现/可验收 | ✅ | 被测 fresh==快照（字节级）；`oracle/verify.py` 对 `package/out` PASS 8/8 |

**两边唯一实质分歧**：会议通知 case2 的选填文本行（会议议题/联系行）——被测「标签保留、值留空」（= 其规范 F2 字面要求），参照「整行省略」（与其自身台账 rendered_as 措辞不对应）。该分歧不涉及数据真伪，不影响本判定；若以参照文风为验收标准，需另行裁决「整行 vs 空标签」，但按双方共同声明的 F2 条款，**被测的渲染才是文档规定行为**。

**修复指向（供 arm 汇总）**：无需修复缺失边界；可选对齐项为参照式的引言/结语/编号文风与 twips 缩进兜底（同 ab1 清单，均非本边界问题）。

## 6. 证据与工件索引（均在 rep2 目录内）

| 文件 | 内容 |
|---|---|
| `_work/step0_backup.py` → `backup/`、`backup_manifest.txt` | 运行前 4 个 case2 产物快照（8 文件 + sha256） |
| `_work/step1_run.py` → `step1_runs.json` | 4 次 CLI 运行的命令/退出码/stdout/stderr/产物清单原始记录 |
| `_work/step2_ab_compare.py` → `step2_ab_report.txt` | fields.json 深度 diff、逐字段台账 dump、docx 逐段画像（文本/对齐/缩进/字体）、针脚检索、数字探针、确定性核验 |
| `_work/step3_followup.py` | ORC fresh vs 快照的 fields.json 差异定位（仅 $.outputs.* 两条） |
| `package/out/{请示函,会议通知}/case2/`、`oracle/out/{请示函,会议通知}/case2/` | 本次双方实际产物 |
- 本轮**未做**：未读两侧实现源码（gen_doc.py / oracle.py），渲染判定基于运行输出与产物程序化解析；未做 Word 打开目测（docx 判定在 OOXML 语义层）。
