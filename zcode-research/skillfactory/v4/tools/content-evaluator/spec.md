# spec.md — 内容确定性评测器（content-evaluator）资产规格

> 资产根：`skillfactory/v4/tools/content-evaluator/`
> 规格依据：oracle 参照实现 `oracle/evaluate.py` 1.0.0（逐行读过）+ 四份 fixtures 的实跑产物
> `oracle/out/{good_dy,good_xhs,bad_xhs,bad_wx}/{report.json,REPORT.md}`，
> 以及本次会话的探针实验（§2.2，全部亲自跑过）。
> 本规格逐条可判定：每条规则都给出「判定方法」，`eval/runner.py` 据此机械化判分。

---

## 1. 目标

把「对一篇 markdown 文案按目标平台做合规与结构打分」的 oracle 行为固化为软件资产：

| 文件 | 角色 |
|---|---|
| `oracle/evaluate.py` | 参照实现（CLI 评测工具，行为在 §3 冻结） |
| `oracle/fixtures/` | 四份样例文案（good_dy / good_xhs / bad_xhs / bad_wx，评测的输入基准） |
| `oracle/out/` | 四份样例的评测报告基线（eval 的参照产物，只读） |
| `spec.md` / `contract.md` | 规格（本文）与接口契约 |
| `eval/runner.py` | 确定性评测器：判「一份 content-evaluator 产物集」是否合格（§5） |

评测的对象是 **markdown 文案**；eval 的对象是 **content-evaluator 的产物**
（report.json + REPORT.md，共 4 样本 × 2 文件）。两层不要混。

## 2. oracle 实测基线（本规格的证据）

### 2.1 四个样本（2026-09-30 基线，存于 `oracle/out/`，本次会话复跑核对）

| fixture | 平台 | score | summary(pass/fail/warn) | FAIL 项 | WARN 项 |
|---|---|---|---|---|---|
| `good_dy.md` | dy | 9/9 | 9/0/0 | 无 | 无 |
| `good_xhs.md` | xhs | 9/9 | 9/0/0 | 无 | 无（emoji 5 个在 [2,15] 内） |
| `bad_xhs.md` | xhs | 4/9 | 4/5/0 | title_length(25>20)、emoji_density(0<2)、tag_count(0<3)、banned_words(12词13次)、structure_cta | 无 |
| `bad_wx.md` | wx | 6/9 | 6/3/1 | paragraph_max(422>350)、banned_words(6词6次)、structure_cta | emoji_density(22>20，pass=true+warning) |

四份 report.json 的 `checks` 数组顺序均为 §3 R2 冻结的 9 项；`tool` 均为
`evaluate.py 1.0.0`；`score.ratio` 分别为 1.0 / 1.0 / 0.4444 / 0.6667。

### 2.2 本次会话探针（2026-09-30 实跑，Python 3.12.10）

- 干净重建：四条 `python evaluate.py --input fixtures/<f>.md --platform <p> --out <临时目录>/<f>`
  全部 exit 0；重跑产物与 `oracle/out/` 基线相比，report.json 仅 `generated_at` 一个键不同
  （checks / score / summary 逐键相等），REPORT.md 仅「生成时间」一行不同（diff 验证）——
  证明 §3 各规则确定性。
- `--platform tiktok` → argparse 报 `invalid choice: 'tiktok' (choose from dy, wx, xhs)`，
  exit 2，`--out` 目录未被创建（ls 验证）。
- `--input` 指向不存在文件 → stderr「错误：--input 不是文件: …」，exit 2，`--out` 未被创建。
- 缺 `--out` 参数 → argparse `the following arguments are required: --out`，exit 2。

## 3. oracle 行为规则（逐条可判定）

### R1 CLI 与参数
`python oracle/evaluate.py --input <markdown文件> --platform <dy|xhs|wx> --out <报告目录>`；
三个参数均必填（argparse 缺任一 → exit 2）。
- `--platform` 非 {dy,xhs,wx} → argparse invalid choice，exit 2，**不创建** `--out`。
- `--input` 不是文件（含不存在）→ stderr 报错，exit 2，**不创建** `--out`、不写任何产物。
- 输入可按 utf-8-sig / utf-8 / gbk 依次尝试解码，全失败 → stderr 报错，exit 2。
- 其余一切情况（红绿均算，本工具只报告不设门）→ exit 0。
- 判定：跑命令看退出码与 `--out` 内容。

### R2 检查项集合与顺序（冻结）
恰 9 项，顺序固定：`title_length` → `emoji_density` → `body_length` → `paragraph_max` →
`tag_count` → `banned_words` → `structure_hook` → `structure_cta` → `structure_para`。
report.json 的 `checks` 数组顺序与此一致。
- 判定：读任一 report.json，`checks[].name` 序列逐字等于上述序列。

