---
name: hot-templates
version: 1.0.0
license: MIT
description: 四平台爆款内容结构模板：把「主题+卖点列表」确定性渲染为可直接交付的文案骨架，覆盖抖音口播稿、小红书图文、公众号文章、短视频分镜表（6镜45秒）。当用户给出主题（可附卖点）需要产出爆款内容框架，或提到「爆款骨架」「抖音口播」「小红书图文」「公众号文章」「短视频分镜」「口播稿」时使用。不用于成文代写与多平台一次生成（一次一平台）；长文成稿转交对应写作类 skill。
permissions: [shell]
metadata:
  domain: content-structure
  requires-bins: python3
  route-to: ""
---

# hot-templates

## 权威规则（置顶）

1. 【MUST RELOAD】多轮对话中出现新指令时，第一个工具调用必须是重新 Read 本 SKILL.md，禁止凭上轮记忆动手。
2. 本技能 references/ 四份文档必须按文档地图完整读完对应平台那份，禁止中途截断。
3. 【红线】`【占位:…】` 是留给使用者的**开放槽位**：生成骨架时禁止自行编造内容填充；扩写成文时才由使用者/AI 补写，且不得改动冻结结构标记。
4. 【红线】骨架生成一律走 `scripts/gen.py`（确定性渲染引擎），禁止手写或改写 `structure.json`；引擎无时间戳、无随机数、无网络、零第三方依赖。
5. 不确定时：声明不知道并停下核实，禁止猜测填充。

## 何时使用

用户给出**主题**（可附卖点列表），需要以下四平台之一的爆款内容**结构骨架**时：

- 抖音口播稿（6 要素：3秒钩子 + 痛点 + 价值点×3 + CTA）
- 小红书图文（7 要素：标题带数字 + emoji 规则 + 正文分块 + 标签组）
- 公众号文章（5 要素：引子 + 三段论 + 金句收尾）
- 短视频分镜表（6 镜 45 秒：时间轴/画面/口播/字幕）

不适用：非上述四平台（如 B 站、知乎）、多平台一次生成、直接产出成文（骨架只给结构+开放槽位）。

## 输入格式

| 参数 | 要求 |
|---|---|
| `--platform` | 仅四值：`dy` \| `xhs` \| `wx` \| `video`；非法值 exit 2 |
| `--topic` | 主题字符串，strip 后非空；否则 exit 2 |
| `--points` | 卖点 JSON：**文件路径**（utf-8-sig，容忍 BOM）或**内联 JSON 串**；形态为纯字符串列表，或含 `points` 键的对象（如 `{"points":[...]}`）；不可解析/缺 points 键/非字符串项 → exit 2 |
| `--outdir` | 输出目录，不存在则递归创建；全部参数校验通过才建目录写文件 |

卖点规整策略（引擎自动做，四平台通用）：模板恰好 **3 个价值点槽位**——非空卖点 strip 后入槽；
缺失或空白串的槽位落 `【占位:价值点N】`；超过 3 条取前 3，第 4 起原文保序记入 `structure.json`
的 `points_unused`。卖点槽位所在要素：dy=`value_1..3`、xhs=`point_block_1..3`、wx=三抓手同居
`thesis_how`、video=`shot_3..5`（id 为 `shot_{2+i}`）。

## 四平台模板表

| platform | 平台 | 结构名 | 要素清单（id，顺序冻结） |
|---|---|---|---|
| `dy` | 抖音口播稿 | 3秒钩子 + 痛点 + 价值点×3 + CTA | 6：`hook_3s`、`pain_point`、`value_1..3`、`cta` |
| `xhs` | 小红书图文 | 标题带数字 + emoji规则 + 正文分块 + 标签组 | 7：`title`、`hook_block`、`point_block_1..3`、`summary_block`、`tag_group` |
| `wx` | 公众号文章 | 引子 + 三段论 + 金句收尾 | 5：`lead_in`、`thesis_what`、`thesis_why`、`thesis_how`、`golden_ending` |
| `video` | 短视频分镜表 | 分镜表：时间轴/画面/口播/字幕 | 6 镜 45 秒：`shot_1..6`（时长 3/7/10/10/10/5 秒，时间轴 00:00-00:03 … 00:40-00:45） |

冻结标记速记：dy 钩子含「别划走！还在为「主题」反复内耗的人」、CTA 含「点赞收藏，评论区扣「1」」；
xhs 标题含 `🔥` 与数字、emoji 映射 🔥/✅/💡/📌/🏷️、标签 3-8 个（首标签=主题派生，去 `#` 与空白）；
wx 三段论以「一、是什么」「二、为什么」「三、怎么办」开头、金句含「共勉」；video 含四列表头
`| 序号 | 时间轴 | 画面 | 口播 | 字幕 |` 与「共 45 秒」。改动即违反模板冻结。
**各要素开放槽位 token、meta.beat 与 `filled_from_input` 语义的逐字清单见 `references/frozen-tokens.md`（接口常量表，逐字节比对口径）。**

