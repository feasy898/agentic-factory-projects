# spec.md — 知识蒸馏器（论文/官方文档 → 可用 skill）

| 项 | 值 |
|---|---|
| 资产 | `skillfactory/assets/paper-to-skill/` |
| 技能名 | `paper-to-skill` |
| 规格依据 | 参照实现 `oracle/oracle.py` 的**实际行为**（本会话已通读源码并实际运行验证，见 §9 验证记录） |
| 冻结口径 | 本文规则逐条可判定；实现（package/）可在接口内自由重写，但产物行为必须满足本文且通过 `eval/runner.py` |

---

## 0. 实现交付与验收姿势（实现方必读）

**写作口径澄清**：§1–§9 以 `oracle/oracle.py` 为参照冻结**产物行为**；被测实现的入口是
`package/scripts/distill.py`（CLI 契约见 contract §2.1：`--source`/`--outdir`/`--url` 与 R1 同名同义），
行为须逐条满足 R1–R7。从零实现时，下列交付清单必须全部成立——评测门禁与盲评阶段都以它们为前提。

### 0.1 交付清单（全部位于资产根下 `package/`）

| 文件/目录 | 必须性 | 说明 |
|---|---|---|
| `package/SKILL.md` | 必须 | 蒸馏器技能自述，满足 contract §3 五要素 |
| `package/scripts/distill.py` | 必须 | 被测实现入口；仅 Python 标准库；产物相对路径写死 `<outdir>/draft_skill/SKILL.md` 与 `<outdir>/outline.json` |
| `package/example/SKILL.md` | 必须 | 示范产物，五要素齐全。**它是 runner check 1/2 的首选判定对象，也是盲评 treatment 组的先读材料**。runner 在其缺失时会静默回退判定 `package/out/draft_skill/SKILL.md`（自校验兜底）且照样可能判绿——实现方**不得依赖该回退**，缺 `example/` 即视为交付不完整 |
| `package/out/` 与 `package/out-blog/` | 必须 | 实现方亲自对两个黄金输入各运行一次 distill.py 生成（命令见 0.3）；缺失则评测直接失败 |
| `references/`、`assets/` 等 | 可选 | 允许；不得改变上述接口与布局（contract §2） |

### 0.2 黄金输入的位置与读取边界

- 黄金输入的权威路径是 `oracle/inputs/source.md`（spec 例）与 `oracle/inputs/source-blog.md`（blog 例），路径相对资产根；资产根当前**没有** `inputs/` 目录，若任何实现指引给出根级 `inputs/`，以 `oracle/inputs/` 为准。
- 读取边界：把上述两个文件作为 `--source` 的**数据输入**运行与读取是允许且必需的；禁读范围指 oracle 的实现代码（`oracle/oracle.py` 等）与参照产物（`oracle/out*/`）——重生成检验的是"只凭 spec+contract+eval 能否造出等价实现"，读实现或参照产物即失去意义。

### 0.3 验收姿势（实现方自测 = 门禁同款命令；在资产根 `paper-to-skill/` 执行，路径相对资产根）

```bash
python package/scripts/distill.py --source oracle/inputs/source.md --outdir package/out --url https://agentskills.io/specification
python package/scripts/distill.py --source oracle/inputs/source-blog.md --outdir package/out-blog --url https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
python eval/runner.py package/out oracle/out            # spec 例（重生成门禁即此条）
python eval/runner.py package/out-blog oracle/out-blog  # blog 例
python eval/runner.py oracle/out oracle/out             # 参照自校验（应 exit 0；实现方不得改动 oracle/）
```

- 交付完整的判定：上块后三行 runner 命令全部 exit 0，且 spec/blog 两例 check 1/2 的 detail 含 `[判定对象=example]`（出现 `[判定对象=draft_skill]` 说明漏交 `package/example/SKILL.md`）。

## 1. 目标

把一篇 Markdown 来源（论文 / 规范页 / 工程博客的文本稿）**确定性**地蒸馏成技能骨架：

- **输入**：一个 Markdown 源文件（UTF-8，容忍 BOM）＋ 可选的来源 URL。
- **输出**：一个输出目录下的两份产物——
  - `<outdir>/draft_skill/SKILL.md`：含 front-matter、能力范围、分步方法、常见坑、来源引用五要素的技能草稿；
  - `<outdir>/outline.json`：源文档的结构统计与标题树。

