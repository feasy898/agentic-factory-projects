# OUT.md — hot-templates · ab-002 / arm-b / rep2 执行成果

- 日期：2026-09-30
- 任务：使用 hot-templates 技能生成小红书图文爆款内容骨架（platform=xhs，冻结模板：标题带数字 + emoji规则 + 正文分块 + 标签组）
- 产物目录：`skillfactory/v4/assets/hot-templates/tests/ab/ab-002/arm-b/rep2/`（本目录，含 `骨架.md`、`structure.json`、本 `OUT.md`）

## 1. 输入（材料自含）

| 参数 | 值 |
|---|---|
| `--platform` | `xhs` |
| `--topic` | `租房避坑指南` |
| `--points` | `["签约前查房东房产证与身份证一致性", "押金条款写明退还条件与时限", "入住当天拍照录像留档", "水电燃气表底数写进合同附件", "转租条款提前约定违约金"]`（共 5 条，超出 3 槽位） |
| `--outdir` | `skillfactory/v4/assets/hot-templates/tests/ab/ab-002/arm-b/rep2` |

## 2. 方法（严格按 SKILL.md）

1. 完整读取 `package/SKILL.md`（109 行全文，含权威规则、使用步骤、gotchas）。
2. 按 SKILL.md「文档地图」完整读取本平台必读文档 `package/references/xhs.md`（44 行全文），
   接口常量表 `package/references/frozen-tokens.md`（77 行全文，占位 token / meta.emoji / filled_from_input 逐字口径），
   以及 `references/dy.md`、`wx.md`、`video.md` 全文（任务要求「读 references/」）。
3. 按红线第 4 条（SKILL.md:20），骨架生成走确定性渲染引擎 `package/scripts/gen.py`（427 行全文已读），
   未手写、未改写 `structure.json`；`【占位:…】` 开放槽位全部保留原样，未编造内容填充（SKILL.md:19）。
4. 卖点 5 条 > 3 槽位：按规整策略（SKILL.md:43-46、xhs.md:24-28）前 3 条入 `point_block_1..3`，
   第 4、5 条保序截断入 `structure.json.points_unused`，不塞进正文。

## 3. 执行命令与输出

```bash
# 卖点经 UTF-8 JSON 文件传入（内容与上表 --points 完全一致，规避 shell 内联中文转义风险）；
# gen.py 对文件路径与内联 JSON 串两种形态等价（SKILL.md:40、gen.py:52-75，utf-8-sig 容忍 BOM）
cd "D:\workspace\zcode研究" && python "skillfactory/v4/assets/hot-templates/package/scripts/gen.py" \
  --platform xhs --topic "租房避坑指南" \
  --points "D:/workspace/zcode研究/_tmp_ab002_armb_rep2/points.json" \
  --outdir "skillfactory/v4/assets/hot-templates/tests/ab/ab-002/arm-b/rep2"
```

stdout（一行，符合 SKILL.md:72 成功判据格式）：

```
OK platform=xhs topic=租房避坑指南 elements=7 open_placeholders=7 filled_from_input=10 -> skillfactory/v4/assets/hot-templates/tests/ab/ab-002/arm-b/rep2
```

exit code = **0**。

## 4. 核验结果（本次实际执行）

### 4.1 成功判据三条（SKILL.md:72）— 全部满足

| 判据 | 结果 | 证据 |
|---|---|---|
| exit 0 | ✅ | 上节 `EXIT=0` |
| stdout 打印 OK 行 | ✅ | 上节 stdout 原文 |
| `骨架.md` 与 `structure.json` 存在且非空 | ✅ | `ls -la`：骨架.md 2647 字节、structure.json 5520 字节 |

参考值核对（SKILL.md:106，满 3 卖点 xhs）：`open_placeholders=7`、`filled_from_input=10` ✅。

### 4.2 确定性复跑（gen.py:13「同输入重复运行逐字节一致」、SKILL.md:79）— 通过

同参数复跑至独立目录 `_tmp_ab002_armb_rep2/rerun/`，sha256 逐字节比对：

| 文件 | 首次 run sha256 | 复跑 sha256 | 一致 |
|---|---|---|---|
| 骨架.md | `6e0fbe493195081f8de0d743383ad6c89ad3d656d4c2e0a66a241986a381feba` | 同左 | ✅ |
| structure.json | `480638b01ffb2d69e518a99d7df6d8348eaf87f1c32ea88ee9eb22158ec5cdb5` | 同左 | ✅ |

