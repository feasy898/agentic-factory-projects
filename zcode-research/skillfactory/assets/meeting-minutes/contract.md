# contract.md — meeting-minutes 模块契约（冻结）

> **版本：1.1**（2026-09-29，specfix-meeting-minutes）：新增资产根 `inputs/` 实现者副本目录与 §1
> 输入样例注记；eval/golden.json 增补 case4（全噪声边界）。接口、命令行契约、检查项均未变更。
> 1.0 = 初版冻结。

本契约冻结**接口与目录布局**；`package/` 内的实现（代码怎么写、规则表放哪）自由，只要产物行为满足 `spec.md` 且评测 `eval/runner.py` 通过。契约变更必须改本文件并升版本号，禁止静默变更。

## 1. 资产根目录布局

```
meeting-minutes/
├── spec.md                  # 行为规格（本资产长期资产，随 oracle 行为冻结）
├── contract.md              # 本文件：模块契约（冻结）
├── inputs/                  # 黄金转写稿实现者副本（1.1 新增；与 oracle/inputs/ 字节一致，规范源仍为 oracle/inputs/）
├── oracle/                  # 参照实现（只读，禁止改动其行为）
│   ├── oracle.py            #   参照实现入口
│   ├── inputs/case1..3.txt  #   黄金输入（3 份转写样例）
│   └── out/case1..3/        #   参照产物：纪要.docx + summary.json（eval 的参照目录）
├── package/                 # 被测技能包（实现方交付物，布局见 §2）
│   ├── SKILL.md
│   ├── scripts/minutes.py
│   └── ...                  # 其余实现自由
└── eval/
    ├── golden.json          # 黄金集（schema 固定，见 §4）
    └── runner.py            # 确定性评测器（见 §5）
```

评测标准姿势（与本资产 howToRun 一致）：

```bash
cd meeting-minutes
python oracle/oracle.py --input oracle/inputs/case1.txt --outdir oracle/out/case1   # 参照产物若缺则补跑
python package/scripts/minutes.py --input oracle/inputs/case1.txt --outdir package/out/case1
python eval/runner.py package/out oracle/out
```

> 运行目录注记：workflow 执行器的工作目录为 `.zcode/workflow-drafts/`，已在该目录放置目录联接
> `skillfactory` → 工作区真实 `skillfactory/`（2026-09-29 建，单一事实源）。因此
> `python skillfactory/assets/meeting-minutes/eval/runner.py <被测> <参照>` 从 workflow
> 工作目录与从资产根目录执行均可；runner 与 golden.json、转写稿均按脚本自身位置/参数相对路径
> 定位，不假设 CWD。

> 输入样例注记（1.1 新增）：实现方评测时 `--input` 一律用 `inputs/<case>.txt`（资产根副本），
> 无需触碰 `oracle/`——「禁止读取 oracle/」的隔离规则针对参照实现 `oracle/oracle.py` 与参照产物
> `oracle/out/`，输入样例是评测材料。`eval/runner.py` 的 no_fabricated_entries 由参照目录上推
> 一级取 `oracle/inputs/<case>.txt`（规范源），故参照目录恒为 `oracle/out`。两处转写稿字节一致
> （`cmp` 可验证）。先产出 `package/out/<case>` 再运行 eval（spec §9 DoD）。

## 2. package/ 必须包含的文件

| 文件 | 必须 | 要求 |
|---|---|---|
| `SKILL.md` | ✅ | 结构见 §3；front-matter `name` 必须为 `meeting-minutes` |
| `scripts/minutes.py` | ✅ | 命令行契约见 §2.1；自包含（仅依赖 python-docx 与标准库） |
| `references/`、`assets/`、辅助模块 | ⛔ 可选 | 允许；但不得改变 §2.1 接口与 §1 布局约定 |
| `eval/`、`oracle/` 的副本 | ⛔ 禁止 | package/ 内不得复制品目录（评测统一用资产根的 eval/ 与 oracle/） |

### 2.1 scripts 命令行契约（冻结）

```bash
python package/scripts/minutes.py --input <转写.txt> --outdir <输出目录>
```

- 参数：`--input`（必填，转写 txt 路径）、`--outdir`（必填，输出目录，不存在自动创建）。路径相对**当前工作目录**解析，脚本不得假设运行位置。
- 产物（固定文件名，写死在 `<outdir>/` 下）：
  - `纪要.docx` — 三段式纪要，结构满足 spec R3；
  - `summary.json` — 四键计数，满足 spec R6。
