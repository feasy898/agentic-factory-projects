# M3 标定 spec（calibration · 码位几何单一真源表）

> 状态：冻结。本页对照 `beaneye/calibration/`（core.py / config.py）、`configs/tray.yaml`、
> `beaneye/acquisition/mock_source.py`、`scripts/make_aruco.py` 逐行核验于 2026-09-29。
> 定位：全链路毫米坐标系的根——没有标定，一切 mm 口径（目数/配对门限/估重面积）都是空谈。

---

## 1. 职责与边界

**做**：整盘图上检测四角定位码 → 原图像素到盘面毫米的平面单应 `H` → `warp_to_tray` 输出
2048² 正射网格（≈0.1465 mm/px）+ `px_to_mm`/`mm_to_px` 逐点变换；双面各解一次组装契约
`CalibResult`（由 M2 写入 `TrayScan.calibration`）。

**不做**：镜头内参/畸变标定（平面单应即完整平面姿态，规格走 findHomography 路线）；
单码姿态兜底（<4 码直接抛错，现场摆正重拍——v1 裁决）；亚克力折射/反光补偿
（现场误差预算见 `docs/calibration-error-budget.md`，D7 真机标定项）。

## 2. 码位几何单一真源表（configs/tray.yaml，改任何一个都要三方同步）

| 项 | 值 | 位置 | 消费方 |
|---|---|---|---|
| 盘面边长 | `tray_mm: 300.0`（正方形） | tray.yaml | config.py `(0,2000]` 校验；Mock 画布、合成器（在飞）、打印板 |
| 正射网格 | `grid_px: 2048`（`(0,16384]`） | tray.yaml | `warp_to_tray`；`mm_per_px = 300/2048 ≈ 0.14648` |
| 码字典 | `DICT_4X4_50`（格式 `^DICT_\d+X\d+_\d+$`，存在性检测期由 cv2 解析） | tray.yaml `aruco.dictionary` | config.py、core.py `_detect_markers`、mock、make_aruco |
| 码边长 | `marker_mm: 60.0`（>0 且 `marker_mm*2 < tray_mm`） | tray.yaml `aruco.marker_mm` | 角点精化 `half=marker/2`；打印板；**待真机打印实测回填** |
| 角位→id | `lt:0, rt:1, rb:2, lb:3`（取值集恰 [0,1,2,3]，契约要求） | tray.yaml `aruco.corner_ids` | 布局生成；检测按 id 配对、与摆放旋转无关 |
| 码中心 mm | id0 (30,30) / id1 (270,30) / id2 (270,270) / id3 (30,270) | tray.yaml `aruco.centers_mm` | 标定目标点；Mock 绘码；make_aruco 默认布局；**四码中心任意三点不得共线**（config 加载期叉积校验，<1e-6 抛错） |
| 角位公式（缺省） | `LT=(m/2,m/2) RT=(T-m/2,m/2) RB=(T-m/2,T-m/2) LB=(m/2,T-m/2)` | tray.yaml 注释；make_aruco `_formula_centers`（显式覆盖 board/marker 时退回此公式） | 与上表显式值互为核对（60/2=30 ✓） |
| 插值 | `warp.interp: linear`（linear/cubic/nearest） | tray.yaml | warpPerspective flags |
| 盘外填充 | `warp.border_value: 235`（0..255） | tray.yaml | 与浅色演示背景一致 |

**单一真源纪律（W13 修复的教训）**：四角码的盘面布局只认 `configs/tray.yaml`。
此前 Mock 自行把码心内缩到 45mm 而配置是 30mm——「检测点对配置点」的自洽门照样放行
约 +14% 尺度误差（跨距 210mm 被配到 240mm）。现 Mock（`mock_source.py:39-47` 加载
`load_tray_config()`）、打印板（make_aruco.py 默认读同源）、标定配置三者同坐标；
`tests/test_acquisition.py` 有「Mock 帧对默认配置标定 px_per_mm 误差 <1%」回归锚点。

## 3. 求解策略（两级，core.py `_solve_view`）

1. **a) 中心精确解**：四码中心（检测角点 4 点均值）↔ 配置中心 mm，`cv2.findHomography(src, dst, 0)`。
   中心配对只依赖 marker id——与检测顺序、托盘摆放旋转完全无关（任意角度均正确）。
