# HN-Robusta 自建集采集协议（v0.1）· docs/collect_protocol.md

> 版本：v0.1（2026-09-29，W12 批次交付） · 适用：啡眼 BeanEye 项目
> 数据主叙事：**HN-Robusta 自建集**（海南罗布斯塔生豆）。本批（W12）素材
> 走程序化生成（`beaneye/synth/`），本协议规定生豆到货后如何把真实豆
> 采集、掩码化、入库为 v0.1 数据集，供阈值回填（D7）、真实盘全链验收
> （D8）与计量系数标定使用。

---

## 1. 目的与范围

- 程序化素材（W12a）解决「有数据可用」，自采集解决「数据可信」：
  真实豆的纹理/色差/缺陷形态用于校准规则分类器阈值与人工核对口径。
- v0.1 范围：生咖啡豆（未烘焙），13 类 = `configs/taxonomy.yaml` 全部
  类别（好豆 + 12 缺陷类），**类别键一律用内部 taxonomy key**（normal /
  black / mold / …），不带任何外部数据集标签。
- 到货生豆按本协议「先分堆、后拍照、再抠掩码、终入库」四步走。

## 2. 到货分堆（人工，依据 NY/T 1519 缺陷图谱）

1. 以 **NY/T 1519（生咖啡 / 缺陷图谱）** 为对照图谱，肉眼分拣：
   每堆一个类别（含 `normal` 好豆堆）；类别归属拿不准的粒子单独放
   「待议」堆（拍照留档，**不入 v0.1**，由第二人复核后归堆或剔除）。
2. 主/次归属以 `configs/taxonomy.yaml` 的 `kind` 为准（black/mold/sour/
   insect/dried=主缺陷，其余=次缺陷）；图谱与 taxonomy 冲突时记录在
   `meta/disputes.md`，不动 taxonomy（契约冻结）。
3. 每堆清点粒数，记入 `meta/sorting_log.md`（堆名/粒数/分拣人/日期）。
   每类有效样本 **≥20 粒**为入库门槛（不足的类在 manifest 标 WARN，
   只用于人工核对，不用于阈值回填）。

## 3. 拍摄规范（含光照/背景/分辨率红线）

### 3.1 器材与机位

- 相机/手机均可，**三脚架垂直俯拍**：传感器平面尽量平行盘面（倾角 ≤5°，
  用水平仪或取景框对边平行核对）；单一机位全程不动。
- 到位的双面拍摄台可用后，top/bottom 各拍一遍（`side` 字段区分）；
  台未到位前先采单面（top）。

### 3.2 光照（红线）

- **均匀漫射光**：两盏灯对称 45° + 柔光罩/硫酸纸柔光；严禁单侧直射
  （强阴影/高光斑会破坏阈值分割与色差计量）。
- 相机**手动模式**：固定白平衡、固定曝光、关自动增益；同一批所有照片
  同一套参数（记入 meta）。
- 环境光稳定（白天拉帘/夜间拍摄），避免频闪。

### 3.3 背景

- 浅色亚克力板或白卡纸（与合成配置 `configs/synth.yaml`
  `render.background_bgr` 同款浅灰，RGB≈(208,203,200)）；
- 豆粒**单层平铺、互不接触**（分割友好模式）；每堆另拍 1 张自然散铺照
  （密度参考，不入掩码流程）。

### 3.4 分辨率（红线）

- 成像 **≥ 20 px/mm**（即 ≤0.05 mm/px）：4K（3840×2160）拍 ≤190mm 视场
  即达标；JPG 质量 ≥90 或直接 PNG。
- 每批拍 1 张**标定参照物**（钢尺/打印的 ArUco 板，见 3.5）用于实测
  px_per_mm。

### 3.5 标定参照

- 盘面四角贴 ArUco 打印板（`scripts/make_aruco.py` 产物，布局 =
  `configs/tray.yaml`），整盘照直接走 M3 自动标定（px→mm）；
- 单粒特写照不贴码，用同视场钢尺照换算并记入 meta 的 `px_per_mm`。

### 3.6 文件命名与元数据

