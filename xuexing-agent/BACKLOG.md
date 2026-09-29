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

- [x] **server 暴露新模块 API**：kt/blueprint/grading/recommend/itembank_v2/standard_coverage 的 HTTP 端点 + 集成测试（/trace /blueprint /grade /recommend）
  （完成于本轮，待主会话提交：src/xuexing/server.py 扩展六个端点（/trace /blueprint
  /grade /recommend /itembank/v2/validate /coverage/standard；相对导入改绝对导入
  以满足注入装载约定），create_app 签名与既有端点不动 + specs/drafts/server.spec.md
  （薄胶水层规格：内核等价/错误映射 400-404-422/共享 store 组装闭环/批量判分原子性
  九条不变量）+ tests/contract/test_server_contract.py（29 项，自封闭夹具，闭式
  现算核实）+ tests/integration/test_module_apis.py（9 项，grade7 真实数据：
  trace→recommend attach 全链路推荐闭式 ["m7_010","m7_011","m7_012","m7_115"]、
  129 题 v2 诚实披露 verified=0、课标 37 KP 归属缺口 0/覆盖 12/28），已登记
  run_contract（module=server；server 为不重生成胶水层，regen/round* 冻结八模块
  目录不含 server.py，--impl-dir 需平铺全模块目录）；全套 405 测试 +
  validate_knowledge --min-items-per-kp 3 + run_contract 全模块参考/平铺目录
  --impl-dir 注入（含 --suite full）全绿）
- [x] **双代理独立复验题库**：321 题逐题由两个独立解题代理验算，分歧提交人工仲裁；回填 verification 字段（当前 0/321）
  （完成于本轮，待主会话提交：src/xuexing/dual_verify.py（确定性内核：answers_match
  verification 级比对规则表 R1–R5——归一化/choice 解析/数值+单位门/多答案集合等值/字面
  兜底，verify_item 三值裁决 agree|disagree|incomplete、verification_record/make_record/
  backfill_item 纯回填、verify_bank/arbitration_rows；与 grading/itembank_v2 行为一致性
  契约测试跨模块锁定、模块间零 import）+ specs/drafts/dual_verify.spec.md +
  tests/contract/test_dual_verify_contract.py（18 项）+ tests/data/test_dual_verify_data.py
  （7 项：ledger 全库覆盖、manifest 与现场重跑逐位一致、回填记录可追溯、仲裁队列闭式、
  台账现算抽查与非复制证据）+ tools/dual_agent_verify.py（CLI：key/ledger 双代理通道 +
  manifest + 仲裁队列 + --apply 回填）；数据侧 321 题真实复验运行（2026-09-29）：
  m3-reviewer（key 通道，M3 独立审题员解题产物即标答，PM-STATE M3 在案）×
  night-reverify-20260929（GLM-5.3-Flash 夜间会话逐题独立重解，台账
  data/verification/ledger_night_20260929.json，数值题 Python 现算复核，m9_30 等按推导序
  落账以证非抄串）→ **agree 321 / disagree 0 / incomplete 0**，仲裁队列空，321/321 回填
  verification（git diff 逐字段核实：除追加 verification 外与 HEAD 逐字节一致）；
  test_itembank_v2_data 诚实披露 0/321 → 321/321 可追溯、integration grade7 verified
  0→129 同步；已登记 run_contract 与根 conftest MODULES；全套 430 测试 +
  validate_knowledge --min-items-per-kp 3（321/321 dual-agent-verified）+ run_contract
  全量 + --impl-dir 平铺目录 --suite full 注入自检全绿）
- [x] **静态卷 PDF 输出**：Paper -> 打印友好排版 JSON（题号/选项/留白/页眉），为机构分发与离线渠道落格式
  （完成于本轮，待主会话提交：src/xuexing/paper_layout.py（确定性内核：render_paper_layout
  排版 JSON——页眉三段连接（注记·卷名·卷号）/全卷顺序题号/选项标签解析/题型留白规则表
  （choice 括号/fill 下划线/solve 六行）/每页题数分页 + 节标题块恒紧邻其首题不占位、
  parse_option、section_ordinal 中文序号闭式；完整性门：未知题/bank 重复 id/选项 <2 或
  标签判重/未知题型/空卷一律 LayoutError 不出残卷；学生卷不含 answer/solution）+
  specs/drafts/paper_layout.spec.md + tests/contract/test_paper_layout_contract.py
  （32 项，paper/bank 鸭子类型自封闭夹具，闭式现算核实）+ tests/data/test_paper_layout_data.py
  （6 项，grade7 真实库端到端：37KP×2 题 seed=11 → 74 题/5 页/题型 23/46/5，节标题块
  "一、绝对值"…"三十七、消元法解二元一次方程组"）；已登记 run_contract 与根 conftest
  MODULES；全套 468 测试 + validate_knowledge --min-items-per-kp 3（321/321
  dual-agent-verified 保留）+ run_contract 参考实现 / --impl-dir 平铺目录注入
  （单模块与 --suite full）全绿）
