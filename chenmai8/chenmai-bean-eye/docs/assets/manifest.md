# 资产包总表（manifest）

> 本表按**逻辑模块**组织。已落地的代码结构不动，物理位置逐行标注。
> 每模块一行：模块ID / 名称 / 语言形态 / 职责 / 冻结契约 / 依赖 / eval 命令与通过线 / 重生成顺序位 / 状态。
> 详细契约汇总见 [CONTRACTS.md](CONTRACTS.md)；整仓再生手册见 [REGENERATE.md](REGENERATE.md)；逐模块 spec 在 [specs/](specs/)。
> 所有 eval 命令在仓库根执行。**2026-09-29 实测基线**：全套件 434 用例 = 431 绿 + 3 已知失败（M6 密排统计场景，
> 见下「实测注记」）；本文所有通过线数字均为当日 `.venv` 实跑值。

## 状态图例

| 状态 | 含义 |
|---|---|
| 冻结 | 已实现且 eval 全绿；契约冻结，改动视为破坏契约 |
| 冻结·已知回归 | 主路径 eval 全绿，存在**确定性的**已知失败用例（如实标注，不带过） |
| regenerating | 正在重生成（另一代理在飞）；只有边界与契约语义说明，**不写可重生 spec** |
| 占位 | 接口已冻结的桩实现，占位语义即当前契约 |
| planned | 未开工；有明确开工前置 |
| 降级运行 | 可运行，但缺位阶段显式降级并在响应中标注 |

## 核心模块（11 + 合成引擎）

