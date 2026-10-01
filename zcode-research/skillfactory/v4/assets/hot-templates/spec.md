# spec.md — 四平台爆款内容结构模板（主题+卖点进、四平台文案骨架出）

| 项 | 值 |
|---|---|
| 资产 | `skillfactory/v4/assets/hot-templates/` |
| 技能名 | `hot-templates` |
| 规格依据 | 参照实现 `oracle/gen.py` 的**实际行为**（本会话已通读源码并实跑 verify.py 与失败路径探针，见 §10 验证记录） |
| 冻结口径 | 本文规则逐条可判定；实现（package/）可在接口内自由重写，但产物行为必须满足本文与 `contract.md` 的接口冻结 |

---

## 1. 目标

把「主题 + 卖点列表」按**冻结的四平台爆款结构模板**，确定性渲染成可直接交付的文案骨架：

- **输入**：四参数命令行——平台（`dy|xhs|wx|video`）、主题字符串、卖点 JSON、输出目录。
- **输出**：输出目录下两份文件（文件名冻结）——`骨架.md`（人读骨架）与 `structure.json`（机器可读结构要素清单与占位符统计）。
- **四平台模板**：`dy`=抖音口播稿（6 要素）、`xhs`=小红书图文（7 要素）、`wx`=公众号文章（5 要素）、`video`=短视频 6 镜 45 秒分镜表（6 要素）。

不做内容创作：`【占位:…】` 开放槽位留给使用者补写；引擎只做**确定性字符串渲染与占位符统计**。无网络、无第三方依赖（纯 Python 标准库）、无时间戳、无随机数。

## 2. 命令行契约与失败路径（R1）

- R1.1 `python gen.py --platform <dy|xhs|wx|video> --topic <主题> --points <卖点json> --outdir <dir>`，四参数全部必填（gen.py:398-403）。
- R1.2 `--platform` 仅接受四个值；非法值以退出码 **2** 结束（gen.py:399 argparse `choices`）。
  - **实测注记**：非法 platform 的报错由 argparse 输出，stderr 为**英文** `invalid choice: 'bilibili' (choose from dy, video, wx, xhs)`、退出码 2、不建目录（§10 T1）。gen.py:39-41 的 `fail()`（`[gen.py] 错误：`中文前缀）只覆盖 topic/points 校验；**不要求**实现把 platform 报错改成中文，只要求退出码 2 + 零产物。
- R1.3 `--topic` 取 `strip()` 后必须非空，否则退出码 2，stderr 为 `[gen.py] 错误：--topic 不能为空`，不建目录（gen.py:405-407；§10 T2）。
- R1.4 `--points` 接受两种形态（gen.py:46-70）：
  - **文件路径**：`os.path.isfile(spec)` 为真则按 `utf-8-sig` 读入（容忍 BOM）；
  - **内联 JSON 串**：否则当 JSON 字面量解析（§10 T7 实测成功路径）。
  - 解析结果为对象时必须含 `points` 键（缺失退出码 2，§10 T4），取其值；最终必须为**字符串列表**——不是列表退出码 2（gen.py:65-66），任一项非字符串退出码 2（§10 T5）；每项 `strip()`（gen.py:70）。
  - 非 JSON 输入退出码 2：`[gen.py] 错误：--points 不是合法 JSON（既非可读文件，也非内联 JSON）`（§10 T3）。
- R1.5 `--outdir` 不存在则递归创建（gen.py:415）；**只有全部参数校验通过后才建目录/写文件**——任一失败路径下零产物、零目录（§10 T1–T5 全部实测 `dir_exists=no`）。
- R1.6 成功以退出码 **0** 结束，stdout 打印一行 `OK platform=<p> topic=<t> elements=<n> open_placeholders=<n> filled_from_input=<n> -> <outdir>`（gen.py:425-427；§10 T6/T7 实测）。

## 3. 确定性（R2）

