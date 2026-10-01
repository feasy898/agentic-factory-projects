# SPEC.md — pfcore validate 子命令（重生成试验）

> **试验性质**：本目录是"只凭 spec + 冻结测试从零重建"的重生成试验（pilot）。
> 本页内容取自对照组仓库 `docs/assets/`（只准该目录）下的两份契约：
> `specs/spec-contract.md` + `pipeline-contract.md`（2026-09-28/29 版），辅以同目录
> `CONTRACTS.md`（C1 枚举与全链 additionalProperties）、`specs/match3-rules-card.md`
> §1（params 的 schema 范围/默认值表）。**未读、未复制对照组任何源码。**
> 冻结评测集 `specs-eval/`（golden 1 + bad 6 + demo-zh + spike-manifest + 1 素材）已原样复制。

---

## 1. 目标（本 pilot 范围）

实现 **pfcore 的 `validate` 子命令**（Python 权威校验器）并通过冻结评测：

```bash
python/.venv/Scripts/python.exe -m pfcore validate specs-eval/golden-match3.json   # → exit 0
python/.venv/Scripts/python.exe -m pfcore validate "specs-eval/bad/*.json"         # → 6 个全 exit 1，错误含 $. 路径
python gate.py                                                                     # → 逐个跑，全 PASS 才 exit 0
```

门禁断言（冻结，不许为过门禁改 bad 样本期望）：
1. validate golden → **exit 0**；
2. bad 6 件逐个 → **exit 1**，且 issue 含字段路径（正则 `\$\.[A-Za-z_][\w.\[\]]*`）；
3. 命令统一 **make/validate**（校验入口名 = `validate`；全流水线冻结名 = `make`；不得引入第三名，`run` 必须不可用）。

**不在本 pilot 范围**（记录即可，不实现）：JS 镜像 `packages/spec`（ajv + invariants.mjs，含
`node packages/spec/test/ajv-check.mjs`）、`make/build/pack/rules-check/serve` 的实际功能、
qacore/packager/模板。占位子命令一律 exit 2（pipeline-contract §2：用法/占位 = 2）。

## 2. 目录形态（仓库根约定，冻结）

```
pfcore-pilot/                      ← 仓库根（validation.py 的 parents[2] 必须是这里）
├── SPEC.md                        ← 本页
├── gate.py                        ← 门禁（逐个跑评测项）
├── packages/spec/playable-spec.schema.json
├── python/
│   ├── pyproject.toml             ← name=pfcore；依赖钉版 jsonschema==4.26.0 / pydantic==2.13.5
│   ├── .venv/                     ← python -m venv；pip install -e python/（勿用 .pth hack）
│   └── pfcore/
│       ├── __init__.py  __main__.py      ← CLI：python -m pfcore validate <spec...>
│       ├── validation.py                 ← validate_spec_file/dict；schema 定位 env PF_SPEC_SCHEMA > parents[2]
│       ├── invariants.py                 ← LCG + 生成器 + I1–I5（+merge）检查
│       └── spec_model.py                 ← pydantic 类型化表示层（extra=forbid，camelCase alias）
└── specs-eval/                    ← 冻结评测集（原样复制，禁改）
```

## 3. PlayableSpec schema v1.0.0（spec-contract §2.1 + CONTRACTS C1）

- JSON Schema **draft 2020-12**；`$id: urn:pf:spec:playable-spec:1.0.0`。
- 顶层 required：`specVersion, meta, game, flow, assets, i18n, channels, qc`；`variants` 可选。
- **全链 `additionalProperties: false`**（CONTRACTS C1）——唯一例外：`i18n.strings.<locale>` 词条对象
  required 五键 `cta/tutorial/win/lose/score` 但**允许额外键**（CONTRACTS 痛点 2："schema 已允许额外键"）；
  以及天然开放的对象映射（`assets.sprites`、`assets.audio`、`channels.overrides`——键是用户定义的）。
- 关键约束：
  - `specVersion` 恒 `"1.0.0"`；
  - `meta.projectId` 匹配 `^[a-z0-9][a-z0-9-]{0,63}$`；`meta.seed` 整数 ≥0；
  - `game.template` 封闭枚举 `match3|merge|pullpin|sort`；
  - `channels.targets` 封闭枚举 6 渠道（CONTRACTS C4 渠道集去掉本地 `preview`，由 golden 的
    6 个 targets 实证）：`applovin, meta, mintegral, unity, google, tiktok`；
  - `flow.endScreen.landingUrl` 匹配 `^https?://\S+$` 且 ≤512（产物内唯一允许外链）；
  - `durationBudgetSec.max ≤ 30`（双保险：schema 亦限，CONTRACTS C1 关键约束）；
  - `qc.maxLoadSec` 0.5–10（默认 2.0）；`qc.autoplayTimeoutSec` 5–120（默认 45）；
  - params 经 allOf/if-then 按 template 选 `$defs/{match3,merge,pullpin,sort}Params`，**全部字段带 default**；
  - match3 params 的 schema 范围/默认（match3-rules-card §1 表）：cols/rows 4–9 默认 6；moves 3–60 默认 15；
    colors 3–5 默认 5；goalCount 1–999 默认 30；goalType `clear-jelly|score` 默认 clear-jelly；
    spriteKeys 恰 5 个。

