# 反馈台账（feedback）

> 整体评审 findings 的逐条处置台账。处置三口径：**修**=文档级小修已当场落地；**缓**=挂起，
> 写明触发条件/负责面/复核日期；**驳**=不构成缺口，写明依据。每条带证据指针（path:line
> 或实测命令）。上游开源名零入本台账（一律中性描述）。

---

## 2026-09-30 · 来源：C5 只读整体评审（政务AI脱敏网关/repo）

### F1 [high] README 识别承诺与实现存在口径差（人名/住址 NER、F1≥95%）

- **finding**：README.md:7 承诺「三层识别…NER（人名/住址/敏感身份）」、README.md:13 承诺
  「人名/地址 F1 ≥95%」；实际 NER 适配器 P0 恒返回空列表（recognizers/ner/adapter.py:27-30），
  人名词表仅 4 个演示名（config/person_names.txt:5-8），兜底为人口普查前 100 姓+右边界
  非汉字启发式、confidence=0.5、复姓显式留给 NER（recognizers/rule/detect.py:78-89）；
  F1≥95% 在 evals/thresholds.py 无对应阈值（2026-09-30 grep「F1|f1」零命中）。
- **处置：修（已落地）**——README.md 两行改时态：识别能力如实分「规则+校验位+语义词表+
  人名词表已实装（结构化号码召回实测 100%）/ NER 为适配器预留位属规划」；删除无验收门
  支撑的「F1 ≥95%」承诺，改主打「结构化号码召回 ≥99.5%（实测 100%）」。
- **挂起（缓）**：①演示词表扩容（config/person_names.txt 增补常见姓名）属识别**行为级**
  改动——会改变 m2_recognizers 断言面数字，须跑回归门验证后由开发批处理，不由文档小修
  承担；②若交付合同硬性要求人名/住址识别 F1，按 specs/benchmark-generator.md §4 的
  m8_baselines 路线先补识别 F1 验收门再谈数字。
- **复核日期**：2026-10-15（交付准备期）。

### F2 [high] 资产文档与代码漂移（m8_quality 被称规划态、e2e 7→8 用例、M11/gate_final 缺位）

- **finding**：manifest.md:9,31,40 与 CONTRACTS.md:149 称 m8_quality「规划态未实现」，实际
  evals/m8_quality.py（548 行）已实现，tmp/m8_quality_full_run.log:25 实录 `M8 QUALITY: 6/6
  checks passed`、:23 ratio=1.0000 ≥0.95；manifest.md:9,40 与 REGENERATE.md:53 写 e2e
  「7 PASS / U1–U7 七用例」，实际 ops/e2e_smoke.py:2 自述「八用例 U1–U8」、
  tmp/gate_final_run5.log:70 实录 `8 PASS / 0 FAIL / 0 DEFERRED`；evals/m11_robust.py（856 行，
  gate_final run5 实录 7/7，tmp/gate_final_run5.log:3090）与 ops/gate_final.py（410 行收官
  终检门九项）在 docs/assets/ 无系统性记载（grep 仅 specs/masking-placeholder.md:73,252 两处
  历史性提及）；specs/benchmark-generator.md §4「如实登记」段仍称两入口规划态。
- **处置：修（已落地，最小回填）**——①manifest.md 头部通过线 7→8 PASS、BENCH 行改判
  （m8_quality 已实现/仅 m8_baselines 规划态）、E2E 行改八用例、支撑面表新增 `ROBUST`
  与 `GATE_FINAL` 两行；②manifest.json 同步 4 处字符串 + supportingAssets 增两行；
  ③CONTRACTS.md 痛点#2 改判；④REGENERATE.md §2 表补 m11_robust/m8_quality 两行、
  §3 补 gate_final 用法、E2E 行改 8 PASS；⑤specs/benchmark-generator.md §4 登记段更新。
- **挂起（缓）**：深回填两项——m11_robust 与 m8_quality 各自缺 spec 专页（盲再生者只能靠
  manifest 两行+eval 自身反推）；specs/gates.md 未补 gate_final 节（该页为 frozen 六门专页，
  补节走资产变更批）。**复核日期：2026-10-15**。
- 注：本条修正后「新 agent 凭 docs/assets 盲再生」至少能发现两道已交付防线与 8 用例口径。

### F3 [medium] JSON 键位检测盲区（字符串键不进检测面）

- **finding**：`_iter_string_leaves`（gateway/pipeline.py:156-166）只递归 dict 的 values，
  字符串键不进检测面——PII 藏在键位（如以手机号作 JSON key、tools 参数键名）时漏检漏替换。
  2026-09-30 核对代码确认行为仍在；CONTRACTS.md 痛点#1 已如实登记为变更候选待批
  （出站全量叶节点=仅值节点）。
- **处置：缓（代码级，不改）**——变更候选走契约流程，由 owner/PM 批准后落地（叶遍历增扫键，
  或入站校验对键位命中 400——与既有 body 校验层合并裁决，gateway/app.py 已有深度/长度帽
  先例）。批准前不得擅改实现（CONTRACTS 冻结铁律 B）。
- **演示话术（备好）**：「值面全量检测已验收（tools/多模态段含内），键面已登记变更候选、
  走契约流程排期」。
- **复核日期**：与 owner/PM 契约裁定会同步（交付前必须有一次明确裁决）。

### F4 [medium] 真实推理链路单点依赖共享 GPU 隧道 :9004

- **finding**：config/app.yaml:19-20 两 real profiles 绑 127.0.0.1:9004；git 0de0c78 记录该
  GPU 为共享机、曾被他人服务占满、keepalive 已死、被迫走透传回退；真实链路延迟实测
  masked-leg mean=3027ms / p95=6162ms（tmp/m8_quality_full_run.log:21），共享负载峰值下
  e2e 客户端超时曾需 30s→120s 放宽（git e4bd963）。
