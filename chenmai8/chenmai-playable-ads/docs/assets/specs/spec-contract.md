# M1 规格 spec（PlayableSpec schema v1 + 双侧校验器）

> 状态：frozen（契约冻结，改动即破坏契约）。对照 `packages/spec/` 与 `python/pfcore/{validation,spec_model,invariants}.py`
> 逐行核验于 2026-09-28；2026-09-29 C2 盲评修正同步：§2.2 I2 重放方向/前置域检查与 merge stub 字段
> 改为如实描述实现。目标读者：只凭本页 + eval 重建本模块的新 agent。

---

## 1. 职责与边界

**做**：定义 PlayableSpec v1.0.0 的结构（JSON Schema draft 2020-12）、五条跨字段语义不变式（I1–I5）、
"由 seed 确定性生成关卡盘面"的规范生成器、以及双侧（Python 权威 / JS 镜像）校验器；错误一律定位到
json-path 字段路径并带稳定错误码。

**不做**：不构建、不打包、不质检；不做模板参数的玩法语义校验之外的任何事；schema 与不变式之外的
宽容归一属于模板（见规则卡 §1）。

## 2. 对外契约

### 2.1 schema（`packages/spec/playable-spec.schema.json`，冻结）

- `$id: urn:pf:spec:playable-spec:1.0.0`；顶层 `additionalProperties: false`；
  required：`specVersion, meta, game, flow, assets, i18n, channels, qc`（`variants` 可选）。
- `specVersion` 恒 `"1.0.0"`；`meta.projectId` 匹配 `^[a-z0-9][a-z0-9-]{0,63}$`；`meta.seed` 整数 ≥0。
- `game.template` 枚举 `match3|merge|pullpin|sort`（封闭枚举——痛点见 CONTRACTS §痛点 1）；
  params 经 allOf/if-then 选 $defs/{match3,merge,pullpin,sort}Params，全部字段带 default（LLM 只填偏差项）。
- `flow.endScreen.landingUrl` 匹配 `^https?://\S+$`（≤512）——打包后它是产物内唯一允许出现的外链。
- `i18n.strings.<locale>` required 五键 `cta/tutorial/win/lose/score`（痛点 §痛点 2：键集锁死）；
  `channels.targets` 枚举 6 渠道（封闭，痛点 §痛点 1）；`qc.maxLoadSec` 0.5–10 默认 2.0；
  `qc.autoplayTimeoutSec` 5–120 默认 45。
- **schema 文本未显式展开、由 eval 样本形状闭合的细节（2026-09-29 回炉列出，冻结）**：
  `meta.title` 可选；`flow.endScreen` 必填、`flow.tutorial` 可选；`assets.*` 路径值类型
  `["string","null"]`（bad01/02 的 `audio.win: null` 实证）；`qc` 两字段可选带默认；
  `variants[]` 元素形状 `{id, seed, palette}`（golden 实证）；`channels.orientation` 为普通
  string（未声明封闭枚举）；`i18n.strings.<locale>` 五键 required 但**允许额外键**；
  `assets.sprites`/`assets.audio`/`channels.overrides` 是键为用户定义的开放映射
  （`additionalProperties` 不设 false）；全链其余对象 `additionalProperties: false`。

### 2.2 五条不变式（I1–I5，语义冻结）