| 模块ID | 名称 | 语言/形态 | 职责（一句话） | 冻结契约 | 依赖 | eval 命令 → 通过线（2026-09-29 实测） | 顺序位 | 状态 | spec |
|---|---|---|---|---|---|---|---|---|---|
| `M1-contract` | 契约（13 模型 + 5 Protocol + taxonomy） | Python（Pydantic v2，`extra="forbid"`）+ YAML | 全链路跨模块数据只走 `beaneye/schemas.py`；`defect` 合法取值由 `configs/taxonomy.yaml` 构造期校验 | schema v1.0（v1.1 只增 `GradingDecision.warnings`）；不变式：每粒只计最严重缺陷 / lab8 单一标度 / 单面 `pairing_cost=-1` | — | `python -m pytest tests/test_schemas.py -q` → **60 passed** | 1 | 冻结 | [CONTRACTS](../CONTRACTS.md) |
| `M2-acquisition` | 采集（Mock / USB / Synth 三源） | Python + OpenCV（DirectShow） | 统一 `Source` 基类落盘双面图 + manifest + M1 出厂自检；无相机阶段 Mock 全程可演示 | `TrayScan` 往返无损；`scan_<prefix>_%04d` 稳定序；图像 IO 只走字节缓冲封装 | M1 | `python -m pytest tests/test_acquisition.py -q` → **22 passed** | 2 | 冻结（SynthSource 占位，等 M12） | [REGENERATE §2](../REGENERATE.md) |
| `M3-calibration` | 标定与坐标变换 | Python + OpenCV（ArUco + 单应） | 四角码检测 → 原图 px → 盘面 mm 单应 → 2048² 正射网格；码位几何单一真源是 `configs/tray.yaml` | `CalibResult`（H_top/H_bottom 3×3、px_per_mm>0、marker_ids 恰 [0,1,2,3]）；<4 码抛 `CalibrationError` | M1 | `python -m pytest tests/test_calibration.py -q` → **34 passed**（中心反投影 0.08–0.41mm ≤0.5mm 线） | 3 | 冻结 | [markers-geometry](specs/markers-geometry.md) |
| `M6-pairing` | 上下配对 | Python + numpy + scipy | 两面观测质心 mm 欧氏距离 + 门限 12mm + 哑节点匈牙利全局最优 + 两遍整体配准残差矫正；单面豆一等保留 | `PairedBean.from_sides` 契约构造；bean_id 按锚定质心 (x,y) 稳定编号 | M1 | `python -m pytest tests/test_pairing.py -q` → **24 passed / 3 failed**（密排统计场景，见实测注记） | 4 | 冻结·已知回归 | [pairing](specs/pairing.md) |
| `M7-severity` | 严重度裁决 | Python（纯 Pydantic + PyYAML） | 每粒两面取最严重缺陷：rank 高者胜、平级取 conf 高记 both、非可计缺陷类不参与比较；与契约校验器逐位一致 | `worst(top,bottom,order)->(final_defect,worst_side)`；severity_order[0] 恒 normal | M1 | `python -m pytest tests/test_severity.py -q` → **83 passed** | 5 | 冻结 | [severity](specs/severity.md) |
| `M8-metrology` | 计量 | Python（math/statistics，无 numpy 依赖面） | 目数分布（1/64 英寸筛，.5 进位）、ΔE76 色差（两面按严重度 0.7/0.5 加权合并）、面积法估重 | `measure(beans, calib, std_yaml) -> Measurements`；lab8↔CIE 仿射互转唯一实现 | M1, M9(YAML) | `python -m pytest tests/test_metrology.py -q` → **31 passed** | 6 | 冻结 | [metrology](specs/metrology.md) |
| `M9-standards` | 标准引擎 | Python + PyYAML（带行号 LMap） | 三套标准 YAML 配置驱动定级：换标准 = 换 YAML 不改代码；`verified:false` 收集 warnings 并阻断 passed | `load_standard(id)`/`StandardEngineV1.evaluate`；语义错误 = `路径:行号: 问题` | M1, M7 | `python -m pytest tests/test_standards.py -q` → **57 passed** | 7 | 冻结（阈值为占位基线，全部 `verified:false`） | [standards-yaml](specs/standards-yaml.md) |
| `M10-report` | 质量护照 | Python + Jinja2 + matplotlib + segno | BatchResult → 中/英/越三语自包含单文件 HTML（A4 打印 CSS）+ 验真二维码（规范化 sha256） | `build_passport -> PassportReport`；QR 负载 `{base}/r/{id}|{sha256}`；证据卡每卡必有图 | M1, M8, M9, M11 | `python -m pytest tests/test_report.py -q` → **27 passed** | 8 | 冻结 | [passport](specs/passport.md) |
| `M11-agent` | 溯因智能体 | Python + PyYAML（模板）+ httpx（LLM 可选） | 检出缺陷 → 加工五环节归因 + 三语建议；模板离线保底，LLM 任何失败自动降级并标注 backend | `RootCauseAgent.explain(result, lang) -> AgentReport`；知识表与 taxonomy 12 类一一对应（加载期校验） | M1 | `python -m pytest tests/test_agent.py -q` → **79 passed** | 9 | 冻结（LLM 后端为可选增强） | [rootcause-kb](specs/rootcause-kb.md) |
| `M13-app` | 应用与 API 壳 | Python + FastAPI + 进程内线程池 | 提交整盘作业 → 全链路管线 → 结果信封 / 护照 / 逐豆证据图 / 标准列表 / 单页演示 UI（零外链） | 端点表与降级语义（缺位阶段显式标注，绝不静默伪装）；见 [passport §6](specs/passport.md) | M1–M11 全部 | `python -m pytest tests/test_app.py -q` → **14 passed** | 10 | 冻结·雏形（segment/classify 缺位 → 显式降级运行） | [passport §6](specs/passport.md) |
| `M12-synth` | 合成数据引擎（差异化核心） | Python（在飞） | 素材库 → 随机铺盘 → top/bottom 成对图 + 逐豆真值 manifest（同布局同 bean_id，种子可复现） | 真值语义见 [REGENERATE §5](../REGENERATE.md)；输入 schema = `configs/synth.yaml`（在飞） | M1, tray.yaml | 进行中，eval 入口未定 | 11 | **regenerating**（D4 进行中；`beaneye/segment/`、`configs/segment.yaml`、`configs/synth.yaml` 为工作树在飞件，未入库，不入本包） | — |

## 计划中 / 桩位（不写可重生 spec）