编码核验：两文件均为合法 UTF-8、CR 计数 = 0（纯 LF）、文件尾一个换行 ✅（gen.py:14）。

### 4.3 结构校验（复用资产评测器 `eval/runner.py` 的检查函数，检查 1–4）— 4/4 通过

执行 `python _tmp_ab002_armb_rep2/verify_rep2.py`（脚本 import `eval/runner.py`，以本任务输入 platform=xhs /
topic=租房避坑指南 / 5 条卖点为样例；`VERIFY_EXIT=0`）：

| 检查 | 结果 | detail |
|---|---|---|
| artifacts_present | ✅ | 骨架.md（1167 字符）+ structure.json（3978 字符）均存在且可解析 |
| structure_json_self_consistent | ✅ | schema 与计数全部自洽（7 要素） |
| platform_template_complete | ✅ | xhs 模板要素齐备（7 要素，卖点 3 条入正文/2 条截断） |
| sample_data_filled_no_template_residue | ✅ | 主题与 5 条卖点全部落位，无 `{{ }}` 残留 |

检查 5（structure_consistency_with_reference，与 oracle 参照逐项比对）**不适用、未跑**：
`oracle/out` 仅覆盖资产自带 8 个 golden case 的输入（`eval/runner.py:10-12`、`eval/golden.json`），
与本任务自定义 topic/points 不同，逐项比对 `points_used`/`topic` 必然失配，属输入差异而非产物缺陷。

### 4.4 冻结口径核对（对照 references/xhs.md + frozen-tokens.md，逐项人工比对）

- 要素 id 序列：`title, hook_block, point_block_1..3, summary_block, tag_group`，order 1–7 连续 ✅（xhs.md:5-13、frozen-tokens.md:31）
- 结构名 `标题带数字 + emoji规则 + 正文分块 + 标签组`、platform_name `小红书图文` ✅（frozen-tokens.md:16-17）
- 标题含 `🔥` 与数字 `3`（「租房避坑指南的3个方法」）✅（xhs.md:9、SKILL.md:58）
- emoji 映射 🔥/✅/💡/💡/💡/📌/🏷️ 与各要素 `meta.emoji` 一一对应 ✅（xhs.md:15-16、frozen-tokens.md:33-39）
- 各要素起头冻结：hook_block 以「✅ 开头钩子」起、干货块以「💡 干货N｜<卖点>」起、总结块以「📌 划重点」起 ✅
- 标签组字面：`#租房避坑指南 #干货分享 #方法论 #自我提升 【占位:…】`——首标签 = `clean_tag("租房避坑指南")`
  （主题无 `#`/空白，派生即原词，gen.py:97-99）；标签数按 `#[^\s#]+` 正则口径 = 6
  （4 个字面 + 占位 token 内 2 个示例），在 3-8 区间且等于冻结口径 6 ✅（xhs.md:17-19、frozen-tokens.md:41-42）
- 5 个去重占位 token 与 frozen-tokens.md xhs 表逐字一致（目标人群／一句真实经历翻车现场／2-3步操作拆解／
  一句互动引导／2个垂直领域标签；干货块三块同名 `2-3步操作拆解，越具体越好`）✅
- 卖点规整：`points_input_count=5`、`points_used` 恒长 3 且为前 3 条原文（strip）、
  `points_unused=["水电燃气表底数写进合同附件","转租条款提前约定违约金"]` 保序 ✅（xhs.md:24-28）
- `filled_from_input` 语义：title/hook 各记 `topic`、point_block_i 记 `point#i`、summary 记
  `["topic","point#1","point#2","point#3"]`、tag 记 `topic(派生标签)`，合计 10 ✅（xhs.md:20-21、frozen-tokens.md:33-39）
- 骨架.md 版式：首行 `# 小红书图文 · 爆款骨架` + 元信息三行 + 每要素一节 `## <序号>. <名称>`（含要素文本与
  「> 写法要点：」）+ 尾部 `## 占位符统计` ✅（SKILL.md:78）
- 计数口径说明（如实）：对整份 `骨架.md` 直接跑正则 `【占位:([^】]*)】` 得 8 处/6 个去重 token，比统计值
  多出的 1 处是尾部「> 说明：」行里对语法 `【占位:…】` 的字面提及（token=`…`），引擎按设计只统计要素文本
  （gen.py:269-288），排除该行后正文 7 处/5 个去重 token，与 `structure.json.placeholder_stats` 完全同源 ✅