| ID | 内容 | 精确判定 |
|---|---|---|
| I1 | pullpin 逐关可解 | 针角色由 seed 经 `pullpin_level_roles` 生成（每关恰 1 救援针 + 1 机关针，其余中性）：`rescuee = below(pins)`；hazard 重抽至多 16 次（`PULLPIN_REROLL_MAX`）非 rescuee 的值，全撞则 `(rescuee+1) % pins`。`orderSolution` 逐关模拟：先拔到 hazard → 败；拔到 rescuee → 成；未拔到 → 败 |
| I2 | sort 栈可逆 | 已解盘面 = 前 `min(colors,rods)` 柱各一色满柱 + 空柱（`sort_solved_board`）；`sort_scramble` 从已解盘面出发恰走 `rods*layersPerRod` 步，候选步仅限"逆步合法"（搬回后目标柱顶同色或空、且不超容量），`mv = cands[below(len(cands))]`。validator 重放（**方向钉死，2026-09-29 回炉**）：从 **`sort_solved_board` 出发正向应用 trace**，逐步断言每步 ∈ `sort_legal_moves`（否则 `I2-sort-scramble`）且逆步合法（否则 `I2-sort-reversible`——该码**只**用于逆步不合法）；重放完毕与**生成器盘面**（`sort_scramble` 返回的盘面）逐柱比对，不等 → `I2-sort-scramble`。I2 侧唯一前置域检查：`colors > rods` → `I2-sort-colors`；其余域约束（`colors ≥ 2`、`rods ≥ 3`、`layersPerRod ≥ 2` 等）属 schema 层（`schema-*` 码），**不**短路返回 I2 码 |
| I3 | match3 存在可行步 | `match3_board(seed,rows,cols,colors)`（行优先逐格 `below(colors)`）生成盘面，`match3_find_move`（扫相邻交换，方向 (0,1)/(1,0)）无解即违规；另 colors ≤ len(spriteKeys) |
| I4 | 时长预算 | `durationBudgetSec.max <= 30`（双保险，schema 亦限）；`target <= max` |
| I5 | i18n 覆盖 | locales 每语言 strings 存在且五键非空白；`defaultLocale ∈ locales`；`rtl ⊆ locales` |

**merge / pullpin / sort 无规则卡——"未覆盖即结构 stub"（2026-09-29 回炉声明）**：
`templates.md §7` 标三模板规则卡 planned 属实。校验器对这三者的现状语义 = schema 结构 +
少量轻量不变式，**不承载玩法语义**：merge 仅三条 `I-merge-sprites`（`maxTier > len(spriteKeys)`）/
`I-merge-spawn`（须 `1 ≤ spawnTierMax < maxTier`）/ `I-merge-goal`（`goalTier ≤ maxTier`）；
其 params 默认值 = `MERGE_DEFAULTS = {cols:5, rows:5, maxTier:5, spawnTierMax:2, goalTier:4,
spriteKeys:["tier-1","tier-2","tier-3","tier-4","tier-5"]}`（`invariants.py` 实现，JS 镜像同名
`MERGE_DEFAULTS` 同值导出；pullpin/sort 默认值同见 `PULLPIN_DEFAULTS`/`SORT_DEFAULTS`）。
三模板规则卡落稿时必须回炉本页复验。

### 2.3 确定性随机源（跨语言一致的关键，冻结）

- 32 位 LCG：`state = (1664525 * state + 1013904223) mod 2^32`，取值 `next() % n`；
  JS 侧 `Math.imul + >>>0` 复刻同余结果。
- **三个自由度（2026-09-29 回炉冻结——此前只有 bad02 单样本隐式锁定）**：
  1. **先推进后取值**：首抽 = `(1664525*seed + 1013904223) mod 2^32`（状态先更新再输出）。
     算例（已过真实 gate）：bad02 `seed=424242` 首两抽 `%3` = `[2, 0]` → L0 `rescuee=2`、
     `hazard=0`，其 `orderSolution[0]=[0,1,2]` 首拔即机关针（I1 命中）。
  2. **单流跨关卡**：`pullpin_level_roles(seed, levels, pins)` 用**一个**从 `meta.seed` 新建的
     LCG 连抽全部关卡（rescuee 与 hazard 抽取共享同一流，无逐关重播种）。
  3. **各生成器独立建流**：`match3_board` / `sort_scramble` / `pullpin_level_roles` 各自从
     `meta.seed` 新建 LCG，互不共享状态。`variants[].seed` **不参与**校验器生成器（无消费方，
     CONTRACTS §痛点 3）。
     算例（已过真实 gate）：golden `seed=20260930` 的 6×6×5 LCG 盘面存在可行步
     `(0,2)↔(1,2)`（`match3_find_move` 返回 `(0, 2, 1, 2)`）。
