# OUT · hot-templates 公众号文章爆款骨架（ab-003 / arm-a / rep1）

## 1. 任务与材料（均来自任务指令本身）

- platform: **wx**（公众号文章）
- topic: **非暴力沟通**
- points: **`[]`**（空列表，零卖点边界）
- 冻结模板: **引子 + 三段论（是什么/为什么/怎么办）+ 金句收尾**（5 要素，模板版本 1.0）
- 产物: 本目录 `骨架.md`、`structure.json`、本文件 `OUT.md`

## 2. 执行方法（严格按 SKILL.md）

- 先完整读 `package/SKILL.md`（109 行全文）与 `package/references/` 全部 5 份：
  `wx.md`（本平台规范）、`frozen-tokens.md`（占位符 token/填充语义权威常量表）、`dy.md`、`xhs.md`、`video.md`（文档地图要求完整读完对应平台那份，另三份一并读毕）。
- 遵守红线 4：骨架生成一律走 `scripts/gen.py` 确定性渲染引擎，**未手写或改写 `structure.json`**。
- 遵守红线 3：`【占位:…】` 为开放槽位，本次**未编造任何内容填充**——0 卖点时三个抓手按冻结口径全部落 `【占位:价值点N】`。

## 3. 生成命令与结果（本次实跑）

```
cd D:\workspace\zcode研究
python skillfactory/v4/assets/hot-templates/package/scripts/gen.py \
  --platform wx --topic 非暴力沟通 --points '[]' \
  --outdir skillfactory/v4/assets/hot-templates/tests/ab/ab-003/arm-a/rep1
```

- 运行环境：Python 3.12.10（Windows，Git Bash 壳层）
- 退出码：**0**
- stdout（SKILL.md 使用步骤 3 判据行）：
  `OK platform=wx topic=非暴力沟通 elements=5 open_placeholders=13 filled_from_input=4 -> skillfactory/v4/assets/hot-templates/tests/ab/ab-003/arm-a/rep1`
- 产物落盘：`骨架.md`（2029 字节）、`structure.json`（3957 字节），均存在且非空

## 4. 骨架成品（`骨架.md` 全文，逐字）

```markdown
# 公众号文章 · 爆款骨架

- 主题：非暴力沟通
- 平台/模板：`wx` @ v1.0（引子 + 三段论 + 金句收尾）
- 卖点输入：0 条 → 规整为 3 条（缺失补占位 3 条，超出截断 0 条）

---

## 1. 引子

【占位:用一个具体场景/对话/新闻切入，150字左右】——这背后，其实是同一个问题：非暴力沟通。

> 写法要点：场景化开场，把读者拉进问题现场

## 2. 三段论·一（是什么）

一、是什么
非暴力沟通的本质，不是【占位:常见误解】，而是【占位:一句话给出你的定义】。

> 写法要点：先破后立，给出定义

## 3. 三段论·二（为什么）

二、为什么
大多数人在非暴力沟通上反复失败，根源有三：【占位:根因1】；【占位:根因2】；【占位:根因3】。

> 写法要点：归因，三条根因对齐后文三个抓手

## 4. 三段论·三（怎么办）

三、怎么办
落到操作层面，给你三个抓手：
1. 【占位:价值点1】——【占位:展开：具体做法+一个例子】
2. 【占位:价值点2】——【占位:展开：具体做法+一个例子】
3. 【占位:价值点3】——【占位:展开：具体做法+一个例子】

> 写法要点：三个抓手一一对应三条根因，可执行

## 5. 金句收尾

「非暴力沟通这件事，【占位:金句主体——句式建议：真正的…不是靠…，而是靠…】」
共勉。

> 写法要点：一句话收束，可直接被读者摘抄转发

---

## 占位符统计

- 未填占位符（待人工/AI 补写）：**13 处**
- 已从输入填充：4 处（topic、topic、topic、topic）
  - 1. 引子：1 处
  - 2. 三段论·一（是什么）：2 处
  - 3. 三段论·二（为什么）：3 处
  - 4. 三段论·三（怎么办）：6 处
  - 5. 金句收尾：1 处

> 说明：所有 `【占位:…】` 为开放槽位，由使用者补写；`structure.json` 为机器可读的结构要素清单与占位符统计，与本文同源同构。
```

## 5. structure.json 摘要（机读全文见本目录该文件）

- 顶层 11 键齐备：`template_version="1.0"`、`platform="wx"`、`platform_name="公众号文章"`、`structure_name="引子 + 三段论 + 金句收尾"`、`topic="非暴力沟通"`、`points_input_count=0`、`points_used=[null,null,null]`、`points_unused=[]`、`element_count=5`、`elements`（5 项）、`placeholder_stats`
- 要素明细（id / name / order / placeholder_count / open_placeholders / filled_from_input）：

| id | name | order | 占位符 | open_placeholders（去重 token） | filled_from_input |
| --- | --- | --- | --- | --- | --- |
| lead_in | 引子 | 1 | 1 | 用一个具体场景/对话/新闻切入，150字左右 | ["topic"] |
| thesis_what | 三段论·一（是什么） | 2 | 2 | 常见误解、一句话给出你的定义 | ["topic"] |
| thesis_why | 三段论·二（为什么） | 3 | 3 | 根因1、根因2、根因3 | ["topic"] |
| thesis_how | 三段论·三（怎么办） | 4 | 6 | 价值点1..3 + 展开：具体做法+一个例子（×3，去重后 1 token） | [] |
| golden_ending | 金句收尾 | 5 | 1 | 金句主体——句式建议：真正的…不是靠…，而是靠… | ["topic"] |

