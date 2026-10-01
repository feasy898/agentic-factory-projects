# spec.md — PPT 方法意图路由（ppt-method-router）规格

> 依据：`oracle/` 参照实现的**实际行为**固化（`oracle/oracle.py`，确定性关键词规则）。
> 每条规则附可判定验证方法：运行所附命令、比对 stdout JSON。全部行号引用 `oracle/oracle.py`。
> 实测环境：本机 Windows x64 + Python 3.12.10（本资产目录下实际运行通过，见 §6）。
> **被测交付物是 `package/` 目录**（完成定义见 §7）；黄金输入 20 条全文内嵌于 §8，
> 实现 package 时**以 §8 为输入的唯一权威来源，无需读取 `oracle/` 目录**（见 §7.3）。

## 1. 目标

给定一条用户的 PPT 制作意图文本，**确定性地**路由到三类制作方式之一，并输出置信度与裁定理由：

| method | 含义 |
|---|---|
| `editable_pptx` | 数据驱动可编辑汇报 |
| `template_fill` | 套用既有公司模板 |
| `visual_report` | 图文海报/信息图 |

本技能是"多方法融合大 skill"的路由层：只决定**选哪条路**，不执行任何一条路（见 §5 非目标）。

## 2. 输入 / 输出契约

### 2.1 输入
- 命令行：`python oracle.py --input <意图.txt>`（package 侧同构脚本契约见 contract.md §2.1；package 侧交付与验收流程见本文 §7）
- `--input` 必填；文本文件，UTF-8 编码、容许 UTF-8 BOM（oracle.py:104 用 `utf-8-sig` 读取）
- 文件内容整体（可多行）视为**一条**意图，读取后 `strip()` 去首尾空白（oracle.py:105）
- 文件不存在 → **退出码 2**，stderr 提示 `输入文件不存在: <路径>`，stdout 无 JSON（oracle.py:100-102）

### 2.2 输出
- stdout **恰一行** JSON（UTF-8、非 ASCII 原样输出，oracle.py:108-112），成功退出码 0：

```json
{"method": "template_fill", "confidence": 0.65, "reasons": ["…", "…"]}
```

- 字段语义：
  - `method`：§1 三值枚举之一；
  - `confidence`：数值 ∈ [0,1]，公式保留两位小数（JSON 序列化省略尾零，如 `0.9`、`0.4`）；
  - `reasons`：非空字符串数组，逐条写明命中关键词、裁定依据（单类/优先级/兜底）与冲突提示。

可判定验证（本机实测通过）：

```
python oracle/oracle.py --input oracle/inputs/case15.txt
# 期望 stdout（reasons 全文见 oracle/out/labels.json case15）：
# {"method": "template_fill", "confidence": 0.65, "reasons": ["命中[template_fill(套用既有公司模板)]关键词：品牌", "命中[visual_report(图文海报/信息图)]关键词：海报、一页", "多类信号同时出现（template_fill > visual_report），按优先级 template_fill > editable_pptx > visual_report 裁定为 template_fill(套用既有公司模板)", "冲突说明：…建议人工复核"]}
```

## 3. 行为规则（逐条可判定）

### R1 关键词表（oracle.py:39-43）

| 类别 | 关键词 |
|---|---|
| template_fill | 模板、公司VI、套用、品牌 |
| editable_pptx | 数据、表格、台账、月报、图表、汇报 |
| visual_report | 海报、一页、信息图、视觉、朋友圈、转发 |

### R2 匹配方式
- 子串匹配、大小写不敏感：对文本与关键词均 `lower()` 后 `in` 判定（oracle.py:57-61）。
- 判定：case3「用我们公司的品牌VI模板做一份对外介绍」→ 命中 模板、品牌，**不命中"公司VI"**（"公司"与"VI"在文本中不连续）→ `template_fill / 0.85`（实测复现，见 §6）。

### R3 单类命中（oracle.py:73-78）
- 仅一类命中 → method = 该类。
- `confidence = 0.80 + 0.05 × (命中词数 − 1)`，上限 0.95（oracle.py:75）。
- 判定：case1 命中 4 词 → 0.95；case2 命中 3 词 → 0.9；case9 命中 1 词 → 0.8。

