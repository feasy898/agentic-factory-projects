# content-evaluator 实现包（内容确定性评测器）

对一篇 markdown 文案按目标平台（抖音 dy / 小红书 xhs / 微信公众号 wx）做合规与结构打分。
纯标准库、离线、无随机：全部检查是字数区间、词表命中、结构计数等确定性规则，
不调 LLM、不做语义评判；**只报告不设门**——红绿都算成功运行（exit 0）。

## 用法

```
python evaluate.py --input <markdown文件> --platform <dy|xhs|wx> --out <报告目录>
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--input` | 是 | 输入 markdown 文件；按 utf-8-sig / utf-8 / gbk 依次尝试解码 |
| `--platform` | 是 | 仅接受 `dy` / `xhs` / `wx` |
| `--out` | 是 | 报告输出目录（自动创建），写出 `report.json` + `REPORT.md` |

**退出码**：`0` = 报告已写出（无论红绿）；`2` = 参数/输入无效（缺参、platform 非法、
input 不是文件、输入不可解码）——此时**不创建** `--out`、不写任何产物。没有 exit 1。

## 平台阈值表

标题/正文/标签按**去空白可见字符数**计（含标点、emoji、#）。

| 平台 | label | 标题字数 | 正文字数 | 单段上限 | 标签数 | emoji 规则 | 最少段落 |
|---|---|---|---|---|---|---|---|
| `dy` | 抖音 | [10, 30] | [50, 300] | 120 | [3, 8] | >10 仅警告 | 2 |
| `xhs` | 小红书 | [8, 20] | [100, 800] | 160 | [3, 10] | **硬区间 [2, 15]**，越界即失败 | 3 |
| `wx` | 微信公众号 | [10, 64] | [300, 3000] | 350 | [0, 8] | >20 仅警告 | 3 |

> 警告不是失败：dy/wx 的 emoji 超软上限输出 `pass=true, warning=true`，不扣分；
> xhs 是硬区间，越界直接 fail。这是有意差异，不是 bug。

## 检查项表（9 项，名称与顺序冻结）

| # | 检查项 | 判定 | 通过示例 detail | 失败/警告示例 detail |
|---|---|---|---|---|
| 1 | `title_length` | 标题去空白字数 ∈ 平台区间；空标题 fail | 标题 12 字，在区间 [10, 30] 内 | 标题 25 字，超出区间 [8, 20] |
| 2 | `emoji_density` | xhs：数量 ∈ [2,15] 越界 fail；dy/wx：超软上限（10/20）→ pass+warning | emoji 共 5 个，在区间 [2, 15] 内 | emoji 共 22 个，超出软上限 20（仅警告，不计失败） |
| 3 | `body_length` | 正文去空白字数 ∈ 平台区间 | 正文 198 字，在区间 [100, 800] 内 | 正文 23 字，超出区间 [100, 800] |
| 4 | `paragraph_max` | 最长段落去空白字数 ≤ 单段上限；无段落 fail | 最长段落 40 字，未超单段上限 160 | 最长段落 422 字，超出单段上限 350 |
| 5 | `tag_count` | `#标签` 数 ∈ 平台区间 | 标签 7 个，在区间 [3, 10] 内 | 标签 0 个，低于区间 [3, 10] |
| 6 | `banned_words` | 标题+正文全文（小写化）命中内置 44 词极限词表任一词即 fail；detail 按次数降序列「词×次数」 | 未命中极限词（词表 44 词） | 命中 12 个极限词（共 13 次）：最好×2、… |
| 7 | `structure_hook` | 标题或首段含钩子词（33 词表）或含问号；xhs 额外承认标题带 emoji | 标题含钩子词「救命」 | 标题与首段均未含钩子词或问号 |
| 8 | `structure_cta` | 正文含 CTA 引导词（21 词表）之一 | 正文含 CTA 引导词「点赞」 | 正文未含 CTA 引导词（词表 21 词） |
| 9 | `structure_para` | 段落数 ≥ 平台最少段落数 | 段落 6 段，达到最少 3 段 | 段落 1 段，少于最少 3 段 |

**解析口径**：标题 = 首个 `# `（一级标题）行的内容，无则取首个非空行充当标题（正文保留原行）；
正文 = 去掉标题行后的全部文本；段落 = 正文按空行（`\n\s*\n`）分块、去空白后非空；
`#标签` 逐行扫描（跳过 markdown 标题行），`#` 后紧跟非空白/非标点才算；
emoji 按码点逐个统计（VS16/ZWJ 等组合符不计，连续 emoji 不并簇）。

**计分**：总分 = 通过项 / 应检项（9 项全部应检，警告计入通过不扣分）；
`summary.warn` = pass 且 warning 的项数；`score.ratio = round(passed/applied, 4)`。

## fixtures 预期（评测基线）

| fixture | 平台 | 预期总分 | FAIL | WARN |
|---|---|---|---|---|
| `fixtures/good_dy.md` | dy | 9/9 | 无 | 无 |
| `fixtures/good_xhs.md` | xhs | 9/9 | 无 | 无（emoji 5 个在 [2,15] 内） |
| `fixtures/bad_xhs.md` | xhs | 4/9 | title_length(25>20)、emoji_density(0<2)、tag_count(0<3)、banned_words(12词13次)、structure_cta | 无 |
| `fixtures/bad_wx.md` | wx | 6/9 | paragraph_max(422>350)、banned_words(6词6次)、structure_cta | emoji_density(22>20) |

## 产物 schema

`report.json`：`tool` / `input`（绝对路径）/ `platform` / `platform_label` / `generated_at`
（本地时间，**唯一非确定性字段**）/ `summary` / `score` / `checks`（9 元素，顺序同上表，
元素 `{name, pass, warning, detail}`）。UTF-8、`ensure_ascii=False`、`indent=2`、结尾换行。

`REPORT.md`：标题 + 五行元信息（输入文件 / 平台 / 生成时间 / **总分：p/a**（xx.x%）/ 汇总）
+ 检查表（`| 检查项 | 结果 | 说明 |`，✅ PASS / ❌ FAIL / ⚠️ WARN）+ `## 修改建议`
（先逐失败项后逐警告项；全过时为「全部通过，无需修改。」）。

**确定性**：同一输入重复运行，除 `generated_at`（及 REPORT.md 生成时间行）外逐字节一致。

## 本目录布局

```
package/
├── evaluate.py    # 评测器本体（本文件所述行为的实现）
├── README.md      # 本文件（检查项与阈值表）
├── fixtures/      # 四份样例文案（good_dy / good_xhs / bad_xhs / bad_wx）
└── out/           # 对同 fixtures 的实跑产物（重跑会覆盖）
```
