# OUT.md — AB1 标准全量生成 A/B 对照报告（arm-a / rep1）

- 任务：被测技能（`package/`，入口 `package/scripts/gen_doc.py`）与参照实现（oracle，`oracle/oracle.py`）分别处理 `oracle/inputs/` 下四类模板 case1 输入（字段全部齐全），按 contract §2 命令行生成 `文书.docx` + `fields.json` 到 `package/out/<模板>/case1/`，与 `oracle/out/<模板>/case1/` 逐一对照**版式**与**字段台账**，判定**被测产物可否替代参照交付**。
- 日期：2026-09-30（全部命令本次实跑）
- 环境：Windows x64 / Python 3.12.10 / python-docx 1.2.0（与 spec.md 附录 A 实测环境一致；版本由 `python --version`、`python -c "import docx; print(docx.__version__)"` 实查）
- 工作目录：`skillfactory/v3/assets/office-templates/`

---

## 0. 结论（先行）

| 口径 | 判定 | 依据 |
|---|---|---|
| **冻结契约口径**（contract §3/§5 + spec V1–V8、§6 S1–S4、§10、D1） | **可替代** | 字段台账逐字节等价（除 `outputs` 路径）；spec §10 字段一致率 **100%**（case1 四单元 33/33；全量 8 单元 66/66）；版式不变量 V1–V8 双方全部达标；`eval/runner.py` `ok=true` exit 0；确定性 D1 成立 |
| **逐段同文口径**（要求与参照 docx 正文一字不差） | **不可替代** | 4 份中 3 份（周报/请示函/会议通知）正文段落序列与参照不同（详见 §4）；工作总结正文全等 |

**主判定**：按任务双方唯一的交付判据——冻结的 contract/spec（`contract.md:3-5` 明示"接口之内 docx 生成细节……实现自由"，spec §10 只比字段填充）——**被测产物可替代参照交付**。差异全部位于 spec V1–V8 未冻结的成文自由区（公文套语有无、周报信息行构成、会议通知条目组织），且被测实现与 `package/references/` 自述结构**逐条一致**，反而是 oracle 在这三处偏离了 references 文档（详见 §5 发现 D5）。若交付方额外要求"与参照逐段同文"，则 3/4 模板不满足——此口径未被任何冻结文件要求，列为保留意见。

---

## 1. 输入确认（oracle/inputs/ 四类 case1，字段全部齐全）

实读四个 JSON（`oracle/inputs/<模板>/case1.json`）并经产物台账验证 filled=total：

| 模板 | 字段数 | 输入字段齐全性 | 产物验证（tested） |
|---|---|---|---|
| 周报 | 7 | 部门/填报人/周期/本周工作内容(列)/下周工作计划(列)/问题与需协调事项(列)/报送日期 全在 | filled/total=7/7 |
| 请示函 | 8 | 请示事由/主送机关/请示缘由/请示事项/请示单位/联系人/联系电话/成文日期 全在 | 8/8 |
| 会议通知 | 11 | 会议名称/召开单位/主送对象/会议时间/会议地点/参会人员/会议议题/会议要求(列)/联系人/联系电话/发文日期 全在 | 11/11 |
| 工作总结 | 7 | 总结主体/总结时段/工作回顾(列)/主要成绩(列)/存在问题(列)/下一步工作打算(列)/成文日期 全在 | 7/7 |

标题与 spec §9 期望表（`spec.md:137-146`）逐一相符：`研发部工作周报`、`关于采购评测用 GPU 服务器的请示`、`关于召开三季度质量评审会的通知`、`评测技术部2026年第三季度工作总结`。

## 2. 执行记录（命令原样，exit 实测）

被测技能 4 条（contract §2 命令行，先 `rm -rf` 旧 case1 单元保证全新生成）：

```bash
python package/scripts/gen_doc.py --template 周报   --data oracle/inputs/周报/case1.json   --outdir package/out/周报/case1     # exit=0
python package/scripts/gen_doc.py --template 请示函 --data oracle/inputs/请示函/case1.json --outdir package/out/请示函/case1   # exit=0
python package/scripts/gen_doc.py --template 会议通知 --data oracle/inputs/会议通知/case1.json --outdir package/out/会议通知/case1 # exit=0
python package/scripts/gen_doc.py --template 工作总结 --data oracle/inputs/工作总结/case1.json --outdir package/out/工作总结/case1 # exit=0
```

每条 stdout 一行人读摘要（如 `已生成：package\out\周报\case1\文书.docx（模板=周报，标题=研发部工作周报，字段 filled/total=7/7，必填缺失=无，模板外键=无）`），每单元恰产出 `文书.docx`+`fields.json` 两文件（`find` 实查 8 个文件）。

