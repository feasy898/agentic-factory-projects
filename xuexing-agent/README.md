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
│  kpgraph(知识图谱)  itembank(题库/Q-matrix)                  │
│  diagnosis(认知诊断)  paper(组卷/CAT选题)                     │
│  route(学习路线)  scheduler(SM-2/FSRS)  pedagogy(策略规则)   │
│  server(FastAPI: /papers /learners /attribute)              │
└────────△───────────────────────────△───────────────────────┘
         │                           │
┌────────┴─────────┐      ┌──────────┴──────────────────┐
│ 知识库 data/      │      │ 渠道：小程序 / 静态卷 / 机构 │
│ 图谱·题库·误解·   │      │                              │
│ 母题·策略         │      │                              │
└──────────────────┘      └──────────────────────────────┘
```

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
