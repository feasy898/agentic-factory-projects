# spec.md — Skill 体检工具（healthcheck）资产规格

> 资产根：`skillfactory/v3/tools/healthcheck/`
> 规格依据：oracle 参照实现 `oracle/healthcheck.py`（逐行读过）+ 三个样本的实跑产物
> `oracle/out/{meeting-minutes-skill,broken-skill,no-eval}/{report.json,REPORT.md}`，
> 以及本次会话追加的探针实验（见 §2.2）。
> 本规格逐条可判定：每条规则都给出「判定方法」，`eval/runner.py` 据此机械化判分。

---

## 1. 目标

把「对任意 skill 包目录跑结构校验并产出体检报告」的 oracle 行为固化为软件资产：

| 文件 | 角色 |
|---|---|
| `oracle/healthcheck.py` | 参照实现（CLI 体检工具，行为在 §3 冻结） |
| `oracle/out/` | 三个样本的体检报告基线（评测的参照产物） |
| `fixtures/` | 阴性对照样本（broken-skill / no-eval） |
| `spec.md` / `contract.md` | 规格（本文）与接口契约 |
| `eval/runner.py` | 确定性评测器：判「一份 healthcheck 产物集」是否合格（§5） |

体检的对象是 **skill 包目录**；eval 的对象是 **healthcheck 的产物**（report.json + REPORT.md）。两层不要混。

## 2. oracle 实测基线（本规格的证据）

### 2.1 三个样本（2026-09-30 03:57 产物，存于 `oracle/out/`）

| target | 评级 | summary | 关键红项 |
|---|---|---|---|
| `skillfactory/dist/meeting-minutes-skill` | A | 5 项 / 5 过 / 0 败 | 无（eval_smoke 实跑 exit=0） |
| `fixtures/broken-skill` | C | 5 项 / 2 过 / 3 败 | front_matter_fields、eval_present、scripts_syntax |
| `fixtures/no-eval` | B | 5 项 / 4 过 / 1 败 | 仅 eval_present（eval_smoke 为 skip=pass） |

### 2.2 本次会话追加探针（补齐三样本未覆盖的分支，2026-09-30 实跑）

- `--target` 指向不存在路径 → stderr「错误：--target 不是目录: …」，exit 2，`--out` 目录未被创建（ls 验证为空/不存在）。
- 重跑三样本到临时 out 目录 → report.json 除 `generated_at` 行外与 `oracle/out/` 基线逐字节一致（diff 验证），证明 §3 各规则确定性。
- 空 skill 包目录（无 SKILL.md / eval/ / scripts/）→ 评级 C（skill_md_exists、front_matter_fields、eval_present、scripts_syntax 四红；eval_smoke=skip pass，detail「skip: 缺 eval/ 目录，跳过 smoke」），exit 0。

## 3. oracle 行为规则（逐条可判定）

### R1 CLI 与参数
`python oracle/healthcheck.py --target <skill包目录> --out <报告目录>`；`--target`、`--out` 均必填（argparse 缺参 exit 2）。
- `--target` 不是目录 → stderr 报错，exit 2，**不创建** `--out`、不写任何产物。
- 其余一切情况（包括全红）→ exit 0（体检工具只报告不设门）。
- 判定：跑命令看退出码与 `--out` 内容。

### R2 检查项集合与顺序（冻结）
恰 5 项，顺序固定：`skill_md_exists` → `front_matter_fields` → `eval_present` → `eval_smoke` → `scripts_syntax`。report.json 的 `checks` 数组顺序与此一致。
- 判定：读任一 report.json，`checks[].name` 序列逐字等于上述序列。

### R3 skill_md_exists
`<target>/SKILL.md` 是普通文件 → pass（detail 含字节数）；否则 fail（detail「包根未找到 SKILL.md」）。
- 判定：探针（空包目录）已验证 fail 分支；meeting-minutes 验证 pass 分支。