| ID | 名称 | 现状 | 开工前置 |
|---|---|---|---|
| `M4-segment` | 分割（Oracle/经典CV/NN 三腿） | **未入库**（工作树在飞 `beaneye/segment/` ClassicSeg 雏形）；M13 装配器探测 `<pkg>.build_default()` 工厂，缺位时 `NullSegModel` 显式降级（0 检出） | M12 素材库 + 分割 eval 入口 `tests/test_segment.py` |
| `M5-classify` | 分类（RulesV0 / NN 占位） | 未开工；缺位时 `NullClsModel` 恒 normal | M4 + 本地豆照片回填规则阈值 |
| `beaneye.kb` | 知识库检索 | 接口留桩：`KbChunk`/`KnowledgeBase` Protocol/`NullKnowledgeBase` 恒空；检索失败不阻塞主链路 | 标准原文核对（D1）后切块 |

## 数据文件与配置（非模块）

| ID | 名称 | 形态 | 职责 | 消费方 | 状态 |
|---|---|---|---|---|---|
| `DATA-taxonomy` | 缺陷分类体系 | `configs/taxonomy.yaml`（13 类 + 默认严重度序） | `defect` 字段合法取值、主/次归属、可计性（peaberry 不计缺陷）、三语名的**唯一数据源** | M1 构造期校验、M7、M9、M10、M11 | 冻结（越语译名 `vi_verified:false` 占位） |
| `DATA-tray` | 托盘几何与码位 | `configs/tray.yaml` | **码位几何单一真源**：盘 300mm、码 60mm、四角中心 (30,30)/(270,30)/(270,270)/(30,270)mm、网格 2048 | M3、MockSource、make_aruco.py、（在飞 M12） | 冻结（码边长待真机打印实测回填） |
| `DATA-camera` | 相机配置 | `configs/camera.yaml` | 双相机设备号/分辨率 3840×2160/对焦/曝光/预热帧 | M2 UsbSource | 占位（真机到货回填设备号） |
| `DATA-standards` | 三套标准 YAML | `configs/standards/{cqi_fine_robusta,nyt_604,db46_t642}.yaml` | 定级阈值配置（CQI 精品罗布斯塔 / NY 行业标准 / 琼地标），全部 `verified:false` 占位基线 | M8, M9, M10 页脚角标 | 冻结结构 · 占位阈值 |
| `DATA-rootcause` | 根因知识表 | `configs/rootcause.yaml` | 12 缺陷类 × 五环节归因先验 × 三语证据句/建议/引用 | M11 TemplateAgent / LLMAgent | 冻结（越语占位同上） |
| `DATA-upstream-map` | 素材来源映射 | `configs/upstream_mapping.internal.yaml`（**gitignore，不入库**） | 上游数据集原标签 → 本体系 key 的映射（上游名只允许存在于此内部文件） | 内部素材管线 | 内部件 |

## 验收门（eval 资产）

| ID | 名称 | 形态 | 门项 | 命令 → 通过线 | 2026-09-29 实测 |
|---|---|---|---|---|---|
| `GATE-d1` | D1 里程碑闸门 | `scripts/gate_d1.py`（系统 python 任意 cwd，内部定位仓库根 + `.venv` + `PYTHONUTF8=1`） | ① doctor exit0 ② `pytest tests/test_schemas.py` 全绿 ③ **现场重跑** oss_smoke（aruco+qrcode 两硬项 ok） ④ 数据集 README 含"解锁步骤" | `python scripts/gate_d1.py` → `GATE D1: PASS (4/4)`，exit 0 | **FAIL (1/4)**：①（DOCTOR: PASS）②（test_schemas 60 绿）④ PASS；③ 现场重跑 oss_smoke **超时 >600s**（本机当时网络受限，NN 冒烟件拉取超时；非产物回归） |
| `GATE-d2` | D2 里程碑闸门 | `scripts/gate_d2.py`（同约定） | ① doctor ② `pytest tests/` 全绿 ③ W3/W6/W7/W2 eval 入口逐个 exit0 ④ 中性名扫描零命中（**28 条**模式，产品面零豁免） ⑤ 禁止 IO 扫描零命中（cv2.imread / cv2.imwrite / np.fromfile 三种直传路径调用形态） | `python scripts/gate_d2.py` → `GATE D2: PASS (5/5)` | **FAIL (2/5)**：②③ 因 M6 密排 3 例回归（实测 `3 failed, 431 passed`）；①④⑤ PASS |
| `GATE-d3` | D3 里程碑闸门 | `scripts/gate_d3.py`（同约定） | ① doctor ② `pytest tests/` 全绿 ③ W8/W9/W10/W11 eval 入口逐个 exit0 ④ 中性名扫描零命中（23 条模式） | `python scripts/gate_d3.py` → `GATE D3: PASS (4/4)` | **FAIL (1/4)**：①③④ PASS（③ 4/4 入口全绿）；② FAIL（见实测注记 4——在飞并发写入的瞬时快照） |

