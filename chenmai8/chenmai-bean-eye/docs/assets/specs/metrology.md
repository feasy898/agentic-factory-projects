# M8 计量 spec（metrology · 公式与标度）

> 状态：冻结（31 用例全绿，2026-09-29 实测）。
> 本页对照 `beaneye/metrology/core.py` / `config.py` 逐行核验于 2026-09-29。
> 定位：把逐粒几何/颜色聚合为整盘 `Measurements`——定级（M9）与护照图表（M10）的直接输入。

---

## 1. 规范入口与边界

```python
measure(beans, calib, std_yaml) -> Measurements   # 契约签名
# beans: M6 配对后的 PairedBean 列表（每粒已带两面 mm 几何 + lab8 颜色）
# calib: CalibResult | None —— v0 仅类型校验透传（计量全部消费已变换 mm 几何，无需像素换算）
# std_yaml: 标准 YAML dict / 路径 / None=契约模板默认；本模块只读 metrology/weight 两节
```

两面皆 None 的占位 `PairedBean`（契约允许、正常配对不会产出）不进任何统计，`bean_count` 也不计。
`config` 参数为可选直注入口（优先于 std_yaml，复用已加载配置）。

## 2. 公式表（全部写死在 core.py，便于验收复核）

### 2.1 粒径与目数

| 公式 | 实现 | 说明 |
|---|---|---|
| 每粒等效直径 | `d = mean(两面 eq_diameter_mm)`，单面取该面 | `_bean_diameter` |
| 筛目 | `screen = floor(d / 25.4 × 64 + 0.5)` | **round-half-up（.5 进位）**，非 Python 内建 round 的银行家舍入——仅恰在 .5 时有差，已注记 |
| 筛号→孔径 | `screen_mm(n) = n × 25.4 / 64` | 供筛孔对照表 |
| 直方键 | `sieve_hist` 键=目数**字符串**（如 "16"），按数值升序 | M9 筛目判定按 `int(key)` 解析，非整数字符串抛 `StandardsError` |
| sieve_pass | `低于 min_screen 的粒数占比 ≤ max_below_frac` | 无筛目目标（`min_screen=None`）或空盘 → `None`（不判定，**None 不是通过**） |

### 2.2 色差（两套标度，最大的坑）

| 公式 | 实现 | 说明 |
|---|---|---|
| lab8 → CIE | `(L×100/255, a−128, b−128)` | `lab8_to_cie`；OpenCV 8-bit LAB 三通道一律 0-255 |
| CIE → lab8 | 上述逆（L×255/100, a+128, b+128） | `cie_to_lab8` |
| 两面合并 | `w×top + (1−w)×bottom`，w：severity 高侧 **0.7** / 平级 0.5 / 单面全占 | `merge_sides_lab`；lab8→CIE 是逐通道仿射，**加权在两标度上可交换**（先合并后换算等价） |
| ΔE | `ΔE76 = ‖Lab_merged(CIE) − Lab_ref(CIE)‖₂` | `delta_e_cie76`；v0 明确不宣称 ΔE2000（留升级位） |
| 输出标度 | `color_lab_mean` = **lab8**（与逐粒同标度可对照）；`delta_e_mean`/`delta_e_hist` = CIE 单位 | 契约构造期拒绝 CIE 负值混入 color_lab（把 ΔE 直接放大） |
| 直方分桶 | 2 ΔE 一桶：`"0-2","2-4",…,"18-20"`，≥20 进开口桶 `"20+"` | `_delta_e_bucket`；`DELTA_E_BUCKET_WIDTH=2.0` |

**契约附件的标度注记**：标准 YAML 的 `reference_lab` 由 loader 按 **CIE 标度**解析
（`reference_lab_scale` 默认 `cie`，可显式声明 `lab8` 加载期归一 + 量程校验 L∈[0,100]、a/b∈[-128,127]）。
已知瑕疵（如实记录）：三份标准 YAML 的行内注释写「0-255 标度」与 loader 实际口径（CIE）矛盾
——数值 `[55,-12,22]` 本身是 CIE 标度（a/b 为负在 lab8 里不可能），以 loader 口径为准，
注释属待清理项。

### 2.3 估重

| 模型 | 公式 | 系数来源 |
|---|---|---|
| `area_linear`（默认） | `Σ 每粒面积 × g_per_mm2` | 标准 YAML `weight.g_per_mm2`（默认 0.00042，**到货蓝牙秤标定回填**） |
| `area_thickness` | `Σ 每粒面积 × thickness_mm × g_per_mm3` | 默认 thickness 3.5mm / g_per_mm3 0.0011 |

- 每粒面积 = 两面 `area_mm2` 均值（单面取该面）；`weight_model` 记 `"<model>:v1"`；未知模型拒。
- 加载期校验：三系数都必须 >0 有限数。

## 3. 模板默认值表（std_yaml=None 时；标准 YAML 同名键覆盖）

| 键 | 默认值 | 位置 |
|---|---|---|
| `metrology.reference_lab` | `(55.0, -12.0, 22.0)`（CIE；精品罗豆参考色，verified:false 占位） | config.py `DEFAULT_REFERENCE_LAB` |
| `metrology.sieve_targets.min_screen` | `13` | `DEFAULT_MIN_SCREEN`（显式 null = 不做筛目判定） |
| `metrology.sieve_targets.max_below_frac` | `0.0`（全部豆 ≥ min_screen 才算过） | `DEFAULT_MAX_BELOW_FRAC` |
| `weight.model` | `area_linear` | `WEIGHT_MODELS` |
| `weight.g_per_mm2` | `0.00042` | `DEFAULT_G_PER_MM2` |
| `weight.thickness_mm` | `3.5` | `DEFAULT_THICKNESS_MM` |
| `weight.g_per_mm3` | `0.0011` | `DEFAULT_G_PER_MM3` |
| 空盘 | stats 全 0 / `color_lab_mean=(0,0,0)` / `delta_e_mean=0` / hist 空 | `measure` 空盘分支 |

## 4. eval（2026-09-29 实测）

```bash
python -m pytest tests/test_metrology.py -q
# → 31 passed
# 通过线（用例内固化）：已知半径合成圆（cv2 渲染→px_per_mm 换算）直径误差 ≤0.92%（线 2%）；
#   手算筛号表 + 阈值两侧点 100%；ΔE 手算字面量（sqrt17/sqrt800/sqrt153）精确一致 +
#   cv2 LAB8 往返偏差 ≤1.0；标定残差 +1% 场景估重误差 ~2%（线 15%）；350 粒盘 3.6ms（线 2s）
```
