# 跨模块冻结契约汇总（CONTRACTS）

> 版本：契约基线 v1.0.0（2026-09-28）。本页汇总跨模块冻结契约，标注版本与变更流程；
> 并如实登记**已识别契约痛点（变更候选）**——这些不是当前契约，是等待 owner 批准的修改提案。

---

## C1 PlayableSpec schema v1.0.0

- 权威文件：`packages/spec/playable-spec.schema.json`（draft 2020-12，`$id: urn:pf:spec:playable-spec:1.0.0`）。
- 顶层：required `specVersion(恒"1.0.0"), meta, game, flow, assets, i18n, channels, qc`；`variants` 可选；
  全链 `additionalProperties: false`。
- 关键约束：`meta.projectId` `^[a-z0-9][a-z0-9-]{0,63}$`；`game.template` 枚举 4 模板；`channels.targets`
  枚举 6 渠道；`flow.endScreen.landingUrl` `^https?://\S+$`（产物内唯一允许外链）；`i18n.strings` 每语言
  五键 `cta/tutorial/win/lose/score`；`durationBudgetSec.max ≤ 30`；模板 params 子 schema 全带默认值。
- 五条不变式 I1–I5 与错误契约（json-path + 稳定错误码 + 缺字段补路径）：见 [spec-contract](specs/spec-contract.md) §2。
- 双侧实现：Python 权威（pfcore）+ JS 镜像（packages/spec）；任一侧改动 = 破坏契约。
- 详细摘要与消费方：`packages/spec/index.mjs`（JS 公开面）、`python/pfcore/spec_model.py`（类型化表示层）。

## C2 运行时契约（模板 ↔ 桥 ↔ 质检）

- `window.PF` 成员表 / 5 个 `pf:*` 事件（detail 字段表）/ locale 五级优先 / 渠道识别四级优先 /
  就绪 8s 超时放行 / 退出路由表（含 window.open 回退）/ 首交互前强制静音 + 平台音量跟随：
  见 [engine-bridge](specs/engine-bridge.md) §2。
- QC 钩子 `window.__PF_QC__`：`hint(): {x,y,type}|null`（视口 CSS 像素真实最优步）、`state()`（直读 PF 相位
  loading/tutorial/playing/end）、`endScreenVisible()`（可选）。QC 侧手势语义（swap-* 定向拖拽 44px×4 步）：
  见 [qacore](specs/qacore.md) §5。
- 静音：一切音频经 `PF.audio` 创建；`isMuted() = 未交互 || 平台音量 0`。

## C3 产物目录契约

- 模板产物两条路径（现状）与渠道包目录 `<out>/<projectId>/<channel>/<locale>/`、`pack-manifest.json` 旁车、
  报告命名 `<产物名>.report.json|.png|-landscape.png`：见 [pipeline-contract](specs/pipeline-contract.md) §3。
- gitignore 约定：`artifacts/`、`tmp/`、`coverage/`、`_vendor/` 不入库；门禁先清旧产物再跑
  （"存在"必须是本次运行的真事实）。

## C4 channel-rules 数据结构（rulesVersion 1.0.0）

```
{ rulesVersion, updated, defaults{externalUrlPolicy:"forbid", allowedUrlSchemes:["data:","blob:"],
  muteBeforeFirstInteraction:true, allowRelativeRuntimeScripts:true},
  channels.<id>{ label, package{format:"single-html"|"zip", entry, structure?},
                 maxBytes>0, maxFiles>0, exit{protocol, call, waitReadyBeforeRender},
                 runtime{muteBeforeFirstInteraction, injectRelativeScripts[], forbidMraid},
                 allowedUrlWhitelist[], source } }
```

- 现有渠道：`preview / applovin / meta / mintegral`（frozen）；`unity / google / tiktok` planned。
- 结构校验：packager `validateRules`（违例即抛错）。每渠道适配器明细（是否传 URL/就绪条件/注入/禁用）：
  见 [channel-adapters](specs/channel-adapters.md)。
- `maxBytes` 上限值（内部从严线）：applovin 5,242,880 / meta 3,145,728 / mintegral 5,242,880 / preview 5,242,880。
- spec `channels.overrides.<channel>.maxBytes` 只许收紧（`effectiveMaxBytes` 取 min）。

## C5 确定性契约（可复现性的根）

- 校验器规范生成器：32 位 LCG（1664525 / 1013904223），pullpin 针角色（重抽 ≤16）、sort 扰动
  （rods×layers 步、逆步合法候选）——双语言逐行镜像（[spec-contract](specs/spec-contract.md) §2.2–2.3）。
- 模板运行时随机流：mulberry32 + 盐值表（`SPAWN_SALT=0x51ed270b`、重排盐 `0x5117`、
  `deriveRng = seed ^ imul(salt,0x9e3779b9)`）——生成/预估/结算/hint 四线同流（[规则卡 §7](specs/match3-rules-card.md)）。
