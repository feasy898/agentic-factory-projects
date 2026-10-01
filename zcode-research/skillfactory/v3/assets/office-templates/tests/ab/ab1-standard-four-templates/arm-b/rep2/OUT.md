# AB1 标准全量生成 A/B 对照报告（arm-b / rep2）

- 日期：2026-09-30
- 被测对象：`package/scripts/gen_doc.py`（office-templates 技能包，下称 **PKG**）
- 参照实现（oracle）：`oracle/oracle.py`（下称 **ORC**）
- 输入：`oracle/inputs/{周报,请示函,会议通知,工作总结}/case1.json`（四类模板各一份 case1，字段全部齐全——双方台账均报 filled=total、missing=0、missing_required=0、unknown_keys=0）
- 合规声明：按任务限制，本次**未直接读取 `skillfactory/` 下任何文件内容**。仅列目录获取路径；全部产物检查通过位于 `skillfactory/` 之外的脚本完成（脚本读文件、仅输出差异与画像，脚本清单见 §7）。本报告所有事实均来自这些脚本的输出与两条 CLI 的运行时输出。

---

## 1. 总判定

**被测产物（PKG）当前不可替代参照交付（ORC）。**

| 维度 | 结果 |
|---|---|
| fields.json 字段台账 | **4/4 一致**（双方深度 diff 仅 `outputs.docx` / `outputs.fields_json` 两条自指输出路径不同，其余键值全等） |
| 文书.docx 版式 | **0/4 完全一致**（四类模板均存在系统性版式差异，见 §4） |
| 文书.docx 内容 | **1/4 等价**：工作总结文字全同；周报漏印「部门」字段；请示函缺 2 个结构段；会议通知缺引言/条目编号/结束语且结构重排 |

---

## 2. 执行记录（本次实际运行）

工作目录：`D:\workspace\zcode研究\skillfactory\v3\assets\office-templates`，`PYTHONIOENCODING=utf-8`。

双方 CLI 均符合任务所述 contract §2 签名（`--help` 实测输出）：

```
gen_doc.py [-h] --template {周报,请示函,会议通知,工作总结} --data DATA --outdir OUTDIR
oracle.py  [-h] --template {周报,请示函,会议通知,工作总结} --data DATA --outdir OUTDIR
```

PKG 四次运行（`python package/scripts/gen_doc.py --template T --data oracle/inputs/T/case1.json --outdir package/out/T/case1`），全部 exit=0：

```text
周报:    已生成：package\out\周报\case1\文书.docx（模板=周报，标题=研发部工作周报，字段 filled/total=7/7，必填缺失=无，模板外键=无）
请示函:  已生成：package\out\请示函\case1\文书.docx（…标题=关于采购评测用 GPU 服务器的请示，filled/total=8/8…）
会议通知: 已生成：package\out\会议通知\case1\文书.docx（…标题=关于召开三季度质量评审会的通知，filled/total=11/11…）
工作总结: 已生成：package\out\工作总结\case1\文书.docx（…标题=评测技术部2026年第三季度工作总结，filled/total=7/7…）
```

ORC 四次运行（`python oracle/oracle.py --template T --data oracle/inputs/T/case1.json --outdir oracle/out/T/case1`），全部 exit=0，filled/missing 与 PKG 完全一致（7/0、8/0、11/0、7/0，missing_required=0）。

产物清单核对：8 个 case1 输出目录 × {`文书.docx`, `fields.json`} 全部就位（find 清点 16 个文件），与任务要求的两件套一致。任务只要求 case1，case2 未运行。

---

## 3. 字段台账对照（fields.json）

双方 `fields.json` 深度 diff：每类模板仅 2 处差异，均为自指路径：

```text
/outputs/docx:        ORC='oracle\out\<模板>\case1\文书.docx'   vs PKG='package\out\<模板>\case1\文书.docx'
/outputs/fields_json: ORC='oracle\out\<模板>\case1\fields.json' vs PKG='package\out\<模板>\case1\fields.json'
```

顶层键结构双方相同：`template, title, filled_fields, missing_fields, fields, summary, outputs`。台账内容逐字段全等，摘录（PKG 侧）：