- 退出码：成功 0；输入文件不存在等致命错误非 0 且不产出半成品。
- 行为满足 spec 全部 R1–R7（关键词表、优先级、负责人/期限启发式、确定性）。
- 依赖上限：`python-docx` + Python 标准库。需要其他第三方依赖即违反契约。

## 3. SKILL.md 必备结构

按 `skillfactory/standard/SKILL-SPEC-v0.1.md` 的骨架，本技能包 SKILL.md 必须含以下节（顺序可调、内容不得缺）：

1. **front-matter**：至少 `name: meeting-minutes` 与 `description`（≤1024 字符，含触发短语，如「会议纪要」「转写稿整理」「决议/待办/风险」）。
2. **何时使用**：用户给出会议转写/录音整理文本、需要抽出决议·待办·风险三段式纪要时。
3. **输入格式**：`[hh:mm] 说话人: 内容` 每行一条；噪声行靠格式+关键词自动排除（引用 spec R1）。
4. **三段式规则**：11 关键词分类表与 决议>待办>风险 优先级（引用 spec R2/R3，或内联等价表）。
5. **使用步骤**：优先调用 `scripts/minutes.py`（命令 + 成功判据：exit 0 且两产物存在）；无脚本执行条件时按规则手工产出**同名产物**。
6. **产物与验收**：`纪要.docx`（三节+待办表格）+ `summary.json`；验收判据 = `python eval/runner.py <被测out> oracle/out` exit 0。
7. **边界**：非目标清单（引用 spec §8）与「不确定填待定、禁止编造负责人/期限」红线。

## 4. eval/golden.json（schema 冻结）

顶层固定三键：`skill`、`eval_inputs`、`ab_tasks`。

```json
{
  "skill": "meeting-minutes",
  "eval_inputs": [
    {"case": "case1", "input": "oracle/inputs/case1.txt", "output": "oracle/out/case1"}
  ],
  "ab_tasks": [
    {"id": "ab-001", "instruction": "…具体到任务本身…", "input": "oracle/inputs/case1.txt", "rubric": ["…3-5 条可判定评分维度…"]}
  ]
}
```

- **路径基準**：所有路径相对资产根 `meeting-minutes/`。
- `eval_inputs`：每条 = 一个黄金用例；`input` 指向 oracle/inputs/ 样例，`output` 指向期望产物目录（oracle/out/<case>）。case 取值与 `oracle/out/` 子目录名一致。
- `ab_tasks`：恰 3 条；`instruction` 写给执行 agent 的具体任务；`input` 为该任务用的转写样例；`rubric` 3–5 条可判定评分维度。
- 冻结规则：修订 golden.json 必须在 CHANGELOG 记录并归档旧版；禁止为让实现通过而改断言。

## 5. eval/runner.py（接口冻结）

```bash
python eval/runner.py <被测输出目录> <参照输出目录>
# 例：python eval/runner.py package/out oracle/out
#     python eval/runner.py oracle/out oracle/out   （自校验）
```

- 两参数必填；目录可相对当前工作目录。
- 评测对象 = 被测目录下的 `case*` 子目录（case 清单读自身同目录的 golden.json `eval_inputs`）；参照目录须含同名子目录。
- 每个用例固定 5 项检查（check name 前缀为 case 名）：
  1. `docx_opens_with_three_sections` — 纪要.docx 存在、python-docx 可打开、含 `一、决议事项`/`二、待办事项`/`三、风险与关注` 三节标题；
  2. `todo_is_table_with_owner_deadline_columns` — 待办节为表格且表头含 `负责人`、`期限` 列；
  3. `summary_counts_match_docx` — summary.json 四键存在且与 docx 实际条目数（两节编号条目 + 表格数据行）一致、合计=三者和；
  4. `no_fabricated_entries` — 每条目内容能在转写稿（`oracle/inputs/<case>.txt`，由参照目录上推一级定位）中逐字找到出处，且出处行含该条目的时间与说话人；
  5. `entry_counts_within_tolerance_of_reference` — 与参照产物比，三类条数与合计的差值绝对值均 ≤2。
- 输出：stdout 打印 JSON `{"ok": <bool>, "checks": [{"name","pass","detail"},...]}`（ensure_ascii=false）；全部 pass → exit 0，任一 fail → exit 1。
- 确定性：无随机、无网络、无时间依赖；对同一对目录重复运行结果逐字一致。
