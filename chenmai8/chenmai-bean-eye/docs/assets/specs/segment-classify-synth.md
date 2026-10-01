# M12 合成 + M4 分割 + M5 分类 合并 spec（segment-classify-synth）

> 状态：三模块均已落库**冻结**（四入口 `tests/test_synth.py` / `tests/test_segment.py` /
> `tests/test_oracle.py` / `tests/test_classify.py` = **74 passed**（23+23+9+19）exit 0；
> 2026-09-30 处置复跑 216.25s、资产漂移回填批同日独立复跑 82.69s/98.55s/101.61s/158.91s
> 逐入口 23/23/9/19 passed，acc 0.7712 / normal 召回 0.95 实读
> `out/eval/classify_report.json` 复核一致；全套件 508 passed）。
> 本页对照已落库代码（`beaneye/synth/`、`beaneye/segment/`、`beaneye/classify/`）、
> 三份配置（`configs/synth.yaml`、`configs/segment.yaml`、`configs/rules_v0.yaml`）
> 与四个测试文件 docstring 提炼于 2026-09-30，为三模块的**合并再生 spec**
> （资产包首版仅覆盖 7 个旧模块，本页补齐 D4 批缺口——见 manifest 变更史）。
> **first-draft：以代码为真相写出，未经盲重生成验证**——本页尚未经「只凭 spec 盲再生
> 三模块」回验；发现 spec 与代码漂移时，以代码为真相修订本页。
> 逐行精读级别低于首版 7 张 spec：以「接口签名 + 契约语义 + 验收线 + 已知坑」为纲，
> 实现细节以代码与提交注记为权威真源。

---

## 1. M12 合成数据引擎（`beaneye/synth`）

### 1.1 职责与边界

程序化生成合成训练/评测数据：**无外部数据集路径**，素材全程序化生成；
真实数据主叙事走自建集（`docs/collect_protocol.md`，生豆到货后启用）。
三子模块：`beans.py`（素材）、`compose.py`（铺盘）、`config.py`（配置）。

### 1.2 公开接口（冻结）

| 入口 | 签名要点 | 语义 |
|---|---|---|
| `sample_library(seed, per_class)` | 每类 ≥20 固定变体（缺省 24），不足拒收 | 变体参数由 `default_rng([seed, cls_i, var_i])` 逐字段确定性生成；`CLASS_PROFILES` 覆盖 taxonomy 13 类（长轴/长宽比/CIE L\*a\*b\* 范围/轮廓波纹/虫孔避让/斑块/弦切/空腔弧/纵皱纹） |
| `sample_spec(library, cls, seed, ...)` | 变体内连续参数抖动 | 只动几何/颜色/孔斑位置等连续量，**形态档位不漂移** |
| `render_sprite(spec)` | RGBA + 二值 alpha | **alpha 即真值轮廓**（`fillPoly` 直出；虫蛀孔不透底、重叠压粒不剔轮廓）；颜色链 CIE→`metrology.cie_to_lab8`→`LAB2BGR` 与 M8 同标度 |
| `compose_tray(seed, *, config=None, library=None)` | → `SynthTray` | 拒绝采样自由摆放（中心距 >`free_factor`×两豆长半轴和，恒不相交）+ 接触/重叠目标摆放（中心距=`overlap_depth`×半径和，必相交）+ 四角码区（码+1/4 静区）矩形避让 + 盘缘 4mm 墙距；渲染含亚克力底噪/斜向光带/逐豆投影阴影/四角 ArUco/gamma/增益/暗角/颗粒 |
| `labels_to_json(tray, *, with_rle=True)` | M1 兼容逐粒标注 dict | 多边形/面积/质心/外接框**先按 3 位小数取整再计算**——JSON 往返后重算恒等（字节级复现与真值一致性检验的共同根）；`rle_top/rle_bottom` 在托盘 mm 网格上由**同一取整多边形**栅格化：解码掩码与按标注多边形自栅格化**逐字节一致** |
| `write_batch(tray, out_dir, *, index=1)` | 四件产物 | `top_NNNN.png` / `bottom_NNNN.png` / `labels_NNNN.json` / `manifest_NNNN.yaml`；manifest 与 `configs/synth.yaml` 同 schema（记录 seed+config+文件清单），回读 `load_compose_config` 后同 seed **字节级复现本批** |
| `load_compose_config()` / `config_to_dict` | 严格校验 | 未列出的键拒绝；坏类权重/区间矛盾拒绝，错误带路径 |

### 1.3 契约语义

- **成对真值**：top/bottom 共享同一布局坐标与 bean_id；bottom 面素材重采样同类另一变体
  但几何（长轴/长宽比/弦切比例）取 top——弦切比例若独立重采样会破坏配对真值
  （弓形质心横移实测 3.2mm，已修）；`mirror_bottom` 时 bottom 朝向取镜像角。
- **托盘几何不进合成配置**：单一真源 `configs/tray.yaml`（合成、打印板、标定三者同源）。
- **确定性**：全部随机性 `default_rng([seed, stage])` 派生，产物零墙钟时间。
- **真值口径**：合成盘上的全部精度数字是管线自洽数字，不是现场检测精度
  （`docs/calibration-error-budget.md` 口径纪律）。