- R2.1 引擎无时间戳、无随机数；**同输入重复运行，`骨架.md` 与 `structure.json` 均逐字节一致**。
  - 验证：oracle verify.py V5 对 8/8 样例复跑到临时目录逐字节比对通过（74 项全 PASS）；§10 T8 对未入库的主题/卖点组合复跑 `cmp` 通过。
- R2.2 文件编码与换行：UTF-8、`newline="\n"`（LF）；`structure.json` 为 `ensure_ascii=False, indent=2` 且文件尾带一个换行（gen.py:418-422）。

## 3A. 四平台模板冻结（R3）

要素清单（id、顺序、数量）逐平台冻结如下；每个要素的 `text` 模板与 `meta` 文案以 `oracle/gen.py` 的 builder 函数为冻结源（gen.py:100-263），其 `【占位:…】` 开放槽位 token 全部为模板常量（不随输入变化）。

### dy 抖音口播稿（6 要素，结构名 `3秒钩子 + 痛点 + 价值点×3 + CTA`）

| order | id | name | 关键冻结标记 |
|---|---|---|---|
| 1 | `hook_3s` | 3秒钩子（0-3s） | text 含「别划走！还在为「<topic>」反复内耗的人」+ 1 开放占位 |
| 2 | `pain_point` | 痛点共鸣 | 1 开放占位 |
| 3-5 | `value_1..3` | 价值点1..3 | text 以「第一/二/三招：」起，卖点或占位 + 1 开放占位 |
| 6 | `cta` | 行动号召（CTA） | text 含「点赞收藏，评论区扣「1」」+ 1 开放占位 |

### xhs 小红书图文（7 要素，结构名 `标题带数字 + emoji规则 + 正文分块 + 标签组`）

| order | id | name | 关键冻结标记 |
|---|---|---|---|
| 1 | `title` | 标题（带数字） | text 含 `🔥` 与数字 `3`；meta.emoji=`🔥` |
| 2 | `hook_block` | 正文·开头钩子块 | text 以 `✅ 开头钩子` 起；meta.emoji=`✅` |
| 3-5 | `point_block_1..3` | 正文·干货块1..3 | text 以 `💡 干货N｜<卖点>` 起；meta.emoji=`💡` |
| 6 | `summary_block` | 正文·总结块 | text 以 `📌 划重点` 起；meta.emoji=`📌` |
| 7 | `tag_group` | 标签组（5个） | text 含 `#` 话题标签 **3-8 个**（实测 6 个，§10 T9）；meta.emoji=`🏷️`；首标签=主题派生（`clean_tag`：去 `#` 与全部空白） |

emoji 映射表（🔥/✅/💡/📌/🏷️）冻结：前四者出现在对应要素 text，`🏷️` 记于 tag_group 的 `meta.emoji`。

### wx 公众号文章（5 要素，结构名 `引子 + 三段论 + 金句收尾`）

| order | id | name | 关键冻结标记 |
|---|---|---|---|
| 1 | `lead_in` | 引子 | 1 开放占位 + topic |
| 2 | `thesis_what` | 三段论·一（是什么） | text 以「一、是什么」开头 |
| 3 | `thesis_why` | 三段论·二（为什么） | text 以「二、为什么」开头；3 个根因占位 |
| 4 | `thesis_how` | 三段论·三（怎么办） | text 以「三、怎么办」开头；三个抓手（卖点槽位同居此要素） |
| 5 | `golden_ending` | 金句收尾 | text 含「共勉」 |

### video 短视频分镜表（6 要素，结构名 `分镜表：时间轴/画面/口播/字幕`）

