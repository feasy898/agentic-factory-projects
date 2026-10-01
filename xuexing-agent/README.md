# xuexing-agent —— 学情诊断 Agent

> 接手文档 ｜ 任务卡见 [TASK.md](TASK.md) ｜ 项目原始自述见 [README-upstream.md](README-upstream.md)

## 项目是什么

「确定性内核 + LLM Agent 壳」的中小学（现数学 1–9 年级）学情诊断软件：出诊断卷 → 作答（含拍照/口述多模态采集）→ 认知诊断 → 学习路线与复习调度。设计形态为 REST API + 小程序/静态卷/机构三渠道（产品化未开始）。

本项目的独特方法论是**契约驱动重生成**：原型即 oracle → 冻结契约（`specs/frozen/` 16 份）→ 子代理只读规格盲重写 → 连续两轮 100% 通过才算契约完备。这是「spec/eval 才是核心资产」理念的项目级实践场。

## 架构一句话

确定性内核（题库/知识库/诊断/调度全部可离线确定性运行，709 个测试覆盖）+ 薄 LLM 壳（多模态采集与讲解生成，默认 mock、零网络隔离，`XX_MM_SMOKE=1` 才开启真调）。

## 构建与运行

- 环境：**Python 3.12**（必须；3.11 会踩 3.12 语法特性报错）。建议项目内建 venv：
  ```bash
  python3.12 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  ```
- 全量测试：`.venv/bin/python -m pytest`（pytest.ini 已含 `-q`，无需重复加）
- 知识库校验：`.venv/bin/python tools/validate_knowledge.py`
- 契约测试：`.venv/bin/python tools/run_contract.py`
- API 起服（产品化第一站，尚在待办）：`.venv/bin/uvicorn xuexing.server:create_app --factory`

## 验收基线（2026-10-01 实测三件套）

| 门 | 命令 | 基线 |
|---|---|---|
| G0-1 全量测试 | `.venv/bin/python -m pytest` | **709 passed, 2 skipped, 0 failed, exit 0（约 2.5s）** |
| G0-2 知识库校验 | `tools/validate_knowledge.py` | **VALIDATION OK: 189 kps, 810 items（全部双代理验证）, 343 misconceptions, 52 archetypes** |
| G0-3 契约测试 | `tools/run_contract.py` | 全绿 exit 0 |
| G0-4 凭据零入库 | `git ls-files | grep -i '\.env$'` | 空（`.env` 已 gitignore；key 只从环境变量读） |
| G0-5 零网络默认 | 不设 `XX_MM_SMOKE` 跑三件套 | 断网环境可通过（多模态默认 mock） |

## 已知问题

1. **产品化未开始**：无任何服务/容器在跑；API 独立起服冒烟、runbook、渠道路线都是待办（见 TASK.md）。
2. **契约第三波未开**：`specs/frozen/` 现有 16 份契约；第三波模块清单尚未拟定。
3. **题库规模**：当前 810 题，BACKLOG 目标 ≥1000（净增 ≥190）；题源未定（待裁定来源与授权）。
4. **多模态真调**：阶跃（StepFun）API 凭据需自备环境变量（`STEPFUN_API_KEY`/`XX_LLM_API_KEY`），默认集永远走 mock。
5. 仓库根有一个 Windows 重定向事故产物 `%TEMP%joint_gate_out.txt`（快照提交收入，内容为 pytest 进度点，无害；可删除）。