### R4 多类命中·冲突裁定（oracle.py:80-91）
- 按 **template_fill > editable_pptx > visual_report** 取最高优先级类（RULES 列表顺序即优先级，oracle.py:38、82）。
- `confidence = 0.60 + 0.05 × (各类命中词总数 − 2)`，上限 0.75——信号冲突压低置信度（oracle.py:84）。
- reasons 必须包含三部分：① 每类命中关键词清单；② 优先级链与裁定结果；③ 冲突说明与人工复核建议（oracle.py:85-90）。
- 判定：case15 → template_fill / 0.65；case14 → editable_pptx / 0.7；case12 → editable_pptx / 0.6。

### R5 无信号兜底（oracle.py:51-52、68-71）
- 任何关键词都未命中 → method = `editable_pptx`，`confidence = 0.40`。
- reasons 必须写明"未命中任何类别关键词（无信号）"与兜底默认，不得编造命中词。
- 说明：任务未规定无信号行为；该兜底是 oracle 实现选定并在 docstring 显式声明的确定性行为（oracle.py:22-23）。黄金集 case10 / case11 固定此期望。

### R6 确定性
- 纯规则、无随机、无外部输入：同一输入重复运行输出逐字节一致。
- 实测：两次全量重跑（`gen_inputs.py` + `run_all.py`）后 `oracle/out/labels.json` md5 均为 `47e74b713811ea7b41b38d9705169f0c`（本次复核一致）。

## 4. 黄金样例（20 条）与期望判定

样例文件 `oracle/inputs/case1-20.txt`（`oracle/gen_inputs.py` 确定性生成）；期望判定 `oracle/out/labels.json`（20 条 `[{case, method, confidence, reasons}]`）。
**20 条样例的全文见本文 §8**：package 实现者据此创建 `package/inputs/`，禁止读取 `oracle/`（见 §7.3）。

构成：清晰型 case1-9、19、20（11 条）；歧义型 case10-12（无信号×2 + 跨类弱冲突×1）；混合型 case13-18（6 条）。
方法分布：editable_pptx=10、template_fill=7、visual_report=3。

| case | 意图（摘要） | 类型 | method | confidence |
|---|---|---|---|---|
| case1 | 销售数据→汇报PPT，带图表表格 | 清晰 | editable_pptx | 0.95 |
| case2 | 9月运营月报+台账数据 | 清晰 | editable_pptx | 0.9 |
| case3 | 公司品牌VI模板对外介绍 | 清晰 | template_fill | 0.85 |
| case4 | 套用上季度模板换内容 | 清晰 | template_fill | 0.85 |
| case5 | 朋友圈转发海报一页 | 清晰 | visual_report | 0.95 |
| case6 | 活动亮点信息图 | 清晰 | visual_report | 0.85 |
| case7 | 项目进度数据图表汇报页 | 清晰 | editable_pptx | 0.9 |
| case8 | 公司VI规范提案模板 | 清晰 | template_fill | 0.85 |
| case9 | 展位海报 | 清晰 | visual_report | 0.8 |
| case10 | 帮我做一个PPT | 歧义·无信号 | editable_pptx | 0.4 |
| case11 | 产品介绍团队情况你看着办 | 歧义·无信号 | editable_pptx | 0.4 |
| case12 | 视觉冲击力+转化数据 | 歧义·弱冲突 | editable_pptx | 0.6 |
| case13 | 公司模板+月报数据 | 混合 | template_fill | 0.65 |
| case14 | 数据台账→海报朋友圈 | 混合 | editable_pptx | 0.7 |
| case15 | 品牌部一页海报 | 混合 | template_fill | 0.65 |
| case16 | 套用模板做图表 | 混合 | template_fill | 0.65 |
| case17 | 汇报页视觉化像信息图 | 混合 | editable_pptx | 0.65 |
| case18 | 月报→朋友圈转发一页图 | 混合 | editable_pptx | 0.7 |
| case19 | 对外介绍贴合品牌调性 | 清晰 | template_fill | 0.8 |
| case20 | 客户自改数据表格汇报材料 | 清晰 | editable_pptx | 0.9 |

