# agentic-factory-projects

> 一人软件工厂的在研项目集（monorepo），公开维护，供任何 AI agent 或开发者**零上下文接手**。
> 每个项目目录内自带两份接手文档：`README.md`（是什么/怎么跑/怎么验收）与 `TASK.md`（目标/验收标准/下一步）。

---

## 1. 这是什么

本仓库由一个人 + 多个 AI agent 协作开发，收录 **7 个在研项目**。所有项目按**全量提交历史**合并进本 monorepo（unrelated-histories 顺序合并，历史完整保留），每个项目位于各自的顶层目录：

```
agentic-factory-projects/
├── README.md            ← 本文件（总入口）
├── qw-arena2/           ← 参赛 agent：智能选购顾问
├── xuexing-agent/       ← 学情诊断 Agent
├── peidian-agent/       ← 园区配电运维智能体
├── ohos-tailscale/      ← 鸿蒙 Tailscale 客户端（纯 TS 协议库）
├── video-capability/    ← AI 营销视频生产流水线
├── zcode-research/      ← skill 资产工厂（课堂产线）
├── chenmai8/            ← 参赛项目群（5 个子项目 + 交付支撑层）
└── .gitignore
```

## 2. 项目索引

| 目录 | 是什么 | 语言栈 | 最小验收命令（基线见各 README） | 当前状态（2026-10-01） |
|---|---|---|---|---|
| `qw-arena2/` | 千问 AI Arena「智能选购顾问」参赛 agent：读商品资料包 → 产出用户画像/产品清单/推荐三份 Markdown | Python | `python -m pytest tests -q`（469 passed）+ `python tools/local_eval.py` | v0.5.2 就绪待提交；赛程 2026-10-23 截止 |
| `xuexing-agent/` | 中小学数学学情诊断软件：确定性内核 + LLM Agent 壳（诊断卷→作答→认知诊断→学习路线与复习调度） | Python 3.12 | `python -m pytest`（709 passed）+ `tools/validate_knowledge.py` + `tools/run_contract.py` | 内核级资产完成全绿；产品化未开始 |
| `peidian-agent/` | 园区配电（10kV/0.4kV，含储能/光伏/充电桩）运维 agent：受控行动网关 + 两票制红线 + 仿真驱动评测 | Python 3.12 | `python run_evals.py --module all`（233/233）+ `python scripts/ci_isolation.py` | 工程底盘 233 全绿；目标转向「理论→契约→模块→模拟练习场」四阶段 |
| `ohos-tailscale/` | 鸿蒙 NEXT 的 Tailscale 兼容客户端：纯 TypeScript 协议核心库（8 个 npm 包）+ HarmonyOS 工程壳 | TypeScript / ArkTS | `npm test`（280 pass）+ `npm run typecheck` | 协议库二期过半；壳从未编译（等编译环境） |
| `video-capability/` | AI 营销视频自动生产流水线（目标「无人干预 70 分」）：生成 → QC 门禁 → judge 盲测 | Python | `python overnight/vpipe/tests/run_v3_checks.py`（ALL PASS / exit 0） | v3 首批完成；模型/凭据等运行时依赖不在仓内，需重建 |
| `zcode-research/` | skill 资产工厂：面向「带学员借助 skill/MCP 走通一次真实交付」的课堂产线（含五代工厂方法论与总台账 REGISTRY） | Python | `python skillfactory/v5/assets/<asset>/eval/runner.py <被测产物> <oracle目录>`（exit 0 过 / exit 1 红路 fail-closed） | v5 三资产达标待发布；发布是唯一保留的人工批准点 |
| `chenmai8/` | 参赛项目群（资产化协议：spec+eval 可稳定再生）：具身助餐机器人 / 可玩广告（成品+oracle 双仓）/ 咖啡豆质检 / 政务AI脱敏网关 / 短剧多国出海 | Python / TypeScript 混合 | 各子仓一键门禁（`chenmai8/README.md` 有逐仓清单） | 六仓代码全量在库；门禁需先按各仓 REGENERATE 重建环境 |

## 3. 接手流程（新 agent 五步开工）

1. **选定项目**，读该目录下的 `README.md`（项目全貌与验收基线）和 `TASK.md`（任务卡：目标/验收标准/状态/下一步）。
2. **重建环境**：按各项目 README 的「构建与运行」节执行（Python 项目注意版本要求，多为 3.12；Node 项目直接 `npm install`）。
3. **跑验收基线**：先跑通 README 记录的基线命令，核对数字（如 `469 passed`、`233/233`）——**基线不绿不要开始改代码**，先在项目 TASK.md 登记环境问题。
4. **按 TASK.md「下一步任务」开工**：从 P0 项做起；每完成一项，更新 TASK.md 的「状态与已完成」节并提交。
5. **提交纪律**：见下节。

## 4. 贡献纪律

1. **先绿后改**：提交前跑该项目 README 的验收基线；改动后再跑一遍。任何「不改阈值凑绿」的行为都算事故——阈值/验收标准变更必须在 TASK.md 留痕（改了什么、为什么）。
2. **密钥零入仓**：任何 API key / token / 密码不进代码、不进文档、不进提交信息。凭据一律走环境变量或密钥服务；顶层 `.gitignore` 已默认排除 `.env`、`.secrets/`、`api_keys*`、`*.pem`、`*.tar` 等。
3. **网络地址卫生**：本仓公开维护，不要把内网地址/内网拓扑写进任何文件。历史中出现的 `198.51.100.x`、`203.0.113.x`、`100.100.0.x` 均为文档保留测试网段（RFC 5737 / 示例段），用于替换历史里的真实内部地址——**不是可路由地址，不要当真实服务使用**。
4. **一门一会话**：长验收门（分钟级以上）单独会话跑，跑完回写结果再继续开发；不要在门禁中途叠加改动。
5. **状态外置**：影响后续工作的事实（验收结果、决定、阻塞项）先写进该项目 TASK.md / 台账文件，再退出会话——新会话只靠仓库内文档就能接续。

## 5. 仓库结构与历史说明

- 所有项目主干在 `main` 分支；合并为 unrelated-histories 顺序合并，**全部原始提交保留**（可用 `git log --oneline -- <项目>/` 查看单项目历史）。
- 个别项目导入时有未提交改动，已按快照提交收入（提交信息含 `handover-snapshot` 字样）——即该项目的最新工作状态。
- `chenmai8/` 是项目群：6 个子仓各在 `chenmai8/<子仓名>/`，交付支撑层（调度台/资产总文件/plan 五件套/盲实现与盲评记录）在 `chenmai8/` 根目录。
- 标签：`xuexing-agent/v0.1.0`、`xuexing-agent/v0.2.0`、`chengmai-feeding-arm/*`、`chengmai-playable-factory/clean-room-v0` 为原仓标签（按项目名加前缀保留）。
- 额外分支：`wip/gov-gateway-review-person-v0`（政务脱敏网关一个未完成的评审线，未并入 main，保留备查）。