- `placeholder_stats`：total_open=13；total_filled_from_input=4；by_element={lead_in:1, thesis_what:2, thesis_why:3, thesis_how:6, golden_ending:1}；filled_slots=["topic","topic","topic","topic"]；UTF-8/LF、文件尾单换行。

## 6. 校验记录（本次实际执行的命令与输出）

1. **成功判据三条**（SKILL.md 使用步骤 3）：exit 0 ✓；stdout OK 行 ✓（见 §3）；两份产物存在且非空（`ls -la`：2029 B / 3957 B）✓。
2. **oracle 逐字节比对**：oracle 样例输入 `oracle/inputs/wx/case2.json` 恰为本任务输入（wx / 非暴力沟通 / `[]`）。执行 `cmp tests/ab/ab-003/arm-a/rep1/骨架.md oracle/out/wx/case2/骨架.md` 与 `cmp …/structure.json …/structure.json` → 两文件均 **BYTE-IDENTICAL**（零差异）。
3. **structure.json 自洽重算**（用冻结正则 `【占位:([^】]*)】` 独立重计数，等价 eval 检查 2 口径）：11 顶层键序与值 ✓；5 要素 id 序列 = `lead_in, thesis_what, thesis_why, thesis_how, golden_ending` ✓；每要素 placeholder_count / open_placeholders 重算一致（recount_ok 全 True）✓；by_element 求和 = total_open = 13 ✓；filled_slots 拼接 = 4 个 topic ✓；`{{ }}` 模板残留 = 0 ✓；JSON 尾单换行 ✓。
4. **资产级验收**（SKILL.md「产物与验收」指名命令，8 case × 5 检查）：
   - `python eval/runner.py package/out oracle/out` → **exit 0**，summary：`cases=8, checks_total=40, passed=40, failed=0, consistency_min=1.0`；
   - `python eval/runner.py oracle/out oracle/out`（自校验，其 wx/case2 与本产物逐字节相同）→ **exit 0**，40/40，其中 wx/case2 五项全过：artifacts_present / structure_json_self_consistent / platform_template_complete / sample_data_filled_no_template_residue / structure_consistency_with_reference（一致率 100%，31/31）。
   - 如实备注：首次跑 runner 时曾得到一次 exit 1，排查为壳层假象——输出重定向到 Git Bash 的 `/tmp`，而 Windows Python 以 `D:\tmp` 解析该路径致读取失败，并非评测失败；改用可读路径复跑后如上（两次均 40/40）。
5. **确定性重跑**（SKILL.md「同输入重跑逐字节一致」）：同参数重跑 gen.py 至临时目录 `/tmp/detcheck_wx` → `cmp` 两文件逐字节一致（RERUN BYTE-IDENTICAL），临时目录已清理。

## 7. 冻结标记核对表（wx，来源：SKILL.md / references/wx.md / references/frozen-tokens.md）

| 冻结项 | 要求 | 本产物 |
| --- | --- | --- |
| 要素 id/顺序 | `lead_in, thesis_what, thesis_why, thesis_how, golden_ending`（5 要素） | 一致 ✓ |
| 三段论标记 | thesis_what/why/how 的 text 分别以「一、是什么」「二、为什么」「三、怎么办」开头 | 一致 ✓ |
| 金句收尾 | text 结构 `「<主题>这件事，…」` + 含「共勉」 | 一致 ✓ |
| 卖点三抓手同居 thesis_how | 行格式 `N. <卖点或【占位:价值点N】>——【占位:展开：具体做法+一个例子】` | 一致 ✓（0 卖点 → 三行全落 `【占位:价值点1/2/3】`） |
| 0 卖点规整 | `points_used=[null×3]`、`points_unused=[]`、`total_filled_from_input=4`（topic × lead_in/what/why/golden） | 一致 ✓ |
| open 计数 | 满足 SKILL.md gotcha：满 3 卖点 10，每缺 1 槽位 how 列多 1 个 `价值点N` → 0 卖点 = 13 | 13 ✓（引擎输出与重算一致） |
| platform_name / structure_name | `公众号文章` / `引子 + 三段论 + 金句收尾` | 一致 ✓ |
| 占位符统计节 | `骨架.md` 尾部 `## 占位符统计`，行以 `- ` 开头 | 一致 ✓ |

**口径差异备注（如实记录）**：`references/wx.md` 第 20 行括注「总 open 恒 10」，与 SKILL.md gotcha 第 106 行（每缺 1 个卖点槽位，how 列另多 `价值点N` 计数）及引擎实跑输出 13 相比，该「恒 10」仅在满 3 卖点时成立；0 卖点正确值为 13。本产物以引擎输出与 SKILL.md gotcha 为准（oracle 逐字节一致亦佐证）。

## 8. 边界与未做事项

- **未做占位符内容补写**：13 处 `【占位:…】` 保持原样。依据 SKILL.md 红线 3 与「边界（非目标）」——引擎/agent 不得为"看起来完整"而编造填充；扩写成文属 SKILL.md 使用步骤 5 的后续环节，需使用者/扩写 AI 补写，且本任务【产物】仅为骨架 + structure.json + OUT.md。
- 未做多平台一次生成（SKILL.md：一次一跑，本次仅 wx）。
- 未做公众号平台侧真实发布校验（阅读/转发效果无法离线验证）。
- 评测中间文件位于系统临时目录（eval_pkg.json / eval_oracle.json），未污染资产目录；确定性重跑的临时目录已删除。
