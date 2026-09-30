# 跨模块冻结契约汇总（CONTRACTS）

> 版本：契约基线 schemas v1.0（v1.1 只增 `GradingDecision.warnings`，2026-09-28 W9 增补）。
> 本页汇总跨模块冻结契约：**单粒 / 整盘 / 护照三张 JSON schema 的字段全表** + 横切契约 +
> 已识别痛点候选。字段定义对照 `beaneye/schemas.py` 逐行核验于 2026-09-29，2026-09-30
> 回炉复核（C2.4 pairing_cost 两口径强制、C2.6/不变式① normal 键口径、C5 逐类归属/rank
> 现查/worst_detail 双 None 补引）；
> 一切跨模块数据只走这些 Pydantic v2 模型（`extra="forbid"`：多余字段报错；
> `to_json()/from_json()` 往返必须无损）。

---

## C1 单粒 schema（一粒豆的一面与两合）

### C1.1 BeanMask（单面单粒几何；盘面毫米坐标系，M3 变换后）

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `mask_id` | str | min_length=1，面内唯一 | 如 `top_0017`（M13 规范化格式 `{side}_{i:04d}`） |
| `side` | `top`/`bottom` | — | 面 |
| `polygon` | list[[x,y]] | 非空；每点恰 2 坐标 | 外轮廓顶点（mm） |
| `bbox_mm` | (x0,y0,x1,y1) | `x0<=x1 且 y0<=y1` | 外接框 |
| `area_mm2` | float | >=0 | 掩码面积 |
| `centroid_mm` | (x,y) | — | 质心（M6 配对代价的输入） |
| `source` | `oracle`/`classic`/`nn` | — | 实现来源；**source=oracle 时 conf 恒 1.0** |
| `conf` | float | [0,1]，默认 1.0 | classic/nn 0-1；oracle=1.0 |

### C1.2 BeanObservation（单面单粒观测：几何+类别+颜色+证据）

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `obs_id` | str | **必须 == mask.mask_id** | 观测 id |
| `side` | top/bottom | **必须 == mask.side** | 面 |
| `defect` | str | **必须在 taxonomy**（构造期校验，非法即 ValidationError；schemas.py:205-210。溯因侧 `CauseItem.defect` 同，schemas.py:462-469；`defect_is_countable` 对未知类恒 False 仅纵深防御，schemas.py:81-91） | 类别键；`normal` 表好豆 |
| `defect_conf` | float | [0,1] | 置信度 |
| `severity_rank` | int | >=0；**normal 恒 0，缺陷类恒 >0** | 0=normal 越大越严重，取 taxonomy/标准 YAML 序 |
| `crop_path` | str | min_length=1 | 掩码裁剪 RGBA PNG 证据（相对路径，M13 解析） |
| `mask` | BeanMask | — | 几何 |
| `color_lab` | (L,a,b) | **三通道 ∈ [0,255]（lab8 单一标度）** | 掩码内均值；CIE 负值混入=构造期报错（见 C4） |
| `eq_diameter_mm` | float | >0 | 面积等效直径 |

## C2 整盘 schema（采集→标定→配对→计量→定级→全链终点）

### C2.1 TrayScan（一次整盘双面采集）

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `scan_id` / `sample_id` / `tray_id` | str | min_length=1 | 标识（采集侧 `scan_<prefix>_%04d` 从 0001 起） |
| `top_image` / `bottom_image` | str | min_length=1 | **相对路径**（相对采集输出根；`scan_paths(scan, root)` 解析） |
| `calibration` | CalibResult \| None | — | M3 职责；采集阶段恒 None |
| `captured_at` | str | **ISO8601**（构造期解析校验） | 带时区 |
| `source` | `mock`/`usb`/`synth` | — | 来源（上传图=真实拍摄语义，取 usb） |

### C2.2 CalibResult（标定）

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `px_per_mm` | float | >0 | 盘面中心局部尺度（估计值，见 markers-geometry §4） |
| `H_top` / `H_bottom` | 3×3 数值矩阵 | **必须 3×3** | 原图 px → 盘面 mm 单应 |
| `marker_ids` | list[int] | **排序后恰 [0,1,2,3]**（角位序可任意排列） | 四角码 id |
| `reproj_err_px` | float | >=0 | 像素量纲；组装规则=两面各自毫米化取 mm 最大再折回均值 px_per_mm |

### C2.3 SegResult（单面分割结果）

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `scan_id` / `side` | str / top,bottom | — | 归属（协议不带 side，装配器规范化） |
| `masks` | list[BeanMask] | — | 该面全部掩码 |
| `runtime_s` | float | >=0 | 耗时 |

