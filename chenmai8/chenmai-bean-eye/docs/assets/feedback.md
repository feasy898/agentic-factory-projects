# 反馈处置台账（feedback）

> **日期**：2026-09-30　**来源**：C5 整体评审（只读整体评审，一次一项目）
> **对象**：啡眼 BeanEye（咖啡生豆质检）　**评审基线**：评审员本机实跑 `pytest tests/ -q`
> → 508 passed in 245.88s（exit 0）、`scripts/doctor.py` → PASS、
> `scripts/e2e_synth_run.py --trays 1` → E2E PASS。
> **处置纪律**：文档级小修当场改；代码级/方向级不动代码、登记本台账（处置=修/缓/驳
> +理由+复核时点）。评审原文含上游名的表述一律中性化转写。
> **本批（2026-09-30）已当场完成的修**：README 重写、manifest 双格式回填（M12/M4/M5
> 状态与 eval 线、GATE-d4 行、依赖图、变更史）、REGENERATE §2 步骤 11-14 回填 + §3 四道门
> + §5 现状化、CONTRACTS 痛点表 #4 勾销 / #7 更新 / 新增 #8 / C6-C7 四道门口径、
> 新增合并 spec `specs/segment-classify-synth.md`、`beaneye/app/main.py` 失实注释与
> 降级文案订正、`beaneye/app/static/demo.html` 合成按钮 hint 订正（三处均纯文案零逻辑）。

---

## 一、topDebts 处置（6 条）

### T0 [high] 产品演示链分类质量与演示效果断裂

- **finding**：演示主链（ClassicSeg+RulesV0）在合成盘上逐粒 final 标签一致率仅
  0.0125~0.034；mold 亮斑规则被掩码外扩的背景像素顶爆，单盘误报 61/71/81 粒 vs 真值
  缺陷 1~8 粒/盘；三盘恒「未达 Fine」。e2e 硬断言不含分类质量，无门禁拦截。
- **证据复核（本批实读）**：`out/e2e_synth/summary.json`（label_agree_rate_total
  final=0.0336；盘 1 grading_defect_counts.mold=61 vs truth_defect_hist.mold=1；
  grades={"未达 Fine":3}）；根因链 `beaneye/segment/classic.py`（掩码外扩）→
  `beaneye/classify/rules.py:130-134`（规则匹配）与 `configs/rules_v0.yaml`（mold
  `l_p95_minus_p50≥26` 亮斑指纹）；e2e 口径 `scripts/e2e_synth_run.py`（一致率列为
  如实记录非硬线）。
- **处置：缓（登记为 D7 生豆到货前置任务，本轮不硬修）**。理由：① W4b 分割参数系与
  W5 阈值均为已验收冻结件，评审与 9346ec6 提交注记均认定改进归 classic 参数调优/NN
  路线，不为演示观感擅调验收参数；② 中期两条路线（掩码内缩/背景剥离 vs 按 classic
  口径重标 rules_v0.yaml 阈值）需要合成盘上的对照实验支撑，属方向级决策；③ 短期
  对外口径护栏本批已落：README「精度与口径声明」+「AI 初检+人工复核」定位、合并 spec
  §3.3 口径声明、manifest M5 行 caliber 注记。
- **复核时点**：生豆到货（D7 启动）时必须先修演示观感再采集回填；若 2026-10-31 前
  无 D7 动向，提前复核是否需要先行落地「掩码内缩」实验。

### T1 [high] 资产包与代码二度漂移（M4/M5/M12 无再生 spec、gate_d4 缺位）——【已修】

- **finding**：manifest 两格式标 M12 regenerating / M4 未入库 / M5 未开工，而
  W12/W4a/W4b/W5fix 已落库 8 个提交；REGENERATE 明写三模块「本包不提供再生步骤」；
  CONTRACTS C7 无 gate_d4、痛点表 #4 已过时、#7 半过时；74 个测试用例对应模块无 spec。
