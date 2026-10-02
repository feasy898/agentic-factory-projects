# TASK: chenmai8 —— 五条并行子线 + 交付支撑层（程序 Task）

> 任务卡版本 v1.1（2026-10-01 公开仓改写）｜状态载体：[_交付/调度台.md](_交付/调度台.md)（全景状态表 + 收账队列，权威）+ 本文件
> owner 指令口径（09-29）：「一切以最高标准全量并行推进」；资产化协议与判据本体不可改（改 = 改契约 + 留痕）

## 1. 目标

把 5 个参赛子项目按资产化协议（spec+eval 可稳定再生可工作的软件）推进到：

- 每线一键门禁在重建环境后**可复跑且全绿**；
- 调度台收账队列逐项有终态（完成 / WAITING_EVENT 物理等待 / WAITING_HUMAN 待裁 / 关闭）；
- C1–C5 资产判据（重生成稳定性 / spec 自含 / eval 强度 / 契约完备 / 目的收敛）持续全绿；
- 五线并行推进、互不阻塞。

**与 R9 的边界**：「澄迈杯 50 份模拟申报材料」是另一条线，已裁定关闭（2026-10-01），与本程序完全无关、不占用任何后续工作。

## 2. 验收标准（按五条子线分节）

### 2.0 程序级贯穿底线（每批收口必过）

| # | 断言 | 判定 |
|---|---|---|
| G0-1 | 迁移锚点在位 | `_交付/调度台.md`、各仓关键资产在库 |
| G0-2 | 零未推积压 | 本 monorepo 为权威副本；如启用外部远端，各仓 `git log <remote>/main..main` = 0 |
| G0-3 | 收账队列逐项有终态 | 调度台收账队列每项状态 ∈ {完成, WAITING_EVENT, WAITING_HUMAN, 关闭}，无无主项 |
| G0-4 | 环境先行 | 任何门禁复跑前，该仓环境已按 README/REGENERATE 重建（跳过环境跑门禁 = 判定无效） |

### 2.1 子线 C1 具身助餐机器人（`chenmai-feeding-arm/`）

| # | 断言 | 判定 |
|---|---|---|
| C1-A1 | 一键门禁复跑全绿 | `python scripts/gate_g1.py` → 8 步全 PASS exit 0，且 `verify_g1_reports.py` 独立复核结论一致（基线 8/8，09-30） |
| C1-A2 | 中性名扫描零命中 | gate_g1 内 check_naming 步 PASS |
| C1-A3 | Mock frozen 口径不破 | 全量 pytest 零回归；Mock 链路无真机化改动 |
| C1-A4 | T10 从臂到货 | 物理等待：置 WAITING_EVENT，到货前不占用会话 |

### 2.2 子线 C2 可玩的小游戏广告（`chenmai-playable-factory/` + `chenmai-playable-ads/`）

| # | 断言 | 判定 |
|---|---|---|
| C2-A1 | factory 门复跑全绿 | `npm run gate:m3` → 4/4 exit 0 + 122 件 `node --test` 全过 |
| C2-A2 | oracle 参照不腐化 | oracle 侧 phase 门复跑 6/6 |
| C2-A3 | 差分报告零回归 | `docs/diff/differential-report.md` 基线不被打破；触碰 oracle 的改动必须重跑差分终审并留档 |
| C2-A4 | 空壳处置 | 「可玩的中转」空目录等废留项由 owner 显式裁定（WAITING_HUMAN） |

### 2.3 子线 C3 咖啡豆质检（`chenmai-bean-eye/`）

| # | 断言 | 判定 |
|---|---|---|
| C3-A1 | 四项门复跑全绿 | `python scripts/gate_d4.py` → 4 项全过 exit 0 |
| C3-A2 | e2e_synth 指标不劣于冻结基线 | 沿用 gate 脚本内既有冻结阈值（基线：trays≥3、粒数恢复率按脚本口径） |
| C3-A3 | 掩码渗入实验完成并留档 | 静窗执行，实验记录 + 结论入仓 |
| C3-A4 | 演示脚本补齐 | 含可执行的一键演示命令 |
| C3-A5 | 生豆到货→自采链 | 物理等待：WAITING_EVENT |

**C3 执行记录（2026-10-01/02 跨夜，三线并行）**：