## 使用步骤

1. 按「何时使用」定平台；用户要多个平台时**一次一跑**（一次调用只出一个平台）。
2. 执行生成命令（相对当前目录解析路径，脚本不假设运行位置）：

   ```bash
   python scripts/gen.py --platform <dy|xhs|wx|video> --topic <主题> --points <卖点.json或'["卖点1","卖点2"]'> --outdir <输出目录>
   ```

3. 成功判据（三条同时满足）：exit **0**；stdout 打印一行 `OK platform=… topic=… elements=… open_placeholders=… filled_from_input=… -> <outdir>`；`<outdir>/骨架.md` 与 `<outdir>/structure.json` 两份文件存在且非空。
4. 失败判据：exit **2**，stderr 有 `[gen.py] 错误：…`（非法 platform 时为 argparse 英文报错，属预期），且输出目录未被创建。按报错修参数后**定向重试一次**。
5. 读 `骨架.md`，按对应 reference 的写法要点把各要素扩写成文；`【占位:…】` 开放槽位在此步补写。

## 产物与验收

- `骨架.md`（人读）：首行 `# <平台> · 爆款骨架` + 元信息三行（主题/平台模板/卖点输入）+ 每要素一节 `## <序号>. <名称>`（内含要素文本与「> 写法要点：」）+ 尾部 `## 占位符统计` 节；video 另含 `## 分镜总表（时间轴 00:00-00:45，共 45 秒）`。
- `structure.json`（机器可读）：顶层 11 键（`template_version="1.0"`、platform、platform_name、structure_name、topic、points_input_count、points_used、points_unused、element_count、elements、placeholder_stats）；每要素 9 键；统计 5 键；UTF-8/LF，同输入重跑逐字节一致。
- 验收判据（本包内评测）：`python eval/runner.py <被测out> reference/out` 退出码 0（8 case × 5 检查，结构一致率阈值 90%；在分发包根目录运行，见 README「运行目录约定」）。

## 边界（非目标）

- 不做：占位符的内容补写（引擎只给结构+槽位）、卖点语义改写（只 strip 与标签派生）、多平台一次生成、四平台之外的平台、网络调用、第三方依赖。
- 红线：`【占位:…】` 是设计内开放槽位，正常产物中大量存在——**禁止**引擎或 agent 为"看起来完整"而编造内容填充；`{{ }}` 类未填充模板变量才是残留缺陷，产物中必须为 0。
- 各平台写作红线（前 3 秒留人、emoji 滥用、标题党、分镜超时等）见对应 reference。

## 文档地图

| 文档 | 何时读 |
|---|---|
| references/dy.md | 生成/扩写抖音口播骨架时必读 |
| references/xhs.md | 生成/扩写小红书图文骨架时必读 |
| references/wx.md | 生成/扩写公众号文章骨架时必读 |
| references/video.md | 生成/扩写短视频分镜表时必读 |
| references/frozen-tokens.md | 涉及占位符 token、填充语义、逐字节一致性问题时的权威常量表 |

## gotchas

- 空白串卖点（如 `"  "`）按**缺失**处理：strip 后为假值 → 落 `【占位:价值点N】`，`points_used` 对应位为 `null`。
- `--points` 传了不存在的文件路径 → 引擎当内联 JSON 解析而报「不是合法 JSON」；先确认路径是否正确。
- 非法 platform 的报错来自 argparse（英文 `invalid choice`），exit 2、不建目录，属预期行为。
- wx 的三个卖点槽位**同居** `thesis_how`（三抓手），不在三个 thesis 要素里分开找。
- video 的卖点槽位在 `shot_3/4/5`（要素 id=`shot_{2+i}`），缺第几条卖点就对号落 `【占位:价值点N】`。
- 骨架里的占位符计数以正则 `【占位:([^】]*)】` 口径统计（`open_placeholders` 为去重保序的 token 内文清单），与 `structure.json` 的 `placeholder_stats` 同源。
- 总 open 参考值（满 3 卖点）：dy=6、xhs=7、wx=10、video=12；每缺 1 个卖点槽位，xhs/wx/video 的 summary/how/分镜字幕列还会各多出 `价值点N` 计数。
- wx 的 `topic` 在 lead_in / thesis_what / thesis_why / golden_ending 四个要素各记一次 `topic` 填充：满 3 卖点 `total_filled_from_input=7`，0 卖点 `=4`。
- `骨架.md` 统计节行以 `- ` 开头（`- 未填占位符（待人工/AI 补写）：**N 处**`），零填充时打印「无」。
