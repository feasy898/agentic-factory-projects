# spec.md — 中文办公模板技能（周报 / 请示函 / 会议通知 / 工作总结）行为规格

- 版本：1.0（固化于 2026-09-30）
- 语义权威：本文是行为语义的唯一权威；`contract.md` 只冻结对外接口与结构，冲突时以本文为准。
- 依据：本文全部规则提炼自 `oracle/oracle.py`（参照实现）的**实测行为**。本机实测环境：
  Windows x64 / Python 3.12.10 / python-docx 1.2.0。实测记录见文末附录 A（全部命令为本资产固化时实跑）。

---

## 1. 目标

给定四类中文事务文书之一（周报 / 请示函 / 会议通知 / 工作总结）与一份数据 JSON，
按 GB/T 9704 风格版式生成 `文书.docx`，并输出字段填充台账 `fields.json`
（哪些字段填了、哪些缺了、缺的怎么渲染的），做到：

1. 版式符合中文公文/事务文书惯例（居中标题、顶格称谓、首行缩进两字符、右对齐落款）；
2. 缺数据不编造：必填缺失以 `____` 占位并如实记账，选填缺失留空或省略；
3. 产物确定性可复现、可被程序逐条判定。

## 2. 术语与目录约定

| 术语 | 含义 |
|---|---|
| **资产根** | `skillfactory/v3/assets/office-templates/`（本文件所在目录） |
| **参照实现（oracle）** | `<资产根>/oracle/oracle.py`；参照产物预置于 `<资产根>/oracle/out/<模板>/case<N>/` |
| **被测（package）** | `<资产根>/package/`（候选技能包，结构见 contract §1） |
| **产物单元（unit）** | 同时含 `文书.docx` 与 `fields.json` 的目录；单元相对名 = `<模板>/case<N>` |
| **产物根** | 含若干产物单元的目录。参照产物根 = `oracle/out`；被测产物根约定为 `package/out` |

四类模板名固定为：`周报`、`请示函`、`会议通知`、`工作总结`（恰此四个，大小写与汉字严格一致）。

## 3. 输入规范

### 3.1 命令行（接口细节见 contract §2）

```
python <入口脚本> --template <周报|请示函|会议通知|工作总结> --data <数据.json> --outdir <输出目录>
```

### 3.2 数据 JSON

- 顶层必须是 JSON 对象（键值对）；键 = 字段名（汉字），值 = 字符串或字符串数组（见 F3）。
- 编码 UTF-8。

### 3.3 四类模板的字段表（name / required / kind）

| 模板 | 字段（\* = 必填；(列) = kind=list，其余 kind=text） |
|---|---|
| 周报（7 字段） | 部门\*、填报人\*、周期\*、本周工作内容\*(列)、下周工作计划\*(列)、问题与需协调事项(列)、报送日期 |
| 请示函（8 字段） | 请示事由\*、主送机关\*、请示缘由\*、请示事项\*、请示单位\*、联系人、联系电话、成文日期 |
| 会议通知（11 字段） | 会议名称\*、召开单位\*、主送对象\*、会议时间\*、会议地点\*、参会人员\*、会议议题、会议要求(列)、联系人、联系电话、发文日期 |
| 工作总结（7 字段） | 总结主体\*、总结时段\*、工作回顾\*(列)、主要成绩\*(列)、存在问题(列)、下一步工作打算\*(列)、成文日期 |

可判定：每类模板 fields.json 中 `fields` 数组长度与 name 集合恰等于上表；`required`/`kind` 与上表一致。

## 4. 版式规则（V1–V8，逐条程序可判）

以下"段落"均指 `doc.paragraphs` 中的段落；"非空段"指 `p.text.strip()` 非空。

- **V1 页面（GB/T 9704 版心）**：A4（宽 21.0 cm、高 29.7 cm）；页边距 上 3.7 / 下 3.5 / 左 2.8 / 右 2.6 cm
  （容差 ≤0.05 cm，吸收 twips 取整）。
- **V2 标题**：第一个非空段水平居中；run 字体 eastAsia=黑体、字号 22pt（二号）；
  段文本与 fields.json 的 `title` 完全相等。标题文案公式：
  - 周报：`{部门}工作周报`
  - 请示函：`关于{请示事由}的请示`
  - 会议通知：`关于召开{会议名称}的通知`
  - 工作总结：`{总结主体}{总结时段}工作总结`
  （缺失字段按 F1 以 `____` 代入，如 `____工作周报`、`关于召开____的通知`。）
- **V3 称谓顶格（仅请示函 / 会议通知）**：第二个非空段无首行缩进（`w:ind/@w:firstLineChars` 缺失或 =0），
  段文本 = `{主送对象/主送机关}：`。周报与工作总结无称谓段。
