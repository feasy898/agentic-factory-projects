# 第三波重生成缺口回炉对照表（30/30，2026-09-29）

> 输入：`_reviews/regen-wave3-gaps.md`（qacore/pfcore/match3rules 三试点实现者自报的
> "只凭 spec 重建时被迫自行裁定"的点）。本表 = 缺口编号 → 落点文件/小节 → 权威来源。
> 数值算例一律对照试点 frozen 测试与真实模板源码取值（未自行发明）；mulberry32 的
> "公版 vs 变体"分歧在回炉中发现并钉死（见 match3 M1）。

## qacore.md（8 项）

| # | 缺口 | 落点 | 来源试点路径 / 真源 |
|---|---|---|---|
| Q1 | 变异样本=gate 现场最小变异 + MUT-01/02/04 构造算法成文 | `specs/qacore.md` §8 新增"样本来源与构造算法"块（注入锚点/翻静音/尾部填充 pad=maxBytes+4096 + 恰命中断言） | 试点 `_regen/qacore-pilot/gate.py`（G2/G3/G4）+ 仓库 `scripts/gate_phase0.py` `_build_mutant_source`（真源） |
| Q2 | 报告字段表并入或显式交叉引用 + 修 pipeline-contract stem 命名矛盾 | `specs/qacore.md` §9（单一来源=pipeline-contract §4，删除误指本页 §4 的旧句）；`specs/pipeline-contract.md` §3.3 stem 命名裁决 + §4 示例注释（`index.report.json` 与 `x.report.png` 同一"产物 stem"口径；`--out` 时截屏跟报告 stem） | 试点 `_regen/qacore-pilot/python/qacore/cli.py`（out/stem 派生）+ 仓库 `python/qacore/cli.py:104`（真源） |
| Q3 | CHK08 网络噪声过滤前提成文 | `specs/qacore.md` §4 新增"CHK08 的隐含前提"块 + §6 CHK08 行 | 试点 cli.py `_is_network_log_noise`（前缀过滤）+ 仓库 cli.py `_on_console`（来源 URL ∈ blocked 集，真源更精确，两者等效） |
| Q4 | 探针监听的 5 个 pf:* 事件名单 | `specs/qacore.md` §4（pf:ready/start/first-interaction/cta/end + pointerdown/touchstart 首指针） | 试点 cli.py `PROBE_JS` + 仓库 `python/qacore/autoplay.py:29-47`（真源） |
| Q5 | `__PF_QC__` 形状与 everVisible 归属 | `specs/qacore.md` 新增 §5.1（六钩子返回形状表 + everVisible 只置真不清零定义） | 仓库 `packages/templates/tmpl-match3/src/main.ts` 声明 + `game.ts` textStates/assetAudit + 试点 autoplay.py `_sample_text_states` |
| Q6 | autoplay 只驱动竖屏趟（明说） | `specs/qacore.md` §5 首条 | 试点 cli.py `_cmd_run`（landscape 传 `False`）+ 仓库 cli.py `run_pass(VIEWPORT_LANDSCAPE, …, autoplay=False)` |
| Q7 | 规则库具体数值（preview maxBytes / mute 默认 / runtime_stubs 机制） | `specs/qacore.md` 新增 §6.1（5242880/3145728、defaults true、空 JS 桩 200 应答+`facts.runtime_stubs` 记账） | 试点 `_regen/qacore-pilot/python/qacore/rules.py` + 仓库 `channel-rules/channel-rules.json`、cli.py `CONTAINER_STUB_JS`（真源）、channel-adapters §1 |
| Q8 | 试点 requirements 最小集说明 | `specs/qacore.md` §9 首条（playwright 1.63.0 + pillow 12.3.0 即全部，其余为仓库其他模块依赖） | 试点 `_regen/qacore-pilot/pyproject.toml` + gate.py 实跑 |

## spec-contract.md（7 项）

| # | 缺口 | 落点 | 来源试点路径 / 真源 |
|---|---|---|---|
| S1 | bad03 张力：I4 标注但 schema-maximum 先行命中（同路径），"两层都收" | `specs/spec-contract.md` §3 新增"bad03 的双层都收登记"块 | 试点 `_regen/pfcore-pilot/SPEC.md` §8.1 + 仓库 `python/pfcore/invariants.py` `check_i4_duration` + 实测输出 `[schema-maximum]` |
| S2 | LCG 三自由度冻结（初态/先推进后取值/单流跨关卡/各生成器独立建流）+ 算例 | `specs/spec-contract.md` §2.3（三条自由度 + bad02 seed=424242 首两抽 %3=[2,0]、golden seed=20260930 可行步 (0,2)↔(1,2)） | 试点 SPEC.md §8.3 + 仓库 invariants.py 实跑复核（本机 Node/venv 验证一致） |
| S3 | merge stub 声明（未覆盖即结构 stub） | `specs/spec-contract.md` §2.2 表后新块（I-merge 三码语义、盲重建默认值无 eval 覆盖、规则卡 planned 回炉前置） | 试点 SPEC.md §8.4 + `_regen/pfcore-pilot/python/pfcore/invariants.py` `check_merge`/`TEMPLATE_PARAM_DEFAULTS` |
| S4 | I2"终局与生成器一致"的具体形态 | `specs/spec-contract.md` §2.2 I2 行（重放解至 `sort_solved_board` 逐柱相等 + 次级域检查 colors≥2/colors<rods/rods≥3/layers≥2/solution 非空） | 试点 `_regen/pfcore-pilot/python/pfcore/invariants.py` `check_i2_sort` |
| S5 | CLI stdout 格式冻结 | `specs/spec-contract.md` §2.5 Python 权威条（仓库 `OK/INVALID` 行格式为主 + 门禁只断言退出码与 `$.` 路径、试点 JSON 行同样过门的边界声明） | 仓库 `python/pfcore/__main__.py` `cmd_validate` 实跑（真源）+ 试点 SPEC.md §8.7 |
| S6 | meta.title/flow.tutorial/assets/qc/variants/orientation 形状契约 | `specs/spec-contract.md` §2.1 新增"eval 样本形状闭合的细节"清单 | 试点 SPEC.md §8.5 + 试点 `specs-eval/{golden-match3,bad/*}.json` 实证 |
| S7 | JS 镜像 ajv-check 归属标注 | `specs/spec-contract.md` §4（属 packages/spec 另一命令范围，Python 单侧重生成不含它） | 试点 SPEC.md §1/§8.8 |

