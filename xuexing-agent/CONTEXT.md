# CONTEXT — xuexing-agent（学情诊断 Agent）

> 建卡：编排批-线3 2026-10-01（docs/project-orchestration.md §1.1）；素材=continue-cards/xuexing-agent.md（迁移验证 2026-10-01 实跑）+ PM-STATE.md/BACKLOG.md。

## 背景
- 学情诊断 Agent：多模态作业采集（拍照/口述）→ 判分 → 学情画像 → 推荐。开发按 Wave 推进（Wave3 多模态线 d5a5463→a558e08 五连提交；方法论：原型即 oracle → spec+eval → 契约内重生成 `python tools/run_contract.py` → 终版入库）。
- git HEAD a558e08 Wave3-5（2026-09-30）。**无 remote——全部历史只在本地 .git**。

## 目标
1. 1-6 年级题库/知识/误解数据铺装收口（工作区 9 M + 26 untracked 即为此批活数据）。
2. 收口 13 个已知失败测试；数据提交入 git；建远端推全量历史。

## 验收标准
- `python -m pytest -q`：当前基线 **13 failed=已知未收口名单**（dual_verify 5 + misconception_coverage 4 + paper_layout 1 + module_apis 2 + recommend_contract 1），与本机逐一相同——数据对齐后应转绿；**新失败=回归**。
- `python tools/validate_knowledge.py` 知识库校验；`python tools/run_contract.py` 契约测试。
- API：`uvicorn xuexing.server:create_app --factory`（需先注入知识库）。

## 干系人
- owner（仓库归属/远端建库裁定）；使用者=学情诊断场景（多模态录入/判分/推荐闭环）。

## 当前里程碑
- PM-STATE.md 是断点续作**权威依据**；BACKLOG.md P0 队列按序推进。
- Temporal 裁定：⏸ 暂不挂（当前工单驱动即可；出现"跨夜多步等待"模式再挂——project-orchestration §1.2）。

## 风险
- **必须用 Python 3.12**（GPU `.venv`=3.12.13 已建；系统 python3 是 3.11，3.12 f-string 特性风险与 peidian 同款——不要用系统 python3 跑本仓）。
- 无远端：.git 损坏即历史全失——建远端推历史是高优先待办。