## 5. 边界与非目标

边界（明确未定义 / 不保证的行为）：
- 纯子串匹配、不做分词与语义理解：措辞变化导致的漏检/误检是**预期行为**（如 R2 的"公司VI"不连续不命中）。
- 关键词全为中文；不收录任何英文关键词，大小写不敏感仅对字母字符有实际意义。
- 输入编码仅保证 UTF-8（±BOM）；GBK 等其它编码的中文会被错误解码，行为未定义。
- `confidence` 是确定性公式值，不具备统计/概率语义，不保证校准。
- 多行文本合并为单意图，不做多意图拆分。

非目标（本技能不做）：
- 不生成 / 渲染任何 PPT、海报或信息图（三类 method 对应路径的执行不在本技能范围）。
- 不做模板资产、品牌 VI 库的管理与检索。
- 不调用 LLM/模型做语义路由——路由层保持确定性、可离线复算。

## 6. 本机实测记录（2026-09-29）

| 命令 | 结果 |
|---|---|
| `python --version` | Python 3.12.10 |
| `python oracle/oracle.py --input oracle/inputs/case15.txt` | exit 0，`template_fill / 0.65`，reasons 4 条（品牌；海报、一页；优先级；冲突说明） |
| `python oracle/oracle.py --input oracle/inputs/case10.txt` | exit 0，`editable_pptx / 0.4`，兜底 reasons 1 条 |
| `python oracle/oracle.py --input oracle/inputs/case3.txt` | exit 0，`template_fill / 0.85`，命中 模板、品牌（未命中"公司VI"） |
| `python oracle/oracle.py --input oracle/inputs/case12.txt` | exit 0，`editable_pptx / 0.6`，editable>visual 弱冲突 |
| `python oracle/gen_inputs.py && python oracle/run_all.py` | 重建 20 条样例并全量重跑，`wrote …/out/labels.json (20 entries)` |
| `md5sum oracle/out/labels.json` | `47e74b713811ea7b41b38d9705169f0c`（与首次全量运行一致 → 确定性成立） |
| `python eval/runner.py oracle/out oracle/out`（2026-09-29 spec 修订时复核） | exit 0，6 项检查全过，一致率 20/20=100% |
| 逐字节检查 20 份 `oracle/inputs/caseN.txt`（2026-09-29 复核） | 全部 UTF-8 无 BOM、恰 1 行、行尾 CRLF、无行内 CR——§8 格式声明成立 |

## 7. 交付物与完成定义（package/，实现者必读）

> 本节澄清"什么在被测、怎样算完成"。§1-§6 固化的是**路由行为**；确定性评测（`eval/runner.py`）的
> 被测对象是 **`package/` 目录及其产物**。只实现行为、不产出 package 产物 = 未交付（2026-09-29 前两轮
> 重生成即失败于 `package/out/labels.json` 不存在，特设本节消除该歧义）。

### 7.1 交付物清单（与 contract.md §1 一致，重述以便单文自足）

`package/` 目录必须包含以下全部文件，且实际可运行：

| 文件 | 作用 | 产生方式 |
|---|---|---|
| `SKILL.md` | 技能入口（必备 8 节结构见 contract.md §4） | 撰写 |
| `scripts/route.py` | 单条路由，命令行契约与 oracle 同构（contract.md §2.1） | 按本文 §2-§3 实现 |
| `inputs/case1.txt … case20.txt` | 黄金集输入，**全文以本文 §8 为唯一权威来源** | 按 §8 逐条创建 |
| `run_all.py` | 批量运行（contract.md §2.2，经 subprocess 走 route.py 命令行契约） | 实现 |
| `out/labels.json` | 批量产物（contract.md §2.3 schema，恰 20 条） | **必须由实际运行 `python run_all.py` 生成**；禁止手写、禁止转抄 oracle 判定 |

### 7.2 完成定义（DoD，三条全部满足才算交付）