不做语义理解、不做摘要改写：**一切内容均为源文档文本的结构化摘取**（标题、列表项、段落句），只按正则与关键词规则抽取。

## 2. 命令行契约（R1）

- R1.1 `python oracle.py --source <md> --outdir <dir> [--url <URL>]`；`--source`、`--outdir` 必填，`--url` 可选（缺省不写入 source_url 相关行）。
- R1.2 源文件不存在 → 以**非 0（实测 2）**退出，stderr 打印含 `ERROR` 的消息，**不创建输出目录、不产出任何文件**。
  - 验证：`--source _verify_tmp/no_such.md` → exit 2、outdir 未创建、stderr 含 ERROR。
- R1.3 成功 → exit 0，stdout 恰好 5 行 `[oracle] ...`（source / title / stats / wrote ×2）。
- R1.4 `--outdir` 不存在时自动创建（含父目录）；已存在时复用。
- R1.5 路径相对当前工作目录解析；脚本不假设运行位置。

## 3. 输入预处理（R2）

按顺序（oracle.py:69-76）：

- R2.1 以 `utf-8-sig` 读取（容忍 BOM），解码失败字节以 U+FFFD 替换，不报错。
- R2.2 **源自身 front-matter 跳过**：若第 1 行 strip 后恰为 `---`，则跳到下一个 strip 后为 `---` 的行，取其后为正文；若无闭合 `---` 则不跳过（全文为正文）。
- R2.3 **头部 HTML 注释剥离**：跳过正文开头的空行后，若首行以 `<!--` 开头，则丢弃直到含 `-->` 的行（含该行）；若注释未闭合（无 `-->`），**不剥离**。
- R2.4 **行号口径（易错点）**：标题/列表/段落/代码块的行号 = 剥离后**正文**内 1 起算的行号，**不是**原文件行号；而 `stats.line_count`/`char_count` 按**全文**（含 front-matter 与头部注释）计。
  - 验证：合成用例 `---/x: y/---/<!--c-->/空/# T1` → H1 行号=2（非 6）；`source.md` 全文 282 行 → `stats.line_count=282`（outline.json:9），而 H1 "Specification" 行号=6（outline.json:33，原文第 13 行）。

## 4. 结构切分规则（R3）

逐行扫描正文（围栏内的行不参与下列任何规则，oracle.py:88-143）：

- R3.1 标题：`^(#{1,6})\s+(.+?)\s*#*\s*$`——行首 1–6 个 `#`，行尾的 `#` 会被剥掉；`> ##` 这类引用块中的标题**不算**标题（`#` 不在行首）。等级 = `#` 个数。
- R3.2 列表项：`^(\s*)(?:([-*+])|(\d{1,9})[.)])\s+(.+)$`——`-`/`*`/`+` 为无序，`数字.` 或 `数字)` 为有序；indent 按 tab 展开为 4 空格后的空格数计。
- R3.3 围栏代码块：`^\s*(`{3,}|~{3,})\s*(.*)$`——开/闭围栏允许行首空白；语言取 info 串**首个空格前 token**（空→`plain`）；闭围栏须以相同字符**开头**且长度 ≥3；**未闭合围栏按文件结尾闭合**；`code_line_count` 含首尾围栏标记行本身。
  - 验证：合成用例 ```python 围栏 → `code_block_languages={"python":1}`、`code_line_count=4`（含两行标记）；`"```\nunclosed"` → 1 块、2 行。
- R3.4 表格行：整行形如 `|...|` 的行计为表格行，但**分隔行**（仅 `|`、空格、`:`、`-`）不计；表格行**只计数**，不进入标题/列表/段落候选池（坑提取也取不到表格行）。
  - 验证：`| a | b |`+`|---|---|`+`| 1 | 2 |` → `table_row_count=2`。
- R3.5 段落：非空且未命中以上规则的行，strip 后记为段落候选。
- R3.6 MDX 标签（如 `<Card>`、`theme={null}`）不特殊处理，按普通文本落入段落/标题规则。

## 5. 结构统计 outline.json 的 stats（R4）

`<outdir>/outline.json` 顶层键固定 8 个：`generator`（"oracle.py"）、`generator_version`、`deterministic`（true）、`source`、`source_url`（无 --url 时为 null）、`source_title`、`stats`、`outline`。`stats` 键固定 13 个（oracle.py:383-408），口径：