### C2.4 PairedBean（配对后的一粒；「每粒只计最严重缺陷」的载体）

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `bean_id` | str | min_length=1 | `b0001..`（锚定质心 (x,y) 稳定序） |
| `top` / `bottom` | BeanObservation \| None | — | 两面观测（可缺面） |
| `pairing_cost` | float | **两口径强制（校验器三分支逐一强制，schemas.py:290-300）**：单面（恰一面 None）与双 None 占位必须恰 = -1；双面齐全必须 >=0（mm 距离），传 -1/任何负值即 ValidationError | 配对判定坐标系下距离 |
| `worst_side` | `top`/`bottom`/`both`/`none` | **必须与裁决器重算一致**（校验器逐位复核） | 见 C5 裁决规则 |
| `final_defect` | str | 同上 | 两面中 severity_rank 最高者（平级取 conf 高） |
| `final_severity_rank` | int | 同上 | — |

规范构造入口 `PairedBean.from_sides(bean_id, top, bottom, pairing_cost)`——按契约裁决规则
构造，保证不变式成立；**任何来源**直接构造 `PairedBean` 时校验器都会重跑 `_resolve_worst`
比对 final_* 三元组，不一致即 ValidationError（M6 不写 final_*，从根上杜绝两面不一致）。

### C2.5 Measurements（整盘计量）

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `bean_count` | int | >=0；**BatchResult 校验其 == len(beans)** | 本盘粒数口径 |
| `sieve_hist` | dict[str,int] | 计数 >=0 | 目数（字符串键）→粒数，按数值升序 |
| `sieve_pass` | bool \| None | — | None=未判定（无筛目目标/空盘），**None 不是通过** |
| `eq_diameter_mm_stats` | StatsSummary{min,max,mean,median} | — | 每粒=两面均值 |
| `color_lab_mean` | (L,a,b) | ∈[0,255]（lab8） | 与逐粒同标度 |
| `delta_e_mean` | float | >=0 | CIE 单位，ΔE76 vs reference_lab |
| `delta_e_hist` | dict[str,int] | 计数 >=0 | 2 ΔE 一桶（"0-2"…"18-20"）+ 开口桶 "20+" |
| `est_weight_g` | float | >=0 | Σ面积×系数 |
| `weight_model` | str | min_length=1 | `"<model>:v1"`（area_linear:v1 / area_thickness:v1） |

### C2.6 GradingDecision（定级结论）

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `standard_id` | str | min_length=1 | cqi_fine_robusta / nyt_604 / db46_t642 |
| `grade` | str | min_length=1 | 级别名或 fail_grade（如"未达 Fine"/"等外"） |
| `passed` | bool | — | **warnings 非空时引擎强制 False**（阈值未核对不宣布通过） |
| `primary_count` / `secondary_count` | int | >=0；**BatchResult 校验其与豆列表按 taxonomy 分计一致** | peaberry 等不可计类不计 |
| `defect_counts` | dict[str,int] | 计数 >=0；**与逐粒 final_defect 直方一致：非 normal 键双向强制（缺键/计数不符均报错），normal 键可省（写则必校）**——计数函数 include_normal 缺省 = False，M9 引擎写出的直方不含 normal 键（engine.py:117）；校验器内部按 include_normal=True 取全直方比对（schemas.py:530-542，2026-09-30 探针实测两向） | 每粒只计一次 |
| `reasons` | list[str] | — | i18n 模板键+数值：`键:k=v;k=v`（M10 按 lang 渲染） |
| `warnings` | list[str] | 默认 []（v1.1 增补，只增不改名） | 标准 YAML verified:false 清单（稳定键路径） |
| `standard_yaml_sha` | str | `^[0-9a-f]{64}$` | 标准 YAML 文件字节 sha256 |

### C2.7 BatchResult（全链终点；护照/智能体/API 唯一数据源）

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `result_id` | str | min_length=1 | uuid4（= report_id） |
| `sample_id` / `scan_ids` | str / list[str] | — | 溯源 |
| `beans` | list[PairedBean] | — | 逐粒 |
| `measurements` / `grading` | C2.5 / C2.6 | — | 计量/定级 |
| `agent_report` | AgentReport \| None | — | 溯因（None 合法） |
| `timings_s` | dict[str,float] | — | 各阶段耗时；**护照前定型**（护照耗时单列，防校验和脱钩） |
| `pipeline_versions` | dict[str,str] | — | 如 `{"segment":"classic","classify":"rules_v0","agent":"template","standard":"cqi_fine_robusta"}`；固定键：calibration=aruco4:v1 / pairing=hungarian:v1 / metrology=measure:v1 / report=passport:v1 |

