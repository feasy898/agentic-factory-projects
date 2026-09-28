# PM-STATE — 学情诊断 Agent 开发台账

> 更新：2026-09-28 夜间开发会话。本文件是断点续作的权威依据：任何新会话从这里恢复上下文。

## 产品愿景（一句话）

有目的地出诊断卷 → 作答 → 认知诊断画知识地图 → 学习路线与教学策略（多媒体/互动/游戏化）
→ 持续调整。确定性内核（状态机+引擎+REST API）+ LLM Agent 壳。渠道：小程序 / 静态卷文件 / 机构接入。

## 开发方法论（用户指定的核心流程）

1. **原型即 oracle**：胶水代码+开源库先做出能跑、测试全绿的原型（M1 ✅）。
2. **spec+eval 迭代**：把原型拆模块，写规格（specs/frozen/*.spec.md）+ 契约测试（tests/contract/），
   冻结契约。
3. **契约内重生成**：子代理只读规格+契约测试重写模块实现（不得读参考实现），
   用 `python tools/run_contract.py --impl-dir <dir>` 判定。
4. **重生成质量反向迭代 spec+eval**：重生成失败 → 归因（规格歧义/评测缺口/生成错误）→ 修规格或评测 → 再重生成。
5. **达标判据**：每个模块连续两轮独立重生成 100% 通过契约测试 → 契约视为完备。
6. **终版入库**：达标后再重生成一次，全绿的那份实现替换/对照入库为正式软件（`src/xuexing/` 为参考实现基线）。

## 里程碑状态

| # | 里程碑 | 状态 | 证据 |
|---|---|---|---|
| M0 | 环境+脚手架 | ✅ | Python 3.12.10, deps OK, git init |
| M1 | 原型 v0 = oracle | ✅ | `9ab7789`，`python -m pytest` = 110 passed（63 常规 + 47 契约） |
| M1.5 | 契约测试框架 | ✅ | tests/contract + tools/run_contract.py（支持 --impl-dir 注入重生成实例） |
| M2 | 工作流#1：规格起草→对抗评审→冻结→重生成第1轮→测试门→失败归因 | 🔄 进行中 | 工作流 dwfrun（见 .zcode） |
| M3 | 工作流#2：知识注入（课标图谱扩充、题库/母题、误解库、策略库） | ⬜ | 待 M2 完成后提交 |
| M4 | 重生成第2/3轮至达标 → 终版重生成入库 | ⬜ | 达标判据：连续两轮 100% |
| M5 | 夜间迭代 saved workflow + BACKLOG 持续清库 | ⬜ | |

## 模块与契约清单（重生成范围）

| 模块 | 参考实现 | 契约测试 | 范围 |
|---|---|---|---|
| kpgraph | src/xuexing/kpgraph.py | tests/contract/test_kpgraph_contract.py | 重生成 |
| itembank | src/xuexing/itembank.py | tests/contract/test_itembank_contract.py | 重生成 |
| diagnosis | src/xuexing/diagnosis.py | tests/contract/test_diagnosis_contract.py | 重生成 |
| paper | src/xuexing/paper.py | tests/contract/test_paper_contract.py | 重生成 |
| scheduler | src/xuexing/scheduler.py | tests/contract/...scheduler_pedagogy... | 重生成 |
| pedagogy | src/xuexing/pedagogy.py | （同上文件） | 重生成 |
| route | src/xuexing/route.py | tests/contract/test_route_contract.py | 重生成 |
| agent_shell | src/xuexing/agent_shell.py | tests/contract/test_agent_shell_contract.py | 重生成 |
| server | src/xuexing/server.py | tests/unit/test_server.py | 不重生成（薄胶水层） |

## 重生成实现的硬性约束（写进每个生成器 prompt）

- 单文件 `<module>.py`；只允许 import 标准库 + `from xuexing.types import ...`（绝对导入）；
- 必须暴露该模块契约测试用到的全部公开 API（类/函数签名一致）；
- **禁止阅读** src/xuexing/<module>.py 与 tests/unit、tests/integration（契约测试除外）；
- 同输入必须同输出（除 Profile.updated_at / paper_id 的时间戳类字段外无隐藏随机性）；
- paper.py 允许 `random.Random(seed)`（seed 外部传入，确定性由 seed 保证）。

## 已定语义决策（冻结，勿反复）

1. 诊断引擎是"行为契约"不是"算法契约"：单调性/猜测感知/确定性/先序一致性必须满足，内部算法自由。
2. 先序平滑规则：**直接证据优先**。间接补证只对无直接证据的前序生效；间接折价只对有直接证据的前序生效；
   无证据链路不衰减。
3. 选题指标：预测答对概率最接近 0.5（最大信息量代理），并列取 id 最小；约束：未做过/主知识点在 scope/
   per-KP cap/难度带。
4. 组卷：blueprint {kp: n}，池=主知识点题按 |difficulty-target| 排序取前 2n 再 seed 洗牌取 n。
5. SM-2 变体调度（FSRS 是升级路径，契约不变）；rating 0-3；interval ∈ [1,365]，ease ∈ [1.3,3.0]。
6. 策略选择：priority 降序第一个条件匹配者胜；无匹配抛 StrategyError；库必须含无条件的兜底策略。
7. 路线：薄弱点全覆盖 + 拓扑有效；优先级 = 后代数×缺口；已达标知识点生成复习日程。

## 已知问题 / 风险

- Mimosa 扫描提示 4 处 low（不安全随机数）：均为固定种子确定性用途（测试+组卷洗牌），非安全用途，接受。
- `.zcode/`、`_research_tmp/`、`nul` 已 gitignore（调研子代理的临时产物，报告已沉淀到 docs/）。
- 契约重生成的"禁读参考实现"靠指令约束（子代理有全盘读权限），诚信依赖 persona + 事后抽查
  （重生成实现若与参考实现逐字雷同视为违规，在分析阶段检查）。

## 恢复指南（新会话从这里开始）

1. `cd D:\workspace\学情agent && python -m pytest` 应 110 passed。
2. 看 `ListWorkflowRuns` / `.zcode` 确认 M2 工作流状态。
3. M2 完成后：审查 specs/frozen/*.spec.md，`git add specs && git commit`，然后提交 M3 知识注入工作流。
4. M4：把通过矩阵里连续两轮 100% 的模块做终版重生成，全绿后 `git tag v0.1.0`。