## match3-rules-card.md（14 项）

| # | 缺口 | 落点 | 来源试点路径 / 真源 |
|---|---|---|---|
| M1 | mulberry32 函数体内联 | 规则卡 §7（bryc 公版 `t|61` 函数体 + 变体风险实录 + 首 5 抽算例） | 仓库 `packages/templates/tmpl-match3/src/rng.ts`（真源，Node 22 实跑）；试点 oracle `*61` 转写即异体——回炉实测钉死 |
| M2 | 全卡带期望输出的数值算例 | 规则卡新增 §12（算例 A 首 5 抽 / B 恰一合法步盘 / C 死局盘 / D 两级连消波形 / E 重力位移盘 / F 评价值与取整） | 试点 `_regen/match3rules-pilot/tests/frozen.py`（构造盘面，gate 已验）+ 真实 `board.ts` Node 实跑输出（波形/分数/终盘逐值） |
| M3 | hint 布局数学 | 规则卡 §8（computeLayout 公式链 + cellCenter + JS Math.round=floor(x+0.5) 与银行家舍入可区分 + 参数化算例） | 仓库 `game.ts` `computeLayout/moveHint`（真源）+ 试点 solver.py `Layout/cell_center` + frozen.py 算例 |
| M4 | seed 钳制参数序消歧 | 规则卡 §1 seed 行（(v, default=1, min=0, max=0x7fffffff)） | 仓库 `spec.ts:51,89`（真源）+ 试点 frozen.py `test_s1_normalize_seed` |
| M5 | qc.maxLoadSec/autoplayTimeoutSec 缺省钉死 | 规则卡 §1 qc 行（缺省 2 / 45；模板钳制 1–10 / 5–300，与 schema 上限差异如实标注） | 仓库 `spec.ts:121-122`（真源；试点因卡面未给曾保留 None——本次补齐缺口本体） |
| M6 | spriteKeys 缺省键名钉死 | 规则卡 §1（恰为 piece-0..piece-4 五键） | 仓库 `spec.ts:74-76` + 试点 frozen.py `test_s1_normalize_defaults` |
| M7 | Fisher-Yates 方向与索引→格映射 | 规则卡 §2（i 自 total-1 降至 1、j=floor(rng()*(i+1))；idx=y·cols+x 行优先） | 仓库 `board.ts` `placeJelly`（真源）+ 试点 board.py `place_jelly` |
| M8 | 生成期 64 次重试的流消耗方式 | 规则卡 §2（主流只构造一次、重试顺序消耗同一主流、不重置） | 仓库 `game.ts` `create()`（真源）+ 试点 board.py `generate` docstring |
| M9 | 死局重排流"第 k 步"定义 | 规则卡 §7 k 条（统一 = moves−movesLeft+1，重排不耗步、同 k 延续） | 仓库 `solver.ts` `simulatePlay` + 试点 frozen.py `test_s7_simulate_play_includes_attract_and_reshuffle_streams` |
| M10 | ResolveResult.steps[] 元素 schema | 规则卡 §4（match/fall/spawn 三型 + 扁平 idx + fall/spawn 空则整步省略 + spawn 列优先自上而下） | 仓库 `board.ts` `resolve`（真源，Node 实跑验证波形）+ 试点 board.py（其"恒 push"为试点自报协议，已注明差异） |
| M11 | bestMove 并列取优规则 | 规则卡 §8（严格更大才替换 → 并列取 allMoves 序靠前；候选间同流） | 仓库 `solver.ts` `pickBest`（真源）+ 试点 solver.py `best_move` |
| M12 | attract.nearWin 归一表补位 | 规则卡 §1（缺省 false） | 仓库 `spec.ts:103`（真源）+ 试点 spec.py |
| M13 | FNV 形状枚举序与调色板 7 色色值表 | 规则卡 §11（圆菱方三角六边序 + 7 色值表 + piece-0..4 逐键算例表 + FNV 已知向量） | 仓库 `textures.ts`（真源）+ 试点 textures.py 实跑 + frozen.py 已知向量（fnv1a("a")/("foobar")） |
| M14 | 相位机/CTA/RTL/音频/程序化贴图属模板侧标注 | 规则卡 §11 末条范围标注（规则核镜像以 §1–§8 + §11 纯派生部分为界） | 试点 SPEC.md 范围（纯逻辑镜像）+ 仓库 game.ts/main.ts/audio.ts 归属 |

## 通用教训（REGENERATE.md）

| 项 | 落点 |
|---|---|
| "数值表类 spec 必须自带带期望输出的算例"（SOP 硬性条款 + mulberry32 变体实证） | `REGENERATE.md` §5 第三波通用教训段 |
| 第三波三试点登记（含 match3rules 冻结 eval 抓出实现者 2 个真实 bug：果冻跨波重复计数/循环导入） | `REGENERATE.md` §5 已登记试验表批次 3 |
| 变更史指针 | `REGENERATE.md` §9 新行 |