**BatchResult 三重一致性不变式**（model_validator，违规即 ValidationError）：
① `grading.defect_counts` == 逐粒 `final_defect` 直方（校验器内部按 include_normal=True 取全直方，schemas.py:530-542；非 normal 键双向强制，normal 键可省、写则必校）；
② `primary_count/secondary_count` == 豆列表按 taxonomy 主/次归属分计（不可计类不计）；
③ `measurements.bean_count` == `len(beans)`。

## C3 护照 schema（PassportReport）

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `report_id` | str | min_length=1 | 与 `result_id` 绑定 |
| `langs` | list[zh/en/vi] | min_length=1；**不得重复** | 生成语言 |
| `html_paths` | dict[str,str] | — | lang→文件路径（实现取绝对路径 posix，契约偏差已注记） |
| `qr_payload` | str | min_length=1 | `{verify_base_url}/r/{report_id}|{sha256}` |
| `sha256` | str | `^[0-9a-f]{64}$` | sha256(canonical_json(BatchResult))；规范化=键排序+紧凑分隔+ensure_ascii=False |

字段级语义、页面区块、QR 渲染参数与端点交付见 [passport spec](specs/passport.md)。
溯因侧 `AgentReport{lang, causes[], advice[], citations[], backend∈template/llm}` 与
`CauseItem{defect(taxonomy 校验), stage∈五环节中文名, likelihood, evidence_summary}`
见 [rootcause-kb spec](specs/rootcause-kb.md)。

## C4 lab8 单一标度契约（计量最大坑的契约化）

- 全链路 `color_lab`/`color_lab_mean` **唯一标度 = OpenCV 8-bit LAB（lab8）**：三通道一律
  [0,255]（L×255/100，a/b 整体 +128）；构造期拒绝越界（CIE 负 a/b 混入会把 ΔE 放大）。
- CIE 量纲只存在于两处：标准 YAML `reference_lab`（loader 按 CIE 解析、`reference_lab_scale`
  可声明 lab8 加载期归一）与 ΔE 计算过程（`lab8_to_cie` 仿射后计算）。互转唯一实现在
  `beaneye/metrology`（lab8↔CIE 逐通道仿射，加权平均两标度可交换）。

## C5 裁决与计数契约（M7 与契约校验器逐位一致）

- 裁决：rank 高者胜；平级取 conf 高并记 `worst_side="both"`（conf 完全相等偏向 top）；
  单面取另面；两面皆 None → ("normal","none")（M7 明细版 `worst_detail` 全取值
  `winner_side="none"/winner_conf=None/tie=False`，adjudicate.py:185-186）；
  **非可计缺陷类（counts_as_defect=false，peaberry）不参与比较**（存在可计面时只在可计面间
  裁决；皆非可计退回全量，标注不丢）。rank 一律按当前生效序**现场查找、无缓存**
  （`SeverityOrder.rank`/`Taxonomy.severity_rank` 皆每次现查）；观测上的 `severity_rank`
  是冻结存储字段而非缓存，换序后必须经 `rebase_observation` 改写为当前序位次
  （`adjudicate_pairs` 内置），否则契约校验器（比存储字段，schemas.py:257）与 M7 现查
  （adjudicate.py:211）可能分歧。
- 计数：`most_severe_per_bean`——每粒只按 `final_defect` 计一次；`defect_counts` 直方即
  BatchResult 不变式①；主/次分计 peaberry 不计。契约 `defect_counts_from_beans` 与
  M7 `count_defects` 独立双实现 + eval 交叉验证；两处 `include_normal` **缺省均 = False**
  （normal 不入直方，normal 键口径见不变式①）。主/次分计按 taxonomy `kind` 归属：
  primary 5 类（insect/dried/sour/mold/black）+ secondary 可计 6 类，peaberry
  （`counts_as_defect=false`）剔除——**逐类 primary/secondary 归属与 counts_as_defect
  全表唯一权威 = 契约附件 `configs/taxonomy.yaml`**（快照表见
  [severity spec §2](specs/severity.md)）。
- severity_order 契约：`[0]` 恒 normal（rank 0），缺陷类 rank>0；taxonomy 默认序与标准
  YAML 覆盖序（须全排列）见 [severity spec](specs/severity.md)。

## C6 可复现与确定性契约

- Mock 采集：`default_rng([seed, frame_idx])`，同 seed 同帧序**像素级一致**；
  `captured_at` 带时区但不进像素流。