1. 在 `package/` 下实际运行 `python run_all.py`，产出 `out/labels.json`（恰 20 条、顺序 case1→case20）；
2. 运行评测并**退出码 0**（`all_pass: true`）——两种等价调用形式任选：
   - 资产根目录形式：`cd <资产根> && python eval/runner.py package/out oracle/out`（资产根 = `skillfactory/assets/ppt-method-router/`）；
   - 绝对路径形式（重生成工作流的实际调用方式，路径相对 `D:\workspace\zcode研究`）：
     `python skillfactory/assets/ppt-method-router/eval/runner.py skillfactory/assets/ppt-method-router/package/out skillfactory/assets/ppt-method-router/oracle/out`；
3. 把所用命令与完整输出如实写进交付说明（不得只报"通过"而无命令与输出）。

### 7.3 与 `oracle/` 的边界（消除"禁止读取"与"逐字节一致"的自相矛盾）

- 实现者**无需、也不应读取** `oracle/` 目录（重生成公平性要求）。独立实现所需的一切都在本 spec 内：
  路由规则在 §2-§3，20 条输入全文在 §8，逐案期望判定在 §4。
- contract.md §1 要求 `package/inputs/` "与 `oracle/inputs/` 同名文件逐字节一致"——**该一致性以本文 §8
  的全文为准**：按 §8 创建即视为满足，无需触碰 `oracle/`。
- 运行 §7.2 的评测命令本身是**被明确要求的验收动作**（runner 只读取参照 `oracle/out/labels.json` 做
  method 比对），不构成"读取 oracle 参照实现"。
- **反作敝条款**：`package/out/labels.json` 必须由 package 自己的 `run_all.py` + `scripts/route.py`
  对 §8 输入实跑产生。把 `oracle/out/labels.json`（或 §4 期望表）直接复制/转写为被测产物，可绕过
  runner 的 method 比对，属作敝——一经发现判不合格，无论一致率多高。

## 8. 黄金输入 20 条全文（`package/inputs/` 的唯一权威来源）

文件格式（已逐字节核验，见 §6 复核行）：每文件恰为下表"文本"列**原样一整行 + 末尾一个换行符**；
oracle 原件为 UTF-8（无 BOM）、行尾 CRLF。创建 `package/inputs/` 时 LF 或 CRLF 均可——读取侧
`utf-8-sig` 打开后 `strip()`（oracle.py:104-105），行尾差异不影响任何判定。
各行期望判定见 §4 表；**禁止**把期望表硬编码为输出（§7.3 反作敝条款），路由必须由自己的规则对文本计算得出。

| case | 文本（整行原文） |
|---|---|
| case1 | 把这份销售数据整理成汇报PPT，要带图表和表格，方便后面改数字 |
| case2 | 做一份9月运营月报，把台账里的数据填进去，下周例会用 |
| case3 | 用我们公司的品牌VI模板做一份对外介绍 |
| case4 | 直接套用上季度评审用过的模板，换内容就行 |
| case5 | 设计一张朋友圈转发用的宣传海报，一页就好 |
| case6 | 把活动亮点做成一张信息图，视觉上要抓人 |
| case7 | 下周例会要用，把项目进度数据做成可编辑的图表汇报页 |
| case8 | 按公司VI规范出一份提案模板 |
| case9 | 做一张海报贴在展位，风格醒目一点 |
| case10 | 帮我做一个PPT |
| case11 | 内容大概是产品介绍和团队情况，你看着办 |
| case12 | 做点有视觉冲击力的东西，里面还要放转化数据 |
| case13 | 用公司模板把月报数据做出来 |
| case14 | 数据台账能不能做成海报风格发朋友圈 |
| case15 | 品牌部要一张一页海报 |
| case16 | 套用模板做几张图表 |
| case17 | 汇报页做得视觉化一点，像信息图那样 |
| case18 | 把月报做成朋友圈转发的一页图 |
| case19 | 对外介绍要贴合公司品牌调性 |
| case20 | 客户要一份能自己改数据表格的汇报材料 |