## 5. 产物清单（本目录）

| 文件 | 说明 |
|---|---|
| `骨架.md` | 人读骨架：首行 `# 小红书图文 · 爆款骨架` + 元信息三行 + 7 要素各一节（含「> 写法要点：」）+ `## 占位符统计`（7 处待补写） |
| `structure.json` | 机器可读：顶层 11 键 / 每要素 9 键 / 统计 5 键，UTF-8 + LF，与 `骨架.md` 同源同构 |
| `OUT.md` | 本报告 |

## 6. 骨架全文（`骨架.md` 原样收录）

```markdown
# 小红书图文 · 爆款骨架

- 主题：租房避坑指南
- 平台/模板：`xhs` @ v1.0（标题带数字 + emoji规则 + 正文分块 + 标签组）
- 卖点输入：5 条 → 规整为 3 条（缺失补占位 0 条，超出截断 2 条）

---

## 1. 标题（带数字）

🔥亲测有效｜租房避坑指南的3个方法，【占位:目标人群，如：打工人/新手宝妈】看完直接抄作业

> 写法要点：标题带数字（3=价值点数，模板冻结为3）+人群词，emoji 置顶

## 2. 正文·开头钩子块

✅ 开头钩子
租房避坑指南这件事，我真的走过太多弯路——【占位:一句真实经历/翻车现场】。这篇一次性讲透，先收藏再看！

> 写法要点：钩子块固定 ✅：身份代入+收藏指令

## 3. 正文·干货块1

💡 干货1｜签约前查房东房产证与身份证一致性
【占位:2-3步操作拆解，越具体越好】

> 写法要点：干货块固定 💡：小标题=卖点，正文=步骤

## 4. 正文·干货块2

💡 干货2｜押金条款写明退还条件与时限
【占位:2-3步操作拆解，越具体越好】

> 写法要点：干货块固定 💡：小标题=卖点，正文=步骤

## 5. 正文·干货块3

💡 干货3｜入住当天拍照录像留档
【占位:2-3步操作拆解，越具体越好】

> 写法要点：干货块固定 💡：小标题=卖点，正文=步骤

## 6. 正文·总结块

📌 划重点
租房避坑指南的核心就三点：签约前查房东房产证与身份证一致性、押金条款写明退还条件与时限、入住当天拍照录像留档。【占位:一句互动引导，如：你最想先试哪个？评论区聊聊】

> 写法要点：总结块固定 📌：三点复述+互动引导

## 7. 标签组（5个）

#租房避坑指南 #干货分享 #方法论 #自我提升 【占位:2个垂直领域标签，如：#时间管理 #精力管理】

> 写法要点：标签组=主题大词+流量泛词+垂直长尾，首标签由主题派生

---

## 占位符统计

- 未填占位符（待人工/AI 补写）：**7 处**
- 已从输入填充：10 处（topic、topic、point#1、point#2、point#3、topic、point#1、point#2、point#3、topic(派生标签)）
  - 1. 标题（带数字）：1 处
  - 2. 正文·开头钩子块：1 处
  - 3. 正文·干货块1：1 处
  - 4. 正文·干货块2：1 处
  - 5. 正文·干货块3：1 处
  - 6. 正文·总结块：1 处
  - 7. 标签组（5个）：1 处

> 说明：所有 `【占位:…】` 为开放槽位，由使用者补写；`structure.json` 为机器可读的结构要素清单与占位符统计，与本文同源同构。
```

## 7. 边界说明（如实）

- 本任务交付**骨架**（结构 + 开放槽位），不做占位符内容补写、不做卖点语义改写（SKILL.md:84 边界）。
- 第 4、5 条卖点（水电燃气表底数／转租违约金）因模板冻结为恰 3 个价值点槽位而**未入正文**，
  保序记录于 `structure.json.points_unused`——这是模板冻结行为（xhs.md:27），非丢失。
- 7 处 `【占位:…】` 为设计内开放槽位（红线，SKILL.md:85），扩写成文时由使用者按 `references/xhs.md`「写法方法」
  五步（标题 20 字内禁标题党／钩子两行内／干货块 2-3 行「动作+效果」／总结引导收藏／标签 3-8 个）补写。
- 未执行网络调用、未引入第三方依赖（gen.py 纯标准库）；未运行 `eval/runner.py` 全量 8 case 评测
  （其输入固定为 golden case，与本任务自定义输入无关，理由见 4.3）。