## 4. 五条不变式（spec-contract §2.2，语义冻结）

| ID | 判定（精确） | 错误码 → 路径 |
|---|---|---|
| I1 | 针角色由 seed 经 `pullpin_level_roles` 生成（每关恰 1 救援 + 1 机关，其余中性）：`rescuee = below(pins)`；hazard 重抽至多 16 次（`PULLPIN_REROLL_MAX`）非 rescuee 值，全撞则 `(rescuee+1)%pins`。`orderSolution` 逐关模拟：先拔到 hazard → 败；拔到 rescuee → 成；未拔到 → 败 | `I1-pullpin-order` / `I1-pullpin-unsolvable` → `$.game.params.orderSolution[<level>]` |
| I2 | 已解盘面 = 前 `min(colors,rods)` 柱各一色满柱 + 空柱；`sort_scramble` 恰走 `rods*layersPerRod` 步，候选步仅限"逆步合法"，`mv = cands[below(len(cands))]`；validator 逐步重放：每步 ∈ `sort_legal_moves` 且逆步合法，终局与生成器一致 | `I2-sort-colors` / `I2-sort-scramble` / `I2-sort-reversible` |
| I3 | `match3_board(seed,rows,cols,colors)`（行优先逐格 `below(colors)`）生成盘面，`match3_find_move`（扫相邻交换，方向 (0,1)/(1,0)）无解即违规；另 colors ≤ len(spriteKeys) | `I3-match3-feasible-move` → `$.game.params`；`I3-sprites-cover-colors` → `$.game.params.spriteKeys` |
| I4 | `durationBudgetSec.max ≤ 30`（双保险）；`target ≤ max` | `I4-duration-max` → `$.game.durationBudgetSec.max`；`I4-duration-target` → `$.game.durationBudgetSec.target` |
| I5 | locales 每语言 strings 存在且五键非空白；`defaultLocale ∈ locales`；`rtl ⊆ locales` | `I5-i18n-coverage` → `$.i18n.strings.<locale>`；`I5-i18n-default` → `$.i18n.defaultLocale`；`I5-i18n-rtl` → `$.i18n.rtl` |

另有 merge 三码（无 eval 覆盖，盲重建）：`I-merge-sprites|spawn|goal`。

### 4.1 确定性随机源（冻结）

32 位 LCG：`state = (1664525 * state + 1013904223) mod 2^32`；取值 `next() % n`（**先推进后取值**：
首抽 = `(1664525*seed + 1013904223) mod 2^32`）。**实证**（本 pilot 预检，见 SPEC 缺口 §8.3）：
bad02 seed=424242 首两抽 %3 = [2, 0] → L0 rescuee=2、hazard=0，`orderSolution[0]=[0,1,2]` 首拔即机关针；
golden seed=20260930 的 6×6×5 LCG 盘面存在可行步 (0,2)↔(1,2)。两者与冻结样本设计完全吻合。

## 5. 错误契约（spec-contract §2.4，冻结）

- 形状 `{path, message, code}`；path 为 json-path 风格（`$.game.durationBudgetSec.max`、
  `$.i18n.strings.ja`、`$.game.params.orderSolution[0]`）。
- **缺字段路径补名**：schema required 错误把缺失字段名补进路径（`$.flow` 而非停 `$`）。
- 稳定错误码：`schema-<keyword>`（如 schema-required / schema-enum / schema-pattern / schema-maximum /
  schema-type / schema-additionalProperties）、I1/I2/I3/I4/I5 与 merge 各码、`io-not-found`、`io-parse`、`model`。
- **校验次序（冻结）**：schema 结构 → 不变式 → pydantic 类型化解析；任一阶段失败即止，不合并报告。
- 文件不存在 → `[io-not-found]`；JSON 非法 → `[io-parse]`；glob 无匹配 → 该模式计一条失败（防静默通过）。
  以上均归一为带路径 issue，CLI 计入失败（exit 1）。

## 6. CLI 与退出码（pipeline-contract §1/§2，冻结）