> 门禁纪律：跳过不是通过；中性名扫描对 git 跟踪文本文件全量扫描（二进制跳过），豁免名单只收
> 不入库内部版文件（`requirements*.txt`/环境装配/数据管线/两块门脚本自身），**产品面
> （beaneye/ tests/ configs/ docs/）零豁免**——本资产包全部页面按此红线书写。

## 重生成依赖图（顺序位即拓扑序）

```
M1 契约(1) ──► M2 采集(2) ──► M3 标定(3) ──┐
   ├──────────► M7 严重度(5) ──┬──────────┤
   └──────────► M6 配对(4) ────┤          ├─► M8 计量(6) ──► M9 标准(7) ──► M10 护照(8) ──► M13 应用(10)
M12 合成(11，在飞) ──► M4 分割 ──► M5 分类 ─┘（识别两腿接入后经 M13 装配器自动接线）
M11 溯因(9，只依赖 M1+知识表，可与 6-8 并行)
```

- 已实现链：1→2→3→(4,5)→6→7→8→(9)→10。识别两腿（M4/M5）与合成引擎（M12）在飞，
  M13 已按「缺位即显式降级」语义先行冻结端点。
- 每步验收命令见 [REGENERATE §2](REGENERATE.md)。

## 实测注记（2026-09-29，资产包落成时点）

1. **全套件**：`python -m pytest tests/ -q` → `3 failed, 431 passed`（77s）。3 个失败全部是
   `tests/test_pairing.py` 的密排统计场景（`test_statistical_dense_324_beans_pitch8mm`
   precision 0.8818 < 0.90 线、密排旋转透视残差、小偏移第二遍安全）——确定性复现（钉种子）。
2. **回归根源（如实记录，未擅自修数）**：提交 `943d8cc` 把该文件随机源从标准库 random 切到
   numpy `default_rng`（提交注记称"钉种子确定性不变"——**种子值未变，但随机流变了**），
   密排场景实例随之改变，precision 跌破 0.90 回归下限。该构型本就是配对算法 docstring
   如实登记的已知局限（规则点阵 + 偏移接近点阵间距整分数时中位数锁错模，劣化守卫只能
   阻止第二遍变差、不能修正第一遍）。修复归属 M6 属主（改算法或改场景参数），本资产包只记录。
3. **工作树在飞件**：`beaneye/segment/`、`beaneye/synth/`、`configs/segment.yaml`、`configs/synth.yaml`、
   `tests/test_segment.py`、`tests/_segment_synth.py` 均未入库（D4 代理在飞，与本文写作并发），
   本资产包不引用其为真源；`M12-synth` 标 regenerating。
4. **GATE-d3 当日实跑**：① doctor PASS、③ W8/W9/W10/W11 四入口 4/4 exit0（31/57/27/79 各全绿）、
   ④ 中性名零命中（88 文件 × 23 条模式）——唯 ② 全绿项 FAIL：闸门起跑正逢在飞代理向 tests/ 并发
   落文件，读到一个中间态快照（`11 failed, 444 passed`，含收集期破损）；随后两次稳定复跑分别为
   `3 failed, 431 passed`（已入库模块集）与 `3 failed, 454 passed`（含在飞 test_segment 23 例），
   失败集合始终只有注记 1 的 3 例密排配对用例。**结论：② 的 FAIL 由并发写入的瞬态放大，
   稳定态差异 = 注记 1 的 3 例**；复跑门禁应等在飞代理落定后进行。
5. 其余各模块 eval 入口当日全绿（数字见上表，逐条实跑）。

## 本资产包的变更史指针

| commit | 内容 |
|---|---|
| （本包落成 commit） | manifest + 7 张 spec + REGENERATE + CONTRACTS 首版（对照 2026-09-29 HEAD 全量核验） |