| 键 | 口径 |
|---|---|
| `line_count` / `char_count` | 全文行数 / 字符数（含 front-matter 与头部注释区；R2.4） |
| `h1_count` / `h2_count` / `h3_count` / `h4_to_h6_count` / `heading_count` | 各级标题数 / 标题总数 |
| `list_item_count` / `unordered_list_item_count` / `ordered_list_item_count` | 列表项总数 / 无序 / 有序（后两者之和=总数） |
| `code_block_count` / `code_line_count` | 围栏块数 / 围栏块总行数（含标记行，R3.3） |
| `code_block_languages` | 语言→块数的字典，**按语言名排序**，无语言块记 `plain`；无代码块时为 `{}` |
| `table_row_count` | 表格行数（分隔行不计，R3.4） |

- 验证：`out/outline.json` 与复跑产物**字节一致**（3492 B，SHA 比对 equal=True）；`out-blog/outline.json` 同（1953 B）。
- 黄金统计值（不得无故漂移，eval 容差见 contract §5）：spec 例 h1=1, h2=6, h3=5, h4+=6, heading=18, list=33（30 无序+3 有序）, code=19（yaml=14, markdown=3, bash=1, plain=1）, code_lines=77, table=7, line=282, char=8457；blog 例 h1=1, h2=6, h3=1, heading=8, list=14（7+7）, code=0, table=0, line=54, char=3943。

## 6. 标题树（R5）

`outline` 键为嵌套树：节点 `{level, text, line, children}`；用栈构建——新标题弹出所有 **level ≥ 自身 level** 的栈顶节点，挂到剩余栈顶节点的 children（栈空则挂根）。任何等级跳档（H2 直接跟 H4）都合法，父节点由栈语义决定。

## 7. SKILL.md 生成规则（R6）

`<outdir>/draft_skill/SKILL.md`，UTF-8、LF 行尾（`newline="\n"`）。结构固定为五要素（oracle.py:246-352）：

- R6.1 **front-matter**：`---` 围起的 `name` / `description` / `metadata` 三键。
  - `name` = slugify(标题)：小写化 → 非 `[a-z0-9-]` 连续段替换为 `-` → 连续 `-` 折叠 → 去首尾 `-` → 截 64 字符再去尾 `-`；结果为空时回退 `paper-to-skill`。
    - 验证：`Hello World!!`→`hello-world`；`中文标题`→`paper-to-skill`；`a--b`→`a-b`；`-a-`→`a`；100×A→64×a。
  - `description` = 模板 `从源文档《标题》确定性蒸馏的技能骨架：涵盖 X 个一级主题、Y 个二级主题、Z 条列表要点与 W 个代码块。适用场景：需要把该来源文档转化为可执行的 SKILL.md 草稿时使用。`（X/Y/Z/W 来自 stats）；超 1024 字符截为前 1023＋`…`。值经 `yaml_quote` 转义（`\`→`\\`、`"`→`\"`，外层加双引号）。
  - `metadata` 三行：`generator: oracle.py`、`source: "<--source 原样>"`、`source_url: "<--url>"`（给了 --url 才有）。
- R6.2 **题头**：H1 为 `# <标题>（蒸馏骨架）`；标题取第一个 H1（无 H1 取第一个任意级标题；再无则取源文件名 stem）。其后 3 行引用块：生成声明、`重新生成：` 命令（**原样内嵌 --source 与 --outdir 文本**）、name 须与技能目录名一致的提示。
- R6.3 **`## 能力范围`**：首条 bullet 为源结构统计行（`line_count` 行 / H1 / H2 / 列表要点 / 代码块 五个数）；其下至多 8 条子 bullet = H1/H2 标题（跳过与文档标题相同的 H1、按文本去重、超 60 字符截 59＋`…`），每条带 `（原文 L<行号>）`；一个都没有时输出人工补充提示行。末条 bullet 指向 `../outline.json`。
- R6.4 **`## 分步方法`**：三级回退——
  1. 按 H2（无 H2 按 H1，都没有则空）切章节，取前 8 节：每步 `N. **<节标题，>60 截断>**（原文 L<起始行>）`，节内前 2 条列表项作子 bullet（>90 字符截 89＋`…`）；超 8 节时追加"源文档共 X 节，此处仅展开前 8 节"省略行；
  2. 无章节但有顶层（indent=0）有序列表项：取前 8 条作 `N. <文本>（原文 L<行号>）`；
  3. 都没有：输出固定两行通用步骤（"通读来源文档…" / "将流程落成…"）。
  - 验证：合成用例三分支各自命中；spec 例（6 个 H2）走分支 1 且无省略行；blog 例同。