```
hnrb/<class>/<class>_<yyyymmdd>_<seq>.png     # 单粒照（mask 友好模式）
hnrb/<class>/<class>_<yyyymmdd>_<seq>_pile.png  # 整堆散铺照
```

每张单粒照配一条 meta（见 §5.3 字段表）；拍摄当日回填，不补记。

## 4. 掩码提取（自动出掩码 → 人工复核）

1. **自动路线（优先）**：LAB b 通道/灰度 Otsu 前景 → 开闭运算 →
   连通域；粘连用分水岭切分（与 M4 ClassicSeg 同参数系，
   `configs/segment.yaml`）。逐图输出二值掩码（8-bit {0,255}）。
2. 自动失败（低对比/粘连切不开/阴影粘连）：人工在标注工具里修正多边形
   （未来接入自研交互分割模块 `beaneye-mat`；任何外部工具导出先转成
   本仓掩码格式再入库）。
3. **一致性核对**：每图掩码数 == 豆数；掩码面积中位数偏离堆均值 ±40%
   的粒子标记复核。
4. 抽检：每类随机 10% 人工目检掩码 IoU（对照手工勾画），**≥0.95** 方可
   入库；不合格图整张重做。

## 5. 入库格式（HN-Robusta v0.1）

### 5.1 目录结构

```
data/datasets/hn_robusta/v0.1/
├─ images/<class>/*.png          # 原图（命名见 3.6）
├─ masks/<class>/<同名>.png      # 8-bit 二值掩码
├─ meta/<图 stem>.json            # 逐图元数据
├─ manifest.json                  # 数据集清单（版本/计数/哈希）
└─ ../disputes.md sorting_log.md  # 放 meta/ 下
```

数据文件不入 git（`.gitignore` 已覆盖 `data/`）；`manifest.json` 与
本协议随仓（哈希清单使数据可校验、可复现）。

### 5.2 manifest.json 字段

```json
{
  "dataset": "hn_robusta", "version": "0.1",
  "created_at": "<ISO8601>", "taxonomy_sha256": "<taxonomy.yaml sha>",
  "counts_per_class": {"normal": 120, "black": 35, "...": 0},
  "files": [{"path": "images/black/black_20261005_001.png",
             "sha256": "...", "mask": "masks/black/...png", "meta": "meta/...json"}],
  "license": "self-collected (项目自有，无第三方素材)",
  "warnings": ["immature 样本 <20，仅人工核对用"]
}
```

### 5.3 逐图 meta 字段

| 字段 | 说明 |
|---|---|
| class | taxonomy key（分堆堆名） |
| side | top / bottom |
| captured_at | ISO8601 |
| device | 机型/镜头 |
| resolution_px | [w, h] |
| px_per_mm | 实测（标定参照物换算或 M3 标定结果） |
| lighting | 白平衡/曝光/灯位摘要 |
| operator | 分拣/拍摄/掩码复核人 |
| mask_source | otsu_auto / watershed_auto / manual_fix |
| qc | {iou_spot_check: 数值或 null, pass: bool} |

## 6. 质量门槛与红线

- 每类 ≥20 粒有效样本（门槛不足 → WARN，不入阈值回填）；
- 掩码抽检 IoU ≥0.95；色差计量用粒需无反光斑；
- **holdout/golden 永不入训练**（工程纪律红线）：v0.1 全量只用于评测/
  阈值回填，任何训练集划分在未来版本另行声明；
- 自采数据项目自有，公开分发前脱敏（不含人名/位置，operator 字段公开版
  以代号替换）。

## 7. 版本与回灌路径

- v0.1 冻结后只增不改（修订进 v0.2，manifest 递增版本号）；
- 回灌三用途：
  1. **D7 阈值回填**：`configs/rules_v0.yaml` 按真实 LAB 分布调规则阈值；
  2. **D8 评测**：真实豆盘对照合成盘跑全链，人工用时与逐豆一致率对比；
  3. **计量标定**：蓝牙秤实测粒重 → 回填标准 YAML `weight.g_per_mm2`；
- 与合成引擎的关系：`beaneye/synth/` 的类画像（`CLASS_PROFILES` 颜色/
  几何范围）在 v0.1 入库后按真实分布**校准一次**（记入提交信息），使
  合成盘与真实盘分布对齐。