### R3 平台阈值（内置，冻结）

| 平台 | label | 标题字数 | 正文字数(去空白) | 单段上限 | 标签数 | emoji 规则 | 最少段落 |
|---|---|---|---|---|---|---|---|
| dy | 抖音 | [10,30] | [50,300] | 120 | [3,8] | >10 警告 | 2 |
| xhs | 小红书 | [8,20] | [100,800] | 160 | [3,10] | **硬区间 [2,15]**，越界即失败 | 3 |
| wx | 微信公众号 | [10,64] | [300,3000] | 350 | [0,8] | >20 警告 | 3 |

- 判定：任一 report.json 的 detail 内嵌了区间数字（如 bad_xhs「标题 25 字，超出区间 [8, 20]」），
  与本表逐一相符；四样本 score 与 §2.1 表一致即为端到端验证。

### R4 文本解析口径（冻结）
- 标题 = 首个 `# `（一级标题）行的内容；无一级标题时取首个非空行充当标题（正文保留原行）。
- 正文 = 去掉标题行后的全部文本；字数按**去空白可见字符**计（含标点、emoji、#）。
- 段落 = 正文按空行（`\n\s*\n`）分块、去空白后非空的块。
- `#标签` 计数：逐行扫描，跳过 markdown 标题行（`^#{1,6}\s`），`#` 后紧跟非空白/非标点才算；
  emoji 计数按 emoji 码点逐个统计（无 `+` 量词，连续 emoji 不并簇；ZWJ 组合按组成码点分别计）。
- 判定：good_xhs「emoji 共 5 个」（标题☕️+🐕+🐻+🌿+📍），bad_wx「emoji 共 22 个」——与
  fixture 内 emoji 数一致。

### R5 各检查项判定（冻结）
1. `title_length`：标题去空白字数 ∈ 平台区间；空标题 fail。
2. `emoji_density`：xhs 数量 ∈ [2,15]，越界 **fail**；dy/wx 仅超上限（10/20）→
   **pass=true 且 warning=true**（不计失败），未超 → pass、无警告。
3. `body_length`：正文去空白字数 ∈ 平台区间。
4. `paragraph_max`：最长段落去空白字数 ≤ 平台单段上限；无段落 fail。
5. `tag_count`：`#标签` 数 ∈ 平台区间。
6. `banned_words`：正文（标题+正文全文，小写化后）命中内置 44 词极限词表任一词即 fail，
   detail 列「命中 N 个极限词（共 M 次）：词×次数…」按次数降序；未命中 pass。
7. `structure_hook`：标题或首段含钩子词（为什么/如何/救命/必看 等 33 词）或含问号 → pass；
   xhs 额外承认「标题带 emoji」。
8. `structure_cta`：正文含 CTA 引导词（点赞/关注/收藏/码住/评论/私信/在看/星标 等 21 词）之一 → pass。
9. `structure_para`：段落数 ≥ 平台最少段落数。
- 判定：§2.1 表的 FAIL/WARN 集合即四份 fixtures 的端到端预期；eval 按 name 取 `pass` 布尔核对。

### R6 计分规则（冻结）
总分 = 通过项 / 应检项，9 项全部应检（警告计入通过并单列 warning 标记，不扣分）。
report.json 的 `score = {passed, applied, ratio, text}`，其中 `ratio = round(passed/applied, 4)`、
`text = "<passed>/<applied>"`；`summary = {applied, pass, fail, warn}`，fail = pass=false 计数、
warn = pass=true 且 warning=true 计数。REPORT.md 的「**总分：p/a**（xx.x%）」行与之同源。
- 判定：json.load 后程序复算 `passed == count(checks.pass=true)`、`applied == len(checks)`，
  summary/fail/warn 同口径复算一致。

### R7 report.json schema（冻结）
字段与类型：`tool`（"evaluate.py 1.0.0"）、`input`（输入文件绝对路径）、`platform`（dy/xhs/wx）、
`platform_label`（中文平台名）、`generated_at`（本地时间 `%Y-%m-%dT%H:%M:%S%z`，
**唯一的非确定性字段**）、`summary`（见 R6）、`score`（见 R6）、`checks`（数组，元素
`{name: str, pass: bool, warning: bool, detail: str}`，warning 由 oracle 恒输出，顺序见 R2）。
序列化：UTF-8、`ensure_ascii=False`、`indent=2`、结尾换行。
- 判定：json.load 后逐字段核对类型；`checks[].warning` 为 bool。