### R4 front_matter_fields
SKILL.md 须以 `---` 行起始的 front-matter 块开头（`^---\n ... \n---`，允许 \r\n 与 BOM）；
块内按行 `key: value` 解析（**行级解析，非完整 YAML**）；五字段 `name` / `version` / `license` / `description` / `permissions` 非空 → pass。
- 块缺失或首行不是 `---` → fail（detail 注明）；SKILL.md 不存在 → fail；缺字段 → fail，detail 格式「front-matter 缺字段: <缺的>（已有: <有的>）」。
- 编码：utf-8-sig 优先，解码失败回退 gbk，再失败 → fail。
- 判定：broken-skill 实报「front-matter 缺字段: version, license, permissions（已有: name, description）」。

### R5 eval_present
`<target>/eval/` 是目录 → pass（「eval/ 目录存在」）；否则 fail（「缺少 eval/ 目录（无确定性评测）」）。
- 判定：no-eval / broken-skill 验证 fail 分支，meeting-minutes 验证 pass 分支。

### R6 eval_smoke（单次确定性调用，不重试掩蔽）
- runner 查找：`eval/runner.py` > `eval/run.py` > `eval/eval.py` > `eval/main.py` > `eval/` 顶层按文件名排序首个 `*.py`（仅文件，不递归）。
- 命令：存在 `<target>/reference/out` **或** `<target>/eval/reference/out` 目录（dist 系列自校验约定）→ `python <runner> <ref> <ref>`；否则 → `python <runner> --help`。`cwd=<target>`，`timeout=60s`，`PYTHONIOENCODING=utf-8`。
- 判定：exit 0 → pass（detail 含 cmd 与 stdout 摘要）；非 0 / 超时 / 无法启动 → fail（detail 记 cmd、exit_code、stderr/stderr 摘要，空白压缩并截尾 400 字符）；**无 runner → pass=true 且 detail 以「skip:」开头（skip 不计入评级失败数，口径冻结）**。
- 判定（机判）：meeting-minutes detail 含「smoke exit=0」；broken-skill / no-eval detail 以「skip: 缺 eval/ 目录」开头。

### R7 scripts_syntax
递归遍历 `<target>/scripts/`（跳过名为 `__pycache__` 的子目录），对每个 `*.py` 以 utf-8-sig 读入后 `compile()`：
- 目录缺失 → fail「scripts/ 目录不存在」；无 py 文件 → fail「scripts/ 下没有 *.py 文件」。
- 任一文件 SyntaxError / 读取错误 → fail，detail「N/M 个脚本语法不过: <相对路径>: 第X行 SyntaxError: <msg>; …」（相对路径用 `/` 分隔）。
- 全部可编译 → pass，detail「scripts/ 下 N 个 *.py 全部语法可编译: <文件列表>」。
- 判定：bad_syntax.py 实报「第6行 SyntaxError: invalid syntax」；ok.py / gen_docx.py+minutes.py 验证 pass 分支。

### R8 评级规则（写死）
评级 = f(失败检查数，即 pass=false 的项数；**skip 不算失败**)：`0→A，1→B，≥2→C`。
评级同时写进 report.json 的 `rating` 字段与 REPORT.md 的「评级：**X**」行。
- 判定：三样本分别落在 A / B / C 三档，与失败数 0 / 1 / 3 一致。

### R9 report.json schema（冻结）
字段与类型：`tool`（"healthcheck.py 1.0.0"）、`target`（target 的绝对路径）、`generated_at`（本地时间 `%Y-%m-%dT%H:%M:%S%z`，**唯一的非确定性字段**）、`summary` `{total, pass, fail}`（fail = pass=false 计数）、`rating`（A/B/C）、`checks`（数组，元素 `{name: str, pass: bool, detail: str}`，顺序见 R2）。
序列化：UTF-8、`ensure_ascii=False`、`indent=2`、结尾换行。
- 判定：json.load 后逐字段核对类型；`summary.fail == count(checks 中 pass=false)`。

