# AB2 必填缺失边界 A/B 对照报告 — arm-b / rep1

- **日期**：2026-09-30（本机 windev-01，Python 3.12.10 + python-docx 1.2.0，与 SKILL.md §8 实测版本一致）
- **判定问题**：对「必填键缺失 / 必填空字符串 / 选填缺失 / 模板外键」边界输入，被测是否做到**缺数据不编造、如实记账**
- **被测方（A）**：office-templates 技能包生成器 `package/scripts/gen_doc.py`（SKILL.md §4 冻结 CLI）
- **参照方/oracle（B）**：`oracle/oracle.py`，另以既有基线产物 `oracle/out/<模板>/case2/` 做可复现性锚定
- **输入**：`oracle/inputs/请示函/case2.json`、`oracle/inputs/会议通知/case2.json`（任务书指定两份边界样例）
- **产物落位**：本 rep1 目录 `_work/` 下，A → `_work/a/<模板>/case2/`，B → `_work/b/<模板>/case2/`（两边对称落沙箱，未写入 `package/out` 与 `oracle/out`，保持共享状态零改动）
- **方法依据**：先完整读 `package/SKILL.md` 与 `package/references/` 全部 4 篇（请示函/会议通知/周报/工作总结），按 SKILL.md §3.2（F1–F6）、§6（V7 占位符）、§9（Agent 工作流第 3/4 步：调用引擎→核对台账）执行；对照基准取 `spec.md` §9 边界样例期望表与 `references/<模板>.md` §3 边界示例

## 0. 输入边界盘点（读入原文核验）

| 输入 | 必填缺失（键不存在） | 必填空字符串 | 选填缺失 | 模板外键 | 其余 filled |
|---|---|---|---|---|---|
| 请示函/case2 | 主送机关 | 请示事项:`""` | 联系电话、成文日期 | 无 | 请示事由、请示缘由、请示单位、联系人 |
| 会议通知/case2 | 会议名称 | 会议地点:`""` | 会议议题、会议要求、联系人、联系电话 | `备注`（值含"此键不在模板字段内…"） | 召开单位、主送对象、会议时间、参会人员、发文日期 |

## 1. 执行的命令与退出码（逐条实测）

```bash
# 参照方（B），cwd = skillfactory/v3/assets/office-templates
python oracle/oracle.py --template 请示函 --data oracle/inputs/请示函/case2.json --outdir <_work>/b/请示函/case2
# → exit=0，stdout：OK template=请示函 … filled=4 missing=4 missing_required=2
python oracle/oracle.py --template 会议通知 --data oracle/inputs/会议通知/case2.json --outdir <_work>/b/会议通知/case2
# → exit=0，stdout：OK template=会议通知 … filled=5 missing=6 missing_required=2

# 被测方（A）
python package/scripts/gen_doc.py --template 请示函 --data oracle/inputs/请示函/case2.json --outdir <_work>/a/请示函/case2
# → exit=0，stdout：已生成…（模板=请示函，标题=关于延期举办季度评审会的请示，字段 filled/total=4/8，
#    必填缺失=['主送机关', '请示事项']，模板外键=无）
python package/scripts/gen_doc.py --template 会议通知 --data oracle/inputs/会议通知/case2.json --outdir <_work>/a/会议通知/case2
# → exit=0，stdout：已生成…（模板=会议通知，标题=关于召开____的通知，字段 filled/total=5/11，
#    必填缺失=['会议名称', '会议地点']，模板外键=['备注']）
```

4/4 exit=0（**C3 边界不是错误**：双方均正常产出、正常退出）。每份 outdir 恰含 `文书.docx + fields.json` 两个文件（`ls` 实证 4/4）。A 的 stdout 摘要行如实报出必填缺失名单与模板外键，与台账一致。

## 2. 缺失记账对照（fields.json）— 两模板 A vs B 均 **0 差异** ✅

用深度 diff（忽略 `$.outputs.*` 自引用路径）逐键比较：

```
[DIFF fields.json A vs B（忽略 outputs）] 完全一致（0 差异）   # 请示函/case2
[DIFF fields.json A vs B（忽略 outputs）] 完全一致（0 差异）   # 会议通知/case2
```

双方记账明细（逐项一致），并与 `spec.md` §9 期望表逐项吻合：

