# OUT.md — hot-templates · ab-003 · arm-a · rep2 完整成果

- 任务：使用 hot-templates 技能生成公众号文章爆款内容骨架（golden.json `ab_tasks` 之 `ab-003`）
- 材料（自含）：`platform=wx`，`topic=非暴力沟通`，`points=[]`（空列表，零卖点边界）
- 冻结模板：引子 + 三段论（是什么/为什么/怎么办）+ 金句收尾（5 要素，模板版本 1.0）
- 输出目录：`skillfactory/v4/assets/hot-templates/tests/ab/ab-003/arm-a/rep2`
- 执行日期：2026-09-30（windev-01，实际 shell 为 Git Bash）

## 一、方法（严格按 SKILL.md）

1. 完整读取 `package/SKILL.md`（107 行全文）；
2. 按文档地图完整读取 `references/` 全部五份：`wx.md`（57 行）、`frozen-tokens.md`（77 行）、`dy.md`（37 行）、`xhs.md`（44 行）、`video.md`（56 行）；
3. 遵守红线：骨架生成一律走 `scripts/gen.py` 确定性引擎（SKILL.md 权威规则 4），**未手写/未改写** `structure.json`；`【占位:…】` 为设计内开放槽位，未做任何内容补写（权威规则 3）。

## 二、生成执行

命令（各参数均命中 SKILL.md「输入格式」表：platform ∈ {dy,xhs,wx,video} 取 wx；topic 非空；points 为内联 JSON 串 `[]`；outdir 不存在由引擎递归创建）：

```bash
python "D:\workspace\zcode研究\skillfactory\v4\assets\hot-templates\package\scripts\gen.py" \
  --platform wx --topic 非暴力沟通 --points "[]" \
  --outdir "D:\workspace\zcode研究\skillfactory\v4\assets\hot-templates\tests\ab\ab-003\arm-a\rep2"
```

实测输出：`exit 0`，stdout 一行：

```
OK platform=wx topic=非暴力沟通 elements=5 open_placeholders=13 filled_from_input=4 -> D:\workspace\zcode研究\skillfactory\v4\assets\hot-templates\tests\ab\ab-003\arm-a\rep2
```

成功判据（SKILL.md「使用步骤」3，三条同时满足）：
- exit **0** ✅（实测 `EXIT=0`）
- stdout 打印 `OK platform=… topic=… elements=… open_placeholders=… filled_from_input=… -> <outdir>` ✅
- `<outdir>/骨架.md`（2029 字节）与 `<outdir>/structure.json`（3957 字节）均存在且非空 ✅（`wc -c` 实测）

## 三、产物一：骨架.md（全文）

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

## 四、产物二：structure.json（全文）

```json
{
  "template_version": "1.0",
  "platform": "wx",
  "platform_name": "公众号文章",
  "structure_name": "引子 + 三段论 + 金句收尾",
  "topic": "非暴力沟通",
  "points_input_count": 0,
  "points_used": [
    null,
    null,
    null
  ],
  "points_unused": [],
  "element_count": 5,
  "elements": [
    {
      "id": "lead_in",
      "name": "引子",
      "order": 1,
      "required": true,
      "text": "【占位:用一个具体场景/对话/新闻切入，150字左右】——这背后，其实是同一个问题：非暴力沟通。",
      "placeholder_count": 1,
      "open_placeholders": [
        "用一个具体场景/对话/新闻切入，150字左右"
      ],
      "filled_from_input": [
        "topic"
      ],
      "meta": {
        "beat": "场景化开场，把读者拉进问题现场"
      }
    },
    {
      "id": "thesis_what",
      "name": "三段论·一（是什么）",
      "order": 2,
      "required": true,
      "text": "一、是什么\n非暴力沟通的本质，不是【占位:常见误解】，而是【占位:一句话给出你的定义】。",
      "placeholder_count": 2,
      "open_placeholders": [
        "常见误解",
        "一句话给出你的定义"
      ],
      "filled_from_input": [
        "topic"
      ],
      "meta": {
        "beat": "先破后立，给出定义"
      }
    },
    {
      "id": "thesis_why",
      "name": "三段论·二（为什么）",
      "order": 3,
      "required": true,
      "text": "二、为什么\n大多数人在非暴力沟通上反复失败，根源有三：【占位:根因1】；【占位:根因2】；【占位:根因3】。",
      "placeholder_count": 3,
      "open_placeholders": [
        "根因1",
        "根因2",
        "根因3"
      ],
      "filled_from_input": [
        "topic"
      ],
      "meta": {
        "beat": "归因，三条根因对齐后文三个抓手"
      }
    },
    {
      "id": "thesis_how",
      "name": "三段论·三（怎么办）",
      "order": 4,
      "required": true,
      "text": "三、怎么办\n落到操作层面，给你三个抓手：\n1. 【占位:价值点1】——【占位:展开：具体做法+一个例子】\n2. 【占位:价值点2】——【占位:展开：具体做法+一个例子】\n3. 【占位:价值点3】——【占位:展开：具体做法+一个例子】",
      "placeholder_count": 6,
      "open_placeholders": [
        "价值点1",
        "展开：具体做法+一个例子",
        "价值点2",
        "价值点3"
      ],
      "filled_from_input": [],
      "meta": {
        "beat": "三个抓手一一对应三条根因，可执行"
      }
    },
    {
      "id": "golden_ending",
      "name": "金句收尾",
      "order": 5,
      "required": true,
      "text": "「非暴力沟通这件事，【占位:金句主体——句式建议：真正的…不是靠…，而是靠…】」\n共勉。",
      "placeholder_count": 1,
      "open_placeholders": [
        "金句主体——句式建议：真正的…不是靠…，而是靠…"
      ],
      "filled_from_input": [
        "topic"
      ],
      "meta": {
        "beat": "一句话收束，可直接被读者摘抄转发"
      }
    }
  ],
  "placeholder_stats": {
    "total_open": 13,
    "total_filled_from_input": 4,
    "by_element": {
      "lead_in": 1,
      "thesis_what": 2,
      "thesis_why": 3,
      "thesis_how": 6,
      "golden_ending": 1
    },
    "open_tokens_unique": [
      "用一个具体场景/对话/新闻切入，150字左右",
      "常见误解",
      "一句话给出你的定义",
      "根因1",
      "根因2",
      "根因3",
      "价值点1",
      "展开：具体做法+一个例子",
      "价值点2",
      "价值点3",
      "金句主体——句式建议：真正的…不是靠…，而是靠…"
    ],
    "filled_slots": [
      "topic",
      "topic",
      "topic",
      "topic"
    ]
  }
}
```