2. **b) 角点级精化**：用 a) 的 H 把布局角点（`cx±marker/2, cy±marker/2`，TL/TR/BR/BL 顺时针序）
   反投影到 px，与检测角点做**循环移位匹配**（4 选 1，取 4 角距离和最小者——对盘面内任意旋转稳健），
   得 16 对（4 码 × 4 角）→ `findHomography` 最小二乘精化。
   **不劣化守卫**：精化解的 16 角点像素 RMS 若反而大于中心解则回退 a)（`rms1 <= rms0` 才采用）。
3. **端到端自洽门（2mm）**：检测中心经最终 H 反投影，与配置中心的最大偏差 >2.0mm 即抛
   `CalibrationError`（布局核对门，非精度指标——它抓的是「码位配错对」，配错对时 4 点单应
   仍可能完美拟合，只有跨布局核对能暴露）。

## 4. 失败语义与魔法数字表

| 项 | 值 | 位置 | 语义 |
|---|---|---|---|
| 检出 <4 码 / id 不全 | `CalibrationError` | `_detect_markers` | 报错列出期望/检出/缺失 id + 盘外误检 id；v1 无单码兜底 |
| 中心解失败 | `CalibrationError` | `_solve_view` | findHomography 返回空/非有限值 |
| 自洽门 | `center_err_mm > 2.0` 抛错 | `_solve_view` | 「检测点对配置点」布局核对 |
| 盘外误检 | 弃置 | `_detect_markers` | 只保留期望四角 id，`found` 中多余 id 只进报错信息 |
| px_per_mm | 盘面中心局部尺度 | `_local_scale_px_per_mm` | H 逆（mm→px）在中心处 `sqrt(|det J|)`（±0.05mm 差分）；透视下逐点变化，此值是全局快速换算的中心估计 |
| calibrate_pair 组装 | px_per_mm=两面均值；reproj=毫米化 max 后折回 | `calibrate_pair` | 两面分辨率不同时像素 RMS 直接取 max 不可比（W13 修复并锁进测试）；契约字段保持像素量纲 |
| warp 变换矩阵 | `M = S(grid_px/tray_mm) · H` | `warp_to_tray` | 盘外填 `border_value`；H 方向 = 原图 px → 盘面 mm |

## 5. 精度数字口径（重要——对外引用前必读）

`tests/test_calibration.py` 全部精度数字（中心反投影 0.08–0.41mm ≤0.5mm 线、px_per_mm
≤0.06% ≤1% 线、12MP 0.28s ≤3s 线）是**合成夹具上的检测/求解残差**：纯针孔投影、无畸变、
空盘、无亚克力、无反光。**D7 真机标定完成前，不得对外引用为「标定精度」**；现场未计入项
（畸变/折射/反光/豆堆挡码/打印贴装误差）与处置见 `docs/calibration-error-budget.md`。

## 6. ArUco 静区与画布规则（与 M2 的接缝，坑位详见 REGENERATE §7 坑 2）

- 码外白静区：打印板取码边 1/8（make_aruco `pad_px = side_px//8`）；Mock 取码边 1/4
  （`pad = max(4, side_px//4)`）——静区不够检测即失败。
- 码心 (30,30) 时静区伸出盘外约 15mm：**正解是画布留外缘**（Mock `_MARGIN_MM=20`，
  `px_per_mm = min(w,h)/(tray+2×margin)`），**不是把码心往盘内缩**（内缩与 tray.yaml 脱钩
  即 W13 前的 +14% 尺度事故）。
- 分割侧对称坑：四角码是盘面印刷物（暗色方块），经典分割若不抑制码区会把全局 Otsu 阈值拖歪
  ——在飞 `configs/segment.yaml` 的 `mask_markers`/`marker_margin_mm=2.0` 即为此设。

## 7. eval

```bash
python -m pytest tests/test_calibration.py -q
# → 34 passed（2026-09-29 实测）
# 通过线（用例内固化）：中心反投影 ≤0.5mm（实测 0.08–0.41）；px_per_mm 相对误差 ≤1%
#   （实测 ≤0.06%）；43/90/180/270° 旋转 + id 置换布局仍正确；缺码/空图正确抛错；
#   12MP 单张 ≤3s CPU（实测 0.28s）
```