| 项 | 期望（spec §9） | A 实测 | B 实测 |
|---|---|---|---|
| 请示函 title | 关于延期举办季度评审会的请示 | ✅ 同 | ✅ 同 |
| 请示函 filled/total | 4/8 | ✅ 4/8 | ✅ 4/8 |
| 请示函 missing_required_names | [主送机关, 请示事项] | ✅ 同 | ✅ 同 |
| 请示函 选填 missing | 联系电话、成文日期（rendered_as=留空（渲染为空字符串）） | ✅ 同 | ✅ 同 |
| 请示函 unknown_keys | — | ✅ [] | ✅ [] |
| 会议通知 title | `关于召开____的通知` | ✅ 同 | ✅ 同 |
| 会议通知 filled/total | 5/11 | ✅ 5/11 | ✅ 5/11 |
| 会议通知 missing_required_names | [会议名称, 会议地点] | ✅ 同 | ✅ 同 |
| 会议通知 选填 missing | 会议议题(留空)、会议要求(省略该条目/小节)、联系人(留空)、联系电话(留空) | ✅ 同 | ✅ 同 |
| 会议通知 unknown_keys | [备注] | ✅ ["备注"] | ✅ ["备注"] |

规范自检（S1/S2/S3，程序化）：两边 4/4 **PASS**——顶层恰 7 键；明细项 `{name,required,kind,status,value}`（missing 另含 `rendered_as`、value=null；filled value=strip 后非空）；summary 恰 6 键且计数自洽（filled+missing=total、missing_required_names 与明细吻合）；`rendered_as` 四种取值文案与 SKILL.md §3.2 逐字一致。

## 3. 占位渲染对照（文书.docx）— F1 占位齐全；F2/F4 行为有一处 A/B 分歧

### 3.1 必填缺失 → `____` 占位（V7/F1）：两边齐全，语义位置一致

| 输入 | A（被测） | B（参照） |
|---|---|---|
| 请示函 | `____：` 称谓（**顶格**，firstLineChars=0 实测）；请示事项段独立 `____` 段。共 2 处 | 同 A，共 2 处 |
| 会议通知 | 标题 `关于召开____的通知`、`会议地点：____`。共 2 处 | 同上 2 处 **外加**引言 `经研究，决定召开____。` 再复述 1 处，共 3 处 |

（B 多出的第 3 处是 B 自带引言句对「会议名称」占位的重复，非 A 漏占位。）

### 3.2 选填缺失渲染（F2/F4）——A/B 实际段落逐段 dump 后的唯一实质分歧

| 边界 | SKILL.md §3.2 / references 口径 | A 实测 | B 实测 |
|---|---|---|---|
| 请示函 联系电话缺失 | `联系电话：` 标签保留、值留空（F2） | 段5 `联系人：李工　　联系电话：` ✅ | 同 A ✅ |
| 请示函 成文日期缺失 | 渲染空串→空段（F2），末个非空段落款一仍右对齐 | 段7 空、右对齐 ✅ | 同 A ✅ |
| 会议通知 会议议题缺失 | `会议议题：` **标签保留、值留空**（F2，references/会议通知.md §2/§3 明示） | 段6 `会议议题：` ✅ **符合口径** | **整行省略**（无该段）⚠️ |
| 会议通知 会议要求缺失 | 小节整节省略、无节头（F4） | 无「一、会议要求」节 ✅ | 同 A ✅ |
| 会议通知 联系人+联系电话均缺 | 联系行 `联系人：　　联系电话：`（references/会议通知.md §3 边界示例原文） | 段7 `联系人：　　联系电话：` ✅ **符合口径** | **整行省略**（无该段）⚠️ |

⚠️ 的后果：B 的台账对会议议题/联系人/联系电话记 `rendered_as="留空（渲染为空字符串）"`，但其 docx 实际是**整行不出现**——B 的记账措辞与 B 的文书在这 3 项上不自洽；A 的 rendered_as 与 A 的文书逐项对得上（`grep` 级核对：A 的 4 项选填缺失渲染方式与台账声明一一吻合）。即：**在「如实」的细节上 A 反而更自洽，B 偏离了双方共享的 F2 口径**（oracle 源码 `if topic:` / `if contact or phone:` 所致，oracle/oracle.py:231,238）。

### 3.3 与边界无关的既有结构差异（不影响本判定，录以备考，同 AB1 结论）

- B 多公文固定文案：请示函 `现就有关事项请示如下：`+`妥否，请批示。`（9 段 vs A 7 段）；会议通知引言+`特此通知。`+事项「一、二、三、」编号。而 `references/请示函.md` §1 的成文结构恰为 7 段（无过渡句/结语）、`references/会议通知.md` §1 中时间/地点/人员为无编号正文段——**A 的段落结构反而与技能自带 references 逐段一致，B 超出 references 结构**。
- 版式：A 标题段未设 28 磅固定行距（ls=None），B 标题设了（AB1 已录的 L3 系统差异）。