### 1.4 eval 与通过线

`python -m pytest tests/test_synth.py -q` → **23 passed**（2026-09-30 实测）：
类画像 13 类齐全/每类 ≥20 变体/库种子逐字段复现/13 类渲染互异；RLE 解码==标注多边形
自栅格化逐字节（逐粒双面全查）+ 解析字段恒等 + sprite↔mm 网栅格 IoU≥0.80；接触/重叠
目标与凸包相交复核一致；同种子图像 array_equal、labels 字节相等、write_batch 四件产物
字节级一致、异种子必异；manifest 回读→同 seed 字节级复现；配置严格校验；labels 直构
`BeanMask(oracle)` 过 M1 契约往返。

## 2. M4 分割（`beaneye/segment`）

### 2.1 双实现与装配约定

| 实现 | 定位 | 关键语义 |
|---|---|---|
| `ClassicSeg` | **产品缺省**（`build_default()` 返回它） | 从标定 warp 后正射网格逐粒出 `BeanMask(source=classic, conf=0.9 单峰/0.72 切分)` |
| `OracleSeg` | **评估专用**合成盘黄金分割器 | 合成 manifest 真值透传：top 逐字段恒等、bottom 按 M12 成对语义由真值多边形解析重算；`source=oracle → conf 恒 1.0`（契约强制）；对非合成盘抛 `OracleSegError`（宁缺毋错） |

协议：`SegModel.predict(img_rgb, scan)` 不携带 side——**同实例不可两面共用**，
按面各备实例（`side` 属性 / `masks_for(side=…)`）；`mask_id` = 质心 (y,x) 排序后
`{side}_{i:04d}`。M13 装配器探测 `<pkg>.build_default(**kwargs)` 零改动接线；
缺位时 `NullSegModel` 显式降级（0 检出 + degraded_stages 标注）。

### 2.2 ClassicSeg 算法（参数系冻结于 `configs/segment.yaml`，W4b 验收）

① 四角码区（`mask_markers`+`marker_margin_mm`）以全图中位数回填后再阈值——码暗区会拖歪
全局 Otsu；② 阈值 = min(Otsu, 边框带中位数背景估计 − `bg_delta_gray`)——背景锚定防亮于
盘面的印刷物把 Otsu 抬到背景之上（极性自检反转、只剩亮斑豆全丢）；③ 开 3 闭 5 形态学；
④ 连通域：`min_area_mm2` 6、单域占比 >`max_component_frac` 0.5 视为阈值病理跳过；
⑤ 逐域精确距离变换 + 3px 窗局部极大 + 小半径并簇 + 种子支配度过滤（浅峰=粘连颈部鞍点
删除，邻豆等深互不抑制）；⑥ `watershed`（域外环带=确定背景）切分；切分退化/单种子整域
输出。全部几何参数以 mm 给出、运行期按 mm/px 换算（改网格分辨率不动配置）。

### 2.3 OracleSeg 真值注册

三来源：labels dict / JSON 文件路径（`from_batch_dir` 扫 write_batch 产物）/ 内存
`SynthTray`（`from_tray` 免落盘）；`scan_id` 重复注册拒绝；`entry(scan_id, mask_id)`
O(1) 回查该粒 bean_id/类别真值（e2e 真值核对约定）。栅格口径 `truth_rasters()` 优先
解码逐粒 RLE、缺 RLE 回退多边形自栅格化（两表示等价）。

### 2.4 已知短板与口径（如实记录）

- 深度重叠（>~60%）共用深峰切不开（§9 风险表已知项）；
- **真实合成盘上**：真值 IoU≈0.63、掩码外扩约 56-67% 真值面积（投影阴影+亮亚克力底
  渗入）——污染下游 LAB 特征，是产品链分类一致率低的根因之一（§3.3 口径）；
- 对照报告 `out/eval/oracle_vs_classic_report.json`（top mean IoU 0.6261 / bottom
  0.5455）如实记录；classic 通过线任务书未给，评测侧 0.60 配对率 / 0.40 平均 IoU 为
  保守护栏。**改进归 classic 参数调优 / NN 路线，不擅调 W4b 已验收参数。**

### 2.5 eval 与通过线

- `python -m pytest tests/test_segment.py -q` → **23 passed**（2026-09-30 实测）：
  简化夹具（`tests/_segment_synth.py`，W12 就绪前替代并注明）稀疏盘 40 粒全路径
  粒数误差 0%（≤5% 线）、平均 IoU 0.961（最小 0.880，≥0.85 线）、predict ≤5s（2048²
  管线实际输入口径）；接触对分离召回 9/12=0.75（≥0.70 自定线）；边缘豆/角码盘/空盘/
  契约往返/确定性/工厂接线/14 类非法配置拒绝。