参照实现 4 条（同 CLI，输出到 rep1 工作区，用于验证预置基线可复现）：

```bash
python oracle/oracle.py --template <t> --data oracle/inputs/<t>/case1.json --outdir <rep1>/_work/oracle-refresh/<t>/case1   # 4 条全部 exit=0
```

标准校验与确定性：

```bash
python eval/runner.py package/out oracle/out   # ok=true, exit=0（66/66 字段一致率 100.0%）
python oracle/verify.py oracle/out             # PASS=8 FAIL=0, exit=0
python package/scripts/gen_doc.py …（同输入双跑 det1/det2）# fields 除 outputs 逐字节一致、docx 语义签名全等（D1 ✓）
```

## 3. 基线可复现性（先于 A/B 验证参照本身）

`_work/oracle-refresh`（本次新跑）vs `oracle/out`（预置基线）逐单元对照（脚本 `_work/ab_compare.py`，提取页面几何+每段 text/对齐/firstLineChars/行距 line+lineRule/右缩进/首 run 字体字号）：

| 模板 | fields 除 outputs 差异 | §10 一致率 | 页面几何 | docx 语义签名 |
|---|---|---|---|---|
| 周报 | 0 | 7/7 | 相等 | **全等**（11 段） |
| 请示函 | 0 | 8/8 | 相等 | **全等**（9 段） |
| 会议通知 | 0 | 11/11 | 相等 | **全等**（12 段） |
| 工作总结 | 0 | 7/7 | 相等 | **全等**（15 段） |

→ 预置 `oracle/out` 是当前 `oracle.py` 的忠实产物，可作 A/B 基线（与 spec 附录 A-2 声明一致）。

## 4. A/B 对照结果（package/out vs oracle/out，case1 ×4）

### 4.1 字段台账 fields.json —— 完全等价

- 顶层 7 键集合相等（S1）；除 `outputs` 外**逐字节相等**（删除 outputs 后以 `ensure_ascii=false, indent=2` 重序列化对比，4/4 byte-identical）。
- `outputs` 键为唯一差异，内容即各自 `--outdir` 路径（spec §6 S4 明示"路径写法随实现，评测不比较此键"）：
  - tested：`{"docx": "package\\out\\周报\\case1\\文书.docx", "fields_json": …}`
  - oracle：`{"docx": "oracle\\out\\周报\\case1\\文书.docx", "fields_json": …}`
- spec §10 逐字段（status 相等且 filled 时 value 相等）：**周报 7/7、请示函 8/8、会议通知 11/11、工作总结 7/7，全部 100%**。

### 4.2 文书.docx 版式 —— 冻结不变量全部达标，两处自由区差异

页面几何（V1）四单元与参照完全相等：21.001×29.7 cm，上 3.701 / 下 3.5 / 左 2.799 / 右 2.6 cm（twips 取整一致）。逐段核对：标题居中黑体 22pt（V2）、称谓顶格全角冒号（V3，请示函/会议通知）、正文 firstLineChars=200 + 仿宋/Times New Roman/16pt/28 磅 exact（V4，`w:line=560/lineRule=exact`）、落款右对齐右缩进 640 twips=32pt（V5）、条目 `1．` 全角点（V6）、无 `____` 之外的占位差异（V7，case1 无缺失）、内容全部由输入推导（V8）。

**发现的差异（共 2 类 4 处，均不触碰 V1–V8 判据）**：

| # | 差异 | tested（gen_doc.py） | oracle（oracle.py） | spec 判定 |
|---|---|---|---|---|
| D1 | **标题段行距**（4 模板同） | 未设行距（Word 默认单倍）；`gen_doc.py:207-211` `add_title` 不设 spacing | `w:line=560/exact`（28 磅）；`oracle.py:149` `para()` 对所有段统一设 | V2 只要求居中/黑体/22pt/文本；V4 的 28 磅限定"正文"。双方合规，属自由区。视觉差异轻微 |
| D2 | **周报基本信息行** | `填报人：王小明　　周期：…`，首行缩进两字符、左对齐（`gen_doc.py:265-266`） | `填报人：王小明　　部门：研发部　　周期：…` 多含部门，居中、无缩进（`oracle.py:177`） | spec V1–V8 未规定该行构成/对齐；**tested 与 `references/周报.md:11` 公式（`填报人：{填报人}　　周期：{周期}`、正文缩进两字符）逐字一致** |
| D3 | **请示函成文结构** | 7 段：无套语（`gen_doc.py:277-282`） | 9 段：多 `现就有关事项请示如下：`、`妥否，请批示。` 两段（`oracle.py:204,206`） | spec 未冻结；**tested 与 `references/请示函.md` 结构表（恰 7 段）一致** |
| D4 | **会议通知成文结构** | 12 段：`会议时间：`等标签行不编号；`会议要求`独立小节 `一、会议要求`（黑体节头）+ `1．2．` 条目（`gen_doc.py:285-295`） | 12 段：多 `经研究，决定召开…。现将有关事项通知如下：`/`特此通知。`；五项事项并成 `一、~五、`编号行；会议要求并入 `五、会议要求：…；…。`（`oracle.py:229-237`） | spec 未冻结；**tested 与 `references/会议通知.md` 结构表逐行一致**（含 V6 节头黑体的正确应用） |