- **证据复核（本批实读）**：`git log`（5fcc9da W12a-lite+W12b / 72a0b85 W12③ /
  347c20c W12 自验收 / 8b0fb43 W4a / fffe331 W5fix / 9346ec6 W4c）；
  b8f0e05 只订正了测试快照未动模块状态。
- **处置：修（本批当场完成）**。① manifest.md+json：M12/M4/M5 三行转「冻结」+
  eval 命令与通过线（synth 23 / segment 23 / oracle 9 / classify 19）、门禁表补
  GATE-d4 行、依赖图与变更史更新；② REGENERATE §2 步骤 11 回填为 M12/M4/M5 三步
  再生步骤并补步骤 14（e2e）、§3 扩四道门 + 09-30 实测态；③ CONTRACTS 痛点表 #4
  勾销（74f020e 已解决）/ #7 更新现状 / 新增 #8（RulesV0 状态语义，见 T5）/ C7 补
  gate_d4；④ 新增合并 spec `specs/segment-classify-synth.md`（含合并三模块的接口/
  契约/验收线/已知坑，声明其精读级别低于首版 7 张 spec）。
- **复核时点**：下次资产包触发放（D7 回填或 NN 腿开工）时对照 git log 复查本页时效。

### T2 [medium] SynthSource 接线悬空（痛点 #7 后半）

- **finding**：`beaneye/synth` 已落库，但 app 合成入口 `_ingest_synth_json` 与
  `SynthSource.capture_pair` 仍回退 MockSource；`beaneye/app/main.py:342` 注释写
  「合成引擎尚未落地」与事实相反；演示页合成盘面与 e2e 合成器（compose_tray）
  不同源。
- **证据复核（本批实读）**：`beaneye/app/main.py:331-383`（MockSource 回退 + 失实
  注释与降级文案）、`beaneye/acquisition/synth_source.py:28-32`（占位抛错）、
  `beaneye/app/static/demo.html:101`（按钮 hint）。
- **处置：缓（接线登记为待办）+ 失实文案本批已修**。理由：接线是行为变更（演示入口
  换合成器），须连带调整 test_app.py 断言口径与演示预演，不宜混入文档批；当前
  MockSource 回退是**显式降级语义**（响应含 degraded_reasons、demo 页有降级演示
  banner），契约允许。本批已修三处失实文案：main.py 注释、降级理由文案（保留测试
  断言的「模拟源」字样）、demo.html hint（注明与评测链合成器不同源）。接线时按
  CONTRACTS #7 变更候选执行：接 `beaneye.synth.compose_tray`、MockSource 回退保留为
  显式降级。
- **复核时点**：生豆到货前部署演示环境时；与 T0 演示观感一并复验。

### T3 [medium] README 双重漂移——【已修】

- **finding**：仓库结构树（vision/standards/passport/synthdata/advisor/web）与实际
  `beaneye/{acquisition,calibration,segment,classify,pairing,severity,metrology,
  standards,report,agent,kb,app,synth}` 完全不符；「AR 指选手选辅助」零实现零 spec。
- **证据复核（本批实读）**：原 README.md:12-24；`ls beaneye/` 实测包结构。
- **处置：修（本批当场完成）**。README 重写：结构树对齐现状（逐子包一句话）、AR 移入
  末尾「规划中（未开工）」行、新增「精度与口径声明」节（合成盘自洽口径 / 标准阈值
  占位 / AI 初检+人工复核定位）、溯因条目补「规则模板离线保底，LLM 后端为可选增强」
  （对应 R5 话术口径）。
- **复核时点**：下次 README 触碰时（NN 腿/AR 开工）。

### T4 [medium] 三套标准 YAML 全 verified:false 占位的定级权威性口径

- **finding**：「按标准一键定级」作为核心卖点，阈值均未对照原文核对；引擎把
  verified:false 收进 warnings 并强制 passed=False（工程诚实、设计正确），护照页脚有
  「标准阈值核对中」角标；越语译名全部未核对。对外若被当作已对标正式文本是合规风险。