- `python -m pytest tests/test_oracle.py -q` → **9 passed**（2026-09-30 实测）：
  真值透传（top 恒等 / bottom 解析重算 + 两面面积一致性 ≤5%）；栅格 IoU=1.0 双面全查
  （实现为逐字节相等，强于线）；索引/错误面；契约 JSON 往返；确定性；M13 注入不降级；
  mask_id→真值 O(1) 回查。

## 3. M5 分类（`beaneye/classify`）

### 3.1 RulesV0 裁决语义（冻结协议 `ClsModel.classify(crop_rgba, mask) -> (defect, conf, rank)`)

规则表 `configs/rules_v0.yaml` 逐条评估：全部 `when` 条件 AND 命中即命中；
**多规则命中取 severity 高者**（rank 从 taxonomy 现查，单一真源）、平级取 conf 高；
无命中 → normal（conf=`defaults.normal_conf`，rank=0）；特征提取退化（空 crop 等）→
normal、conf 0——分类器自身绝不抛异常阻塞管线（管线另有 `_validate_cls_output`
契约校验）。`explain()/decide_features()` 为评测扩展入口，裁决路径与 `classify` 同一。

### 3.2 特征与阈值（阈值即数据）

特征面：LAB 统计（均值/分位差/亮斑/暗斑比）、几何（圆度/长宽比/eq_d/直边段）、纹理、
孔洞（带受蚀亮圈孔计数）、色差（对 black/premium 两 CIE 参考点 ΔE76）。全部类别知识
只在 `rules_v0.yaml`（代码零类别阈值）；阈值按 4 个开发种子基础（52 盘）逐粒特征
pooled 分布 p05/p95 标定，**D7 真实豆照片回填只改此文件**（`docs/collect_protocol.md`
回灌约定）。交叉防护显式写在规则条件里（dried/broken 互斥、mold 排虫孔亮缘、
shell 排亮斑底、immature 三重收紧等，见 YAML 头注释速记表）。

**area_ratio 滚动窗口语义（CONTRACTS 痛点 #8）**：`area_reference` 取前 `area_window`
粒面积中位数为参考、不足 `area_min_ref` 时该特征恒 -1（引用它的规则静默不命中）——
分类结果依赖调用顺序，单粒零散调用/换盘行为不同；这是**记录在案的行为**而非缺陷，
评测按整盘顺序调用。并行化/NN 腿接入前改为请求级批参数或显式注入。

### 3.3 口径声明（必须随数字出现）

acc **0.7712**（≥0.75 线）为 **oracle 掩码口径**（真值掩码 = 上界）。产品链
classic 掩码下逐粒 final 一致率仅 ~0.034（合成盘 e2e 如实记录于
`out/e2e_synth/summary.json`；根因 = classic 掩码外扩污染 LAB 特征 + mold 亮斑规则
`l_p95_minus_p50≥26` 被背景像素顶爆，单盘 mold 误报 61-81 vs 真值缺陷 1-8）。当前
**无任何门禁把分类质量设为硬线**（e2e 只将一致率列为如实记录）——对外定位
「**AI 初检 + 人工复核**」，改进路径登记 `docs/assets/feedback.md`（D7 前置）。

### 3.4 eval 与通过线

`python -m pytest tests/test_classify.py -q` → **19 passed**（2026-09-30 实测）：
26 评测盘 896 粒（每缺陷类 ≥30 粒配额 + 正常盘），**生产同路裁剪**（compose→
`calibrate_pair`→`warp_to_tray`→真值 BeanMask→M13 同款 crop 提取，与管线逐字节同构）；
acc ≥0.75、normal 召回 ≥0.95、混淆矩阵落盘 `out/eval/classify_report.json`、16.4ms/crop；
**验收种子不参与阈值标定**。全绿但 0.7712 靠近下沿——阈值回填前不得上调宣传。

## 4. 全链 e2e 与门

- `scripts/e2e_synth_run.py`（缺省 3 盘）走 `beaneye.app.pipeline.run_pipeline` 与 API
  完全同一条装配路径；硬断言：装配非降级 / px_per_mm 误差 ≤2% / 重投影 ≤1.5px /
  配对粒数 ≥真值 50% / bean_count==配对数 / 三语护照 >20KB + QR 解码回读一致；
  如实记录不作硬线：粒数恢复率、逐粒标签一致率、defect_counts vs 真值直方、逐阶段耗时。
- `scripts/gate_d4.py` 四门项：全量 pytest 全绿 / e2e 缺省 exit0 / gate_d3 原样回归 /
  中性名扫描零命中（import 复用 gate_d3 模式表，单一事实源）。
- 评估口径演示件：`scripts/smoke_synth_chain.py` 用真值观测直出（分类全对）——**评估
  口径非产品链**，演示使用必须明示。

## 5. 再生顺序与依赖

```
M12 synth(11) ──► M4 segment(12) ──► M5 classify(13) ──► e2e(14) ──► gate_d4
（M4/M5 经 M13 装配器 build_default 工厂自动接线进产品链）
```

再生顺序 = 上表步号；每步验收命令见 [REGENERATE §2 步骤 11-14](../REGENERATE.md)。