- 打包 zip 固定 DOS 时间戳 2026-01-01 → 同输入字节可复现（[packager §3.4](specs/packager.md)）。
- **两套随机源（LCG vs mulberry32）已分叉**：见 §痛点 8。

## C6 eval 契约（裁定规则）

- 通过线唯一裁定 = 门禁脚本真实运行（`scripts/gate_phase1.py` 公开环境 / `gate_phase0.py` 本机含 spike 依赖）。
- 评测资产：`specs-eval/` golden + bad 6 件（各自击中点见 [spec-contract](specs/spec-contract.md) §3）。
- 纪律：不许 mock 被测物（渠道 stub/LLM mock 服务端除外——被测本体必须真实）；skip 不是 pass；
  变异样本必须"恰好只失败在对应检查项"；bad 样本属于规格，不许为过门禁改期望。

## 已识别契约痛点（变更候选——待 owner 批准，批准前不得擅改实现）

| # | 痛点 | 影响 | 变更候选 |
|---|---|---|---|
| 1 | 模板名（4）与渠道名（6）是封闭枚举 + `additionalProperties:false` | 加第 5 个玩法、加微信/巨量渠道 = 一次 schema 破坏性变更 | 冻结"信封"（meta/flow/assets/i18n/channels/qc），模板参数由各模板子 schema **注册制**扩展 |
| 2 | i18n 锁死五键（cta/tutorial/win/lose/score） | 结束页加副标题/年龄分级/商店徽标无处安放 | localeStrings `additionalProperties: allow`（schema 已允许额外键，痛点在实际消费侧按白名单取键——改为"必需键 + 自由扩展键"） |
| 3 | `variants` / `difficulty.targetLevel` / `channels.overrides.<c>.ctaStyle` 已进 schema 但**无任何消费方** | 规格字段形同虚设，误导 spec 作者 | 三选一：接线（variants 打包期换 seed、difficulty 接玩法）、或标注"预留"、或 v1.1 移除 |
| 4 | 素材路径必填但**缺失不报错**，构建直接忽略 | 评委按 schema 准备素材，得到与素材无关的程序化画面 | assetkit 最小函数落地时：素材存在则真实进包 + 校验存在性告警；演示 spec 提供中英文案 |
| 5 | 双打包路径：模板 `build.mjs` 直接吐单 HTML（含真实玩法），打包器要 dist 目录再内联一次 | 两条路径都会"打包"，无唯一内联者；门禁门项 3 打的是占位工程不是真游戏 | 裁决唯一内联者：模板输出 dist 目录形态，打包器为唯一内联点；门禁改用真产物 |
| 6 | `durationBudgetSec.max ≤ 30`（校验器）vs 45s 自动试玩预算（QC/模板）不一致 | 时长承诺与实测口径脱节 | 统一口径：模板按 30s 收束玩法，QC 预算 = max(45, spec 配置) 或直接沿用 spec qc 字段 |
| 7 | CHK06"参数=landingUrl"与 meta/google/tiktok 真实 API 不符（onComplete/ExitApi.exit/openAppStore 不收 URL） | 按字面实现永远失败 | 按 [channel-adapters §3](specs/channel-adapters.md#3-chk06-验收与真实-api-的冲突契约修正候选重要) 分型断言 |
| 8 | 可解性算法双实现（Python/JS 镜像）且与模板运行时随机流分叉（LCG vs mulberry32；I3 判的是校验器自己的盘面） | 每加一个玩法要改三处；两侧人工保持同步 | **可解性单一真源**：模板导出 `check(spec)`，Python 校验器调用（[spec-contract §5](specs/spec-contract.md)） |
| 9 | 命令名漂移：规划 `make` vs 占位 `run` | 新 agent 会造出第三种流水线入口 | [pipeline-contract §1](specs/pipeline-contract.md) 裁决后删除另一名 |
| 10 | "渠道规范变化只改配置"在退出路由上不成立（`exit.call` 是人读字符串，新渠道要改规则 JSON + 桥代码两处） | 扩渠道成本被低估 | 接受两处改动的现实并写进扩渠道流程（channel-adapters §4）；或 v2 把 call 变为可执行适配器注册 |

## 版本与变更流程（冻结）

- **版本锚**：PlayableSpec `specVersion = "1.0.0"`（schema 内 const）；规则库 `rulesVersion = "1.0.0"`；
  桥 `PF_VERSION = "0.1.0"`；包版本见各 package.json。
- **谁批准**：契约（C1–C6 与痛点候选）变更由仓库 owner / PM 批准；实现者不得单方面变更。
- **怎么广播**（每次契约变更必须全做）：
  1. 更新本页对应小节 + 受影响 specs/*（含"待统一/修正候选"的裁决回填）；
  2. 双侧实现同步改（schema/不变式/桥/规则库），golden + bad 评测集按需增补；
  3. `python scripts/gate_phase1.py`（及受影响的其他 eval）全绿；
  4. 单独 commit，标题带 `contract-change:` 前缀；版本锚号递增（破坏性变更进大版本）。