- **新增实时标注模块**：`beaneye/realtime/` 四模块（sources 三源+IP 丢帧策略 / engine 逐帧管线 / overlay 13 类配色+中文 HUD / server MJPEG 推流中枢）+ app 增量 `GET /live/stream`（源失败 503/参数错 400）与 demo.html「实时」入口 + `scripts/demo_realtime.py`；加分项：画面四角 ArUco 时周期重解单应 warp 正射网格，`eq_diameter_mm` 给真毫米（未标定时诚实标注伪毫米）。实测：合成源 720p 引擎处理帧 EMA **5.91 FPS**（≥5 目标达成；消费循环 3.64 FPS，elapsed 含合成盘预合成热身）；ArUco 标定生效（mm/px 与合成真值偏差 <10%）。本线新增 28 测试全过；接手时 `test_realtime_sources` 1 失败系该线遗留测试自身两处 bug（时钟增量/`grab→retrieve` 配对语义），已修复并披露。
- **新增 SO-101 分拣软件链**（真机延后，Mock 全链验证）：`beaneye/sort/` 九模块（arm 冻结 ArmProtocol / mock_arm / so101 惰性 import lerobot / frame 复用 ArUco 单应+三点仿射 / planner / session 状态机+软件急停 / render / config）+ `configs/sort.yaml` + `scripts/demo_sort_sim.py`。实测：合成盘检出 55 粒→规划 43 步→MockArm 43 步全执行（行程 21710mm）；`--strict-envelope` 下 28 粒超界显式 skipped、15 步执行。6 个测试文件 100 用例全绿；so101 真机路径（transport=None）舵机换算/连杆几何为占位默认值，无硬件未实测，核对清单已写入 `docs/SO101联调手册.md`。
- **训练脚本复核 7 条修复全闭环**（high 2 / medium 2 / low 3）：merge_ext_coco 去重、真实档门槛改逐盘相对误差、跨类 TP 强制、种子重叠双向拒绝、onnxruntime 导入护栏、措辞纠正、缺图盘剔除；修复后全量 pytest **649 passed / 0 failed / exit 0**（含既有 508 基线 + 本线 13 + 并行线测试）。
- **终局 gate_d4**：`python scripts/gate_d4.py` → 四项口径过，**exit 0**（本轮新代码态下的复跑结论）。
- **已知问题与物理等待**：摄像头真机实测（USB 直插 / 手机 IP 推流）待做，操作单见 `docs/交接-实时标注与SO101联调.md`；SO-101 上电联调待硬件（接线→.venv-arm→自检→三点标定→空载试跑→急停，见 `docs/SO101联调手册.md`），`configs/sort.yaml` 外参与几何为「明日实测」占位值；NN 栈真实模式 API 仍待 GPU 机 `--cpu-smoke`/`--smoke-train` 核对；C3-A5 生豆到货维持 WAITING_EVENT。

**C3 执行记录（2026-10-02 批1：标准回填 / 数据集入库 / 采集操作卡，三线并行；终局 gate_d4 exit 0）**：