- **证据复核（本批实读）**：`configs/standards/cqi_fine_robusta.yaml:56,63,65,71`、
  `nyt_604.yaml:41-66`、`db46_t642.yaml:43-68`（全 verified:false）；
  `configs/taxonomy.yaml:10,21-29`（vi_verified 全 false）；README 原 :7 免责句在位。
- **处置：缓（D7 回填路径已冻结，本批落口径护栏）**。理由：这不是缺陷而是**声明的
  占位状态**（结构冻结+阈值占位），引擎行为与角标均正确；回填唯一路径 = D7 生豆到货
  后按 `docs/collect_protocol.md` 采集 + 原文核对，提前手工改 YAML 反而破坏「阈值即
  数据」纪律。本批护栏：README「精度与口径声明」节明示「结构冻结+阈值占位、D7 回填、
  不作为标准符合性声明」；**对外材料纪律：禁用「符合 CQI 标准」类表述**（话术见
  第二节 R4）。
- **复核时点**：D7 生豆到货时（回填 verified 与 vi_verified）；对外材料发布前。

### T5 [low] RulesV0 跨调用滚动窗口状态

- **finding**：`area_reference` 取前 area_window 粒面积中位数为参考、不足则 area_ratio
  特征恒 -1 静默失效——分类结果依赖调用顺序；该语义只在模块 docstring 自记录，未进
  CONTRACTS。
- **证据复核（本批实读）**：`beaneye/classify/rules.py:20-23`（docstring 自记录）、
  `:70`（deque 初始化）、`:114-127`（`_decide`/`_area_reference` 实现）。
- **处置：缓（登记完成，代码不动）**。理由：单线程整盘顺序调用下行为正确且确定性
  （评测口径即整盘顺序）；改动会连带 rules 阈值有效性（area_ratio 规则按顺序口径
  标定）——改为请求级批参数属方向级，留 NN 腿/并行化接入前处理。本批已登记
  **CONTRACTS 痛点表 #8**（变更候选：请求级批参数或显式注入），manifest M5 行亦注明。
- **复核时点**：NN 分类腿或并行重打分开工前（CONTRACTS #8 关闭时）。

## 二、demoRisks 处置（7 条）

> 处置形态说明：R1/R3 随 T0/T2 台账项；R2/R5 为契约行为的口径确认（驳「缺陷」定性）；
> R4/R6/R7 为演示预案留档（不涉代码与文档缺陷，无需修）。

### R1【最大风险】演示主链逐粒证据卡穿帮 —— 缓（随 T0）+ 演示预案钉死

处置：登记 T0（生豆到货前必修演示观感）。演示预案（提前彩排，二选一）：
① 话术钉死「AI 初检 + 人工复核」（本批已写入 README 口径声明）；② 另备评估口径
演示件 `scripts/smoke_synth_chain.py`（真值观测直出、分类全对）——**必须明示这是
评估口径非产品链**（合并 spec §4 已写明此纪律）。

### R2 上传无四角码图 → 标定失败作业 failed —— 驳（非缺陷，契约行为）

处置：驳「应做单码兜底」方向。理由：v1 契约明确标定失败=作业 failed、绝不静默伪装
完整识别结果（`beaneye/app/pipeline.py:147-152` 抛 PipelineStageError；M3 约定现场
摆正重拍）——这是设计语义不是缺陷。演示预案：备打印 ArUco 板（`scripts/make_aruco.py`）
+ 浅色亚克力底 + 单层平铺盘。

### R3 两条合成路径并存（demo MockSource vs e2e compose_tray）—— 缓（随 T2）

处置：登记 T2 接线待办；本批已在 demo.html hint 与响应降级文案中注明「与评测链
合成器不同源、显式降级」——评委追问时的统一口径：内置合成=交互体验降级路径，
评测/e2e 数字一律出自 compose_tray 合成器（真值可核对）。

