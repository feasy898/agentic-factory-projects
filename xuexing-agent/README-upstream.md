# 学情诊断 Agent（xuexing）

中小学学情诊断 Agent + 配套软件：确定性内核（测量/诊断/出卷/路线/复习调度 REST API）
+ LLM Agent 壳（讲解、归因、命题——经确定性入库门）。

完整 SOTA 调研见 `docs/SOTA调研报告-学情诊断Agent.md`；开发流程与状态见 `PM-STATE.md`。

## 快速开始

```bash
pip install -r requirements.txt
python -m pytest                 # 全套测试（单元/集成/数据/契约）
python tools/run_contract.py     # 仅契约测试（参考实现）
uvicorn xuexing.server:create_app --factory   # 启动 API（需先注入知识库，见 server.py）
```

## 架构（确定性内核 + Agent 壳）

```
┌────────────────────────────────────────────────────────────┐
│  Agent 壳（LLM）：讲解生成 / 错因归因 / 命题草稿             │
│        │ 只有通过确定性入库门(try_accept_draft)才能进题库    │
└────────△───────────────────────────△───────────────────────┘
         │ MCP/REST                  │
┌────────┴───────────────────────────┴───────────────────────┐
│  确定性内核（纯 Python，同输入同输出）                       │
│  【测量】kpgraph itembank diagnosis paper scheduler          │
│  【规划】route pedagogy blueprint recommend                  │
│  【能力】grading kt xapi paper_layout omr_sheet multitenant │
│  【数据】itembank_v2 dual_verify standard_coverage           │
│         misconception_coverage                              │
│  server(FastAPI: 全模块端点 + X-Org-Id 多租户)              │
└────────△───────────────────────────△───────────────────────┘
         │                           │
┌────────┴─────────┐      ┌──────────┴──────────────────┐
│ 知识库 data/      │      │ 渠道：小程序 / 静态卷 / 机构 │
│ 图谱·题库·误解·   │      │                              │
│ 母题·策略·验证台账│    │                              │
└──────────────────┘      └──────────────────────────────┘
```

## 模块总览（v0.1.0 起，v0.2.0 起全部契约冻结+重生成达标）

| 层 | 模块 | 职责 |
|---|---|---|
| 知识层 | kpgraph / itembank / itembank_v2 | 知识点先序图、题库与 Q-matrix、schema v2（来源/双代理验证） |
| 诊断层 | diagnosis / kt | 单卷认知诊断、跨会话掌握度轨迹（遗忘衰减） |
| 出卷层 | paper / blueprint / paper_layout / omr_sheet | 组卷+CAT、TIMSS 认知域蓝图、打印版面、OMR 答题卡 |
| 教学层 | route / pedagogy / recommend | 学习路线、循证策略库、误解针对性推荐 |
| 工程层 | grading / xapi / multitenant / server / agent_shell | 判分、学习事件导出、多租户、REST API、Agent 壳 |
| 数据工程 | dual_verify / standard_coverage / misconception_coverage | 双代理复验、课标覆盖检查、误解覆盖管线 |

契约状态：`specs/frozen/` 共 16 份（v0.1.0 八模块 + 夜间新增八模块），每份均经对抗评审冻结、连续 3 轮独立重生成 100% 通过。

## 契约驱动重生成方法论

1. 原型 = oracle（本仓库 `src/xuexing/`，110 测试全绿）。
2. 契约 = `specs/frozen/*.spec.md` + `tests/contract/`（行为 ground truth）。
3. 重生成 = 子代理只读规格+契约测试重写模块 → `python tools/run_contract.py --impl-dir <dir> --modules <m>` 判定。
4. 重生成质量反向迭代规格/评测；模块连续两轮独立重生成 100% 通过 = 契约完备。
5. 达标后终版重生成一次，全绿者入库。

## 目录

| 路径 | 内容 |
|---|---|
| `src/xuexing/` | 参考实现（oracle） |
| `tests/{unit,integration,data,contract}/` | 四层测试 |
| `specs/frozen/` | 冻结契约规格 |
| `data/` | 知识库（图谱/题库/误解/母题/策略） |
| `tools/run_contract.py` | 契约测试运行器（支持重生成实例注入） |
| `tools/validate_knowledge.py` | 知识库验证器 |
| `regen/round*/` | 重生成实现（门控对象） |