- **注意**：本生成器（LCG）服务于校验器；三消模板运行时用的是另一套 mulberry32 + 盐流（规则卡 §7）。
  两套规则已经分叉——见 §5 单一真源声明。

### 2.4 错误契约（冻结）

- 形状：`{path, message, code}`；path 为 json-path 风格（`$.game.durationBudgetSec.max`、`$.i18n.strings.ja`、
  `$.game.params.orderSolution[0]`）。
- **缺字段路径补名约定**（两侧一致）：schema required 错误把缺失字段名补进路径（`$.flow` 而非停 `$`）。
- 稳定错误码：`schema-<keyword>`、`I1-pullpin-order`、`I1-pullpin-unsolvable`、`I2-sort-colors|scramble|reversible`、
  `I3-sprites-cover-colors`、`I3-match3-feasible-move`、`I4-duration-max|target`、`I5-i18n-coverage|default|rtl`、
  `I-merge-sprites|spawn|goal`、`schema-type`、`io-not-found`、`io-parse`、`model`。
- 校验次序（冻结）：schema 结构 → 不变式 → pydantic 类型化解析（`code="model"`，表示层）；任一阶段失败即止，
  不合并报告。

### 2.5 双侧实现与权威

- **Python 权威**：`pfcore.validation.validate_spec_file/dict`（jsonschema Draft 2020-12 + invariants + pydantic）。
  schema 定位：env `PF_SPEC_SCHEMA` 优先，否则 `validation.py` 的 `parents[2]` 仓库根约定
  （**模块位置不可挪**）。CLI：`python -m pfcore validate <spec...>`（glob 内建展开；全部文件过才 exit 0）。
  **stdout 格式（2026-09-29 回炉冻结）**：逐文件一行裁定——通过 `OK <file>`、失败
  `INVALID <file>` + 其下逐条缩进两格 `<path>: <message> [<code>]`；glob 无匹配计
  `INVALID <pattern>: 模式无匹配文件：<pattern> [io-not-found]`；末行汇总
  `validate: <passed>/<total> 通过`。门禁只断言**退出码**与输出含 `$.` 路径（正则
  `\$\.[A-Za-z_][\w.\[\]]*`），不解析 stdout 机器格式——pfcore 试点曾按每文件一行 JSON
  （`{"file","ok","issues":[…]}` + 末行 `{"summary":…}`）实现，同样过门；仓库人类可读格式为准，
  两者皆合法的边界以门禁断言为准。
- **JS 镜像**：`packages/spec`（`validate.mjs` ajv + `invariants.mjs` 逐行镜像）。
  公开面：`schema / schemaErrors / validateSpec / checkInvariants` + 生成器与常量（`Lcg, match3Board,
  match3FindMove, pullpinLevelRoles, pullpinSimulate, sortSolvedBoard, sortLegalMoves, sortApplyMove,
  sortInverseLegal, sortScramble, REQUIRED_STRING_KEYS, *_DEFAULTS, MAX_DURATION_SEC`）。
  types 入口 `src/types.ts`（TS 消费方从这里 import，不自行声明）。
- 任何一侧算法改动都视为破坏契约，必须双侧同步 + bad 样本回归。

## 3. 行为规格（边界与失败路径）

- 文件不存在 → `[io-not-found]`；JSON 非法 → `[io-parse]`——归一为带路径 issue，CLI 计入失败（exit 1）。
- glob 无匹配 → 该模式计一条失败（防静默通过）。
- pydantic 模型（spec_model.py）：`extra="forbid"`、camelCase alias、`typed_params` 按 template 合并默认值
  （`{**DEFAULTS, **params}` 一次性构建）。