- R3.1 分镜时长表冻结为 `SHOT_DURATIONS = [3, 7, 10, 10, 10, 5]`，共 45 秒（gen.py:209）；时间区间依次为 `00:00-00:03`、`00:03-00:10`、`00:10-00:20`、`00:20-00:30`、`00:30-00:40`、`00:40-00:45`（`shot_1..shot_6` 的 `meta.time_range`，§10 T9 实测）。
- R3.2 每个分镜要素 `text` 为一行表格行 `| <序号> | <时间轴> | <画面> | <口播> | <字幕> |`；`meta` 另含 `shot_no / time_range / duration_sec / visual / voiceover / subtitle / beat`。
- R3.3 `骨架.md` 含四列分镜表头 `| 序号 | 时间轴 | 画面 | 口播 | 字幕 |`（ask 所指"四列分镜表头"= 时间轴/画面/口播/字幕四内容列，前置序号列，§10 T9 实测在文）；镜头 3-5 承载三个卖点槽位（要素 id 为 `shot_{2+i}`）。
- R3.4 md 尾部含 `## 分镜总表（时间轴 00:00-00:45，共 45 秒）` 节，聚合全部 6 行（gen.py:333-343）。

## 4. 卖点规整策略（R4）

模板冻结为**恰好 3 个价值点槽位**（gen.py:73-84）：

- R4.1 槽位 i（1-3）有非空卖点 → 填入该卖点（`strip` 后原文），对应要素 `filled_from_input` 含 `point#i`；`points_used[i-1]` 为该字符串。
- R4.2 槽位 i 缺失（列表不足 3 条，**或该项为空白串**——空白串 strip 后为假值按缺失处理，§10 T6 实测）→ 对应要素 text 落 `【占位:价值点i】`，`points_used[i-1]` 为 `null`，`filled_from_input` 不含 `point#i`。各平台卖点槽位所在要素：dy=`value_i`、xhs=`point_block_i`、wx=全部同居 `thesis_how`、video=`shot_{2+i}`。
- R4.3 超出 3 条 → 取前 3，第 4 起原文保序记入 `structure.json` 的 `points_unused`（§10 实测 xhs/case2 5 条 → 2 条入 points_unused）。
- R4.4 `points_input_count` = 规整前条数；`points_used` 恒为长度 3 的列表。

## 5. structure.json（R5）

顶层键与 `placeholder_stats` 键冻结如下（与 oracle README 一致；schema 由本资产契约冻结，见 contract §5）：

- R5.1 顶层 11 键：`template_version`（`"1.0"`）、`platform`、`platform_name`、`structure_name`（四平台结构名逐字见 §3 各表）、`topic`、`points_input_count`、`points_used`、`points_unused`、`element_count`、`elements`、`placeholder_stats`。
- R5.2 每个 element 9 键：`id`、`name`、`order`、`required`（恒 `true`）、`text`、`placeholder_count`、`open_placeholders`、`filled_from_input`、`meta`（对象）。
- R5.3 `placeholder_stats` 5 键：`total_open`（开放占位符出现总次数）、`total_filled_from_input`、`by_element`（要素 id → 计数）、`open_tokens_unique`（去重保序 token 清单）、`filled_slots`（各要素 filled_from_input 依序拼接）。
- R5.4 计数自洽（eval 判定项）：`element_count == len(elements)`；每个要素 `placeholder_count` 与 `open_placeholders` 等于对 `text` 以正则 `【占位:([^】]*)】` 重计数/去重保序的结果；`by_element` 求和 == `total_open` 且与分要素计数一致（gen.py:271-297；oracle verify V3 同口径）。

## 6. 骨架.md（R6）

- R6.1 首行 `# <platform_name> · 爆款骨架`；元信息三行：`- 主题：<topic>`、`- 平台/模板：\`<platform>\` @ v1.0（<structure_name>）`、`- 卖点输入：<n> 条 → 规整为 3 条（缺失补占位 <m> 条，超出截断 <k> 条）`（gen.py:300-311）。
- R6.2 每要素一节 `## <order>. <name>`，节内为要素 `text`（video 平台每节为 表头+该行+画面/口播/字幕三条明细）；随后一行 `> 写法要点：<meta.beat 或 meta.rule>`（gen.py:312-329）。
- R6.3 尾部 `## 占位符统计` 节：`未填占位符（待人工/AI 补写）：**<total_open> 处**`、`已从输入填充：<k> 处（<filled_slots 顿号列表>）`、分要素 `  - <order>. <name>：<n> 处`，结尾保留说明段（gen.py:344-356）。
- R6.4 抽查判据（oracle verify V4 同口径）：topic 出现在 md；`structure_name` 出现在 md；含「占位符统计」节；video 另需含 `| 时间轴` 与 `00:00-00:03`。

