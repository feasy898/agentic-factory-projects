# TASK: ohos-tailscale —— 成果保全 + 协议面续作 + 互操作回归（真机线冻结）

> 任务卡版本 v1.1（2026-10-01 公开仓改写）｜状态载体：本文件 + `DELIVERY_REPORT.md` + `worklog.md`
> owner 裁定：app 编译与真机验收**冻结为 WAITING_EVENT**（等编译/真机环境这一外部事件），不排期、不上抛、不催办，也不得阻塞其余子线。

## 1. 目标

把「GPU 单点、互操作不可复跑、壳从未编译」的协议核心库半成品，推进为「成果保全到位、协议面按包续作、互操作可复跑、壳就绪待编」的鸿蒙组网客户端工程。

**非目标**：不主动推进 app 编译与真机（子线 E 冻结）；不在任何生产 tailnet/生产 headscale 上联调；不推翻 8 包接口冻结（`docs/architecture.md` AU 清单是权威，续作只增不改语义）。

## 2. 验收标准（可判定；数字即契约，改动须留痕）

### 2.0 贯穿底线 G0（每批收口必过）

| # | 断言 | 判定 |
|---|---|---|
| G0-1 | 全仓测试 | `npm test` → `# fail 0` 且 tests **≥ 280**（只增不减） |
| G0-2 | 类型 | `npm run typecheck` → exit 0 |
| G0-3 | bridge | `npm run test:bridge` → fail 0 且 ≥13 |
| G0-4 | 壳机检 | `npm run validate:shell` → 0 failed 且 ≥54 |
| G0-5 | D4/P4 机检 | `Date.now\|Math.random` 非注释行 0；`node:` 导入 0；网络调用特征文件 0（注释过滤口径已写死） |

### 2.1 子线 A：成果保全（本仓公开化即已完成主体）

- [x] 全历史保全（本 monorepo 即权威副本）
- [ ] A-2 ArkTS linter 复建路径抢救成文：写明 09-29 官方 linter（OpenHarmony 7.0 SDK ets-loader，src 告警 154→0）的工具链构成与 `interop/arkts-check.js` 调用方式；SDK 获取渠道如实标注
- [ ] A-3 文档漂移勘正：`CONTEXT.md` 中过时口径（「6 包」「238 pass」等）逐处修正

### 2.2 子线 B：协议面二期 · 发现与中继（三项相互独立，可并行）

范围：disco UDP relay 家族 0x04–0x09、netcheck 引擎调度、DERP region 随机选节点。

| # | 断言 | 判定 |
|---|---|---|
| B-1 | 上游对齐先于编码 | 每件开工前 tailscale 上游源码实读，对齐笔记（含文件路径+行号）归档 `docs/upstream/` |
| B-2 | 每件带测试收口 | 新增 ≥1 测试文件；KAT/上游取证锚定（XChaCha 用 draft-irtf-cfrg-xchacha-03 KAT 等）；G0-1~G0-5 全过 |
| B-3 | 架构契约同步 | `docs/architecture.md` AU 清单补新条目（✅/❌ 逐条标注） |

### 2.3 子线 C：协议面二期 · 数据面与控制面

范围：netmap→WG peer 推导、完整状态机、能力/knob 体系、LocalAPI/IPC、PeerAPI、MagicDNS、TUN fd 接线形态。

| # | 断言 | 判定 |
|---|---|---|
| C-1 | 接口冻结续作 | 每件先定模块接口（输入/输出/依赖/禁读）再实现；G0 全过 |
| C-2 | TUN 以纯 TS mock 先行 | `app/bridge/` 新增 TUN 桩接口 + mock 实现 + 集成测试；`test:bridge` 只增不回归 |
| C-3 | 加密面改动过评审 | 涉握手/Cookie/密钥派生的改动每件过一次双臂对照评审（上游语义 vs 实现），结论留档 |

### 2.4 子线 D：互操作回归（把一次性历史证据变成可复跑门）