- **标准回填线**（法定数值落地，文件 19 个）：DB46/T 642—2024 印刷稿（15 页）经仓库外临时 venv 文本层全文抽取 + 表 1/表 2 所在页（6/7 页）150dpi 位图逐页人工复核（文本与图一致），三套 YAML 就地回填——`configs/standards/db46_t642.yaml` 法定值 `verified: true`（杯品一级≥80/二级 70~79/三级 60~69；缺陷豆% ≤4.0/4.1~7.0/7.1~10.0、外来杂质 ≤0.5/0.6~0.8/0.9~1.2、粒度筛号 ≥16/14~15/12~13、水分≤12.0/灰分≤5.5/咖啡因≥1.5、一级应无严重缺陷；`legal:` 节每值带条款号；`delta_e_max=10.0` 保留并显式标注机器内控线）；`cqi_fine_robusta.yaml` 按简报公开口径回填（350g/Fine 0+≤5/新增优质档≤12 双轴近似/奎克 100g 样≤3·≤5/筛 16 乌干达实施口径）；`nyt_604.yaml` 数值维持折算基线并锚定 TCVN 4193:2014 与巴西 COB 等效表（注释标明「待 NY/T 604-2020 正式文本替换」——**正式文本待用户补，找到后回填并置 verified:true**）。关键工程决策：法定%口径以引擎新增 `defect_pct_max` 轴进入定级主链路（粒数占比近似，理由键 `defect_pct_within/over` 显式标注，不编造粒数当量）；6.5.4 粒度 5% 降档容差在 `premium.db46_legal_grade` 如实实现（恰 5% 过/6% 降档有测试钉住）。轨2：`configs/size_bands.yaml` + `beaneye/metrology/size_bands.py`（大≥17/中 15-16/小≤14 + ICO 筛径表，待真实豆标定）；轨3：PremiumDecision 契约 v1.2 只增 + `beaneye/standards/premium.py`；`docs/standards_matrix.md` 六标准矩阵 + ISO 10470 双系数表；`tests/test_standards_values.py` 25 例（既有 `test_standards.py` 12 处同步/替换，无 skip/xfail/删断言/放宽容差，清单见批 1 简报）。
- **数据集入库线**（复核修复全闭环，文件 8 个）：HIGH-1 dcv 模式显式 `--out` 时 manifest internal_name 取目录名；HIGH-2 自抓 ext-main 页面证实类别表为西语，`mapping.yaml` 改西语键并纠正 broca→insect（brocade 旧译系误配），登记册同步；MEDIUM-3 「分割格式×检测型项目」下载前预检警告；MEDIUM-4 登记册 §0 manifest 入库口径（ext-main dcv 模式含上游坐标不入库；universe 三集仅中性代号）；LOW-5 为复核员未复跑备注。四集（ext-main/ext-rseg/ext-rgreen/ext-scaa17）登记册 + mapping.yaml 就位，状态 **PENDING_KEY**（真实下载待 Private Key；Publishable Key 401 实测）；下载器 selftest 5/5 PASS；本线 20 项=12 passed+8 skipped（skip=数据未下载）。
- **采集操作卡线**（明日可执行，文件 7 个）：`docs/采集操作卡-v0.1.md`（13 类分堆指引 + 大中小三堆；≥20px/mm 设备换算表、双灯 45°+柔光、背景 RGB≈(208,203,200)、ArUco 1:1 打印核验、命名/自检/预标注两命令、蓝牙秤补做项；工作量预估 ≥260 粒/约 540 张/7~9.5h，经验估算）+ 脚手架 `data/datasets/hn_robusta/v0.1/`（13 类子目录 + size_trays + sorting_log/photo_log 模板）；`tests/test_hn_scaffold.py` 4 例。
- **终局与基线**：全量 pytest **690 passed / 8 skipped / 0 failed**（前夜基线 653 passed；8 个 skip 均为数据集线「数据未下载」跳过；中途一轮瞬时失败系并行线 mapping.yaml 编辑窗口，单独重跑即绿）；终局 `gate_d4` **exit 0**；中性名自扫（gate_d3 同款 23 条模式）19 个新增/改动文件 0 命中。
- **批1成果简报**：`chenmai-bean-eye/docs/批1成果-标准与数据集.md`（三线摘要/回填前后对照表/四集统计/明日拍摄指引/批 2 触发条件）。
- **待补与物理等待**：NY/T 604-2020 正式文本待用户补；四集真实下载待 Private Key；C3-A5 生豆到货维持 WAITING_EVENT（到货后按 `docs/采集操作卡-v0.1.md` 执行自采链）。

### 2.4 子线 C4 政务AI脱敏网关（`chenmai-gov-ai-gateway/`）

| # | 断言 | 判定 |
|---|---|---|
| C4-A1 | 最终代码态整门新跑认证 | 在最新 HEAD：逐模块 evals exit 0 → 七门链 → `gate_final` **9/9 PASS exit 0**（预算 ≥90 分钟 + 三条服务隧道 + 静窗） |
| C4-A2 | 认证独立可复核 | run 日志编号留档，验收会话逐项核对 PASS 行与退出码 |
| C4-A3 | 资产回填解锁 | 通过后政务资产回填资产总文件，调度台同步 |

### 2.5 子线 C5 短剧多国出海（`chenmai-drama-dub/`，最重子线）

| # | 断言 | 判定 |
|---|---|---|
| C5-A1 | D1 回炉：五模块 spec 成文 + 盲重生成过冻结测试 | B4/B5 五模块（M10/M12/M13/M14/M15）各产出 spec，按资产化协议重生成（隔离目录 + 冻结测试 + **禁看原实现**），产物过各模块冻结 eval |
| C5-A2 | 素材母盘链收口 | 真素材可下后 `material_fetch.py --fetch-all --only-missing` 续跑；每件 verify 留档；损坏件换源并 verify PASS |
| C5-A3 | D2 时长对齐修复 | **不预编数字**：先从既有口径提取阈值 → 冻结入 thresholds 并 git 化 → 修复后成片过阈值判定 |
| C5-A4 | 整门复跑认证 | 含修复的 HEAD 上 `gate_b4` 复跑 6/6 PASS、0 SKIP-GPU、0 FAIL（墙钟预算 ≥3600s，一门一会话） |
| C5-A5 | VLM 腿解除 BLOCKED | LLM 凭证供给后，`proto_shot_qa` e2e_vlm 线重跑 PASS |
| C5-A6 | 演示脚本补齐 | 内容遵守红线：D2 修复并判定通过前，任何演示禁播全链成片 |