## 7. 边界与非目标

- **不做**：占位符的内容补写（骨架只给结构+开放槽位）、语义改写卖点（只 strip 与 `clean_tag`）、多平台一次生成（一次一平台）、非四平台的账号/平台（非法 platform 直接拒绝）、网络调用、第三方依赖。
- **已知可接受的"错"（规则如此，不视为缺陷）**：`【占位:…】` 是**设计内的开放槽位**，正常产物中大量存在——eval 的"无残留"检查只针对 `{{ }}` 类未填充模板变量（§10 T9 实测 8 份参照产物 `{{` 计数全为 0），**不**要求消除 `【占位:…】`；xhs 标签组内示例标签（如 `#时间管理`）计入标签数（实测 6，落在 3-8）。
- 结构名、要素 id/顺序、emoji 映射、分镜时长、占位符 token 均为模板常量，改动即违反冻结；模板版本 `1.0`。

## 8. 交付物与验收流程（DoD）

- D.1 交付物 = `package/`（见 contract §2/§3）**加** `package/out/<platform>/<caseN>/` 评测产物：对 `eval/golden.json` `eval_inputs` 列出的**每个** case（8 个），实现方必须亲自运行 `python package/scripts/gen.py --platform <P> --topic <T> --points inputs/<P>/<caseN>.json --outdir package/out/<P>/<caseN>`，使每个 case 目录下真实存在 `骨架.md` + `structure.json`。**先产出、后评测**；未产出即运行 eval 属于流程违规（全部检查将以"被测用例目录不存在"判红）。
- D.2 输入样例位置：资产根 `inputs/<platform>/<caseN>.json` 是样例的实现者副本（与规范源 `oracle/inputs/` **字节一致**，本会话 `cmp` 逐对验证通过）。实现方经 `inputs/` 使用样例，无需触碰 `oracle/`；「禁止读取 oracle/」的隔离规则指参照实现 `oracle/gen.py` 与参照产物 `oracle/out/`。
- D.3 评测命令固定：`python eval/runner.py package/out oracle/out`（也可用绝对路径，runner 不假设 CWD——本会话已从工作区根与资产根两种 CWD 实跑验证）。exit 0 为通过。
- D.4 自查顺序（实现方返回前完成）：① 跑 D.1 全部 8 个 case；② 跑 D.3 评测命令；③ 有失败修实现后重跑 ①②；返回必须附 eval 真实 stdout 与 exit code。

## 9. eval/runner.py 判定口径（R7）

对 8 个 case 各执行 5 项检查（check name 前缀为 case 名，如 `dy/case1/…`）：

1. `artifacts_present` — `骨架.md` + `structure.json` 存在、非空、JSON 可解析；
2. `structure_json_self_consistent` — R5.1-R5.3 键齐全 + R5.4 计数自洽；
3. `platform_template_complete` — R3 各平台冻结要素齐备（dy 钩子+CTA；xhs 标题含数字与 🔥、emoji 映射、标签 3-8；wx 三段论标记+共勉；video 四列分镜表头+冻结时间轴+共 45 秒）+ R4 卖点规整（缺失槽位落 `【占位:价值点N】`、截断入 `points_unused`）；
4. `sample_data_filled_no_template_residue` — 样例主题与卖点全部填充落位（前 3 条进要素 text、其余进 `points_unused`），且两份产物无 `{{ }}` 残留；
5. `structure_consistency_with_reference` — 与参照产物逐项比对（要素 id 序列/各要素 name·order·placeholder_count·open_placeholders/顶层 4 键/统计 3 键/points_used·points_unused/md 小节标题序列），结构一致率 **≥90%**。