## 4. 编造检测与模板外键（F6）— 两边全 PASS ✅

程序化检测（`_work/ab2_compare.py`）：对每份 docx 的每个非空段，验证其文本可完全分解为「输入数据 strip 值 ∪ 模板固定公式/标签词 ∪ 标点编号」，剩余残差为空：

```
[A] 编造检测: PASS（全文文本均可由输入值+模板固定公式解释，无凭空内容）   # 请示函
[B] 编造检测: PASS                                                       # 请示函
[A] 编造检测: PASS                                                       # 会议通知
[B] 编造检测: PASS                                                       # 会议通知
```

即：缺失的电话/日期/会议名称**没有被任何一方编造**（A 无虚构号码/日期/名称；B 的引言只复用占位符）；`备注` 键及其值在 A、B 四份 docx 中均未出现（显式 `in` 检索 = False，F6「不影响文书」成立）。

## 5. 参照基线可复现性 + oracle 自带验收器

- **B 基线锚定**：本次 B fresh 重跑 vs 既有 `oracle/out/<模板>/case2/`——两模板 fields.json（除 outputs）一致=True、docx 段落文本一致=True（docx sha 不同仅因 zip 内嵌时间戳，语义层全同）。**对照是在可信基线上进行的。**
- **verify.py（oracle 自设门槛，含「必填缺失>0 ⇒ 文书含 ____」「称谓顶格」「落款右对齐」不变量）**：
  - `python oracle/verify.py <_work>/a` → **共 2 份产物: PASS=2 FAIL=0，exit=0**
  - `python oracle/verify.py <_work>/b` → **共 2 份产物: PASS=2 FAIL=0，exit=0**

## 6. 判定结论：**被测做到「缺数据不编造、如实记账」 ✅（对参照可整体替代）**

1. **不编造**：两份边界输入下，A 全文无一处凭空内容（§4 PASS）；必填缺失一律 `____`（标题/称谓/正文/地点行共 4 个语义位全占位），选填缺失仅「标签留空/空段/整节省略」，模板外键不泄入文书。
2. **如实记账**：A 的 fields.json 与参照 B **逐字节级等价（除 outputs 自引用路径外 0 差异）**，且与 spec §9 期望表逐项吻合；S1/S2/S3 自洽；退出码 0 + stdout 摘要如实报出缺失名单与外键（C3）。通过 oracle 自带 verify.py 2/2。
3. **加分项**：在会议通知 case2 上，A 的文书渲染与自身台账 `rendered_as` 及 SKILL.md F2/references 口径完全自洽；**B 反而出现 3 处「台账称留空、文书实为整行省略」的措辞失真**。就本判定问题而言，A 不弱于参照，细节自洽性强于参照。
4. **遗留差异（不影响本判定）**：B 多引言/过渡句/结语/编号等固定文案、标题行距版式差异（§3.2/§3.3）——属 AB1 已定性的结构性/版式项；就「占位渲染与缺失记账」而言两等级一致（占位齐全、记账零差异）。

## 7. 证据与工件索引

- 本目录 `_work/`：`ab2_compare.py`（fields 深度 diff + docx 段落级 dump + 占位清点 + 编造检测）；`a/<模板>/case2/`、`b/<模板>/case2/`（双方 4 份产物，各恰 2 文件）
- §1 四条命令及 stdout、§2 diff 输出、§3 段落 dump、§4 编造检测输出、§5 verify.py 输出均为本次实跑原文（见会话执行记录与脚本输出）
- sha256（前 16 位）：A 请示函 docx=`ab9150dce5ba5e58`/fields=`b333fee6199f2cba`；B 重跑 docx=`157868877c186818`/fields=`f38353c26e7944a8`；B 基线 docx=`87a4d82bae93a3ed`/fields=`4dce6c7fab1e3a82`；A 会议通知 docx=`f1d18b60c5b9aa16`/fields=`0b4b1cad7226e3c6`；B 重跑 docx=`031fa15400f1bb97`/fields=`f2027fc7a1c774f7`；B 基线 docx=`ef4973b6fc690264`/fields=`edb0d80dbfb7064c`
- **未做事项**：D1 同输入双跑确定性核验未执行（非本 AB 判定问题）；docx 渲染级目检未做（SKILL.md §8 明示不做真实渲染目检，判定基于 OOXML 语义层）；退出码 2 负路径不在本任务两份输入范围内，未触发