### R4 定级页三重占位同屏（grade 未达 Fine + 页脚角标 + warnings 清单）—— 预案留档

处置：无需修（三处都是诚实的占位标注，行为正确）。预案：预置一句话解释——
「结构冻结+阈值占位，生豆到货后 D7 按自采协议采集并对照原文回填；当前定级不作为
标准符合性声明」；对外材料禁用「符合 CQI 标准」表述（随 T4 口径）。

### R5 「大模型溯因」宣传与 backend=template 矛盾 —— 驳（非矛盾，话术统一）

处置：驳「宣传与实现矛盾」定性。理由：LLM 后端是**可选增强**、模板是**保底缺省**
（`beaneye/app/pipeline.py:114-117` `make_offline_agent` backend=template；LLM 任何
失败自动降级并标注 backend）——README 原文即写「由大模型给出溯因建议」的能力描述
口径，本批已重写为「规则模板离线保底，LLM 后端为可选增强」，话术按此统一。

### R6 现场被要求「跑一遍验收证明」的时间预算 —— 预案留档

处置：留档数字（本批与评审两轮实测背书）：全量 pytest ≈246-404s（508 passed）、
e2e ≈17s/盘（缺省 3 盘 ≈46s）、四新模块入口 74 passed in 216.25s（2026-09-30 处置
复跑实测）、gate_d4 全量约 15-20 分钟。演示建议预录实测输出引用，现场只跑 e2e。

### R7 低风险已排除项 —— 确认留档

处置：确认评审排除结论（doctor PASS 钉版链、中文路径字节缓冲封装 + gate_d2 ⑤ 静态
扫描、越语字形链按语言选字体）均有实测背书，无处置动作。

## 三、本批补充留档（评审未列，处置员观察）

- 仓库存在**嵌套自拷贝目录** `咖啡豆质检/repo/`（git 跟踪，含 scripts/gate_d*.py
  等副本，`git ls-files` 实证）——疑为历史误提交。不影响运行（包根在仓库顶层），但
  会稀释中性名扫描覆盖语义并干扰新 agent 定位。**处置：缓**（删除属仓库结构级操作，
  需属主确认后单独批次执行）。
- `configs/rules_v0.yaml:5-6` 自述阈值标定口径为「开发种子 604100-604112，13 盘 448 粒」，
  而同文件 :28-30 写「4 个开发种子基础 × 13 盘 × 34 粒」、`tests/test_classify.py:23`
  写「4 个开发种子基础（各 13 盘）」——**同一 YAML 文件头注释自相矛盾**（单基础 13 盘
  vs 4 基础 52 盘），以测试文件口径（4 基础）为准登记存疑，D7 回填时一并订正。
  **处置：缓（文字订正，D7 批次）**。

---

## 处置汇总

| 项 | 处置 | 状态 |
|---|---|---|
| T1 资产包漂移 / T3 README | 修 | 本批已完成 |
| T2 失实文案部分 | 修（文案）/ 接线=缓 | 文案已改；接线待办 |
| T0 分类质量 / R1 | 缓（D7 前置） | 口径护栏已落（README/spec/manifest） |
| T4 标准阈值口径 | 缓（D7 回填） | 口径护栏已落；对外表述纪律见 R4 |
| T5 RulesV0 状态 | 缓 | 已登记 CONTRACTS #8 |
| R2 无码失败 / R5 LLM 话术 | 驳 | 契约行为确认，话术口径已统一 |
| R3 合成双路径 | 缓（随 T2） | demo 口径已注明 |
| R4/R6/R7 | 预案/留档 | 本页留档 |

**整体反馈归零核验**：评审 topDebts 6 条 + demoRisks 7 条全部处置完毕
（修 3 项当场完成、缓 5 项带复核时点登记、驳 2 项带依据）——无未处置项。