- 校验：`python -m pfcore validate <spec...>`（**glob 内建展开**；全部文件过才 exit 0）。
- 全流水线冻结名 = **`make`**（裁决记录：占位名 `run` 已删除，任何新代码不得引入第三个全流水线命令名）。
  本 pilot 中 `make` 为占位：**exit 2**。
- 退出码：0 = 全部通过；1 = 判定失败（任一校验 issue）；2 = 用法错误 / 占位子命令 / 产物不存在。
  （`python -m pfcore run …` → argparse invalid choice → exit 2，即"无第三名"可被门禁实测。）

## 7. 评测集（冻结，`specs-eval/` 原样复制）

- `golden-match3.json`：match3、6 语言含 ar、nearWin=true、全字段 → 必须 exit 0。
- bad 6 件各自击中（spec-contract §3）：`01` 缺顶层 flow（required 补路径 `$.flow`）；
  `02` pullpin 第 1 关先拔机关针（I1）；`03` max=35（时长预算域，见 §8.1 裁定）；
  `04` locales 声明 ja 缺词条（I5 → `$.i18n.strings.ja`）；`05` landingUrl 无 scheme（schema-pattern）；
  `06` 未知模板（schema-enum → `$.game.template`）。
- **禁止事项**：不许为过 gate 改 bad 样本期望（bad 样本是规格的一部分）。
- `demo-zh.json` / `spike-manifest.json` / `assets/demo-zh/piece-0.png`：随集复制，不在 §4 eval 命令内。

## 8. spec 未尽事项与本 pilot 的重建裁定（如实记录）

以下点两份契约**没有**给出可执行的精确定义，本 pilot 按下列裁定实现（每条都标注依据）：

1. **bad03 的击中层**：spec-contract §3 说 03 击中"I4"，但 C1 关键约束 + I4"schema 亦限"都写明
   schema 限 `max ≤ 30`，且校验次序 schema 先行 → 实际先命中 `schema-maximum`（路径同为
   `$.game.durationBudgetSec.max`）。门禁断言（exit 1 + $. 路径）两种实现都满足；本 pilot 按
   C1 字面实现 schema `maximum: 30` + I4 双保险。此为两份契约内部张力，如实登记。
2. **pydantic 层形态**：契约只给三句话（extra=forbid、camelCase alias、typed_params 按 template
   `{**DEFAULTS, **params}` 合并），字段清单未给 → 按 schema 形状 1:1 建模。
3. **LCG 流的三个自由度**契约未定：①先推进后取值（由 bad02 实证锁定）；②单流跨关卡/跨生成器
   （seed 一次实例化，pullpin 各关卡连抽；与 bad02 相容，但无第二样本可证）；③match3/sort/pullpin
   各自从 `meta.seed` 新建 LCG（golden/bad02 相容）。variants[].seed 不参与校验器生成器（无消费方，
   CONTRACTS 痛点 3）。
4. **merge / sort / pullpin 的 params 子 schema** 无规则卡（templates.md §7：三模板 planned，规则卡
   未写）→ 字段取自 bad02 实证（levels/pinsPerLevel/hazard/rescuee/orderSolution）+ 不变式文案
   （sort: colors/rods/layersPerRod/solution；merge: 盲重建 spriteKeys/spawnColors/goalScore），
   默认值为猜测值，**无 eval 覆盖**。
5. **schema 未给出的形状细节**（eval 样本全部满足，按样本形状闭合）：meta.title 可选；
   flow 内 endScreen 必填、tutorial 可选；assets 各路径值允许 `["string","null"]`（bad01/02 的
   `audio.*: null` 实证）；qc 两字段可选带默认；variants[] 形状 {id, seed, palette}（golden 实证）；
   channels.orientation 用普通 string（契约未声明封闭枚举）。
6. **I2/I-merge 的路径与次级判定**（solution 步数、越界针号等）契约只有一句话，按 §4 表实现，
   无 eval 可校。
7. **CLI stdout 格式**契约未冻结（只冻结 issue 形状/退出码）→ 每文件一行 JSON
   `{"file","ok","issues":[{path,message,code}]}`，门禁按行解析。
8. **JS 镜像 / ajv-check** 属对照仓 packages/spec，本 pilot 明确不实现（范围见 §1）。

## 9. 依赖与环境

- Python ≥3.10（本机 3.12.10 实测）；钉版：`jsonschema==4.26.0`、`pydantic==2.13.5`。
- 安装：`python -m venv python/.venv` → `python/.venv/Scripts/python.exe -m pip install -e python/`。
- schema 定位：env `PF_SPEC_SCHEMA` 优先，否则 `validation.py` 的 `parents[2]` 仓库根约定
  （**模块位置不可挪**，spec-contract §2.5）。
