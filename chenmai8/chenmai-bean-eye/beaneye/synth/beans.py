"""W12a-lite · 程序化豆素材生成器（M12 素材库的程序化路径）。

背景（本批决策）：外部数据集路径弃用，素材改为**程序化生成**——按 taxonomy
13 类逐类参数化生成单粒豆素材，等生豆到货后按 ``docs/collect_protocol.md``
自采回灌（HN-Robusta 自建集为数据主叙事）。

三类信息分层（全部确定性，种子固定即字节级复现）：

1. **类画像** :data:`CLASS_PROFILES`——每 taxonomy 类的几何/颜色/形态算子
   参数范围：长轴 mm、长宽比、CIE L\\*a\\*b\\* 颜色范围、轮廓波纹（干瘪）、
   虫孔/斑块（霉斑、花脸、酸斑）、弦切（破碎）、空腔弧（贝壳豆）、纵皱纹。
2. **素材库** :func:`sample_library`——每类 ≥20 个固定变体
   （:class:`BeanSpec`，含 variant_id），由 library 种子确定性生成。
   这是「素材库 lite」：变体是参数集而非位图，渲染按需进行（省盘省内存）。
3. **单粒渲染** :func:`render_sprite`——把一粒 :class:`BeanSpec` 渲染成
   RGBA sprite + 真值轮廓多边形（mm/px 双坐标系）。alpha 通道即逐粒真值
   掩码（多边形 fillPoly 直出，W12b 合成器的真值来源）。

颜色标度：类画像用 CIE L\\*a\\*b\\*（与标准 YAML ``reference_lab`` 同量纲），
进渲染管线前经 :func:`beaneye.metrology.core.cie_to_lab8` 转契约唯一的
lab8 标度，再经 OpenCV LAB→BGR 落到像素——与 M8 色差计量同一标度链。

真值语义约定：alpha/多边形是**豆的完整轮廓**——虫蛀孔洞渲染为孔内暗色
（不透底）、重叠摆放中被压部分也不从轮廓中剔除（W12b manifest 记录完整
轮廓 + 可见性由渲染叠序决定）。分类真值逐粒记录在 W12b manifest 中。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import cv2
import numpy as np

from beaneye.metrology.core import cie_to_lab8
from beaneye.taxonomy import Taxonomy, load_taxonomy

__all__ = [
    "CLASS_PROFILES",
    "BeanSpec",
    "Sprite",
    "SynthBeanError",
    "sample_library",
    "sample_spec",
    "render_sprite",
    "bean_polygon_mm",
    "lab8_to_bgr",
]


class SynthBeanError(ValueError):
    """程序化素材参数非法 / 类不在 taxonomy 中。"""


# ---------------------------------------------------------------------------
# 每类参数画像（W12a-lite 核心数据）
# ---------------------------------------------------------------------------
# 字段（区间闭，采样均匀分布）：
#   length_mm   长轴范围（mm）      aspect  长宽比范围（length/width）
#   lab         CIE L*a*b* 范围 [lo, hi]，每维独立均匀采样
#   ripple      轮廓波纹幅度范围（相对半径；干瘪/皱缩豆大）
#   ripple_freq 波纹角频率范围（整数）
#   crease      是否画中缝（生豆特征）
#   wrinkles    纵向皱纹强度范围（0=无）
#   cut         破碎弦切保留比例范围（None=不切；如 (0.35,0.65)）
#   crescent    贝壳豆空腔弧强度范围（0=无）
#   holes       虫孔数范围 (None=无)；孔半径 mm 范围
#   blotches    斑块数范围 (None=无) + (dL,da,db) 色偏范围 + 半径 mm 范围
# 尺寸先验：等效直径 eq_d = L/√aspect，罗布斯塔生豆典型 5.2-6.9mm
# （筛目 13-17），画像据此设定（象豆天然偏大 6.3-8.9mm）。
CLASS_PROFILES: dict[str, dict] = {
    "normal": dict(
        length_mm=(5.8, 7.8), aspect=(1.25, 1.55),
        lab=((45.0, -15.0, 16.0), (62.0, -7.0, 26.0)),
        ripple=(0.010, 0.035), ripple_freq=(3, 5), crease=True, wrinkles=(0.0, 0.12),
    ),
    "black": dict(
        length_mm=(5.6, 7.4), aspect=(1.25, 1.60),
        lab=((16.0, 2.0, 2.0), (34.0, 10.0, 12.0)),
        ripple=(0.02, 0.06), ripple_freq=(3, 6), crease=True, wrinkles=(0.05, 0.2),
    ),
    "mold": dict(
        length_mm=(5.5, 7.6), aspect=(1.20, 1.55),
        lab=((42.0, -12.0, 12.0), (56.0, -4.0, 20.0)),
        ripple=(0.015, 0.05), ripple_freq=(3, 6), crease=True, wrinkles=(0.0, 0.15),
        blotches=dict(n=(3, 7), dlab=((14.0, 0.0, -8.0), (34.0, 8.0, 2.0)), r_mm=(0.7, 1.8)),
    ),
    "sour": dict(
        length_mm=(5.6, 7.6), aspect=(1.20, 1.50),
        lab=((40.0, 4.0, 16.0), (54.0, 12.0, 28.0)),
        ripple=(0.015, 0.045), ripple_freq=(3, 5), crease=True, wrinkles=(0.0, 0.15),
        blotches=dict(n=(1, 4), dlab=((-16.0, 0.0, -4.0), (-6.0, 8.0, 6.0)), r_mm=(0.9, 2.2)),
    ),
    "insect": dict(
        length_mm=(5.7, 7.6), aspect=(1.25, 1.55),
        lab=((44.0, -14.0, 16.0), (60.0, -6.0, 26.0)),
        ripple=(0.02, 0.05), ripple_freq=(3, 6), crease=True, wrinkles=(0.0, 0.15),
        holes=dict(n=(1, 3), r_mm=(0.5, 1.1)),
    ),
    "dried": dict(
        length_mm=(5.2, 7.2), aspect=(1.35, 1.75),
        lab=((38.0, -2.0, 14.0), (50.0, 6.0, 22.0)),
        ripple=(0.08, 0.16), ripple_freq=(5, 9), crease=True, wrinkles=(0.35, 0.7),
    ),
    "broken": dict(
        length_mm=(5.7, 7.6), aspect=(1.20, 1.60),
        lab=((44.0, -14.0, 16.0), (62.0, -6.0, 26.0)),
        ripple=(0.01, 0.04), ripple_freq=(3, 5), crease=True, wrinkles=(0.0, 0.12),
        cut=(0.35, 0.65),
    ),
    "brocade": dict(
        length_mm=(5.7, 7.6), aspect=(1.25, 1.55),
        lab=((44.0, -13.0, 15.0), (60.0, -6.0, 24.0)),
        ripple=(0.01, 0.04), ripple_freq=(3, 5), crease=True, wrinkles=(0.0, 0.12),
        blotches=dict(n=(6, 12), dlab=((-14.0, -2.0, -6.0), (-4.0, 6.0, 4.0)), r_mm=(0.4, 1.0)),
    ),
    "shell": dict(
        length_mm=(5.8, 7.8), aspect=(1.20, 1.50),
        lab=((46.0, -14.0, 16.0), (62.0, -6.0, 26.0)),
        ripple=(0.01, 0.04), ripple_freq=(3, 5), crease=True, wrinkles=(0.0, 0.12),
        crescent=(0.5, 0.9),
    ),
    "elephant": dict(
        length_mm=(8.0, 10.5), aspect=(1.30, 1.60),
        lab=((48.0, -13.0, 16.0), (62.0, -6.0, 26.0)),
        ripple=(0.01, 0.035), ripple_freq=(2, 4), crease=True, wrinkles=(0.0, 0.1),
    ),
    "peaberry": dict(
        length_mm=(4.9, 6.2), aspect=(1.00, 1.25),
        lab=((48.0, -14.0, 16.0), (62.0, -7.0, 26.0)),
        ripple=(0.01, 0.04), ripple_freq=(3, 5), crease=False, wrinkles=(0.0, 0.1),
    ),
    "immature": dict(
        length_mm=(4.5, 5.8), aspect=(1.20, 1.50),
        lab=((60.0, -18.0, 18.0), (74.0, -10.0, 28.0)),
        ripple=(0.01, 0.04), ripple_freq=(3, 5), crease=True, wrinkles=(0.0, 0.1),
    ),
    "faded": dict(
        length_mm=(5.4, 7.4), aspect=(1.30, 1.60),
        lab=((70.0, -6.0, 10.0), (86.0, 0.0, 18.0)),
        ripple=(0.015, 0.05), ripple_freq=(4, 7), crease=False, wrinkles=(0.05, 0.2),
    ),
}

_BASE_JITTER = dict(
    length=0.05, aspect=0.06, lab=(2.0, 1.5, 1.5), pos=0.06  # 放置期抖动幅度
)


# ---------------------------------------------------------------------------
# BeanSpec：一粒豆的全部渲染参数（确定性可复现）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BeanSpec:
    """单粒豆素材（渲染所需的全部参数）。

    ``holes``/``blotches`` 用豆本地相对坐标 (u, v) ∈ [-0.6, 0.6]（×各自半轴
    得 mm 位置），保证落在轮廓内；``cut`` 为弦切保留比例（破碎豆）。
    """

    cls: str
    variant_id: str
    length_mm: float
    aspect: float
    angle_deg: float
    cie_lab: tuple[float, float, float]
    ripple_amp: float
    ripple_freq: int
    ripple_phase: float
    crease: bool
    crease_phase: float
    wrinkles: float
    cut: float | None = None
    crescent: float = 0.0
    holes: tuple[tuple[float, float, float], ...] = ()
    blotches: tuple[tuple[float, float, float, float, float, float], ...] = ()
    seed: int = 0

    @property
    def width_mm(self) -> float:
        return self.length_mm / self.aspect


@dataclass
class Sprite:
    """单粒渲染产物：BGR 颜色 + 二值 alpha（真值轮廓）+ 双坐标系多边形。

    ``poly_mm`` 为豆本地系（椭圆中心=原点）mm 多边形；``poly_px`` 为 sprite
    图内像素多边形；``center_px`` 为椭圆中心在 sprite 图内的像素坐标
    （compose 据此把 sprite 贴到布局中心）。
    """

    bgr: np.ndarray
    alpha: np.ndarray
    poly_mm: np.ndarray
    poly_px: np.ndarray
    center_px: tuple[float, float]

    @property
    def size_px(self) -> tuple[int, int]:
        return int(self.bgr.shape[1]), int(self.bgr.shape[0])


# ---------------------------------------------------------------------------
# 采样：类画像 → 变体库 → 单粒 spec
# ---------------------------------------------------------------------------


def _u(rng: np.random.Generator, rng_range: Sequence[float]) -> float:
    lo, hi = float(rng_range[0]), float(rng_range[1])
    return float(rng.uniform(lo, hi))


def _sample_spec_from_profile(
    cls: str, profile: dict, rng: np.random.Generator, variant_id: str, seed: int
) -> BeanSpec:
    """按类画像采样一粒变体参数（全部确定性来自 rng）。"""
    length = _u(rng, profile["length_mm"])
    aspect = _u(rng, profile["aspect"])
    lab_lo, lab_hi = profile["lab"]
    lab = tuple(float(rng.uniform(lo, hi)) for lo, hi in zip(lab_lo, lab_hi))
    ripple = _u(rng, profile["ripple"])
    freq = int(rng.integers(profile["ripple_freq"][0], profile["ripple_freq"][1] + 1))
    holes: tuple[tuple[float, float, float], ...] = ()
    if "holes" in profile:
        n = int(rng.integers(profile["holes"]["n"][0], profile["holes"]["n"][1] + 1))
        r_lo, r_hi = profile["holes"]["r_mm"]
        # 简单避让：逐孔重采样，孔心距（mm，椭圆半轴各自缩放）≥ 两孔半径和
        # （最多 40 次后放弃避让——孔缘轻微相融视觉上可接受）
        a_h, b_h = length / 2.0, length / (2.0 * aspect)
        for _ in range(n):
            for _try in range(40):
                u, v = float(rng.uniform(-0.52, 0.52)), float(rng.uniform(-0.52, 0.52))
                r = float(rng.uniform(r_lo, r_hi))
                ok = True
                for u0, v0, r0 in holes:
                    if math.hypot((u - u0) * a_h, (v - v0) * b_h) < (r + r0):
                        ok = False
                        break
                if ok:
                    break
            holes += ((u, v, r),)
    blotches: tuple[tuple[float, float, float, float, float, float], ...] = ()
    if "blotches" in profile:
        bl = profile["blotches"]
        n = int(rng.integers(bl["n"][0], bl["n"][1] + 1))
        dlo, dhi = bl["dlab"]
        for _ in range(n):
            u, v = float(rng.uniform(-0.55, 0.55)), float(rng.uniform(-0.55, 0.55))
            r = float(rng.uniform(*bl["r_mm"]))
            dlab = tuple(float(rng.uniform(lo, hi)) for lo, hi in zip(dlo, dhi))
            blotches += ((u, v, r, *dlab),)
    return BeanSpec(
        cls=cls,
        variant_id=variant_id,
        length_mm=length,
        aspect=aspect,
        angle_deg=0.0,  # 朝向由放置期决定（sample_spec）
        cie_lab=lab,  # type: ignore[arg-type]
        ripple_amp=ripple,
        ripple_freq=freq,
        ripple_phase=float(rng.uniform(0.0, 2.0 * math.pi)),
        crease=bool(profile["crease"]),
        crease_phase=float(rng.uniform(0.0, 2.0 * math.pi)),
        wrinkles=_u(rng, profile["wrinkles"]),
        cut=_u(rng, profile["cut"]) if "cut" in profile else None,
        crescent=_u(rng, profile["crescent"]) if "crescent" in profile else 0.0,
        holes=holes,
        blotches=blotches,
        seed=seed,
    )


def sample_library(
    seed: int = 20260929, per_class: int = 24, taxonomy: Taxonomy | None = None
) -> dict[str, list[BeanSpec]]:
    """构建程序化素材库：每 taxonomy 类 ``per_class`` 个固定变体。

    变体参数由 ``default_rng([seed, class_idx, variant_idx])`` 确定性生成；
    同种子逐参数一致（字节级复现的根）。``per_class < 20`` 拒绝（W12a-lite
    交付线：每类 ≥20 变体）。
    """
    if per_class < 20:
        raise SynthBeanError(f"per_class 必须 >= 20（每类变体交付线），得到 {per_class}")
    tax = taxonomy if taxonomy is not None else load_taxonomy()
    lib: dict[str, list[BeanSpec]] = {}
    for ci, cls in enumerate(tax.keys()):
        profile = CLASS_PROFILES.get(cls)
        if profile is None:
            raise SynthBeanError(f"taxonomy 类 {cls!r} 没有程序化画像（CLASS_PROFILES 缺类）")
        variants: list[BeanSpec] = []
        for vi in range(per_class):
            vrng = np.random.default_rng([int(seed), ci, vi])
            variants.append(
                _sample_spec_from_profile(cls, profile, vrng, f"{cls}_v{vi:02d}", seed=int(vrng.integers(0, 2**31)))
            )
        lib[cls] = variants
    return lib


def sample_spec(
    variants: Sequence[BeanSpec],
    rng: np.random.Generator,
    *,
    scale_jitter: float = 0.0,
    angle_jitter: float = 180.0,
) -> BeanSpec:
    """从某类变体中抽一粒并做放置期抖动（尺寸/朝向/颜色/形态微扰）。

    抖动只动连续参数（长轴、长宽比、颜色、孔斑位置），形态算子档位
    （孔数/斑块数/是否弦切）保持变体原值——真值类别语义不漂移。
    """
    if not variants:
        raise SynthBeanError("variants 为空，无法采样")
    base = variants[int(rng.integers(0, len(variants)))]
    a, b, c = _BASE_JITTER["lab"]
    # CIE 量纲钳制：L ∈ [0,100]，a/b ∈ [-128,127]（a/b 可负，不得钳到 ≥0）
    bounds = ((0.0, 100.0), (-128.0, 127.0), (-128.0, 127.0))
    lab = tuple(
        float(np.clip(v + rng.uniform(-j, j), lo, hi))
        for (v, j, (lo, hi)) in zip(base.cie_lab, (a, b, c), bounds)
    )
    length = base.length_mm * (1.0 + rng.uniform(-scale_jitter, scale_jitter))
    aspect = base.aspect * (1.0 + rng.uniform(-_BASE_JITTER["aspect"], _BASE_JITTER["aspect"]))
    pos = _BASE_JITTER["pos"]
    holes = tuple(
        (
            float(np.clip(u + rng.uniform(-pos, pos), -0.6, 0.6)),
            float(np.clip(v + rng.uniform(-pos, pos), -0.6, 0.6)),
            r,
        )
        for u, v, r in base.holes
    )
    blotches = tuple(
        (
            float(np.clip(u + rng.uniform(-pos, pos), -0.62, 0.62)),
            float(np.clip(v + rng.uniform(-pos, pos), -0.62, 0.62)),
            r,
            dl,
            da,
            db,
        )
        for u, v, r, dl, da, db in base.blotches
    )
    return BeanSpec(
        cls=base.cls,
        variant_id=base.variant_id,
        length_mm=length,
        aspect=aspect,
        angle_deg=float(rng.uniform(-angle_jitter, angle_jitter)),
        cie_lab=lab,  # type: ignore[arg-type]
        ripple_amp=base.ripple_amp,
        ripple_freq=base.ripple_freq,
        ripple_phase=base.ripple_phase,
        crease=base.crease,
        crease_phase=base.crease_phase,
        wrinkles=base.wrinkles,
        cut=base.cut,
        crescent=base.crescent,
        holes=holes,
        blotches=blotches,
        seed=int(rng.integers(0, 2**31)),
    )


# ---------------------------------------------------------------------------
# 几何：参数 → 真值轮廓多边形（豆本地 mm 系，椭圆中心=原点）
# ---------------------------------------------------------------------------


def bean_polygon_mm(spec: BeanSpec, n_pts: int = 72) -> np.ndarray:
    """BeanSpec → 轮廓多边形 (N,2) mm（含波纹、弦切；朝向已旋转入内）。"""
    a = spec.length_mm / 2.0
    b = spec.width_mm / 2.0
    theta = np.linspace(0.0, 2.0 * math.pi, n_pts, endpoint=False)
    rs = 1.0 + spec.ripple_amp * np.sin(spec.ripple_freq * theta + spec.ripple_phase)
    xb = a * np.cos(theta) * rs
    yb = b * np.sin(theta) * rs

    if spec.cut is not None:
        # 破碎：保留 x ≤ chord 的弓形段，弦边加锯齿（断裂茬口）
        chord_x = a * (2.0 * spec.cut - 1.0)
        t = min(max(chord_x / a, -1.0), 1.0)
        yr = b * math.sqrt(max(0.0, 1.0 - t * t))
        keep = xb <= chord_x + 1e-9
        arc_x, arc_y = xb[keep], yb[keep]
        n_jag = 6
        jy = np.linspace(arc_y[-1], arc_y[0], n_jag + 2)[1:-1]  # 从尾到头沿弦回连
        jx = np.full(n_jag, chord_x) + np.array(
            [rng_j for rng_j in _jag_offsets(spec.seed, n_jag, 0.10)]
        )
        xb = np.concatenate([arc_x, jx])
        yb = np.concatenate([arc_y, jy])

    ang = math.radians(spec.angle_deg)
    ca, sa = math.cos(ang), math.sin(ang)
    x = xb * ca - yb * sa
    y = xb * sa + yb * ca
    return np.stack([x, y], axis=1)


def _jag_offsets(seed: int, n: int, amp: float) -> list[float]:
    rng = np.random.default_rng([seed, 977, n])
    return [float(v) for v in rng.uniform(-amp, amp, size=n)]


# ---------------------------------------------------------------------------
# 渲染：BeanSpec → Sprite（颜色 + alpha 真值轮廓）
# ---------------------------------------------------------------------------


def lab8_to_bgr(lab8: Sequence[float]) -> tuple[int, int, int]:
    """lab8 (0-255 三通道) → BGR（OpenCV LAB 标度互转，构造期钳制）。"""
    px = np.zeros((1, 1, 3), dtype=np.uint8)
    for i, v in enumerate(lab8):
        px[0, 0, i] = int(np.clip(round(float(v)), 0, 255))
    bgr = cv2.cvtColor(px, cv2.COLOR_LAB2BGR)[0, 0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])


def render_sprite(spec: BeanSpec, px_per_mm: float, rng: np.random.Generator) -> Sprite:
    """渲染一粒豆：RGBA sprite（BGR+二值 alpha 真值轮廓）+ 本地多边形。

    ``rng`` 驱动纹理噪声与弦口锯齿等的*渲染细节*；几何（多边形）只由
    spec 决定，与 rng 无关——真值掩码与合成参数严格一致。
    """
    poly_mm = bean_polygon_mm(spec)
    poly_px = poly_mm * float(px_per_mm)
    pad = 3
    min_xy = poly_px.min(axis=0)
    max_xy = poly_px.max(axis=0)
    w = int(np.ceil(max_xy[0] - min_xy[0])) + 2 * pad
    h = int(np.ceil(max_xy[1] - min_xy[1])) + 2 * pad
    w = max(w, 4)
    h = max(h, 4)
    # 椭圆中心（本地 (0,0)）在 sprite 内的像素坐标
    center_px = (float(-min_xy[0]) + pad, float(-min_xy[1]) + pad)
    poly_loc = poly_px - min_xy + pad
    ipts = np.round(poly_loc).astype(np.int32)

    alpha = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(alpha, [ipts], 255)
    inside = alpha > 0

    # ---- 基色 + 纹理 -----------------------------------------------------
    base_bgr = lab8_to_bgr(cie_to_lab8(spec.cie_lab))
    img = np.empty((h, w, 3), dtype=np.float32)
    img[:] = base_bgr
    grain = rng.normal(0.0, 6.0, size=(h, w)).astype(np.float32)
    img += grain[..., None]
    mottle_small = rng.uniform(-1.0, 1.0, size=(max(2, h // 8), max(2, w // 8))).astype(np.float32)
    mottle = cv2.resize(mottle_small, (w, h), interpolation=cv2.INTER_LINEAR)
    mottle = cv2.GaussianBlur(mottle, (0, 0), 2.0)
    img += (mottle * 7.0)[..., None]
    # 单向光梯度（左上受光）：豆体立体感，几何无关不需 rng
    gx = np.linspace(-1.0, 1.0, w, dtype=np.float32)[None, :]
    gy = np.linspace(-1.0, 1.0, h, dtype=np.float32)[:, None]
    shade = 1.0 + 0.13 * (0.7 * gx - 0.7 * gy)
    img *= shade[..., None]
    # 边缘暗晕（豆缘背光）
    er = cv2.erode(alpha, np.ones((3, 3), np.uint8), iterations=2)
    ring = inside & (er == 0)
    img[ring] *= 0.78

    def _to_px(u: float, v: float, mm: float) -> tuple[float, float, float]:
        """豆本地相对坐标 (u,v)（×半轴）+ mm 尺寸 → sprite px 坐标/尺寸。"""
        lx, ly = u * spec.length_mm / 2.0, v * spec.width_mm / 2.0
        ang = math.radians(spec.angle_deg)
        ca, sa = math.cos(ang), math.sin(ang)
        rx, ry = lx * ca - ly * sa, lx * sa + ly * ca
        return (
            center_px[0] + rx * px_per_mm,
            center_px[1] + ry * px_per_mm,
            max(1.0, mm * px_per_mm),
        )

    # ---- 斑块（霉斑/花脸/酸斑） ------------------------------------------
    if spec.blotches:
        blotch_layer = np.zeros((h, w), dtype=np.float32)
        patch = img.copy()
        for u, v, r_mm, dl, da, db in spec.blotches:
            cx, cy, rp = _to_px(u, v, r_mm)
            # dL 为 CIE 量纲 → lab8 的 L 通道乘 2.55；a/b 偏移直接加
            col = lab8_to_bgr(
                (
                    spec.cie_lab[0] * 2.55 + dl * 2.55,
                    spec.cie_lab[1] + 128.0 + da,
                    spec.cie_lab[2] + 128.0 + db,
                )
            )
            cv2.circle(patch, (int(round(cx)), int(round(cy))), int(round(rp)), col, -1)
            cv2.circle(blotch_layer, (int(round(cx)), int(round(cy))), int(round(rp)), 1.0, -1)
        blotch_layer = cv2.GaussianBlur(blotch_layer, (0, 0), 1.5)[..., None]
        img = img * (1.0 - blotch_layer) + patch * blotch_layer

    # ---- 中缝（生豆特征）：沿长轴的暗色 S 曲线 ----------------------------
    if spec.crease:
        pts = []
        for t in np.linspace(-0.78, 0.78, 16):
            lx = t * spec.length_mm / 2.0
            ly = 0.08 * spec.width_mm / 2.0 * math.sin(t * math.pi * 1.3 + spec.crease_phase)
            ang = math.radians(spec.angle_deg)
            ca, sa = math.cos(ang), math.sin(ang)
            rx, ry = lx * ca - ly * sa, lx * sa + ly * ca
            pts.append(
                [
                    int(round(center_px[0] + rx * px_per_mm)),
                    int(round(center_px[1] + ry * px_per_mm)),
                ]
            )
        dark = tuple(int(c * 0.55) for c in base_bgr)
        cv2.polylines(img, [np.asarray(pts, dtype=np.int32)], False, dark, 1, cv2.LINE_AA)

    # ---- 纵向皱纹（干瘪/僵豆） --------------------------------------------
    if spec.wrinkles > 0.02:
        wrng = np.random.default_rng([spec.seed, 331, int(spec.wrinkles * 100)])
        n_w = 3 + int(spec.wrinkles * 5)
        dark = tuple(int(c * (1.0 - 0.35 * spec.wrinkles)) for c in base_bgr)
        for k in range(n_w):
            off = float(wrng.uniform(-0.5, 0.5)) * spec.width_mm / 2.0
            t0, t1 = float(wrng.uniform(-0.7, -0.1)), float(wrng.uniform(0.1, 0.7))
            pts = []
            for t in np.linspace(t0, t1, 8):
                lx = t * spec.length_mm / 2.0
                ly = off + 0.04 * spec.width_mm / 2.0 * math.sin(t * 9.0 + k)
                ang = math.radians(spec.angle_deg)
                ca, sa = math.cos(ang), math.sin(ang)
                rx, ry = lx * ca - ly * sa, lx * sa + ly * ca
                pts.append(
                    [
                        int(round(center_px[0] + rx * px_per_mm)),
                        int(round(center_px[1] + ry * px_per_mm)),
                    ]
                )
            cv2.polylines(img, [np.asarray(pts, dtype=np.int32)], False, dark, 1, cv2.LINE_AA)

    # ---- 贝壳豆空腔弧（贴边的深色月牙） ------------------------------------
    if spec.crescent > 0.02:
        dark = lab8_to_bgr((max(10.0, spec.cie_lab[0] * 0.35), 120.0, 120.0))
        r_px = 0.62 * spec.length_mm / 2.0 * px_per_mm
        ang = math.radians(spec.angle_deg)
        cv2.ellipse(
            img,
            (int(round(center_px[0])), int(round(center_px[1]))),
            (int(round(r_px)), int(round(0.55 * r_px))),
            math.degrees(ang),
            150,
            230,
            dark,
            max(1, int(round(0.22 * spec.width_mm * px_per_mm))),
            cv2.LINE_AA,
        )

    # ---- 虫蛀孔（孔内暗色 + 受蚀亮圈；不透底，轮廓完整） -------------------
    if spec.holes:
        hole_col = lab8_to_bgr((24.0, 126.0, 122.0))
        rim_col = lab8_to_bgr(
            (
                min(255.0, spec.cie_lab[0] * 2.55 + 26.0),
                spec.cie_lab[1] + 128.0 + 6.0,
                spec.cie_lab[2] + 128.0 + 8.0,
            )
        )
        for u, v, r_mm in spec.holes:
            cx, cy, rp = _to_px(u, v, r_mm)
            cxi, cyi, rpi = int(round(cx)), int(round(cy)), int(round(rp))
            if rp < 0.8 or cxi < 0 or cyi < 0 or cxi >= w or cyi >= h:
                continue
            if alpha[min(h - 1, cyi), min(w - 1, cxi)] == 0:
                continue  # 孔心落轮廓外（弦切豆）则跳过
            cv2.circle(img, (cxi, cyi), rpi + 1, rim_col, 1, cv2.LINE_AA)
            cv2.circle(img, (cxi, cyi), rpi, hole_col, -1, cv2.LINE_AA)

    # ---- 破碎弦口亮面（断面颜色更浅） --------------------------------------
    if spec.cut is not None:
        a = spec.length_mm / 2.0
        chord_x = a * (2.0 * spec.cut - 1.0)
        t = min(max(chord_x / a, -1.0), 1.0)
        yr = spec.width_mm / 2.0 * math.sqrt(max(0.0, 1.0 - t * t))
        n_jag = 6
        jx = _jag_offsets(spec.seed, n_jag, 0.10)
        cut_col = lab8_to_bgr(
            (
                min(255.0, spec.cie_lab[0] * 2.55 + 30.0),
                spec.cie_lab[1] + 128.0 + 10.0,
                spec.cie_lab[2] + 128.0 + 2.0,
            )
        )
        pts = []
        for i in range(n_jag + 1):
            frac = -1.0 + 2.0 * i / n_jag
            lx, ly = chord_x + (jx[i - 1] if 0 < i <= n_jag else 0.0), frac * yr
            ang = math.radians(spec.angle_deg)
            ca, sa = math.cos(ang), math.sin(ang)
            rx, ry = lx * ca - ly * sa, lx * sa + ly * ca
            pts.append(
                [
                    int(round(center_px[0] + rx * px_per_mm)),
                    int(round(center_px[1] + ry * px_per_mm)),
                ]
            )
        cv2.polylines(img, [np.asarray(pts, dtype=np.int32)], False, cut_col, 2, cv2.LINE_AA)

    out = np.clip(img, 0, 255).astype(np.uint8)
    return Sprite(bgr=out, alpha=alpha, poly_mm=poly_mm, poly_px=poly_loc, center_px=center_px)