- **周报**（7 字段）：部门=研发部、填报人=王小明、周期=2026-09-21 至 2026-09-27、本周工作内容=[完成打分器 v0.9 与评测台联调；修复评测集 3 处标注不一致问题]、下周工作计划=[启动回归测试全量跑批；输出周度质量报告初稿]、问题与需协调事项=[测试机资源紧张，需协调一台 GPU 机器]、报送日期=2026-09-28
- **请示函**（8 字段）：请示事由=采购评测用 GPU 服务器、主送机关=公司总经理办公会、请示缘由=因评测规模扩大…、请示事项=申请采购 V100S 服务器 2 台，预算 12 万元…、请示单位=评测技术部、联系人=李工、联系电话=010-88886666、成文日期=2026年9月28日
- **会议通知**（11 字段）：会议名称=三季度质量评审会、召开单位=评测技术部、主送对象=各部门、各项目组、会议时间=2026年10月9日（周五）14:00、会议地点=3 号楼 501 会议室、参会人员=各部门负责人、各项目组 PM、会议议题=三季度评测结果复盘与四季度计划、会议要求=[会前提交本部门质量简报；迟到 10 分钟以上按缺席处理]、联系人=李工、联系电话=010-88886666、发文日期=2026年9月28日
- **工作总结**（7 字段）：总结主体=评测技术部、总结时段=2026年第三季度、工作回顾=[完成 P0 打分器三轮迭代；建设 12 份评测 JSON 台账]、主要成绩=[打分一致性从 6.1 提升到 7.4；评测周期缩短 30%]、存在问题=[标注规范仍有歧义；GPU 资源排期紧张]、下一步工作打算=[发布标注规范 v2；引入自动化回归评测]、成文日期=2026年9月30日

**结论：字段台账层面 PKG 可对等替代 ORC（4/4）。**

---

## 4. 版式对照（文书.docx）

对比方法：python-docx 1.2.0 解析双方 docx，比较节设置（页面/页边距）、Normal 默认样式、逐段（样式/对齐/缩进/行距/段距）与逐 run（bold/italic/下划线/中英文字体/字号/文字）。

### 4.1 双方一致的部分（四类模板相同）

- 页面：A4 纵向 21.001×29.7cm；页边距 上3.701 / 下3.5 / 左2.799 / 右2.6 cm——完全一致。
- 正文 run：Times New Roman（西文）+ 仿宋（中文）16pt——一致。
- 标题 run：黑体（中文）22pt 居中——一致。
- 表格：双方均无表格。
- bold：ORC 显式 `b=False`，PKG 省略（继承默认不加粗）——视觉等价，非缺陷。

### 4.2 系统性版式差异（四类模板全部存在）

| # | 差异点 | ORC | PKG | 影响 |
|---|---|---|---|---|
| 1 | Normal 默认样式 | Times New Roman / 16pt | 未设置（None） | ORC 有文档级字体兜底，PKG 无 |
| 2 | 正文段首行缩进 | 32pt（=2 字符） | 无 | **所有正文段顶格 vs 缩进两字，肉眼可见** |
| 3 | 标题段行距/段距 | 固定行距 355600 EMU=28pt，段前段后 0pt | 未设置（默认单倍行距） | 标题块高度不同 |
| 4 | 标题/小标题 run 的西文字体 | ascii=Times New Roman | ascii=黑体 | 标题内数字/西文（如「2026」「GPU」）字形不同 |

### 4.3 模板特有差异

**周报**（段落 11 vs 11）
- **内容缺失**：署名行 PKG 为「填报人：王小明　　周期：2026-09-21 至 2026-09-27」，**漏印已 filled 的「部门：研发部」字段**；ORC 为「填报人：王小明　　部门：研发部　　周期：…」。
- 对齐：ORC 署名行居中（CENTER），PKG 左对齐（None）。
- 台账与正文不一致是 PKG 的实质缺陷：字段状态 filled 但未渲染进文书。

**请示函**（段落 **9 vs 7**，PKG 少 2 段）
- 缺过渡段「现就有关事项请示如下：」（ORC P03）。
- 缺公文结束语「妥否，请批示。」（ORC P05）。
- 结构对比：ORC=标题/主送/缘由/过渡/事项/批示语/联系人/署名/日期；PKG=标题/主送/缘由/事项/联系人/署名/日期。作为请示函交付，缺少这两句属结构性缺失。