## 五、ab-003 rubric 逐项核验（程序化断言，25/25 PASS，脚本 exit 0）

| rubric 项 | 断言结果 |
|---|---|
| 结构：5 要素齐备，id 顺序 `lead_in→thesis_what→thesis_why→thesis_how→golden_ending` | PASS（实测 ids 即此序列，element_count=5） |
| 结构：thesis_what / thesis_why / thesis_how 的 text 分别以「一、是什么」「二、为什么」「三、怎么办」开头 | PASS（三要素 startswith 全真） |
| 零卖点边界：thesis_how 三抓手全落【占位:价值点1】【占位:价值点2】【占位:价值点3】 | PASS（三个 token 均在 text 中） |
| 零卖点边界：points_used == [null, null, null] | PASS（实测 `[None, None, None]`） |
| 零卖点边界：任何要素 filled_from_input 不含 point#N | PASS（全要素仅 `["topic","topic","topic","topic"]`，thesis_how 为 `[]`） |
| 收尾：golden_ending 含「共勉」 | PASS |
| 统计：total_open(13) == by_element 之和(1+2+3+6+1=13)，且与骨架.md「占位符统计」节的 **13 处** 一致 | PASS |
| 附加自洽：每要素 `placeholder_count` 与正则 `【占位:([^】]*)】` 重计数及去重保序清单一致（5 要素） | PASS |
| 附加纯净：两份产物无 `{{`/`}}` 模板残留 | PASS |
| 附加冻结：platform=wx、platform_name=公众号文章、structure_name=引子 + 三段论 + 金句收尾、金句结构 `「<主题>这件事，…」\n共勉。`、topic 四要素填充（total_filled_from_input=4） | PASS |

零卖点 open 口径说明：wx 满 3 卖点总 open=10（SKILL.md gotchas 参考值），每缺 1 个卖点槽位 +1 计数，0 卖点 = 10+3 = **13**（SKILL.md:106），与引擎实测一致；`total_filled_from_input=4` 亦符合 SKILL.md:107 的 0 卖点口径。

## 六、验收证据

1. **oracle 同材料逐字节比对**：oracle 用例 `wx/case2`（`oracle/inputs/wx/case2.json`：platform=wx，topic=非暴力沟通，points=[]，与本任务材料完全相同）。实测：
   ```
   cmp oracle/out/wx/case2/骨架.md      rep2/骨架.md        → 骨架.md IDENTICAL
   cmp oracle/out/wx/case2/structure.json rep2/structure.json → structure.json IDENTICAL
   ```
2. **资产内全量验收**（SKILL.md:80 判据）：将 golden.json 全部 8 用例（dy/xhs/wx/video × case1/case2，输入取自 `oracle/inputs/`）用同一 `scripts/gen.py` 生成到临时候选根后执行
   `python eval/runner.py <候选根> oracle/out`
   → 实测 **exit 0**，summary：`{"cases": 8, "checks_total": 40, "passed": 40, "failed": 0, "consistency_threshold": 0.9, "consistency_min": 1.0}`（8 case × 5 检查全过，结构一致率全部 100%，其中 `wx/case2` 31/31）。临时目录已在验收后删除。

## 七、红线遵守声明

- 未手写或改写 `structure.json`，产物由 `scripts/gen.py` 确定性渲染（同输入重跑逐字节一致，已由 oracle 比对与全量验收间接证实）；
- `【占位:…】` 共 13 处均为**设计内开放槽位**（零卖点点位 3 处 + 要素槽位 10 处），未由引擎或本 agent 编造内容填充；
- 产物中无 `{{ }}` 类未填充模板变量残留；
- 冻结标记（三段论段首「一、是什么/二、为什么/三、怎么办」、金句「共勉」、要素 id 与顺序）未做任何改动。

## 八、本目录交付物清单

| 文件 | 说明 |
|---|---|
| `骨架.md` | 人读骨架（2029 字节，UTF-8/LF） |
| `structure.json` | 机器可读结构（3957 字节，UTF-8/LF，顶层 11 键/每要素 9 键/统计 5 键） |
| `OUT.md` | 本文件（完整成果与验收记录） |