- **V4 正文首行缩进两字符**：标题之后存在 `w:ind/@w:firstLineChars=200` 的段落；
  正文 run：eastAsia=仿宋、字号 16pt（三号）、ascii/hAnsi=Times New Roman；
  行距固定 28 磅（`w:spacing/@w:line=560`，`lineRule=exact`），段前段后 0。
- **V5 落款右对齐**：最后一个非空段水平右对齐，且带右缩进两字（`w:ind/@w:right` ≈ 32pt，容差 ≤2pt）。
  落款行构成：周报一行 `报送日期：{报送日期}`；请示函两行 `{请示单位}` + `{成文日期}`；
  会议通知两行 `{召开单位}` + `{发文日期}`；工作总结两行 `{总结主体}` + `{成文日期}`（日期行为裸日期，无标签）。
- **V6 小节与条目**：含列表的模板按"一、二、三、"编小节，节头黑体、首行缩进两字符；
  条目以 `1．2．3．` 编号（全角点），首行缩进两字符。选填小节整节省略（见 F4）。
- **V7 占位符**：必填字段缺失处文中出现字面 `____`（四个下划线）。
- **V8 无时间源**：文书内容全部由输入数据推导，不得含当前时间、随机内容等不可复现源。

## 5. 字段语义规则（F1–F7，逐条程序可判）

判定"缺失"：键不存在，或值为空白字符串（strip 后为空）。列表字段的空数组、全空白数组亦为缺失。

- **F1 必填文本缺失** → 文中以 `____` 占位；fields.json 记 `status="missing"`、`required=true`、
  `rendered_as="以____占位"`。
- **F2 选填文本缺失** → 渲染为空字符串（行内留空，标签保留，如 `联系电话：`）；记
  `status="missing"`、`required=false`、`rendered_as="留空（渲染为空字符串）"`。
- **F3 列表字段取值宽容**：字符串 → 视为单项 `[strip(s)]`（空白串 → 缺失）；数组 →
  各元素 `str(x).strip()` 后去空；其他类型 → `str(x).strip()` 单项。
- **F4 列表字段缺失**：必填 → 渲染占位条目 `1．____`，`rendered_as="以____占位条目"`；
  选填 → 该条目/小节整节省略（文中不出现该节头），`rendered_as="省略该条目/小节"`。
- **F5 填充值 strip**：文本与列表项入文前均 `strip()`；fields.json 中 `value` 即 strip 后的值
  （text 为字符串，list 为字符串数组）。
- **F6 模板外键**：数据中未被模板消费的键按字典序记入 `summary.unknown_keys`，不影响文书与字段台账。
- **F7 必填缺失不是运行错误**：C1 正常退出、正常产出（如实记账），见 C2/R3。

## 6. fields.json 规范（S1–S4，逐条程序可判）

UTF-8、`ensure_ascii=false`、缩进 2。

- **S1 顶层键集合**：`{template, title, filled_fields, missing_fields, fields, summary, outputs}`
  （恰此 7 键）。`template` ∈ 四类模板名；`title` 与文书标题段文本相等。
- **S2 明细项**：`fields` 为数组，每项含 `{name, required, kind, status, value}`，
  缺失项另含 `rendered_as`（字符串）；`status` ∈ {`filled`, `missing`}；filled 项 `value` 非 null，
  missing 项 `value` 为 null；name 顺序与 §3.3 字段表一致、不重复。
- **S3 清单与汇总自洽**：`filled_fields` = 明细中 status=filled 的 name 序列；`missing_fields` = missing 的；
  `summary` 恰含 `{total, filled, missing, missing_required, missing_required_names, unknown_keys}`，
  且 `total = len(fields)`、`filled + missing = total`、`filled/missing` 计数与明细一致、
  `missing_required_names` = missing 且 required=true 的 name 序列、`missing_required = len(missing_required_names)`。
- **S4 outputs**：`{"docx": <文书.docx 路径>, "fields_json": <fields.json 路径>}`（字符串；
  路径写法随实现，评测不比较此键）。

## 7. CLI 行为规则（C1–C3，均已实测）

- **C1 成功**：模板名合法、数据文件存在、JSON 可解析且为对象 → 退出码 0；stdout 打印一行人读摘要
  （格式自由）；`--outdir` 不存在则递归创建；写入 `文书.docx` + `fields.json` 两个文件。
- **C2 非法输入拒绝**（以下任一 → 退出码 2、stderr 打印中文错误、**不写任何产物文件、不建产物目录**）：
  1. `--template` 不在四类之名（argparse choice 报错）；
  2. `--data` 文件不存在；
  3. 数据文件不是合法 JSON；
  4. JSON 顶层不是对象（如数组）。
  实测：4 条负路径各 exit=2，产物残留 0（附录 A-3）。