| # | 断言 | 判定 |
|---|---|---|
| D-1 | 隔离互操作复建复跑 | 用隔离 headscale 实例（容器，用后即弃）跑 `interop/start-headscale.sh` + register/h2c/derp：全部 exit 0 且输出含 `INTEROP PASS` 与 `DERP INTEROP PASS` |
| D-2 | 固化为可复跑回归门 | 一条命令复跑全套（npm script / Makefile）；此后每批大收口必跑 |
| D-3 | 复跑留证 | 判定输出 + 环境参数（headscale 版本/容器 id）落 `evidence/interop-<date>/` |

### 2.5 子线 E：壳就绪线（**冻结 WAITING_EVENT**；维持动作不冻结）

- [ ] E-1 维持：validate:shell ≥54 且 0 failed；`app/bridge/` 接口对齐由 test:bridge 锚定
- [ ] E-2 解冻包随时可用：每季度核对 `HARMONY_AGENT_TASK.md`（自包含任务书）与 CU1–CU10 清单（`docs/arkts-constraints.md`）无漂移；解冻后按任务书执行：首编 HAP → 真机 VPN 冒烟 → 报告回传，第一优先回答 CU6（`.ts` specifier 是否被 ets loader 接受）
- E-3（冻结项）app 编译 + 真机 VPN 冒烟：不判定、不排期——达成时整卡方可置 COMPLETED

## 3. 状态与已完成（截至 2026-10-01）

- 10 提交全历史在库；8 npm 包协议库（common/crypto/noise/wireguard/derp/control/disco/netcheck）一期+二期过半。
- 已达成：真实 headscale v0.29.4 互操作（09-29，历史证据）、ArkTS linter src=0（09-29）、280 测试全绿、D4/P4 机检在岗、bridge mock 集成层（13 用例）、XChaCha20 KAT 锚定、Cookie Reply 键语义修正。
- 关键文档：`docs/architecture.md`（AU1–AU4 上游核对清单）、`DELIVERY_REPORT.md`、`HARMONY_AGENT_TASK.md`（自包含任务书）、`docs/build-feasibility-linux.md`、`interop/arkts-check.js`。

## 4. 下一步任务清单（按优先级）

1. **A-2/A-3**：linter 复建文档 + 文档漂移勘正（小工作量，先清账）。
2. **子线 B**：三件（disco relay 0x04–0x09 / netcheck 调度 / DERP 选节点）各按「上游实读 → 实现 + 测试 → AU 清单同步」推进，可并行。
3. **子线 C**：netmap→peer 推导与状态机续作；TUN mock 桩。
4. **子线 D**：B/C 首批收口后，容器化重建隔离互操作环境并固化为回归门。
5. **子线 E**：仅季度核对（E-2），不占常规会话。

## 5. 会话分解与委托要点

| 会话类型 | 职能 | 输入 | 输出 | 禁止 |
|---|---|---|---|---|
| S-研究 | 上游实读取证 | 该件的 tailscale 上游范围 | 对齐笔记（路径+行号）+ 原文归档 `docs/upstream/` | **不凭记忆写协议语义**（一期 5 处语义错误教训） |
| S-执行 | 按件实现 | 对齐笔记 + 该包现有测试 | 代码 + 测试 + worklog 行 | 不自判完成；不引 `node:*`/时钟/随机/网络（G0-5）；不碰 app/ 冻结项（bridge mock 除外） |
| S-验收 | 每批判定 | G0 判定命令 | PASS/FAIL 行 + 证据 | 不信任自报；与执行不同会话 |
| S-环境 | 子线 D 专用 | interop/ 脚本 + 容器方案 | 互操作环境证据 | 禁用生产网络；环境用后即弃 |
| S-评审 | 加密面双臂对照 | 上游语义摘录 vs 实现摘录（盲态） | 对照结论留档 | 不与执行/验收混同 |

**红线**：D4/P4/ArkTS 禁则不可放宽（放宽 = 改契约 + 留痕）；互操作只用隔离实例；headscale 临时凭据用后即弃不入仓。