- R6.5 **`## 常见坑`**：候选池 = 标题＋列表项＋段落（**不含表格行**）按行号排序；命中警示关键词（大小写不敏感子串）即入选。关键词 24 个：`must not, do not, don't, cannot, can't, avoid, never, warning, caution, careful, pitfall, mistake, invalid, malicious, security, not recommended`（16 英）＋ `注意, 避免, 不要, 禁止, 切勿, 谨慎, 慎用, 坑`（8 中）。按文档顺序取前 6 条；以**前 60 字符小写**为键去重；>120 字符截 119＋`…`；每条 `- <文本>（原文 L<行号>）`；零命中时输出人工补充提示行。
  - 验证：8 条仅 60 字符后才不同的候选 → 恰取 6 条；表格行 `| warning | row |` 不入选；200 字符候选项长度恰 120 且以 `…` 结尾。
- R6.6 **`## 来源引用`**：固定 4–5 条 bullet——`源文件`（--source 原样）、`来源 URL`（给了 --url 才有）、`源标题`、`结构统计`（H1/H2/列表要点/代码块四数＋指向 `../outline.json`）、`生成方式`（generator 版本＋声明＋完整重跑命令，**内嵌 --source 与 --outdir 原文**）。

## 8. 确定性（R7）

- R7.1 同一输入文件＋同一参数（--source/--outdir/--url 逐字相同）→ 两产物**字节级一致**（无随机、无时间戳、无网络访问）。
  - 验证：本会话复跑 spec/blog 两例，`outline.json` 与存量产物字节一致；SKILL.md 仅因 `--outdir` 文本内嵌于 R6.2/R6.6 而不同（换算后逐字一致）。
- R7.2 **允许的差异**：`--outdir` 字符串会作为"重新生成命令"写进 SKILL.md，故换 outdir 重跑允许 SKILL.md 不同；传相对路径可跨机一致。outline.json 不内嵌 outdir，任何同参重跑都必须字节一致。

## 9. 边界与非目标

- **不做**：语义摘要/改写/翻译（一切文本均为源文档逐字摘取＋截断）、PDF/docx/HTML 直接输入（仅 Markdown 文本稿）、联网抓取（oracle 无网络访问；来源网页由使用者先行抓好）、断言源文档内容正确性、生成 scripts//references/ 等可选目录。
- **已知可接受的"错"**（规则如此，不视为缺陷）：警示关键词命中即整句收录，不判断语境（如博客 "Security considerations" 标题整体成为一条坑）；name 丢中文（中文标题 → 回退名）；截断一律硬截＋`…`。
- 空文件/纯文本输入：不报错，走 R6.4 分支 3 产出合法两产物（合成用例已验证）。

## 10. 验证记录（本会话实际运行）

| 验证 | 命令/方式 | 结果 |
|---|---|---|
| 确定性复跑 | `python oracle/oracle.py --source oracle/inputs/source.md --outdir _verify_tmp/out --url https://agentskills.io/specification`（blog 例同理） | exit 0、stdout 5 行；outline.json 与存量**字节一致**（3492 B / 1953 B）；SKILL.md 仅差内嵌 outdir 文本（10 B，两处命令行） |
| 缺源报错 | `--source _verify_tmp/no_such.md` | exit 2、stderr 含 ERROR、不创建 outdir |
| 解析规则 | `_verify_tmp/verify_oracle.py` 合成 18 项断言（front-matter/注释剥离/行号口径/表格/围栏/列表/slugify/坑提取/三分支回退/yaml_quote；会话级临时脚本，验证后已清理） | **18/18 PASS** |
| 黄金统计 | 读 `oracle/out/outline.json`、`oracle/out-blog/outline.json` | 与 §5 表格逐项一致 |

> oracle 源码行号引用以 `oracle/oracle.py` 为准；本 spec 冻结的是**行为**，行号仅佐证出处。