- 评测样本集（`specs-eval/`）：golden-match3（6 语言含 ar、nearWin=true、全字段）；bad 6 件各自击中：
  `01` 缺顶层 flow（required 补路径）、`02` pullpin 第 1 关先拔机关针（I1）、`03` max=35（I4）、
  `04` locales 声明 ja 缺词条（I5）、`05` landingUrl 无 scheme（schema-pattern）、`06` 未知模板（schema-enum）。
- **bad03 的"双层都收"登记（2026-09-29 回炉成文，消除 §2.2 I4 与 schema 的张力）**：
  schema 限 `durationBudgetSec.maximum = 30`，I4 又判 `max <= 30`——两层同守一个域且**同路径**
  `$.game.durationBudgetSec.max`。按 §2.4 校验次序 schema 先行，bad03（max=35）实际先命中
  `schema-maximum`；`I4-duration-max` 是第二层兜底（schema 层被绕过/放宽时仍拦截）。
  实测输出：`$.game.durationBudgetSec.max: 35 is greater than the maximum of 30 [schema-maximum]`。
  两种实现（报 schema-maximum 或报 I4-duration-max）都满足门禁断言（exit 1 + `$.` 路径）；
  改动任何一层前先跑 bad03 回归。

## 4. eval：精确命令与通过线

```bash
python/.venv/Scripts/python.exe -m pfcore validate specs-eval/golden-match3.json        # → exit 0
python/.venv/Scripts/python.exe -m pfcore validate "specs-eval/bad/*.json"              # → 6 个全 exit 1，错误含 $. 路径
node packages/spec/test/ajv-check.mjs                                                   # → AJV-CHECK: PASS，exit 0
```

- 门禁固化：`scripts/gate_phase1.py` 门项 1（逐文件裁定 bad、断言字段路径正则 `\$\.[A-Za-z_][\w.\[\]]*`）。
- **归属标注（2026-09-29 回炉）**：上块第三条 `node packages/spec/test/ajv-check.mjs` 属
  **JS 镜像（`packages/spec`）** 的验收命令，不是 Python 侧 `pfcore validate` 的一部分——
  pfcore 试点（只重生成 Python 校验器）不含它；它在完整仓库的 M1 门禁（gate_phase1 门项 1
  的 ajv 子断言）内执行。单独重生成 Python 侧时无需也不应临时补建 JS 镜像。
- **禁止事项**：不许为了过 gate 改 bad 样本的期望（bad 样本是规格的一部分）；不许只在单侧修算法。

## 5. 可解性单一真源声明（本页最重要的架构裁决候选）

**现状（如实）**：可解性算法存在三处——
1. 校验器规范生成器（Python `invariants.py` + JS `invariants.mjs` 镜像，LCG）；
2. 三消模板运行时（`board.ts/rng.ts/solver.ts`，mulberry32 + 盐流，规则卡 §7）——
   **校验器 I3 判定的是校验器自己 LCG 盘面的可行步，不是模板真实盘面**；两者"必胜保证"路径不同
   （模板靠生成期 64 次重试 + 同流模拟，规则卡 §7）。
3. 每加一个玩法，Python 与 JS 还要各实现一遍不变式。

**声明（目标形态）**：可解性只有一份真源——**每个模板包导出 `check(spec)`（Node 可执行，含盘面生成与
可解性判定），Python 校验器只负责结构校验并调用它**（子进程或 Node 桥），废除"两种语言各实现一遍"。
过渡期内维持双实现，但任何算法改动必须以本节 + 门禁为裁定。

## 6. 重生成注意事项

- Python 依赖钉版：jsonschema 4.26.0 / pydantic 2.13.5；`pip install -e python/`（勿用 .pth hack）。
- JS：ajv 8.20.0（根 devDependency，draft 2020 支持 `ajv/dist/2020.js`）；schema JSON 以
  `import ... with { type: "json" }` 导入（Node 22 语法）。
- bad 样本与 golden 是 eval 资产：改 schema 必须同步检查 6 个 bad 是否仍各自击中原检查项（或按契约变更流程
  显式新增）。
- 变更史：commit `b4be5ff`（M1 冻结）。
