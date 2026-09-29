# BACKLOG — 夜间迭代队列（night-iteration workflow 按优先级逐项实现）

> 约定：每项完成后必须 (1) 带契约测试 (2) 全套 pytest 绿 (3) 在本文件把该项移到「已完成」并附提交号。

## P0（核心能力闭环）

- [x] **KT 时序追踪**：在 diagnosis 旁加 `kt.py`——同一学习者跨多次会话的掌握度轨迹（遗忘曲线衰减 +
  新证据更新），契约：轨迹单调可解释、可重放。数据基础：XES3G5M 格式对接。
  （完成于本轮，待主会话提交：src/xuexing/kt.py + specs/drafts/kt.spec.md +
  tests/contract/test_kt_contract.py（22 项），已登记 run_contract；全套 134 测试 + validate_knowledge 全绿）
- [x] **诊断卷蓝图生成器**：`blueprint.py`——输入目标知识点集合+预算题数+认知维度（记忆/理解/应用，
  参考 TIMSS 二维框架），输出 blueprint（供 generate_paper）。契约：认知维度配比约束、覆盖约束。
  （完成于本轮，待主会话提交：src/xuexing/blueprint.py + specs/drafts/blueprint.spec.md +
  tests/contract/test_blueprint_contract.py（18 项），已登记 run_contract 与根 conftest MODULES；
  全套 152 测试 + validate_knowledge + run_contract --impl-dir 注入自检全绿）
- [x] **主观题判分接口**：Response.correct 目前要求外部给定；加 `grading.py`：数值答案归一化比对
  （分数/小数/单位），choice 自动判。契约：归一化规则表 + 判分确定性。
  （完成于本轮，待主会话提交：src/xuexing/grading.py + specs/drafts/grading.spec.md +
  tests/contract/test_grading_contract.py（115 项）+ tests/data/test_grading_data.py（4 项），
  已登记 run_contract 与根 conftest MODULES；全套 271 测试 + validate_knowledge +
  run_contract --impl-dir 注入自检全绿）
- [x] **知识点掌握 -> 母题推荐**：route.py 的 steps 里挂 recommended_item_ids（从题库按误解标签挑
  针对性题）。
  （完成于本轮，待主会话提交：src/xuexing/recommend.py + specs/drafts/recommend.spec.md +
  tests/contract/test_recommend_contract.py（16 项）；types.PlanStep 增补默认字段
  recommended_item_ids（附加式，route 自身按冻结规格非目标不改动，挂载由
  recommend.attach_recommendations 纯步骤完成）；已登记 run_contract 与根 conftest MODULES；
  全套 287 测试 + validate_knowledge + run_contract --impl-dir 注入自检全绿）

## P1（知识工程）

- [x] **课标覆盖检查器**：`tools/check_standard_coverage.py`——knowledge json 的 standard_ref 与
  课标主题清单对照，报告缺口。
  （完成于本轮，待主会话提交：src/xuexing/standard_coverage.py（确定性内核）+
  tools/check_standard_coverage.py（CLI：--grades/--format text|json，退出码 0/1/2）+
  data/curriculum/math_standard_2022_topics.json（2022 课标第四学段主题清单 28 条，领域/
  主题结构经课标原文核实，aliases 经全库 101 条 standard_ref 逐条核验：全归属+全覆盖，
  无跨条目重复关键词）+ specs/drafts/standard_coverage.spec.md +
  tests/contract/test_standard_coverage_contract.py（19 项）+
  tests/data/test_standard_coverage_data.py（6 项，含 7 个已知多归属闭式与 7 年级子库
  16 条覆盖缺口闭式），已登记 run_contract 与根 conftest MODULES；全套 312 测试 +
  validate_knowledge + run_contract --impl-dir 注入自检全绿。附带修复：
  kp_rta_apply 的 standard_ref 截断（检查器显形后按课标原句补全，math_grade9.json 与
  生成物 math_all.json 各 1 行））
- [x] **误解库扩充管线**：把 Eedi "错误→误解模式"思想落地：每 KP ≥2 条典型误解 + signature 答案 +
  教学提示，数据测试强制（每 KP 有误解或显式声明无）。
  （完成于本轮，待主会话提交：src/xuexing/misconception_coverage.py（确定性内核：
  parse_bank/audit/audit_dicts，结构校验 + 覆盖门 + 豁免语义 + 同 KP 签名去重）+
  specs/drafts/misconception_coverage.spec.md + tests/contract/test_misconception_coverage_contract.py
  （20 项）+ tests/data/test_misconception_coverage_data.py（7 项，含覆盖门咬合与算术闭式抽查）；
  误解库数据 65→202 条（g7 +49 / g8 +38 / g9 +50，全部逐条验算，101 KP 恰各 2 条，
  签名跨条目同 KP 不重复）；validate_knowledge.py 新增 --min-mc-per-kp 覆盖门（默认 2）；
  已登记 run_contract 与根 conftest MODULES；全套 339 测试 + validate_knowledge +
  run_contract --impl-dir 注入自检全绿）
- [x] **题库 schema v2**：加 source（原创/真题改编/LLM生成+验证）、verification（双代理独立解题一致性）
  字段，validate_item 校验 v2 字段完整性。
  （完成于本轮，待主会话提交：src/xuexing/itembank_v2.py（确定性内核：validate_item_v2/
  validate_bank_v2/source_counts/verification_stats，全函数不抛异常、错误消息目录冻结）+
  specs/drafts/itembank_v2.spec.md + tests/contract/test_itembank_v2_contract.py（24 项）+
  tests/data/test_itembank_v2_data.py（4 项，含 12 题算术闭式现算抽查）；冻结 itembank 的
  validate_item（R1..R9c 目录）按规格不动，v2 完整性由独立模块承担、validate_knowledge.py
  接线（item v2 错误前缀 + 摘要行 dual-agent-verified 计数）；数据侧 321 题全部标注
  source=original（M3 原创、无真题标记，逐项核实），verification 语义定为 original/adapted
  允许 null（诚实未验证）、llm_generated 强制通过记录（0/321 真实披露，不伪造）；
  已登记 run_contract 与根 conftest MODULES；全套 367 测试 + validate_knowledge
  （含负向门：坏 source 退出码 1）+ run_contract --impl-dir 注入自检全绿）

## P2（产品化）

（已并入下方「P2（第二波）」队列，按更细的验收标准执行）

## 已完成

- [x] M1 原型 v0（8 模块 + 110 测试全绿）—— 9ab7789

## P2（第二波，2026-09-29 夜 按产品价值排序）

- [ ] **server 暴露新模块 API**：kt/blueprint/grading/recommend/itembank_v2/standard_coverage 的 HTTP 端点 + 集成测试（/trace /blueprint /grade /recommend）
- [ ] **双代理独立复验题库**：321 题逐题由两个独立解题代理验算，分歧提交人工仲裁；回填 verification 字段（当前 0/321）
- [ ] **静态卷 PDF 输出**：Paper -> 打印友好排版 JSON（题号/选项/留白/页眉），为机构分发与离线渠道落格式
- [ ] **xAPI 学习事件导出**：Response/ReviewEntry/PlanStep -> xAPI statement JSON，附学习记录标准符合性测试
- [ ] **OMR 答题卡对接规范**：answer-sheet.json（题号-选项映射）+ OMRChecker 输出适配层
- [ ] **机构多租户**：server 加 org 维度数据隔离（org_id 贯穿 store/attempt/api）
- [ ] **契约冻结第二波**：把 kt/blueprint/grading/recommend 等新规格草稿走冻结工作流（对抗评审+两轮重生成达标）