- **C3 边界不是错误**：必填缺失 / 选填缺失 / 模板外键 / 空列表 / 字符串型列表均按 F1–F6 处理，
  退出码 0。

## 8. 确定性（D1）

- **D1 语义确定性**：同输入连跑两次，`fields.json`（除 S4 outputs 外）逐字节一致；
  `文书.docx` 解析后的段落文本、对齐、缩进、字体、行距、页边距全部一致
  （zip 条目时间戳允许不同，不做逐字节要求）。
  实测：全新进程重跑 8 样例与 oracle/out 语义签名全等（附录 A-2）。

## 9. 边界样例期望表（oracle/out 实测值）

| 单元 | title | filled/total | missing_required（names） | 选填 missing | unknown_keys |
|---|---|---|---|---|---|
| 周报/case1 | 研发部工作周报 | 7/7 | — | — | — |
| 周报/case2 | `____工作周报` | 3/7 | 部门、周期、本周工作内容 | 问题与需协调事项 | — |
| 请示函/case1 | 关于采购评测用 GPU 服务器的请示 | 8/8 | — | — | — |
| 请示函/case2 | 关于延期举办季度评审会的请示 | 4/8 | 主送机关、请示事项 | 联系电话、成文日期 | — |
| 会议通知/case1 | 关于召开三季度质量评审会的通知 | 11/11 | — | — | — |
| 会议通知/case2 | `关于召开____的通知` | 5/11 | 会议名称、会议地点 | 会议议题、会议要求、联系人、联系电话 | 备注 |
| 工作总结/case1 | 评测技术部2026年第三季度工作总结 | 7/7 | — | — | — |
| 工作总结/case2 | `____2026年9月工作总结` | 3/7 | 总结主体、主要成绩 | 存在问题、成文日期 | — |

（8 个 case 输入见 `oracle/inputs/<模板>/case<N>.json`；case2 系列覆盖：必填键缺失、必填空字符串、
必填空列表、选填缺失、模板外多余键、字符串型列表。）

## 10. 与参照产物的一致率口径（评测用）

对 8 个单元按相对名一一配对，逐字段比较（字段全集 = 参照 fields.json 的 `fields` name 序列）：
`status` 相等且（均 filled 时）`value` 相等 → 该字段记"一致"。
**字段填充一致率 = 一致字段数 / 参与比较字段总数 ≥ 90%**（8 单元 66 字段全对齐为 100%）。

## 11. 安全要求（解析不可信产物）

runner/校验器解析候选 docx（zip 内 XML）前必须拒绝含 `<!DOCTYPE` 或 `<!ENTITY` 的 XML 条目、
不启用外部实体（防 XXE/实体爆炸）；不满足即判该单元 docx 检查失败，不崩溃。

## 12. 非目标

- 不做 Word/WPS 真实渲染目检：字形效果取决于查看机字体库（仿宋/黑体为字体**声明**，写入 docx 即达标）。
- 不支持模板定制、字段增删、多文档合并、docx→pdf、红头/公章/版记等公文要素。
- 不做并发、增量、批量目录输入：一次调用生成一份文书。
- 不校验数据语义（日期格式、电话号码合法性等按原样字符串处理）。
- runner 不评测 aesthetic 措辞质量（文案由数据公式化推导，见 V2/V5/V6）。

---

## 附录 A：本 spec 固化时的实测记录（2026-09-30，本机实跑）

1. `python oracle/verify.py` → 8 份产物 `PASS=8 FAIL=0`，exit 0。
2. 全新进程重跑 8 样例（`for t in 周报 请示函 会议通知 工作总结; for c in 1 2; python oracle.py
   --template $t --data inputs/$t/case$c.json --outdir _selfcheck/$t/case$c`）→ 8 条命令全部 exit=0；
   与 `oracle/out` 逐单元比对：fields.json（除 outputs）逐字节相等、docx 语义签名
   （段落文本/对齐/firstLineChars/eastAsia 字体/字号/行距/右缩进/页面与边距）全等、zip 条目表相等。
3. 负路径（`--template 证书`、`--data 不存在`、数据为 `不是JSON`、数据为 `["数组","非对象"]`）：
   4 条命令全部 exit=2，`find ... -name 文书.docx -o -name fields.json` 残留计数 = 0。
4. `python oracle.py --data inputs/请示函/case2.json` 产物抽查：主送机关缺失渲染为 `____：` 顶格称谓、
   请示事项为 `____`、联系电话留空；`out/会议通知/case2/fields.json` 记
   `missing_required=[会议名称,会议地点]`、`unknown_keys=[备注]`，与 §9 表一致。
