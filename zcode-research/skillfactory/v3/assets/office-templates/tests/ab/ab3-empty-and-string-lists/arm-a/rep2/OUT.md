# AB3 空列表/字符串型列表边界 A/B 对照报告（arm-a / rep2）

- 任务：让被测技能（`package/scripts/gen_doc.py`）与参照实现（`oracle/oracle.py`）分别处理 `oracle/inputs/周报/case2.json`（周期空字符串、本周工作内容空数组、问题与需协调事项选填缺失）与 `oracle/inputs/工作总结/case2.json`（总结主体缺失、主要成绩空数组、工作回顾为字符串型列表、存在问题与成文日期选填缺失），对照两边列表字段的占位条目/省略/字符串单项化行为。
- 判定结论：**被测技能通过该边界 —— 空数组=缺失、必填列表缺失→占位条目、选填列表缺失→整节省略、字符串列表→单项化、空串文本→`____`，全部与参照实现记账完全一致（两模板 fields.json 深度 diff 排除输出路径后均 0 差异）；docx 仅 2 处良性结构性差异（详见 §4/§5），不影响列表边界语义。**

---

## 0. 方法与声明

- 按本臂任务要求，**先完整读 `package/SKILL.md` 与 `references/` 全部 4 篇**（周报/请示函/会议通知/工作总结），再严格按其 §3.2 字段语义（F1–F6）与 §9 工作流执行；为裁决节头编号分歧，另查证了 SKILL.md §6 所引口径来源 `spec.md` 的 V6/F4 原文（仅 grep 定位行 77–78、93，未全文精读）。未触碰 `eval/`（golden.json、runner.py）。
- 输入 fixture / 两侧产物（fields.json、docx）的内容均由仓外 Python 岔线脚本程序化读取并只打印派生结论，脚本存于 `D:\workspace\zcode研究\_ab3_arma_rep2_scratch\`（step1_run.py / step2_compare.py / step3_followup.py / step4_invariants.py 及 step2/3/4 输出 txt、step1_runs.json）。
- 运行输出全部写到仓外 scratch，不覆盖 skillfactory 内既有 `out/` 产物；并与仓内既有产物做了确定性核对（§5.4）。
- 环境：Python 3.12.10 + python-docx 1.2.0（与 SKILL.md §8、oracle README 记载一致）。

## 1. 实际执行的命令（原样语义，cwd=`skillfactory/v3/assets/office-templates`）

```
python oracle/oracle.py           --template 周报     --data oracle\inputs\周报\case2.json     --outdir <SCR>\out\oracle\周报\case2
python package/scripts/gen_doc.py --template 周报     --data oracle\inputs\周报\case2.json     --outdir <SCR>\out\package\周报\case2
python oracle/oracle.py           --template 工作总结 --data oracle\inputs\工作总结\case2.json --outdir <SCR>\out\oracle\工作总结\case2
python package/scripts/gen_doc.py --template 工作总结 --data oracle\inputs\工作总结\case2.json --outdir <SCR>\out\package\工作总结\case2
```
（`<SCR>` = `D:\workspace\zcode研究\_ab3_arma_rep2_scratch`。首轮 oracle 侧因脚本路径少写 `oracle\` 前缀报 exit 2「can't open file …\oracle.py」，属我方调用笔误、非实现问题；修正后如下。）

四次运行结果（exit 全 0，产物均恰 2 文件 `fields.json`+`文书.docx`）：

| 运行 | exit | stdout 摘要 |
|---|---|---|
| oracle 周报 | 0 | `OK template=周报 … filled=3 missing=4 missing_required=3` |
| package 周报 | 0 | `已生成…（模板=周报，标题=____工作周报，字段 filled/total=3/7，必填缺失=['部门','周期','本周工作内容']，模板外键=无）` |
| oracle 工作总结 | 0 | `OK template=工作总结 … filled=3 missing=4 missing_required=2` |
| package 工作总结 | 0 | `已生成…（模板=工作总结，标题=____2026年9月工作总结，字段 filled/total=3/7，必填缺失=['总结主体','主要成绩']，模板外键=无）` |

两次汇总计数与 `references/周报.md` §3、`references/工作总结.md` §3 边界示例的**预言逐字吻合**（filled 3/7；missing_required=[部门, 周期, 本周工作内容] / [总结主体, 主要成绩]）。

## 2. 输入边界（读出的 fixture 剖面）

- **周报 case2**（5 键）：`填报人='赵倩'`、**`周期=''（必填文本空串）`**、**`本周工作内容=[]（必填列表空数组）`**、`下周工作计划=['整理缺陷清单并分派责任人']`、`报送日期='2026-09-28'`；完全没有：**部门（必填）**、**问题与需协调事项（选填列表）**。
- **工作总结 case2**（4 键）：`总结时段='2026年9月'`、**`工作回顾='完成评测平台月度巡检'（字符串，非数组）`**、**`主要成绩=[]（必填列表空数组）`**、`下一步工作打算=['制定四季度评测排期']`；完全没有：**总结主体（必填）**、**存在问题（选填列表）**、**成文日期（选填文本）**。

## 3. 列表/空值记账对照（fields.json）

**深度 diff 结果：两个 case 均为 0 处差异**（抹去 `$.outputs` 绝对路径后），被测与参照的台账逐字段一致。

**周报 case2**（两侧一致，7 字段）：

| 字段 | 输入形态 | status | rendered_as | SKILL.md 条款 |
|---|---|---|---|---|
| 部门 | 键不存在 | missing | `以____占位` | F1 |
| 填报人 | "赵倩" | filled | value="赵倩" | — |
| 周期 | `""` 空串 | missing | `以____占位` | 缺失判定+F1 |
| **本周工作内容** | **`[]` 空数组** | missing | **`以____占位条目`** | F4 必填 |
| 下周工作计划 | 1 元素数组 | filled | value=["整理缺陷清单并分派责任人"] | — |
| **问题与需协调事项** | **键不存在（选填列表）** | missing | **`省略该条目/小节`** | F4 选填 |
| 报送日期 | "2026-09-28" | filled | value="2026-09-28" | — |

summary：total=7, filled=3, missing=4, missing_required=3, names=[部门, 周期, 本周工作内容], unknown_keys=[]。

**工作总结 case2**（两侧一致，7 字段）：

| 字段 | 输入形态 | status | rendered_as / value | SKILL.md 条款 |
|---|---|---|---|---|
| 总结主体 | 键不存在 | missing | `以____占位` | F1 |
| 总结时段 | "2026年9月" | filled | value="2026年9月" | — |
| **工作回顾** | **字符串（必填列表）** | filled | **value=`["完成评测平台月度巡检"]`**（单项化入账） | F3 |
| **主要成绩** | **`[]` 空数组** | missing | **`以____占位条目`** | F4 必填 |
| **存在问题** | **键不存在（选填列表）** | missing | **`省略该条目/小节`** | F4 选填 |
| 下一步工作打算 | 1 元素数组 | filled | value=["制定四季度评测排期"] | — |
| **成文日期** | **键不存在（选填文本）** | missing | **`留空（渲染为空字符串）`** | F2 |

summary：total=7, filled=3, missing=4, missing_required=2, names=[总结主体, 主要成绩], unknown_keys=[]。

要点：**空数组没有被当成「已填空列表」，两侧一致归为缺失**；**字符串型列表两侧一致单项化为数组入账（value 是数组而非字符串）**；三种 rendered_as 文案（以____占位 / 以____占位条目 / 省略该条目/小节 / 留空（渲染为空字符串））两侧逐字一致。

## 4. 渲染对照（文书.docx 段落，程序化抽取全文）

**周报 case2**（两侧各 7 段，仅 p01 一处文本差异）：

| 段 | oracle | package |
|---|---|---|
| 标题 | `____工作周报` | 同左 |
| 基本信息行 | `填报人：赵倩　　部门：____　　周期：____`（3 段式） | `填报人：赵倩　　周期：____`（2 段式） |
| 节头/条目 | `一、本周工作内容`→`1．____`；`二、下周工作计划`→`1．整理缺陷清单并分派责任人` | 同左 |
| 小节三 | **不出现**（选填缺失整节省略 ✓） | 同左 |
| 落款 | `报送日期：2026-09-28` | 同左 |

**工作总结 case2**（两侧各 9 段，仅 p05 一处文本差异）：

| 段 | oracle | package |
|---|---|---|
| 标题 | `____2026年9月工作总结` | 同左 |
| 一、工作回顾 | `1．完成评测平台月度巡检`（字符串单项化成条目 ✓） | 同左 |
| 二、主要成绩 | `1．____`（必填空列表→占位条目 ✓） | 同左 |
| 三/四、下一步工作打算 | `三、下一步工作打算`→`1．制定四季度评测排期` | `四、下一步工作打算`→`1．制定四季度评测排期` |
| 落款 | `____`（落款一）→ 空段（成文日期缺，落款二空段，末个非空段仍落款一） | 同左 |

**列表边界行为核对（SKILL.md F3/F4 声明 vs docx 实况，两侧全部兑现）**：

| 声明行为 | oracle 实况 | package 实况 |
|---|---|---|
| 必填列表空数组→节头保留+`1．____` 占位条目（本周工作内容/主要成绩） | `一、本周工作内容`+`1．____`、`二、主要成绩`+`1．____` ✓ | 同左 ✓ |
| 选填列表缺失→整节省略、文中无节头（问题与需协调事项/存在问题） | `三、`节头 0 次出现（存在问题字样 0 次）✓ | 同左 ✓ |
| 字符串列表→单项化（工作回顾） | `1．完成评测平台月度巡检` ✓ | 同左 ✓ |
| 必填文本空串/缺失→`____`（周期/部门/总结主体） | 标题+信息行 `____`（全文 4 处）✓ | 标题+信息行 `____`（全文 3 处）✓ |
| 选填文本缺失→留空/空段（成文日期） | 落款二为空段 ✓ | 同左 ✓ |

## 5. 边界语义判定与如实记录的差异

**判定：通过（两侧均通过，被测无任何编造迹象）。** 依据（全部为本次实测）：

1. **记账如实且一致**：两模板 fields.json 深度 diff（抹 `$.outputs` 路径）均 0 差异（§3）；空数组=缺失、字符串=单项化、选填缺失也记账，计数自洽（7=3+4 两模板）。
2. **不编造**：成文日期缺失的工作总结两侧均无独立日期段（全文日期型字符串仅 `2026年9月`，即输入已填的总结时段出现在标题中，两侧各 1 次）；存在问题/问题与需协调事项未出现任何代填条目；`____` 计数：工作总结两侧 3=3，周报 oracle 4 / package 3（差异见下条）。
3. **缺数据必有可见交代**：必填列表缺失渲染为显式 `1．____` 占位条目（节头保留），选填列表缺失整节省略不出现节头，绝不代填——与 SKILL.md §3.2 F4 及两篇 references 边界示例的预言完全一致。
4. **内容级确定性**：scratch 新跑与仓内既有产物（`oracle/out`、`package/out` 同名 case2）比对——两侧、两模板 ledger 差异均仅 2 处且全部是 `$.outputs.{docx,fields_json}` 的相对路径 vs 绝对路径字样，**docx 段落文本 4/4 完全一致**，台账其余内容逐字节等价。

**如实记录的差异（非边界语义问题，均为固定文案/结构取舍，且两侧各自确定复现）**：

- 周报基本信息行：oracle 渲染 3 段式并补 `部门：____`；package 为 2 段式（部门只进标题）。`references/周报.md` §1 的信息行公式恰为 `填报人：{填报人}　　周期：{周期}`（无部门段）——**package 与其技能声明公式吻合，oracle 多补一段**（其 `____` 总数 4 vs package 3 即源于此）。
- 工作总结节头编号：省略选填节「三、存在问题」后，oracle 重排为 `三、下一步工作打算`（连续无跳号），package 按固定序号保持 `四、`。`references/工作总结.md` §1 结构表钉死该节头公式为序 8 `四、下一步工作打算`（`spec.md` V6 只说「按一、二、三、编小节…选填小节整节省略」，未直接规定重编号）——**package 与其技能声明结构表吻合，oracle 做了跳号重排**。两者各自内部一致，属口径取舍而非语义错误。

## 6. 附加校验

- **台账自洽性（SKILL.md §5 不变量）**：4 份 ledger（2 模板×两侧）逐份检查顶层 7 键、fields 明细键集、filled⇒value 非空且 list 为数组、missing⇒value=null 且带 rendered_as、summary 6 键与计数（filled+missing=total）、missing_required_names 一致、filled_fields/missing_fields 序列一致、`title`==文书首个非空段全文——**0 错误**；标题公式（V2）预期 `____工作周报` / `____2026年9月工作总结` 两侧均精确命中。
- **oracle 自带校验器**：`python verify.py`（cwd=oracle）exit 0，`共 8 份产物: PASS=8 FAIL=0`——参照实现自身版式不变量健康。

## 7. 复现信息

- 机器：windev-01（Windows Server 2022），Python 3.12.10，python-docx 1.2.0；工作目录 `D:\workspace\zcode研究\skillfactory\v3\assets\office-templates`。
- 岔线脚本与全部原始输出：`D:\workspace\zcode研究\_ab3_arma_rep2_scratch\`（step1_runs.json、step2_out.txt、step3_out.txt、step4_out.txt）。
- 局限：本结论基于黑盒运行行为与产物对比（按任务要求先读了 SKILL.md/references 作对照口径，但未读 `gen_doc.py`/`oracle.py` 源码）；`eval/` 未触碰。