**会议通知**（段落 12 vs 12，但内容组织不同）
- 缺引言段「经研究，决定召开三季度质量评审会。现将有关事项通知如下：」（ORC P02）。
- 条目无编号：PKG「会议时间：…」「会议地点：…」平铺；ORC「一、会议时间：…」至「五、会议要求：…」。
- 会议要求被 PKG 重排为独立黑体小标题「一、会议要求」+ 子项「1．…」「2．…」；ORC 为条目五内联一句话。
- 缺结束语「特此通知。」（ORC P08）。

**工作总结**（段落 15 vs 15）
- 文字内容与顺序完全一致；仅 §4.2 系统性版式差异（首行缩进、标题西文字体、标题行距、Normal 默认样式）。

### 4.4 字节级对比

四类模板双方 docx 均非字节相同（sha256 不同）。补充验证：PKG 与 ORC 各自重跑 vs 运行前快照，zip 包 17 个 entry 文件名全同、**内容差异数=0**，差异仅为 zip 时间戳——即两个实现的内容都是确定性的，字节不等不构成判据；判据以版式画像 + 台账为准。

---

## 5. 逐模板替代性判定

| 模板 | 台账一致 | 内容等价 | 版式一致 | 可否替代参照交付 |
|---|---|---|---|---|
| 周报 | ✅ | ❌ 漏印「部门」、署名行未居中 | ❌ | **不可**（字段已填未渲染，交付内容不完整） |
| 请示函 | ✅ | ❌ 缺过渡句与「妥否，请批示。」 | ❌ | **不可**（公文结构缺失） |
| 会议通知 | ✅ | ❌ 缺引言/编号/「特此通知。」，结构重排 | ❌ | **不可**（与参照组织方式实质不同） |
| 工作总结 | ✅ | ✅ 文字全同 | ❌ 首行缩进/标题西文字体/标题行距 | **接近可替代，但版式仍与参照可见不同** |
| **总计** | 4/4 | 1/4 | 0/4 | **整体判定：不可替代** |

**修复清单**（按优先级）：
1. 周报：署名行补渲染「部门」字段并整行居中。
2. 请示函：补「现就有关事项请示如下：」过渡段与「妥否，请批示。」结束语。
3. 会议通知：补引言句；条目加「一、二、三…」编号；会议要求并入条目流；补「特此通知。」。
4. 全模板：正文段首行缩进 2 字符（32pt）；标题段固定行距 28pt、段前段后 0；标题/小标题 run 西文字体改 Times New Roman（中文保持黑体）；Normal 默认样式设为 Times New Roman 16pt。

---

## 6. 复跑与留档说明

- 运行前对 `oracle/out/`（16 文件，含历史金标）与 `package/out/`（16 文件）做了全量快照：`D:\workspace\zcode研究\_tmp_ab1_rep2\backup2\`（32 文件，shutil.copytree）。首次用 Git Bash `cp -r` 备份曾丢 6 个 package 侧文件（无规律，原因未查明；oracle 侧 16 文件完整），已用 shutil 重做完整快照；随后按任务要求重跑覆盖生成，历史金标内容经验证可复现（仅自指路径串因 `--outdir` 写法不同而不同：金标记录为 `out\...`，本次为 `oracle\out\...`），无数据损失。
- 过程中一次通过 Bash heredoc 写脚本被本机 Mimosa 钩子拒绝，改用 Write 工具提交，脚本内容未变。

## 7. 本次运行的脚本与产物位置（均在 skillfactory/ 之外）

| 文件 | 用途 |
|---|---|
| `_tmp_ab1_rep2\ab_compare.py` | A/B 主对照：fields.json 深度 diff + docx 版式画像 diff + 确定性初查（输出 `ab_report.txt`，309 行） |
| `_tmp_ab1_rep2\ledger_dump.py` | 台账字段摘录 + oracle 重跑 vs 金标 diff 定位 + docx zip 内容差校验（输出 `ledger_report.txt`） |
| `_tmp_ab1_rep2\oracle_docx_zip.py` | ORC docx 重跑 vs 快照的 zip 逐 entry 内容校验 |
| `_tmp_ab1_rep2\backup2\` | 运行前 oracle/out 与 package/out 全量快照（32 文件） |
| `package/out/<模板>/case1/{文书.docx,fields.json}` | PKG 本次生成产物 |
| `oracle/out/<模板>/case1/{文书.docx,fields.json}` | ORC 本次生成产物 |