### 2.6 支撑层与资产收敛

| # | 断言 | 判定 |
|---|---|---|
| S-1 | C1–C5 资产判据保持全绿 | 对本周期新增/改动模块按资产总文件 acceptance_ref 实跑五判据 |
| S-2 | 新改动模块独立评审留档 | `_reviews/` 形态覆盖，结论回写 |
| S-3 | 五文档与实况同步 | `_交付/` 每批收口刷新；各仓 `docs/assets/feedback.md` 反馈台账保持归零 |

**验收顺序（强制）**：环境重建（G0-4）→ 门禁复跑 → S-1/S-2 独立判定 → 人审收口。

## 3. 状态与已完成（截至 2026-10-01）

- 六仓代码全量在库（全历史保留）；五仓资产化收敛一轮完成（C1–C5 反馈归零）、可玩线按模式 M 走完五步闭环。
- 各线门禁最近基线（09-30 实跑）：C1 8/8、C4 9/9、C5 6/6、C2 4/4+差分 PASS、C3 四项口径过。
- 支撑层五文档 + plan 五件套 + _regen/_reviews 判定基建全部在库。
- 2026-10-01/02 跨夜（C3 夜班）：实时标注模块 / SO-101 分拣软件链（Mock 全链）/ 训练脚本 7 条修复三条线落地，终局 gate_d4 exit 0；真机增量（摄像头、SO-101 上电）与生豆到货为后续物理等待项，操作单 `chenmai-bean-eye/docs/交接-实时标注与SO101联调.md`。
- 待解：六仓环境未重建（门禁不能开箱跑）；C4 整门新跑；C5 D1/D2；VLM 凭证；损坏素材换源。

## 4. 下一步任务清单（按优先级，分批）

- **批 0（前置，串行）**：按各仓 README/REGENERATE 重建六仓环境 → 短剧/政务所需服务连通性验证 → 记录 `evidence/env-rebuild.md`。
- **批 1（并行）**：C4 gate_final 整门新跑认证（静窗）→ 资产回填；C5 D1 五模块 spec 回炉（盲态重生成）；C2 空壳处置上抛 owner。
- **批 2（并行）**：C3 演示脚本 + 掩码渗入实验（静窗）；C5 D2 阈值冻结 → 修复 → 判定；C5-A2 素材续跑（网络恢复即启）。
- **批 3（收口）**：C1/C2/C3/C5 门禁在各自 HEAD 复跑收口 → S-3 五文档同步 → G0-3 核对。
- **物理等待线（贯穿）**：C1 从臂到货、C3 生豆到货 = WAITING_EVENT 挂起，不空转。

## 5. 会话分解与委托要点

| 会话类型 | 职能 | 输入 | 输出 | 禁止 |
|---|---|---|---|---|
| S-调度 | 每批派工 | 调度台收账队列 + 本文件 | 派工单 + G0-3 核对 | 不亲自执行；不改各线产物 |
| S-通道 | 环境/隧道/素材 | 各仓 REGENERATE | env-rebuild 证据 + 连通性证据 | 不碰业务代码；凭据零落盘 |
| S-执行 | 五线并行开发 | 该线 `plan--*/` 开发指令 + spec | 代码/文档 + worklog 行 | 不自判完成；C1 不做真机；重生成会话**禁看原实现** |
| S-验收 | 门禁判定 | §2 判定命令 | PASS/FAIL 行 + run 日志编号留档 | 不信任自报（verify_g1_reports 式独立复核）；与执行不同会话 |
| S-评审 | 盲评/独立审查 | 盲态材料（_regen2/quiz 形态） | 裁决回写 `_reviews/` | 与执行隔离；不知实现细节 |
| S-人审 | 废留处置/凭证供给/阈值冻结确认 | 待裁清单 | 显式裁定入 evidence/ | 其他角色不可代签 |

**红线**：密钥零落盘；**D2 修复并阈值判定通过前，任何演示禁播全链成片**；盲实现纪律（隔离目录 + 冻结测试 + 禁看原实现）；factory 线对 oracle 仓只读；阈值/判据第一批判定后不可改；中性名纪律（各线门禁内含 check_naming，保持零命中）。

**方法论资产（可迁移）**：「开源复刻 → 资产化协议」全套（协议本体 + 模式 M 成品/oracle 差分 + plan 五件套模板 + 一键门禁族 + C1–C5 判据）；`verify_g1_reports.py` 式「不信任自报」独立复核范式。