### R8 REPORT.md schema
固定结构：标题 `# 内容评测报告（<平台中文名> · <输入文件名>）`；五行元信息（输入文件 / 平台 /
生成时间 / `**总分：p/a**（xx.x%）` / `汇总：应检 N 项，通过 P / 失败 F / 警告 W`）；检查表格
（表头 `| 检查项 | 结果 | 说明 |`，每检查一行，✅ PASS / ❌ FAIL / ⚠️ WARN——warning 项用 ⚠️）；
`## 修改建议` 节（先逐失败项，后逐警告项，均带内置建议文案；全过时为「全部通过，无需修改。」）。
机器可判锚点（正则）：`总分：(\d+/\d+)`、`应检 (\d+) 项，通过 (\d+) / 失败 (\d+) / 警告 (\d+)`、
逐检查行 `` | `<name>` | (✅ PASS|❌ FAIL|⚠️ WARN) | ``。
- 判定：四份 REPORT.md 均能以锚点提取出与 report.json 一致的数字与逐项标记。

### R9 退出码
`0` = 报告已写出（**无论红绿**，本工具只报告不设门）；`2` = 参数/输入无效（缺参、platform 非法、
input 不是文件、输入不可解码）。没有 exit 1。
- 判定：§2.2 三条探针 + 四样本实跑均为 0。

### R10 确定性
同一输入重复运行：除 `generated_at`（及由它派生的 REPORT.md 生成时间行）外，
report.json / REPORT.md 逐字节一致。纯标准库、离线、无随机。
- 判定：§2.2 干净重建 diff 实验。

## 4. 边界与非目标

- **不做语义/文风评判**：全部检查是字数区间、词表命中、结构计数等确定性规则；
  不调 LLM、不联网、无随机（同输入同输出）。
- **警告不是失败**：dy/wx 的 emoji 超上限只警告（pass=true+warning=true），总分不受影响；
  这是 xhs（硬区间）与 dy/wx（软上限）的有意差异，不是 bug。
- **单文件单平台**：一次调用评一篇文案对一个平台；不做多平台对比、不做批量目录扫描。
- **极限词表内置且有限**：44 词是内置口径，不做分词、不做变体识别（如「最⭐好」绕过不算命中）。
- 标题/正文解析只覆盖常规 markdown（一级标题 + 空行分段）；嵌套列表/代码块不特判。
- `eval/runner.py` 判的是「content-evaluator 的产物集」，不重跑 evaluate.py、不接触 fixtures 源文件。
- 平台口径：win32 + Python ≥3.8（本机 3.12.10 实测）；标准库实现，无第三方依赖。

## 5. eval/runner.py 判分规则（写死在工具内）

- **产物根布局**（被测与参照同构）：`<root>/{good_dy, good_xhs, bad_xhs, bad_wx}/`，
  各含 `report.json` 与 `REPORT.md`（四个样本名写死，与 `oracle/fixtures/` 一一对应）。
- **CLI**：`python eval/runner.py [<被测产物根> <参照产物根>]`；零参数时两者均取内置缺省
  `<runner 目录>/../oracle/out`（自校验应全过）；参数个数非 0/2 → 用法错误 exit 2。
- **report.json 结构校验口径**：顶层 JSON 对象；`checks` 为非空数组；元素含
  `name:str / pass:bool / detail:str`（`warning` 可缺省，出现时须为 bool，缺省按 false 计警告口径）。
- **固定 6 项检查**（全部通过 exit 0 并打印 JSON；任一失败 exit 1）：
  1. `good_fixtures_all_pass` — good_dy 与 good_xhs 的 report.json 存在、结构合法、9 项全部 pass=true。
  2. `bad_xhs_expected_fails` — bad_xhs 的 `title_length` / `emoji_density` / `tag_count` /
     `banned_words` / `structure_cta` 五项**均** pass=false（§2.1 基线违规集）。
  3. `bad_wx_expected_fails` — bad_wx 的 `paragraph_max` / `banned_words` / `structure_cta`
     均 pass=false，**且** `emoji_density` 为 pass=true + warning=true（软上限警告路径）。
  4. `score_recompute` — 四样本各自的 checks 恰为 R2 冻结的 9 项且顺序一致；
     `score.{passed,applied,ratio,text}` 与 `summary.{applied,pass,fail,warn}` 全部与逐项复算一致
     （复算口径见 R6）。
  5. `report_md_consistency` — 四样本 REPORT.md 的三个锚点（总分 `p/a`、汇总四元组、逐检查行
     PASS/FAIL/WARN 标记）与 report.json 逐一一致。
  6. `oracle_agreement_90pct` — 与参照产物按（4 样本 × 9 检查名）共 36 对 `pass` 布尔比对，
     一致率 ≥ 0.90（即至多容忍 3 对不一致）；参照产物缺失/损坏直接判败。
- **输出**：stdout 打印 `{"ok": bool, "summary": {total, pass, fail, tested_root, reference_root},
  "checks": [{name, pass, detail}]}`；无时间戳，同输入同输出。
- **退出码**：0 = 全过；1 = 任一检查失败；2 = 用法错误（参数个数非 0/2）。