### R10 REPORT.md schema
固定结构：标题 `# Skill Healthcheck Report`；四行元信息（目标包 / 生成时间 / 评级：**X**（A=0 失败 / B=1 失败 / C=≥2 失败） / 汇总：N 项检查，P 通过 / F 失败）；检查表格（表头 `| 检查项 | 结果 | 说明 |`，每检查一行，✅ PASS / ❌ FAIL）；`## 建议` 节（先评级建议一句，再逐失败项一条）。
机器可判锚点：正则 `评级：\*\*([ABC])\*\*` 提取评级字母，须与 R8 推导及 report.json `rating` 一致。
- 判定：三份 REPORT.md 均能以此正则提取出 A / C / B。

### R11 退出码
`0` = 报告已写出（**无论红绿**）；`2` = 参数缺失或 `--target` 不是目录。没有 exit 1。
- 判定：R1 探针 + 三样本实跑均为 0。

### R12 确定性
同一 target 重复运行：除 `generated_at`（及由它派生的 REPORT.md 生成时间行）外，report.json / REPORT.md 逐字节一致。smoke 的 stdout 摘要进入 detail，因此要求被测 runner 本身输出确定。
- 判定：§2.2 重跑 diff 实验。

## 4. 边界与非目标

- **不做完整 YAML 解析**：front-matter 用行级 `key: value` 解析（覆盖本仓全部样本，零第三方依赖）；嵌套/锚点/多行标量不支持。
- **smoke 单次确定性调用**：无多策略重试、无失败掩蔽；超时/非零只记录，不中断整体。
- **只报告不设门**：体检红绿都 exit 0；是否拦截由调用方（流水线）决定。
- **eval_smoke 的 skip 口径冻结**：无 runner → pass=true + detail 注明 skip，不计入评级失败数。
- 不评估 SKILL.md 正文质量；不校验被测 eval runner 的判定逻辑正确性（只看其 exit code）。
- `eval/runner.py` 判的是「healthcheck 产物」，不重跑 healthcheck、不接触 skill 包源目录。
- 平台口径：win32 + Python ≥3.10（本机 3.12.10 实测）；标准库实现，无第三方依赖。

## 5. eval/runner.py 判分规则（写死在工具内）

- **产物根布局**（被测与参照同构）：`<root>/{meeting-minutes-skill, broken-skill, no-eval}/`，各含 `report.json` 与 `REPORT.md`。
- **CLI**：`python eval/runner.py [<被测产物根> <参照产物根>]`；零参数时两者均取内置缺省 `<runner 目录>/../oracle/out`（自校验应全过）；参数个数非 0/2 → 用法错误 exit 2。
- **report.json 结构校验口径**：顶层 JSON 对象；`checks` 为非空数组；元素含 `name:str / pass:bool / detail:str`。
- **固定 5 项检查**（全部通过 exit 0 并打印 JSON；任一失败 exit 1）：
  1. `meeting_minutes_all_pass` — 好样本 report.json 存在、结构合法、所有检查项 pass=true。
  2. `broken_skill_expected_fails` — broken-skill 的 `front_matter_fields` 与 `scripts_syntax` **均** pass=false。
  3. `no_eval_eval_present_fail` — no-eval 的 `eval_present` pass=false。
  4. `rating_consistency` — 三样本各自的 REPORT.md 评级字母 == 按失败数推导评级（R8 规则）== report.json `rating` 字段。
  5. `oracle_agreement_90pct` — 与参照产物按（3 样本 × 5 检查名）共 15 对 `pass` 布尔比对，一致率 ≥ 0.90（即至多容忍 1 对不一致）；参照产物缺失/损坏直接判败。
- **输出**：stdout 打印 `{"ok": bool, "summary": {total, pass, fail, tested_root, reference_root}, "checks": [{name, pass, detail}]}`；无时间戳，同输入同输出。
- **退出码**：0 = 全过；1 = 任一检查失败；2 = 用法错误。