工作总结：正文 15 段与参照**逐段全等**（仅 D1 标题行距声明不同）。

### 4.3 标准评测（冻结口径）

- `python eval/runner.py package/out oracle/out` → **`"ok": true`，exit 0**。case1 四单元的 `docx_opens_safe`/`layout_title_centered`/`layout_salutation_flush_left`/`layout_body_indent`/`layout_signature_right`/`fields_json_self_consistent`/`fields_match_docx`/`boundary_reported` 全部 pass；总判 `field_fill_agreement_ge_90pct` = **100.0%（66/66，阈值 90%）**。
  - 范围声明：runner 按契约必须评测 8 单元；case1 四单元为本 ask 全新生成，case2 四单元为同日更早一轮运行的既有产物（04:49，早于本次重跑），本次未按 ask 要求重新生成，仅随 runner 一并复检并全部通过。
- `python oracle/verify.py oracle/out` → PASS=8 FAIL=0，exit 0（参照完好）。
- 确定性（D1，SKILL.md §2 技能自述）：同输入双跑 `_work/det1` vs `_work/det2`，fields 除 outputs 差异 0、docx 语义签名全等（4/4）。旁证：重跑前后 `fields.json` md5 完全一致（如周报 `2acbd82b…`），docx md5 不同仅为 zip 时间戳（D1 允许）。

## 5. 附加发现

- **D5（资产不一致）**：`package/references/` 三处结构描述（周报基本信息行、请示函无套语、会议通知分节条目）与 oracle 实际产物不符，而与被测实现一致；`spec.md:5` 自称"全部规则提炼自 oracle.py 实测行为"，但 spec V1–V8 恰未覆盖这三处。即：references 更像按"理想成文结构"撰写，oracle 是更早的朴素实现。**对本次判定无影响**（比较基线是 oracle/out 实际产物），但若后续把"与 references 同构"纳入验收，oracle 反而不达标。
- 被测产物无 XXE 面：runner `docx_opens_safe`（DOCTYPE/ENTITY 扫描）4 单元 case1 全过。

## 6. 判定

**被测产物（package/out/<模板>/case1/）在冻结契约口径下可替代参照交付**：

1. 字段台账完全等价（除不比较的 `outputs` 路径外逐字节一致，§10 一致率 100%）；
2. 版式满足全部冻结不变量 V1–V8，页面/字体/字号/缩进/行距/落款各项属性与参照在可比属性上完全相等；
3. 产物确定性（D1）、安全（§11）、CLI 契约（§2，exit 0 + 单行摘要）全部实测通过。

**保留意见**：被测 docx 与参照 docx **不是同一份文档**——周报信息行构成、请示函与会议通知的公文套语/条目组织不同（§4.2 D2–D4）。这些差异处于 contract 明示的实现自由区，且被测实现与其自带 references 逐字一致；但若交付验收隐含"与参照逐段同文"（冻结文件未要求），则 3/4 模板需先对齐成文结构方可替代。

## 7. 证据与产物清单

- 本报告：`tests/ab/ab1-standard-four-templates/arm-a/rep1/OUT.md`
- 对照脚本：`_work/ab_compare.py`（页面几何+逐段签名提取与 diff）
- 机读结果：`_work/step1_oracle_refresh_vs_stored.json`（基线复现）、`_work/step2_package_vs_oracle.json`（A/B 全量逐段数据）、`_work/step3_determinism.json`（D1）
- 新生成产物：`package/out/{周报,请示函,会议通知,工作总结}/case1/{文书.docx,fields.json}`；oracle 复跑与双跑样例在 `_work/{oracle-refresh,det1,det2}/`（不影响 `oracle/out` 基线）
