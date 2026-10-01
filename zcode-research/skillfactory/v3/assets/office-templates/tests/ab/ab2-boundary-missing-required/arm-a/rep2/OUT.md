# AB2 必填缺失边界 A/B 对照报告（arm-a / rep2）

- 任务：让被测技能（`package/scripts/gen_doc.py`）与参照实现（`oracle/oracle.py`）分别处理 `oracle/inputs/请示函/case2.json` 与 `oracle/inputs/会议通知/case2.json`，对照两边占位渲染与缺失记账，判定被测是否做到「缺数据不编造、如实记账」。
- 判定结论：**被测技能通过该边界 —— 缺数据不编造、如实记账，与参照实现记账完全一致（除输出路径外 0 差异）；docx 结构性差异不影响诚实性（详见 §5）。**

---

## 0. 方法与合规声明

- 本臂为盲评基线臂：**未读取 skillfactory/ 下任何文件内容**（含 SKILL.md、references/、oracle.py / gen_doc.py 源码、golden.json）。获取入口的方式仅是**列出目录名**（`find -maxdepth 3`，只看文件名）与**运行脚本 `--help`**（运行产物为 stdout，非读源码）。
- 两个实现的调用方式由 `--help` 实测得出，两者 CLI 完全同构：`--template {周报,请示函,会议通知,工作总结} --data <json> --outdir <目录>`。
- 输入 fixture / 两侧产物（fields.json、docx）的内容均由我方 Python 岔线脚本**程序化读取并只打印派生结论**（沿用上一轮 ab1 的对照惯例），脚本存于仓外 `D:\workspace\zcode研究\_ab2_arma_rep2_scratch\`（run_ab2.py / compare_ab2.py / verify2.py）。
- 运行输出写到仓外 scratch 目录，不覆盖 skillfactory 内既有 `out/` 产物；运行前已将既有产物备份到 scratch，用于确定性核对。

## 1. 实际执行的命令（原样）

```
# 备份既有产物 + 四次运行（scratch 下各生成 fields.json + 文书.docx，全部 exit=0）
python oracle/oracle.py          --template 请示函   --data oracle/inputs/请示函/case2.json   --outdir <SCR>\out\oracle\请示函\case2
python package/scripts/gen_doc.py --template 请示函   --data oracle/inputs/请示函/case2.json   --outdir <SCR>\out\package\请示函\case2
python oracle/oracle.py          --template 会议通知 --data oracle/inputs/会议通知/case2.json --outdir <SCR>\out\oracle\会议通知\case2
python package/scripts/gen_doc.py --template 会议通知 --data oracle/inputs/会议通知/case2.json --outdir <SCR>\out\package\会议通知\case2
```

四次运行的 stdout（实现自报的记账摘要）：

| 运行 | exit | stdout 摘要 |
|---|---|---|
| oracle 请示函 | 0 | `OK … filled=4 missing=4 missing_required=2` |
| package 请示函 | 0 | `已生成…（模板=请示函，标题=关于延期举办季度评审会的请示，字段 filled/total=4/8，必填缺失=['主送机关','请示事项']，模板外键=无）` |
| oracle 会议通知 | 0 | `OK … filled=5 missing=6 missing_required=2` |
| package 会议通知 | 0 | `已生成…（模板=会议通知，标题=关于召开____的通知，字段 filled/total=5/11，必填缺失=['会议名称','会议地点']，模板外键=['备注']）` |

## 2. 输入边界（harness 读出的 fixture 剖面）

- **请示函 case2**（5 个键）：`请示事由='延期举办季度评审会'`、`请示缘由='因关键评审人出差，原定会议时间无法保证评审质量。'`、**`请示事项=''`（空串，模板内必填）**、`请示单位='评测技术部'`、`联系人='李工'`；输入完全没有：**主送机关（必填）**、**联系电话（选填）**、**成文日期（选填）**。
- **会议通知 case2**（7 个键）：`召开单位/主送对象/会议时间/参会人员/发文日期` 均有值；**`会议地点=''`（空串，模板内必填）**；完全没有：**会议名称（必填）**、会议议题/会议要求（list）/联系人/联系电话（选填）；另含**模板外键 `备注`**（值=「此键不在模板字段内，用于测试 unknown_keys 记录」）。

## 3. 缺失记账对照（fields.json）

两侧 ledger 顶层结构同构：`template / title / filled_fields / missing_fields / fields[]（含 required/kind/status/value/rendered_as）/ summary{total,filled,missing,missing_required,missing_required_names,unknown_keys} / outputs`。

**深度 diff 结果（排除 `$.outputs` 路径与我注入的 docx 段落探针后）：两个 case 均为 0 处差异** —— 被测与参照的记账逐字段一致。

| 记账项 | 请示函 case2（两侧一致） | 会议通知 case2（两侧一致） |
|---|---|---|
| filled | 请示事由、请示缘由、请示单位、联系人（4） | 召开单位、主送对象、会议时间、参会人员、发文日期（5） |
| missing | 主送机关、请示事项、联系电话、成文日期（4） | 会议名称、会议地点、会议议题、会议要求、联系人、联系电话（6） |
| summary | total=8, filled=4, missing=4, **missing_required=2**，names=[主送机关, 请示事项]，unknown_keys=[] | total=11, filled=5, missing=6, **missing_required=2**，names=[会议名称, 会议地点]，unknown_keys=**[备注]** |
| 空串处理 | `请示事项`（必填空串）→ status=missing、value=null、rendered_as=「以____占位」 | `会议地点`（必填空串）→ 同左；`会议议题/联系人/联系电话`（选填）→「留空（渲染为空字符串）」；`会议要求`（选填 list）→「省略该条目/小节」 |

要点：**空串被正确归为「缺失」而非「已填」**；未出现的选填键也被如实记账；模板外键 `备注` 被两侧同样记入 `unknown_keys`（被测还在 stdout 显式报出 `模板外键=['备注']`）。记账与 §2 的输入真值完全吻合。

## 4. 占位渲染对照（文书.docx 全文段落）

**请示函 case2**（oracle 9 段 / package 7 段）：

| # | oracle | package |
|---|---|---|
| 标题 | 关于延期举办季度评审会的请示 | 同左 |
| 主送 | `____：` | `____：` |
| 缘由 | 因关键评审人出差，原定会议时间无法保证评审质量。 | 同左 |
| 引导句 | `现就有关事项请示如下：` | （无此段） |
| 请示事项 | `____` | `____` |
| 结束语 | `妥否，请批示。` | （无此段） |
| 联系行 | `联系人：李工　　联系电话：`（电话空） | 同左 |
| 落款 | 评测技术部 / （成文日期空段） | 同左 |

**会议通知 case2**（两侧各 9 段）：

| # | oracle | package |
|---|---|---|
| 标题 | `关于召开____的通知` | 同左 |
| 主送 | `各部门：` | 同左 |
| 引言 | `经研究，决定召开____。现将有关事项通知如下：` | （无此段） |
| 条目 | `一、会议时间：2026年10月16日（周五）10:00`／`二、会议地点：____`／`三、参会人员：全体评测组成员` | `会议时间：…`／`会议地点：____`／`参会人员：…` |
| 会议议题 | （整行省略） | `会议议题：`（空值，按 rendered_as 留空） |
| 联系行 | （整行省略） | `联系人：　　联系电话：`（空值） |
| 结尾 | `特此通知。`／评测技术部／`2026年9月30日` | 同左 |

**渲染一致性核对（rendered_as 声明 vs docx 实况，实测）**：

| 字段（声明） | oracle 实况 | package 实况 |
|---|---|---|
| 请示函/主送机关（以____占位） | `____：` ✓ | `____：` ✓ |
| 请示函/请示事项（以____占位） | `____` ✓ | `____` ✓ |
| 请示函/联系电话（留空） | `联系电话：` 空值 ✓ | 同左 ✓ |
| 会议通知/会议名称（以____占位） | 标题+引言中 `____` ✓ | 标题中 `____` ✓ |
| 会议通知/会议地点（以____占位） | `会议地点：____` ✓ | `会议地点：____` ✓ |
| 会议通知/会议议题、联系人（留空） | **整行省略，与其自身声明不符** | 空值标签行，与声明一致 ✓ |
| 会议通知/会议要求（省略条目） | 省略 ✓ | 省略 ✓ |

即：**被测对自身声明的兑现度反而高于参照**（参照在会议通知上把声明「留空」的选填文本行整行删了）。

## 5. 「缺数据不编造、如实记账」判定

**判定：通过（两侧均通过，被测无任何编造迹象）。** 依据（全部为本次实测）：

1. **记账如实**：fields.json 深度 diff 排除输出路径后 0 差异；空串=缺失、缺键=缺失、选填缺失也记账、外键 `备注` 入 unknown_keys、missing_required_names 与计数（8=4+4、11=5+6）全部与输入真值吻合（§3）。
2. **不编造**：对全部缺省字段做编造针检——电话正则 `\d{3,4}-\d{7,8}|1\d{10}` 在**两侧全部产物中 0 命中**；日期正则在请示函两侧 **0 命中**（成文日期缺失就没有日期，连落款都是空段），在会议通知两侧仅命中**输入里真实存在的两个日期**（会议时间 2026年10月16日、发文日期 2026年9月30日）；`备注` 的值（含「此键不在模板字段内」字样）**未泄漏进任何一侧 docx**。
3. **缺数据必有可见交代**：必填缺失一律渲染为显式 `____` 占位（含标题「关于召开____的通知」），选填缺失按声明留空或整节约省略，绝不代填。
4. **内容级确定性**：本次 scratch 重跑与 skillfactory 内既有产物（先前流水线所产）逐项核对——**4/4（两模板×两侧）ledger（抹去 $.outputs 后）与 docx 正文文本完全一致**；字节级不等仅源于 zip 时间戳与内嵌输出路径，属良性。

**如实记录的差异（非诚实性问题，均为版式/结构取舍）**：

- 请示函：oracle 多渲染两段固定套话（`现就有关事项请示如下：`、`妥否，请批示。`），被测省略（9 段 vs 7 段）；两侧占位 `____` 数量相同（2=2）。
- 会议通知：oracle 有引言句「经研究，决定召开____」与「一、二、三」编号条目（`____` 3 处），被测为无编号平铺（`____` 2 处）。
- 参照实现自身在会议通知上未兑现其「留空（渲染为空字符串）」声明（整行省略）；被测兑现了。此为**参照侧**的自洽性小瑕疵，与被测无关。

## 6. 复现信息

- 机器：windev-01（Windows Server 2022），Python 3.12；工作目录 `D:\workspace\zcode研究\skillfactory\v3\assets\office-templates`。
- 岔线脚本与全部原始输出：`D:\workspace\zcode研究\_ab2_arma_rep2_scratch\`（run_ab2.py、compare_ab2.py、verify2.py、compare_out.txt）。
- 局限：本臂受盲评限制未读取任何实现源码/技能文档，以上结论全部基于黑盒运行行为与产物对比；`eval/`（golden.json、runner.py）未触碰。
