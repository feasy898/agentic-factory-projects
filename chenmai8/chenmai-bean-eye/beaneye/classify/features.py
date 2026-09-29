"""M5 分类 · 逐粒特征提取（RulesV0 的特征层）。

输入是冻结协议 ``ClsModel.classify(crop_rgba, mask)`` 的两件东西：

- ``crop_rgba``：掩码裁剪证据图（RGB + alpha，``uint8``）——生产路径由
  M13 管线 ``extract_mask_crop_rgba`` 从正射盘面网格按掩码多边形裁出；
- ``mask``：契约 :class:`~beaneye.schemas.BeanMask`（盘面 mm 多边形 /
  面积 / 外接框）。

特征分四组（开发指令 §4 M5）：

1. **颜色统计**：掩码内（腐蚀去边后）L\\*a\\*b\\* 均值与分位数（lab8 标度，
   与 M8 计量/合成器同一标度链）、暗/亮像元占比、L 通道熵；
2. **色差**：对黑豆参考与精品参考的 CIE76 ΔE（参考点在
   ``configs/rules_v0.yaml`` 配置，量纲 CIE L\\*a\\*b\\*）；
3. **形状**：等效直径、长轴/短轴/长宽比（多边形最小外接矩形）、圆度、
   实度（面积/凸包面积）、最长真直边段长（破碎豆弦切口的几何指纹——
   逐弦最大偏差判定，见下）；
4. **纹理**：L 通道标准差、中缝对比度（沿长轴中线的暗线深度——生豆中缝，
   花豆/褪色豆无中缝）、内部深色圆孔计数（虫蛀孔；另计「带亮环孔」——
   孔缘受蚀亮圈是虫孔区别于贝壳豆空腔弧的指纹）、深色圆斑计数（花脸
   碎斑指纹，拉长的皱纹线/中缝不计）、HSV 色相直方峰。

关键实现注记（开发期实测踩坑，阈值标定见 configs/rules_v0.yaml 头注）：

- **真直边 vs approxPolyDP**：``cv2.approxPolyDP`` 的容差语义允许「以长弦
  跨过周期性波纹」（波纹轮廓被桥接出跨周期长弦），实测干瘪豆波纹幅
  0.08-0.16mm 被桥出 >2.9mm 假直边、与破碎豆真弦切口（≥2.9mm）重叠。
  改用**逐弦最大偏差**定义：存在某对轮廓点，弦长 ≥ 判定下限且中间全部
  采样点到弦的最大垂距 ≤ ``straight_tol_mm`` 才算直边——光滑椭圆弦长 c
  的弓高 c²/8R（R≤4.7mm）在 c=2.6mm 时 ≥0.18mm、干瘪波纹径向偏差
  ≥0.16mm，均大于破碎弦口锯齿偏差（≤0.10mm）与判定容差 0.13mm，三类
  严格分离。
- **虫孔双阈值 + 亮环验证**：深暗判据 ``max(p50−margin, abs_floor)`` 兼顾
  亮豆（相对阈值）与暗豆（孔内 lab8 亮度恒定 ≈61，绝对下限兜底）；
  「带亮环」= 暗斑外 2px 环带的 L 的 p90 比 p50 高出 ``hole_rim_margin``
  ——虫孔渲染带受蚀亮圈（约 +26 L8），而贝壳豆空腔弧（同为深色、形态上
  也近圆）周围是正常豆体，无亮环，二者由该特征区分。
- **像素→mm 比例从 crop 自身恢复**（alpha 外接框 px ÷ ``bbox_mm`` 外接框
  mm），不依赖调用方传入标定——分类调用点（冻结协议）拿不到 mm_per_px。

全部特征为确定性纯函数（同一输入同一次输出，无随机性、无墙钟时间）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields

import cv2
import numpy as np

from beaneye.metrology.core import delta_e_cie76, lab8_to_cie
from beaneye.schemas import BeanMask

__all__ = [
    "FeatureParams",
    "ColorRefs",
    "BeanFeatures",
    "FEATURE_NAMES",
    "extract_features",
    "feature_value",
]


# ---------------------------------------------------------------------------
# 参数与参考点（configs/rules_v0.yaml 的 features/references 节映射到这里）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeatureParams:
    """特征提取参数（全部有缺省；YAML 只需覆盖需要调的项）。"""

    erode_px: int = 2                    # 统计前腐蚀次数（3×3 核；去边缘 AA/边缘暗晕）
    min_stat_px: int = 24                # 腐蚀后像元低于此数 → 退回未腐蚀掩码统计
    dark_margin: float = 25.0            # 暗像元判据：L < 中位数 − dark_margin
    bright_margin: float = 25.0          # 亮像元判据：L > 中位数 + bright_margin
    hole_dark_margin: float = 38.0       # 孔判据（相对）：L < max(p50−margin, abs_floor)
    hole_abs_floor: float = 64.0         # 孔判据（绝对下限；暗豆 p50 低时相对阈值失效——
                                         # 孔内 lab8 亮度恒定 ≈61，与豆体明暗无关）
    hole_min_area_px: float = 5.0        # 孔斑块最小面积 px
    hole_max_area_px: float = 300.0      # 孔斑块最大面积 px
    hole_max_elong: float = 2.2          # 孔斑块最大拉长比（超过视为皱纹线/暗晕）
    hole_margin_ring_px: int = 1         # 孔不得触及（腐蚀后）掩码边界环的宽度 px
    hole_rim_margin: float = 15.0        # 带亮环孔判据：环带 L 的 p90 ≥ p50 + margin
    hole_rim_dilate_px: int = 2          # 亮环验测的环带宽度 px
    blob_dark_margin: float = 18.0       # 深色圆斑判据（花脸碎斑）：L < p50 − margin
    blob_max_elong: float = 3.5          # 深色圆斑最大拉长比（中缝/皱纹线被排除）
    crease_strip_frac: float = 0.6       # 中缝采样带占长轴比例（|t| ≤ frac/2）
    crease_halfwidth_px: float = 1.5     # 中缝采样带半宽 px
    crease_pct: float = 5.0              # 中缝深度取采样带的第 crease_pct 百分位
    straight_tol_mm: float = 0.13        # 真直边判定的最大垂差容差 mm（见模块 docstring）
    straight_min_mm: float = 1.2         # 直边扫描的最短弦长 mm（低于此不计）
    entropy_bins: int = 32               # L 通道熵分箱数
    hue_min_sat: int = 40                # 色相统计的最小饱和度（滤去消色像元）
    area_window: int = 200               # 面积比特征的滚动窗口长度（盘内逐粒）
    area_min_ref: int = 30               # 面积比可用的最少已见粒数


@dataclass(frozen=True)
class ColorRefs:
    """色差参考点（CIE L*a*b* 量纲；规则 YAML references 节）。"""

    black_ref_cie: tuple[float, float, float] = (25.0, 6.0, 7.0)
    premium_ref_cie: tuple[float, float, float] = (55.0, -12.0, 22.0)


# ---------------------------------------------------------------------------
# 特征向量（字段名 = 规则表 YAML 里 feat 的合法取值）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BeanFeatures:
    """一粒豆的全部特征（lab8 标度注明；几何 mm；比例无量纲）。"""

    # ---- 颜色统计（掩码内，lab8 标度 0-255） -----------------------------
    lab_l_mean: float
    lab_a_mean: float
    lab_b_mean: float
    lab_l_p05: float
    lab_l_p50: float
    lab_l_p95: float
    lab_l_std: float
    l_p95_minus_p50: float          # 亮斑对比（霉斑亮斑指纹）
    l_p50_minus_p05: float          # 深暗区指纹（贝壳空腔弧/虫孔/霉斑暗底）
    dark_frac: float                # L < p50 − dark_margin 的像元占比
    bright_frac: float              # L > p50 + bright_margin 的像元占比
    l_entropy: float                # L 通道香农熵（归一化 0-1）
    # ---- 色差（CIE76，CIE 量纲） ----------------------------------------
    de_black: float                 # 对黑豆参考
    de_premium: float               # 对精品参考
    # ---- 形状（mm） ------------------------------------------------------
    eq_diameter_mm: float           # 面积等效直径（契约口径，出自 mask.area_mm2）
    length_mm: float                # 最小外接矩形长边
    width_mm: float                 # 最小外接矩形短边
    aspect_mm: float                # length/width（≥1）
    perimeter_mm: float
    circularity: float              # 4π·A/P²（轮廓波纹/锯齿使其下降）
    solidity: float                 # A / 凸包面积
    straight_seg_mm: float          # 最长真直边段（弦切口指纹；光滑/波纹面 <2.4mm）
    # ---- 纹理 ------------------------------------------------------------
    crease_contrast: float          # 中线暗线深度（lab8；无中缝 ≈ 噪声底）
    n_dark_round_holes: float       # 内部深色圆孔计数（虫蛀初筛；空腔弧可混入）
    n_holes_with_rim: float         # 带亮环孔计数（虫蛀确认；空腔弧无亮环）
    n_dark_blobs: float             # 深色圆斑计数（花脸碎斑；拉长线不计）
    hue_peak: float                 # HSV 色相直方峰（0-179；全消色 = −1）
    hue_peak_frac: float            # 峰 bin 占比
    area_ratio: float               # 面积 / 盘内已见面积中位数（参考不足 = −1）


FEATURE_NAMES: tuple[str, ...] = tuple(f.name for f in fields(BeanFeatures))


def feature_value(feats: BeanFeatures, name: str) -> float:
    """按名取特征值（规则引擎用；未知名由配置加载器先行拒绝）。"""
    return float(getattr(feats, name))


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def extract_features(
    crop_rgba: np.ndarray,
    mask: BeanMask,
    params: FeatureParams | None = None,
    refs: ColorRefs | None = None,
    *,
    area_ref: float | None = None,
) -> BeanFeatures | None:
    """crop_rgba(RGB+alpha) + BeanMask → 特征向量。

    退化输入（空 alpha / 面积非正 / 形状奇异）返回 ``None``——调用方按
    「无法分类型态」处理（RulesV0 记 normal、conf 0）。本函数不做任何
    类别判断，也不抛异常（除参数构造错误）。
    """
    p = params if params is not None else FeatureParams()
    r = refs if refs is not None else ColorRefs()

    img = np.asarray(crop_rgba)
    if img.ndim != 3 or img.shape[2] < 4 or img.dtype != np.uint8:
        return None
    rgb = img[:, :, :3]
    alpha_raw = img[:, :, 3] > 127
    if int(alpha_raw.sum()) < 3 or not math.isfinite(float(mask.area_mm2)) or mask.area_mm2 <= 0:
        return None

    # ---- 像素→mm 比例：alpha 外接框 px ÷ bbox_mm 外接框 mm（与朝向无关） ----
    ys, xs = np.nonzero(alpha_raw)
    bw_px = float(xs.max() - xs.min() + 1)
    bh_px = float(ys.max() - ys.min() + 1)
    x0, y0, x1, y1 = (float(v) for v in mask.bbox_mm)
    w_mm, h_mm = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    s = max(bw_px / w_mm, bh_px / h_mm)
    if not math.isfinite(s) or s <= 0:
        s = 1.0 / 0.146484375  # 兜底：托盘正射网格标称 mm/px

    # ---- 统计掩码（腐蚀去边；退化时退回原掩码） ---------------------------
    m_u8 = alpha_raw.astype(np.uint8)
    inner = cv2.erode(m_u8, np.ones((3, 3), np.uint8), iterations=max(1, int(p.erode_px)))
    if int(inner.sum()) < p.min_stat_px:
        inner = m_u8
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2Lab).astype(np.float32)
    lchan = lab[..., 0]
    lvals = lchan[inner > 0]
    if lvals.size < 3:
        return None
    avals = lab[..., 1][inner > 0]
    bvals = lab[..., 2][inner > 0]

    l_p05, l_p50, l_p95 = (float(v) for v in np.percentile(lvals, (5, 50, 95)))
    l_mean = float(lvals.mean())
    l_std = float(lvals.std())
    dark = lvals < (l_p50 - p.dark_margin)
    bright = lvals > (l_p50 + p.bright_margin)

    # L 通道熵（entropy_bins 箱，0-255 均分）
    hist = np.bincount(
        np.clip((lvals.astype(np.int32) * p.entropy_bins) // 256, 0, p.entropy_bins - 1),
        minlength=p.entropy_bins,
    ).astype(np.float64)
    pr = hist / max(hist.sum(), 1.0)
    nz = pr[pr > 0]
    l_entropy = float(-(nz * np.log2(nz)).sum() / math.log2(p.entropy_bins))

    # ---- 色差（CIE76；lab8 均值 → CIE） -----------------------------------
    mean8 = (l_mean, float(avals.mean()), float(bvals.mean()))
    de_black = float(delta_e_cie76(lab8_to_cie(mean8), tuple(r.black_ref_cie)))
    de_premium = float(delta_e_cie76(lab8_to_cie(mean8), tuple(r.premium_ref_cie)))

    # ---- 形状（多边形，mm） -----------------------------------------------
    poly = np.asarray(mask.polygon, dtype=np.float32)
    if poly.ndim != 2 or poly.shape[0] < 3:
        return None
    perimeter = float(np.linalg.norm(np.diff(np.vstack([poly, poly[:1]]), axis=0), axis=1).sum())
    area = float(mask.area_mm2)
    hull = cv2.convexHull(poly)
    hull_area = max(float(cv2.contourArea(hull)), 1e-9)
    rect = cv2.minAreaRect(poly)
    rw, rh = sorted((float(rect[1][0]), float(rect[1][1])))
    length_mm = max(rh, 1e-6)
    width_mm = max(rw, 1e-6)
    straight_seg = _longest_true_straight(poly, p)

    # ---- 纹理：中缝对比度（沿长轴中线暗线深度） ----------------------------
    rect_c = (float(rect[0][0]), float(rect[0][1]))
    box = cv2.boxPoints(rect).astype(np.float32)
    d1 = box[1] - box[0]
    d2 = box[3] - box[0]
    major = d1 if float(np.linalg.norm(d1)) >= float(np.linalg.norm(d2)) else d2
    major = major / max(float(np.linalg.norm(major)), 1e-9)  # mm 系单位向量
    # 多边形 mm → crop px 的同一仿射作用于矩形中心（crop 像素 = mm·s + c，
    # c 已由外接框对齐隐含消去——此处只用方向与相对距离，无需显式 c）
    py, px = np.nonzero(inner)
    ppx = np.stack([px, py], axis=1).astype(np.float32)  # (x, y)
    ctr_px = np.array(
        [rect_c[0] * s + (float(xs.min()) - x0 * s), rect_c[1] * s + (float(ys.min()) - y0 * s)],
        dtype=np.float32,
    )
    rel = ppx - ctr_px[None, :]
    u = rel @ np.asarray(major, dtype=np.float32)             # 沿长轴（px）
    perp = np.array([-major[1], major[0]], dtype=np.float32)
    v = rel @ perp                                            # 垂直长轴（px）
    half_len = 0.5 * p.crease_strip_frac * length_mm * s
    strip = (np.abs(v) <= p.crease_halfwidth_px) & (np.abs(u) <= max(half_len, 1.0))
    if int(strip.sum()) >= 5:
        # lvals 与 (py, px)=nonzero(inner) 同序（行主序），strip 是同一像元
        # 列表上的 1-D 布尔选择
        crease_contrast = l_p50 - float(np.percentile(lvals[strip], p.crease_pct))
    else:
        crease_contrast = 0.0
    crease_contrast = float(max(crease_contrast, 0.0))

    # ---- 纹理：虫孔（双阈值深暗 + 亮环验证）与花脸碎斑 ----------------------
    n_holes, n_rim_holes = _detect_holes(m_u8, inner, lchan, l_p50, p)
    n_blobs = _count_dark_blobs(inner, lchan, l_p50, p)

    # ---- HSV 色相直方峰 ----------------------------------------------------
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    sel = (hsv[..., 1] >= p.hue_min_sat) & (inner > 0)
    hues = hsv[..., 0][sel]
    if hues.size >= 5:
        hh = np.bincount(hues.astype(np.int32) // 8, minlength=23)
        peak_bin = int(hh.argmax())
        hue_peak = float(peak_bin * 8 + 4)
        hue_frac = float(hh[peak_bin]) / float(hues.size)
    else:
        hue_peak, hue_frac = -1.0, 0.0

    area_ratio = float(area / area_ref) if (area_ref and area_ref > 0) else -1.0

    return BeanFeatures(
        lab_l_mean=l_mean,
        lab_a_mean=float(avals.mean()),
        lab_b_mean=float(bvals.mean()),
        lab_l_p05=l_p05,
        lab_l_p50=l_p50,
        lab_l_p95=l_p95,
        lab_l_std=l_std,
        l_p95_minus_p50=l_p95 - l_p50,
        l_p50_minus_p05=l_p50 - l_p05,
        dark_frac=float(dark.mean()),
        bright_frac=float(bright.mean()),
        l_entropy=l_entropy,
        de_black=de_black,
        de_premium=de_premium,
        eq_diameter_mm=2.0 * math.sqrt(area / math.pi),
        length_mm=length_mm,
        width_mm=width_mm,
        aspect_mm=length_mm / width_mm,
        perimeter_mm=perimeter,
        circularity=4.0 * math.pi * area / max(perimeter * perimeter, 1e-9),
        solidity=area / hull_area,
        straight_seg_mm=straight_seg,
        crease_contrast=crease_contrast,
        n_dark_round_holes=float(n_holes),
        n_holes_with_rim=float(n_rim_holes),
        n_dark_blobs=float(n_blobs),
        hue_peak=hue_peak,
        hue_peak_frac=hue_frac,
        area_ratio=area_ratio,
    )


# ---------------------------------------------------------------------------
# 内部：真直边 / 孔与斑检测
# ---------------------------------------------------------------------------


def _longest_true_straight(poly: np.ndarray, p: FeatureParams) -> float:
    """最长「真直」轮廓段（mm）：存在弦使中间全部采样点垂差 ≤ 容差。

    语义与 approxPolyDP 不同（后者允许长弦跨过周期波纹，见模块 docstring）。
    多边形是闭合折线；按起点展开成两倍长，只考虑不绕圈超过一周的弦。

    复杂度：逐起点 i 一次外积得到全部 (k, j) 的叉积矩阵
    （cross = dx_j·y_k − dy_j·x_k），沿 k 轴 cumulative-max 后与
    tol·chord 比较——每粒 O(n²) 运算全部在 ~n 次 numpy 调用内完成
    （开发期逐对 Python 循环实测 ~90ms/粒，向量化后 ~3ms/粒）。
    """
    n = int(poly.shape[0])
    tol = float(p.straight_tol_mm)
    min_len = float(p.straight_min_mm)
    if n < 4:
        return 0.0
    x2 = np.concatenate([poly[:, 0], poly[:, 0]]).astype(np.float64)
    y2 = np.concatenate([poly[:, 1], poly[:, 1]]).astype(np.float64)
    m = n - 2  # 弦终点与中间点的相对索引个数
    tri = np.arange(m)[:, None] <= np.arange(m)[None, :]  # k_idx ≤ j_idx ⇔ i < k < j
    best = 0.0
    # 逐起点全扫：弦 (i, j) 的两条弧（直接弧与跨闭合弧）都须独立检验——
    # 半圈起扫会漏掉「两端点都在前半圈」的弦的另一条弧（随机多边形实测不等价）
    for i in range(n):
        xi, yi = x2[i], y2[i]
        # 弦终点 j ∈ [i+2, i+n)（x2 展开两倍长，跨闭合的弦同义于反向起点）
        dxj = x2[i + 2 : i + n] - xi
        dyj = y2[i + 2 : i + n] - yi
        # 中间点 k ∈ [i+1, i+n)
        xk = x2[i + 1 : i + n - 1] - xi
        yk = y2[i + 1 : i + n - 1] - yi
        # cross[k_idx, j_idx] = dxj·yk − dyj·xk（|叉积| = 垂差 × 弦长）
        cross = np.where(tri, np.abs(np.outer(yk, dxj) - np.outer(xk, dyj)), 0.0)
        max_cross = np.maximum.accumulate(cross, axis=0)[-1, :]  # 逐 j 的 k 前缀最大
        ln = np.hypot(dxj, dyj)
        ok = (ln >= max(best, min_len)) & (max_cross <= tol * ln)
        if ok.any():
            best = float(ln[ok].max())
    return float(best)


def _hole_dark_threshold(l_p50: float, p: FeatureParams) -> float:
    """孔深暗判据：max(相对, 绝对下限)。亮豆由相对阈值主导（孔内 lab8 亮度
    恒定 ≈61，深豆体不构成干扰：豆体自身亮度波动 ≤ ±13%·p50 < 38 恒成立），
    暗豆由绝对下限兜底（见模块 docstring）。"""
    return max(l_p50 - p.hole_dark_margin, p.hole_abs_floor)


def _detect_holes(
    raw: np.ndarray, inner: np.ndarray, lchan: np.ndarray, l_p50: float, p: FeatureParams
) -> tuple[int, int]:
    """（深色圆孔数, 带亮环孔数）。

    圆孔 = 深暗 + 面积合适 + 不拉长 + 不贴掩码边界；带亮环 = 斑外
    ``hole_rim_dilate_px`` 环带 L 的 p90 比 p50 高出 ``hole_rim_margin``
    （虫孔渲染带受蚀亮圈；贝壳空腔弧周围是正常豆体，无亮环）。

    孔斑在**未腐蚀掩码** ``raw`` 上检测：虫孔允许落在豆缘附近（u,v
    ±0.52 半轴），在腐蚀 2px 的掩码上近缘孔全部被判「贴边界」丢失
    （开发期实测：腐蚀掩码上虫孔检出率骤降）。边界误报（边缘 AA、
    边缘暗晕、贴边阴影）由 ``raw`` 的边界环排除；环带亮度和圆孔邻域
    统计仍限制在 ``inner`` 内（避开掩码外的背景/阴影）。
    """
    thr = _hole_dark_threshold(l_p50, p)
    dark = ((lchan < thr) & (raw > 0)).astype(np.uint8)
    if int(dark.sum()) == 0:
        return 0, 0
    n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    if n_lab <= 1:
        return 0, 0
    k = np.ones((3, 3), np.uint8)
    ring = raw & ~cv2.erode(raw, k, iterations=p.hole_margin_ring_px)
    n_round = 0
    n_rim = 0
    for lab_i in range(1, n_lab):
        area = int(stats[lab_i, cv2.CC_STAT_AREA])
        if area < p.hole_min_area_px or area > p.hole_max_area_px:
            continue
        blob = (labels == lab_i).astype(np.uint8)
        if int((blob & ring).sum()) > 0:
            continue  # 贴边暗晕/边缘 AA/阴影，不是内部孔
        pts = np.nonzero(blob)
        bp = np.stack([pts[1], pts[0]], axis=1).astype(np.float32)
        _, (w, h), _ = cv2.minAreaRect(bp)
        w, h = sorted((float(w), float(h)))
        if w < 1e-6 or h / w > p.hole_max_elong:
            continue  # 拉长 → 皱纹线/中缝，不是孔
        n_round += 1
        # 亮环验证：膨胀环带（去掉斑本体）内 L 的 p90（限制在豆体统计掩码内）
        dil = cv2.dilate(blob, k, iterations=max(1, int(p.hole_rim_dilate_px)))
        ann = (dil > 0) & (blob == 0) & (inner > 0)
        if int(ann.sum()) >= 4:
            p90 = float(np.percentile(lchan[ann], 90))
            if p90 >= l_p50 + p.hole_rim_margin:
                n_rim += 1
    return n_round, n_rim


def _count_dark_blobs(
    inner: np.ndarray, lchan: np.ndarray, l_p50: float, p: FeatureParams
) -> int:
    """深色圆斑计数（花脸碎斑指纹）：较浅的深暗阈值、允许小斑、排除拉长线。"""
    thr = l_p50 - p.blob_dark_margin
    dark = ((lchan < thr) & (inner > 0)).astype(np.uint8)
    if int(dark.sum()) == 0:
        return 0
    n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    if n_lab <= 1:
        return 0
    ring = inner & ~cv2.erode(inner, np.ones((3, 3), np.uint8), iterations=1)
    count = 0
    for lab_i in range(1, n_lab):
        area = int(stats[lab_i, cv2.CC_STAT_AREA])
        if area < 3 or area > p.hole_max_area_px:
            continue
        blob = (labels == lab_i).astype(np.uint8)
        if int((blob & ring).sum()) > 0:
            continue
        pts = np.nonzero(blob)
        bp = np.stack([pts[1], pts[0]], axis=1).astype(np.float32)
        _, (w, h), _ = cv2.minAreaRect(bp)
        w, h = sorted((float(w), float(h)))
        if w < 1e-6 or h / w > p.blob_max_elong:
            continue  # 中缝/皱纹线
        count += 1
    return count