- bean_id 稳定序（锚定质心 (x,y)+obs_id 兜底）→ 同输入同输出。
- 合成器（M12 在飞）契约：固定种子像素级复现；真值 manifest 可再驱动（REGENERATE §5）。
- 护照：同 BatchResult → 同 sha256 → 同 QR；占位图 sha256 派生、同输入像素级一致。
- LLM 不确定性被模板保底兜住：`backend` 字段显式标注本次来源。

## C7 eval 契约（裁定规则）

- 通过线唯一裁定 = **真实运行**：每模块 `pytest tests/test_<pkg>.py -q` + 三道门
  （gate_d1/d2/d3，任意 cwd，内部自定位仓库根与 .venv）。
- 纪律：skip 不是 pass；门禁入口缺失=FAIL；中性名扫描产品面零豁免（上游代号只存在于
  不入库内部文件）；禁止 IO 静态扫描（cv2.imread / cv2.imwrite / np.fromfile 直传路径
  三种形态）；**已知失败必须如实标注状态**（本包 manifest「冻结·已知回归」用法）。
- 数字口径纪律：合成夹具上的精度数字（0.41mm、P/R 0.989…）是检测/配对残差与管线
  自洽性数字，**D7 真机标定前不得对外引用为现场精度**（docs/calibration-error-budget.md）。

## C8 命名与红线（公开仓纪律）

- 产品名 BeanEye（啡眼）；上游数据集/模型/工具一律中性内部名（beaneye-det / beaneye-mat /
  beaneye-slice / beaneye-review / beaneye-aug 中性名族）；素材来源原标签→本体系 key 的
  映射只允许存在于 `configs/upstream_mapping.internal.yaml`（gitignore）。
- 图像 IO 红线：只走字节缓冲封装（坑 1）；AGPL 件零引入（钉版红线见 requirements.txt 头注释）。
- 凭据零入库；数据与模型目录 gitignore。

## 已识别契约痛点（变更候选——待规划方批准，批准前实现不得擅改）

| # | 痛点 | 影响 | 变更候选 |
|---|---|---|---|
| 1 | `SegModel.predict(img_rgb, scan)` 不携带 side | 装配器只能每面各调一次再规范化（side/scan_id/mask_id 重键），实现方易踩 | v2 给 predict 增加 side 参数或改签名 `predict(img_rgb, side, scan)` |
| 2 | `count_rule: per_side` 可通过加载、evaluate 才报错 | 配置作者到运行期才发现不支持 | 加载期即拒绝 per_side，或在契约层支持 per_side 计数（需同步改 BatchResult 不变式①） |
| 3 | 标准 YAML `reference_lab` 行内注释写"0-255 标度"，loader 实际按 CIE 解析 | 文档误导配置作者（数值本身是 CIE，负 a/b 不可能为 lab8） | 清理三份 YAML 注释（文档修复，无行为变更） |
| 4 | pairing 密排构型 3 例统计用例在随机源切换（943d8cc）后跌破回归下限 | gate_d2 ②③ 持续 FAIL，掩盖真回归 | M6 属主二选一：改算法（点阵构型去锁模）或按新随机流重新钉场景/通过线（附数据依据） |
| 5 | `PassportReport.html_paths` 实现取绝对路径 | 产物目录不可整体搬移 | 契约明确为相对 out_dir 的相对路径并迁移消费方 |
| 6 | LLMAgent 的 response_format 支持探测=响应体子串匹配 | 个别网关错误文案不含该词时多打一轮请求（有兜底，不阻塞） | 记录为已知边界；或按状态码+JSON 解析失败统一判"不支持" |
| 7 | `SynthSource` 占位、`synth` JSON 请求回退 MockSource | 演示盘面是程序化合成而非素材库真实缺陷豆（响应已注明降级） | M12 落地后接线 SynthSource，回退路径保留为显式降级语义 |

## 版本与变更流程（冻结）

- **版本锚**：`SCHEMA_VERSION = "1.0"`（v1.1 只增 warnings，历史兼容）；taxonomy `version: 1`；
  根因知识表 `version: 1`；合成配置 schema `version: 1`（在飞）；app `version "0.1.0"`。
- **谁批准**：本页 C1–C8 与痛点候选变更由规划方/仓库 owner 批准；实现者不得单方面变更
  （契约只增不改名；发现契约问题上报）。
- **怎么广播**（每次契约变更必须全做）：
  1. 更新本页对应小节 + 受影响 specs/* + 契约附件（taxonomy/标准 YAML/根因知识表）；
  2. 契约校验器与消费模块同步改，fixtures 按需再生成；
  3. 三道门 + 全套件复跑（稳定树上）全绿（或如实登记新的已知状态）；
  4. 单独 commit（`contract-change:` 前缀），版本锚递增（破坏性变更进大版本）。