- [x] **xAPI 学习事件导出**：Response/ReviewEntry/PlanStep -> xAPI statement JSON，附学习记录标准符合性测试
  （完成于本轮，待主会话提交：src/xuexing/xapi.py（确定性内核：三类事件产器
  answered/review-scheduled/plan-assigned + export_statements/plan_statements 批量导出
  + validate_statement 标准符合性校验器（xAPI 1.0.3 数据 API 离线 MUST 子集：
  actor 恰一 IFI/verb IRI/Activity IRI/UUID id/ISO 8601 timestamp+duration/
  version 1.0.0/score 约束/extensions 键 IRI）+ is_iri 等判定积木；statement id 用
  uuid5 冻结命名空间派生——确定性、无时钟（timestamp 由调用方传入）、无随机、纯 stdlib，
  鸭子类型零 xuexing 依赖；标准事实当日实读 adlnet/xAPI-Spec xAPI-Data.md 核对）+
  specs/drafts/xapi.spec.md + tests/contract/test_xapi_contract.py（33 项，闭式现算
  核实，符合性测试对产出 statement 另做独立正则/解析复核）；已登记 run_contract 与
  根 conftest MODULES；全套 501 测试 + validate_knowledge --min-items-per-kp 3
  （321/321 dual-agent-verified 保留）+ run_contract 参考实现 / --impl-dir 平铺目录
  注入（单模块）+ --suite full 全绿）
- [x] **OMR 答题卡对接规范**：answer-sheet.json（题号-选项映射）+ OMRChecker 输出适配层
  （完成于本轮，待主会话提交：src/xuexing/omr_sheet.py（确定性内核：build_answer_sheet
  题号-选项映射文档——卷面题号 1..N 与 paper_layout 同编号语义/choice 出涂点
  q<题号>·气泡值 A–Z/fill·solve 标 manual 不出涂点/outputColumns 自然排序/
  fieldBlocks 字段串（q1..10 含端点）+ parse_omr_results 解析 OMRChecker Results
  CSV（表头 file_id,input_path,output_path,score,<列…>，单元格=涂点拼接串、
  未涂=空串）+ to_responses 涂点→Response（未涂 None/False、单涂=该选项 options
  原文全串并与 grading.grade_choice 跨模块同判、多涂拼接串恒 False 不猜、manual
  题不产 Response、sheet/bank 漂移与未知涂点一律 OMRError 硬失败）+
  parse_option/field_label/parse_field_ranges/natural_sort_key 积木；OMRChecker
  对接事实当日实读 Udayraj123/OMRChecker master 源码核对：Results CSV 表头与行
  （src/utils/file.py、src/entry.py）、涂点拼接与 emptyValue=""（src/core.py）、
  字段串 q1..10 含端点与自然排序（src/utils/parsing.py）、QTYPE_MCQ4 气泡值表
  （src/constants/common.py））+ specs/drafts/omr_sheet.spec.md +
  tests/contract/test_omr_sheet_contract.py（26 项，自封闭鸭子夹具，闭式现算核实，
  含与 paper_layout.parse_option / grading.grade_choice 的零 import 跨模块锁定与
  generate_paper 端到端）；已登记 run_contract 与根 conftest MODULES；全套 527
  测试 + validate_knowledge --min-items-per-kp 3（321/321 dual-agent-verified 保留）
  + run_contract 参考实现 / --impl-dir src/xuexing 平铺目录注入（单模块与
  --suite full）全绿）
- [ ] **机构多租户**：server 加 org 维度数据隔离（org_id 贯穿 store/attempt/api）
- [ ] **契约冻结第二波**：把 kt/blueprint/grading/recommend 等新规格草稿走冻结工作流（对抗评审+两轮重生成达标）