- **处置：缓（部署侧/演示日执行项，不改代码）**——演示口径已写入 ops/demo/README.md：
  主演示走 mock（全离线零 key，网关开销与识别/脱敏/审计全链不受影响），真实 8B 链路仅作
  可选增强；演示前一天按 gpu/llm_keepalive.sh 预热并**预录一段真实链路视频兜底**；对外讲
  延迟用识别+脱敏自身数字（thresholds.py 线 p95<150ms），不用含真实推理的端到端延迟。
  隧道运维（透传模式/keepalive）降级为可选增强，不再列交付硬项。
- **复核日期**：演示日前一天（T-1 检查单）。

### F5 [low] 演示物料缺口与未实测交付物（场景脚本三缺三、compose 未实测）

- **finding**：ops/demo/README.md 场景表曾自注场景 1/3「页面待上线」、场景 1-3 脚本
  「T6.2 补」，目录实际仅 scene4.md/scene5.md——而 /webui/chat 与 /webui/dashboard 已上线
  （m9_webui 14/14 验收内），演示文档滞后于页面；docker-compose.yml:6 自述「构建环境无
  Docker，未在容器环境实测」。
- **处置：修（已落地，文档部分）**——场景表过期「页面待上线」标注删除，改「页面就绪 /
  脚本待补」并注明页面在 m9_webui 14/14 验收内；演示叙事建议向已脚本化的场景 4（防注入）、
  场景 5（扫描件体检）+双屏页+看板页收敛。
- **挂起（缓）**：场景 1-3 成文脚本（scene1-3.md）补齐，归 T6.2 演示批；docker-compose.yml
  保持如实声明，**「容器化部署」从验收范围划走**，安装一律走 README.public.md §2 四步
  原生起法（评审建议采纳，属交付口径裁定，随 F4 演示口径一并执行）。
- **复核日期**：2026-10-15。

---

## demoRisks 逐条（同源：C5 整体评审 demoRisks 1–7）

### R1 人名现场穿帮（最高危）→ **缓**
- 依据：词表 4 名外仅姓氏启发式兜底且要求右边界（recognizers/rule/detect.py:86-89），
  复姓与连续汉字内嵌名字不脱敏（detect.py:79 注释自证复姓留给 NER）。
- 处置：演示纪律已入 ops/demo/README.md 口径注（预置输入，勿让评委自由输人名）；
  词表扩容挂 F1 残留项（行为级，需回归）。**复核：2026-10-15**。

### R2 真实链路腿断（:9004 不在线/共享 GPU 被占 → U8 DEFERRED）→ **缓**
- 处置：并入 F4（mock 主口径+预录兜底+T-1 预热）。**复核：演示日 T-1**。

### R3 懂行评委现场构造 JSON 键位 PII 演示漏检 → **缓**
- 处置：并入 F3（代码盲区实锤在 gateway/pipeline.py:156-166，唯一防线是契约裁定或备好
  F3 话术）。**复核：与 F3 同**。

### R4 环境坑连锁（PYTHONUTF8=1、端口占用）→ **驳（已有覆盖）**
- 依据：REGENERATE.md §4 坑 1-2（GBK 控制台/PYTHONUTF8=1）、坑 3（9000/8901/8902 端口
  竞争与只碰本仓标识进程的清理口径）已逐条在册；「演示机当天不并行跑其他批次」为执行
  纪律，不构成新文档缺口。**无需复核**。

### R5 评委当场跑 `python -m ops.name_lint --strict` 见 19 命中 → **缓（话术备好）**
- 依据：2026-09-30 处置复核实测 `name_lint --strict` = 19 命中，全部在 config/ 内部坐标
  （config/install_check.json、config/synthetic_corpus.yaml 等依赖坐标，公开导出时被
  `_BY_DEPLOYER_` 置换）——设计内。
- 话术：默认档 0 命中；strict 档命中仅 config/ 内部坐标（引擎依赖坐标，不入公开树）；
  公开导出树 strict 0 命中（tmp/gate_final_run5.log 实录「严格档 lint 扫 154 文件 0 命中」）。
- **复核：随导出面变更**（engine 坐标增减时）。

### R6 不要当场跑整门/容器编排 → **驳（已有覆盖）**
- 依据：REGENERATE.md §3 已明示嵌套整门小时级、gate_final ≈90min 与「不要在窄超时窗口里
  启动整门」；docker-compose.yml 文件头未实测声明在位（:6）。演示引用 tmp/gate_final_run5.log
  九项记录与两张指标终值表即可。**无需复核**。

### R7 演示引用数字一律实测可溯源 → **缓（清单备好）**
- README「F1 ≥95%」承诺已删（F1 处置），最大穿帮源已消除。
- 可溯源数字清单（出处标注）：结构化号码召回 618/618=100%（整体评审实测，m2 口径）、
  2000 字规则层 ≈1.95-2.29ms（REGENERATE §2 表 / 整体评审实测）、m3 还原亚毫秒级
  （REGENERATE §2：还原 0.046ms）、审计零明文三重扫描 0 命中（m7 16/16 口径）、
  e2e 8 PASS（tmp/gate_final_run5.log:70）、name_lint strict 19 命中全 config（本次实测）。
  未亲测不引用：gate_final 未重跑（90min 超处置预算，引用 run5 日志）、m0/m6_ocr/m10_e2e
  慢门未复跑（引用 manifest 与 tmp 日志）。**复核：随 F1/F4**。