全部通过 → exit 0 并打印 `{"ok": true, "summary": …, "checks": […]}`；任一失败 → exit 1。退出码 2 = 用法/golden 错误。确定性：无随机、无网络；同输入对同一对目录重复运行结果一致。

## 10. 验证记录（本会话实际运行）

| 验证 | 命令/方式 | 结果 |
|---|---|---|
| oracle 验收全量 | `python skillfactory/v4/assets/hot-templates/oracle/verify.py` | 74 项全 PASS，exit 0（V1 存在性/V2 顶层键与计数/V3 占位符重计数/V4 md 抽查/V5 复跑逐字节/V6 非法 platform） |
| T1 非法 platform | `gen.py --platform bilibili …`（临时目录） | exit 2；stderr=argparse 英文 `invalid choice: 'bilibili'`；不建目录 |
| T2 空 topic | `gen.py --platform dy --topic "   " …` | exit 2；stderr=`[gen.py] 错误：--topic 不能为空`；不建目录 |
| T3 points 非 JSON | `--points 'not json'` | exit 2；中文报错；不建目录 |
| T4 dict 缺 points 键 | `--points '{"a":1}'` | exit 2；中文报错；不建目录 |
| T5 非字符串项 | `--points '["ok",42]'` | exit 2；`--points 第 2 项不是字符串（got int）`；不建目录 |
| T6 空白串卖点 | `--points '["  ","实测第二点",""]'` | exit 0；`points_used=[None,'实测第二点',None]`；槽位 1/3 落 `【占位:价值点1/3】`，filled_slots=[topic, point#2] |
| T7 内联 JSON 成功 | `--platform wx --points '["卖点甲","卖点乙","卖点丙"]'` | exit 0；OK 行打印；element_count=5、total_open=10 |
| T8 确定性复跑 | 同输入（video，2 条卖点）跑两次 `cmp` | `骨架.md` 与 `structure.json` 均 BYTE_IDENTICAL=yes |
| T9 模板常量实测 | 解析 8 份参照产物 | xhs 标签数=6（case1/case2 同）；video 六镜 time_range 与 §3A 逐项一致、md 表头与「共 45 秒」在文；8 份产物 `{{` 残留计数全 0 |
| 8 case 规整边界 | 读 out/*/structure.json | dy/case2（2 条→槽位 3 为 null）、xhs/case2（5 条→2 条入 points_unused）、wx/case2（0 条→全占位）、video/case2（1 条→槽位 2/3 占位）全部按 R4 落盘 |
| eval 自校验（绿） | `python …/eval/runner.py …/oracle/out …/oracle/out` | exit 0；40/40 通过；8 例结构一致率均 100.0% |
| eval 空目录（红） | runner `<空目录> oracle/out` | exit 1；40/40 判红（首条：被测用例目录不存在） |
| eval 敏感性 | 原样副本 vs 篡改副本（cta 计数改 99 + 删一份 骨架.md） | 原样 exit 0（40/40）；篡改 exit 1 精确判红 6 项 |
| CWD 无关性 | 工作区根（绝对路径）与资产根（相对路径 `eval/runner.py oracle/out oracle/out`）各跑一次 | 均 exit 0 |

> oracle 源码行号引用以 `oracle/gen.py` 为准；本 spec 冻结的是**行为**，行号仅佐证出处。

---

## 附录：冻结接口常量表（2026-09-30 增补，根治 D31-60 轮接口文档缺陷）

> **来源**：实现包 `package/references/frozen-tokens.md`（实现者经雇主批准的接口例外，自模板冻结源全文整理而成，随包分发、使技能包自包含）。
> **核对方式**：本附录为该表权威口径的全文誊录，增补时已逐条与 `oracle/gen.py` 实际定义核对一致——`TEMPLATE_VERSION`/`PLATFORMS`（gen.py:26-33）、占位符正则（:36）、卖点缺失槽位 token（:87-89）、`clean_tag`（:92-94）、`build_dy`（:100-128）、`build_xhs`（:131-166）、`build_wx`（:169-205）、`SHOT_DURATIONS` 与 `build_video`（:209、:224-263）、统计口径（:271-297）。核对仅用于佐证一致性：实现者**不需要也不应该**读取 oracle 源文件，以本表为准。

占位符语法：`【占位:<token>】`；统计正则 `【占位:([^】]*)】`——`placeholder_count` = 出现次数；`open_placeholders` = 去重保序后的 **token 内文**清单（不含外壳）。

### 附.1 通用常量

| 常量 | 冻结值 |
|---|---|
| `template_version` | `"1.0"` |
| platform_name | dy=`抖音口播稿`、xhs=`小红书图文`、wx=`公众号文章`、video=`短视频分镜表` |
| structure_name | dy=`3秒钩子 + 痛点 + 价值点×3 + CTA`、xhs=`标题带数字 + emoji规则 + 正文分块 + 标签组`、wx=`引子 + 三段论 + 金句收尾`、video=`分镜表：时间轴/画面/口播/字幕` |
| 卖点缺失槽位 token | `价值点1` / `价值点2` / `价值点3`（即 `【占位:价值点N】`，四平台通用） |
| `clean_tag` | 去掉 `#` 与全部空白（正则 `[\s#]+` 替换为空） |
| 分镜时长表 | `[3, 7, 10, 10, 10, 5]` 共 45 秒 |

### 附.2 dy 抖音口播稿（6 要素，总 open=6；每个要素恰 1 个 token）

| 要素 | token（去重前=后） | meta.beat | filled_from_input |
|---|---|---|---|
| `hook_3s` | `可替换为你的原创钩子强句，一句制造好奇或冲突` | 0-3秒留住人：反问+利益点，语速快、重音落在主题词 | `["topic"]` |
| `pain_point` | `痛点场景，写目标人群最扎心的一个具体瞬间` | 说中一件事，让观众对号入座 | `[]` |
| `value_1..3` | 三槽位**同名**：`一句话展开：怎么做/效果/案例` | 一条卖点一句展开，信息密度拉满 | 已填槽位记 `point#i` |
| `cta` | `配套资料/下期选题` | 点赞+收藏+评论三连指令，给一个扣词降低互动门槛 | `[]` |

### 附.3 xhs 小红书图文（7 要素，总 open=7；每个要素恰 1 个 token）

| 要素 | token | meta.emoji / meta.rule | filled_from_input |
|---|---|---|---|
| `title` | `目标人群，如：打工人/新手宝妈` | 🔥／标题带数字（3=价值点数，模板冻结为3）+人群词，emoji 置顶 | `["topic"]` |
| `hook_block` | `一句真实经历/翻车现场` | ✅／钩子块固定 ✅：身份代入+收藏指令 | `["topic"]` |
| `point_block_1..3` | 三块**同名**：`2-3步操作拆解，越具体越好` | 💡／干货块固定 💡：小标题=卖点，正文=步骤 | 已填槽位记 `point#i` |
| `summary_block` | `一句互动引导，如：你最想先试哪个？评论区聊聊` | 📌／总结块固定 📌：三点复述+互动引导 | `["topic"]` + 已填的 `point#1..3` |
| `tag_group` | `2个垂直领域标签，如：#时间管理 #精力管理` | 🏷️／标签组=主题大词+流量泛词+垂直长尾，首标签由主题派生 | `["topic(派生标签)"]` |

- 标签组字面：`#<主题派生> #干货分享 #方法论 #自我提升 ` + 占位槽位；标签数判定口径 = 6
  （4 个字面标签 + 占位 token 内 2 个示例标签 `#时间管理`、`#精力管理`，正则 `#[^\s#]+` 计数）。
- `summary_block` 的三点复述用卖点槽位值（缺失槽位落 `【占位:价值点N】` 原样进复述句）。

### 附.4 wx 公众号文章（5 要素，总 open=10）

| 要素 | token（出现次数） | meta.beat | filled_from_input |
|---|---|---|---|
| `lead_in` | `用一个具体场景/对话/新闻切入，150字左右`（1） | 场景化开场，把读者拉进问题现场 | `["topic"]` |
| `thesis_what` | `常见误解`（1）+ `一句话给出你的定义`（1） | 先破后立，给出定义 | `["topic"]` |
| `thesis_why` | `根因1`、`根因2`、`根因3`（各 1） | 归因，三条根因对齐后文三个抓手 | `["topic"]` |
| `thesis_how` | `展开：具体做法+一个例子`（**3 次，去重后 1 个 token**） | 三个抓手一一对应三条根因，可执行 | 已填槽位记 `point#1..3` |
| `golden_ending` | `金句主体——句式建议：真正的…不是靠…，而是靠…`（1） | 一句话收束，可直接被读者摘抄转发 | `["topic"]` |

- thesis_how 行格式：`三、怎么办\n落到操作层面，给你三个抓手：` 后接三行 `N. <卖点或【占位:价值点N】>——【占位:展开：具体做法+一个例子】`。
- **`total_filled_from_input` 语义（wx 特有）**：wx 的 `topic` 在 **4 个要素**（lead_in / thesis_what / thesis_why / golden_ending）各记一次 `topic` 填充：满 3 卖点时 `total_filled_from_input=7`，0 卖点时 `=4`。
- 金句收尾 text 结构：`「<主题>这件事，【占位:金句主体…】」\n共勉。`

### 附.5 video 短视频分镜表（6 要素；总 open：满 3 卖点=12、2 条=14、1 条=16、0 条=18——每缺 1 槽位，口播+字幕列各多 1 次 `价值点N`）

- 要素 `name` 冻结为 `分镜<N>（<起>-<止>）`，如 `分镜1（00:00-00:03）`；
  `text` = 一行表格行 `| N | 起止 | 画面 | 口播 | 字幕 |`；
  `meta` 7 键：`shot_no / time_range / duration_sec / visual / voiceover / subtitle / beat`。

| 要素 | 画面列 token | 口播/字幕列 token | meta.beat | filled_from_input |
|---|---|---|---|---|
| `shot_1` | `画面1：冲突感特写/大字标题卡` | 口播无占位（`别划走！还在为「主题」头疼？这条一次讲透。`）；字幕无占位（`大字花字：主题，45秒讲透`） | 0-3秒钩子：画面+花字同时制造停顿 | `["topic"]` |
| `shot_2` | `画面2：痛点情景再现（空镜+人物）` | 口播 `痛点行为描述`（1）；字幕 `痛点一句话字幕`（1） | 痛点具象化：情景再现让观众对号入座 | `[]` |
| `shot_3..5` | `画面N：卖点M演示（实操/录屏/对比）`（N=镜号，M=槽位号） | 口播 `口播补充一句效果`（1）；卖点缺失时口播与字幕列另现 `价值点M` | 价值点逐条演示：一镜一招，画面与口播同频 | 已填槽位记 `point#M` |
| `shot_6` | `画面6：结尾定格+关注引导贴纸` | 口播 `下期选题`（1）；字幕无占位（`花字：关注不迷路`） | CTA：口播+贴纸双引导 | `[]` |

- 口播/字幕列带卖点的句子：口播 `第<X>招，<卖点或占位>。【占位:口播补充一句效果】`（X∈一二三）、
  字幕 `字幕要点：<卖点或占位>`。
- 缺失槽位示例（0 卖点时 shot_4）：`placeholder_count=4`（画面1 + 口播2 + 字幕1），
  `open_placeholders` 去重后 3 个 token（`价值点2` 出现 2 次计 1）。
