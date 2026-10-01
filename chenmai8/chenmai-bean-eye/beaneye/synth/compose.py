"""W12b · 铺盘合成器（M12 合成数据引擎的 compose 核心）。

从程序化素材库（:mod:`beaneye.synth.beans`）抽豆 → 随机铺盘（数量/接触/
重叠/旋转）→ 成对渲染 top/bottom 整盘图（光照扰动/投影阴影/亚克力反光
简化/四角 ArUco）→ **逐粒掩码=真值直出**（多边形 mm + 托盘 mm 网格 COCO
RLE）→ M1 兼容逐粒标注 JSON + 标准 YAML 输入格式的 batch manifest。

确定性：全部随机性由 ``seed`` 经 ``np.random.SeedSequence([seed, stage])``
派生，同种子两次合成图像 ``array_equal``、labels JSON 字节级一致（PNG 编码
确定性）。产物不含墙钟时间——时间戳由下游（TrayScan/采集层）负责。

真值语义（与 :mod:`beaneye.synth.beans` 一致）：
- 每粒标注轮廓 = 豆完整轮廓（重叠摆放中被压部分不从轮廓剔除；
  渲染叠序决定可见性：自由摆放豆先画、接触/重叠豆后画在上层）；
- bottom 面按 M12 成对语义**重采样同 mm 同类另一粒**（两图共享布局坐标
  与 bean_id，配对真值成立）；``mirror_bottom=true`` 时 bottom 朝向取
  top 的镜像角（翻面几何）；
- 接触/重叠判定 = 两粒轮廓凸包相交面积 > 0.01 mm²（弦切口微凹的破碎豆
  按凸包近似，属轻微高估，作为生成器自身的判定定义记录在 manifest）。

颜色/计量链路：素材 CIE L\\*a\\*b\\*（与标准 YAML 同量纲）→ metrology
``cie_to_lab8`` → OpenCV LAB→BGR 落像素；等效直径/面积由真值多边形解析
计算（shoelace），与 M8 计量口径可直接对账。

图像落盘一律 ``imencode/imdecode`` 字节缓冲（中文路径红线），见
``beaneye.acquisition.base.imwrite_bgr``。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
import yaml

from beaneye.acquisition.base import imwrite_bgr, write_json
from beaneye.calibration.config import load_tray_config
from beaneye.synth.beans import (
    BeanSpec,
    Sprite,
    bean_polygon_mm,
    render_sprite,
    sample_library,
    sample_spec,
)
from beaneye.synth.config import (
    ComposeConfig,
    SynthConfigError,
    config_to_dict,
    load_compose_config,
)

__all__ = [
    "BeanPlacement",
    "SynthTray",
    "SynthComposeError",
    "compose_tray",
    "labels_to_json",
    "write_batch",
    "rle_encode",
    "rle_decode",
    "rasterize_poly_mm",
]

GENERATOR_ID = "beaneye.synth.compose/v1 (W12b)"
_LABELS_VERSION = 1


class SynthComposeError(ValueError):
    """铺盘合成失败（配置/素材/几何不自洽）。"""


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class BeanPlacement:
    """盘面上一粒豆的布局与双面真值（M1 兼容标注的来源）。"""

    bean_id: str
    cls: str  # taxonomy key（上下同类，M12 成对语义）
    center_mm: tuple[float, float]
    spec_top: BeanSpec
    spec_bottom: BeanSpec
    poly_mm_top: np.ndarray
    poly_mm_bottom: np.ndarray
    area_mm2: float
    eq_diameter_mm: float
    bbox_mm: tuple[float, float, float, float]
    centroid_mm: tuple[float, float]
    contact_bean: bool  # 是否按「接触/重叠目标」放置
    overlap_with: list[int] = field(default_factory=list)  # 轮廓相交的盘内索引

    @property
    def variant_top(self) -> str:
        return self.spec_top.variant_id

    @property
    def variant_bottom(self) -> str:
        return self.spec_bottom.variant_id


@dataclass
class SynthTray:
    """一盘合成结果：双面整盘图 + 布局真值 + 实际生效配置。"""

    seed: int
    scan_id: str
    config: ComposeConfig
    config_echo: dict  # config_to_dict（manifest 回读可复现）
    top_bgr: np.ndarray
    bottom_bgr: np.ndarray
    beans: list[BeanPlacement]
    overlap_pairs: list[tuple[int, int]]  # 排序后的 (i, j)，i<j
    contact_target: int  # 目标接触/重叠豆数
    n_contact_placed: int  # 实际按接触/重叠放置成功数
    px_per_mm: float
    origin_px: tuple[float, float]  # 盘面 (0,0)mm 在画布上的像素坐标
    tray_mm: float
    marker_mm: float
    rle_grid_px: int  # RLE/真值栅格用的托盘 mm 网格边长（configs/tray.yaml）

    @property
    def canvas_size(self) -> tuple[int, int]:
        return int(self.top_bgr.shape[1]), int(self.top_bgr.shape[0])


# ---------------------------------------------------------------------------
# 真值栅格与 RLE（COCO 未压缩 counts，列主序）
# ---------------------------------------------------------------------------


def rasterize_poly_mm(
    poly_mm: np.ndarray | Sequence[Sequence[float]],
    *,
    grid_px: int,
    tray_mm: float,
    out: np.ndarray | None = None,
) -> np.ndarray:
    """盘面 mm 多边形 → 托盘 mm 网格二值掩码（grid_px²，OracleSeg 直接可用）。"""
    pts = np.round(np.asarray(poly_mm, dtype=np.float64) * (float(grid_px) / float(tray_mm)))
    pts = pts.astype(np.int32)
    if out is not None:
        if out.shape != (grid_px, grid_px):
            raise SynthComposeError(f"out 缓冲形状 {out.shape} != ({grid_px}, {grid_px})")
        out[:] = 0
        mask = out
    else:
        mask = np.zeros((grid_px, grid_px), dtype=np.uint8)
    cv2.fillPoly(mask, [pts], 255)
    return mask


def rle_encode(mask: np.ndarray) -> dict:
    """二值掩码 → COCO 未压缩 RLE（列主序 counts；契约友好的纯 JSON 结构）。"""
    h, w = int(mask.shape[0]), int(mask.shape[1])
    flat = (np.asarray(mask).T > 0).ravel()  # 转置后按行展开 = 原图列主序
    if flat.size == 0:
        return {"size": [h, w], "counts": []}
    change = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    bounds = np.concatenate([[0], change, [flat.size]])
    counts = np.diff(bounds).astype(int).tolist()
    if bool(flat[0]):
        counts = [0] + counts
    return {"size": [h, w], "counts": counts}


def rle_decode(rle: dict) -> np.ndarray:
    """:func:`rle_encode` 的逆（uint8 {0,255}）。"""
    h, w = (int(x) for x in rle["size"])
    counts = [int(c) for c in rle["counts"]]
    total = h * w
    if sum(counts) != total:
        raise SynthComposeError(f"RLE counts 总和 {sum(counts)} != size 积 {total}")
    flat = np.zeros(total, dtype=np.uint8)
    pos = 0
    val = 0
    for c in counts:
        if val:
            flat[pos : pos + c] = 255
        pos += c
        val = 1 - val
    return flat.reshape((w, h)).T


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def compose_tray(
    seed: int,
    *,
    config: ComposeConfig | None = None,
    library: dict[str, list[BeanSpec]] | None = None,
) -> SynthTray:
    """合成一盘：固定种子 → 布局 → 成对渲染 → 真值标注（全部确定性）。"""
    cfg = config if config is not None else load_compose_config()
    lib = library if library is not None else sample_library(cfg.library_seed, cfg.per_class)

    tray_cfg = load_tray_config()
    tray_mm = tray_cfg.tray_mm
    marker_mm = tray_cfg.marker_mm
    ppm = min(cfg.width_px, cfg.height_px) / (tray_mm + 2.0 * cfg.margin_mm)
    ox = (cfg.width_px - tray_mm * ppm) / 2.0
    oy = (cfg.height_px - tray_mm * ppm) / 2.0

    rng = np.random.default_rng([int(seed), 0])

    # ---- 目标数量与类别 ----------------------------------------------------
    n_target = int(rng.integers(cfg.n_beans_min, cfg.n_beans_max + 1))
    contact_target = min(int(rng.integers(cfg.contact_min, cfg.contact_max + 1)), n_target - 1) if n_target > 1 else 0
    defect_keys = sorted(cfg.class_weights)
    w = np.asarray([cfg.class_weights[k] for k in defect_keys], dtype=np.float64)
    classes: list[str] = []
    for _ in range(n_target):
        if rng.random() < cfg.defect_rate and defect_keys:
            classes.append(defect_keys[int(rng.choice(len(defect_keys), p=w / w.sum()))])
        else:
            classes.append("normal")
    for cls in set(classes):
        if cls not in lib:
            raise SynthComposeError(f"素材库缺类 {cls!r}（library 与配置类集不一致）")

    # ---- 抽豆（同 mm 同类成对：bottom 重采样变体、几何取 top） --------------
    def _pair_specs(cls: str) -> tuple[BeanSpec, BeanSpec]:
        top = sample_spec(
            lib[cls], rng, scale_jitter=cfg.scale_jitter, angle_jitter=cfg.angle_jitter
        )
        bottom = sample_spec(
            lib[cls], rng, scale_jitter=cfg.scale_jitter, angle_jitter=cfg.angle_jitter
        )
        # 同一粒豆的两面：几何（长轴/长宽比/弦切比例）必须一致——弦切比例
        # 若各面独立重采样，弓形段质心会横移数 mm（实测 3.2mm），破坏配对
        # 真值；颜色/纹理/孔斑/波纹相位等*外观*按 M12「另一粒」语义独立重采样。
        bottom = _with_geometry(bottom, top)
        if cfg.mirror_bottom:
            # 翻面镜像几何：bottom 朝向 = top 朝向的镜像角
            bottom = _replace(bottom, angle_deg=(-top.angle_deg) % 180.0)
        return top, bottom

    def _r_max(s: BeanSpec) -> float:
        return (s.length_mm / 2.0) * (1.0 + s.ripple_amp)

    # ---- 布局：自由摆放（不相交）+ 接触/重叠摆放 ---------------------------
    # 活动区 = 盘面内缩 margin_mm（默认 4mm 墙距）；四角码区（码 + 1/4 边长
    # 静区）单独按矩形避让——比「整体大内缩」多出近 3 倍可用盘面。
    margin = cfg.layout_margin_mm if cfg.layout_margin_mm is not None else 4.0
    lo, hi = margin, tray_mm - margin
    if hi - lo <= 8.0:
        raise SynthComposeError(f"豆心活动区过小：margin={margin}mm（盘边 {tray_mm}mm）")
    quiet = marker_mm / 4.0
    marker_rects = [
        (mx - marker_mm / 2.0 - quiet, my - marker_mm / 2.0 - quiet,
         mx + marker_mm / 2.0 + quiet, my + marker_mm / 2.0 + quiet)
        for mx, my in tray_cfg.centers_mm.values()
    ]

    placed: list[dict] = []  # {center, r, contact}
    n_free_target = max(0, n_target - contact_target)

    def _in_zone(p: tuple[float, float], r: float) -> bool:
        if not ((lo + r) <= p[0] <= (hi - r) and (lo + r) <= p[1] <= (hi - r)):
            return False
        for x0, y0, x1, y1 in marker_rects:
            qx = min(max(p[0], x0), x1)  # 圆心到矩形最近点
            qy = min(max(p[1], y0), y1)
            if math.hypot(p[0] - qx, p[1] - qy) < r:
                return False  # 与四角码区（含静区）相交
        return True

    def _fits(p: tuple[float, float], r: float) -> bool:
        return all(
            math.hypot(p[0] - q["center"][0], p[1] - q["center"][1])
            > cfg.free_factor * (r + q["r"])
            for q in placed
        )

    specs: list[tuple[BeanSpec, BeanSpec]] = []
    for _ in range(n_target):
        specs.append(_pair_specs(classes[len(specs)]))

    for i in range(n_free_target):
        top, _ = specs[i]
        r = _r_max(top)
        for _try in range(120):
            p = (float(rng.uniform(lo + r, hi - r)), float(rng.uniform(lo + r, hi - r)))
            if _in_zone(p, r) and _fits(p, r):
                placed.append({"center": p, "r": r, "contact": False})
                break
        # 120 次未放下则弃粒（盘满）——实际粒数记录在 manifest

    n_contact_placed = 0
    for i in range(n_free_target, n_target):
        top, _ = specs[i]
        r = _r_max(top)
        ok = False
        for _try in range(40):
            if not placed:
                break
            anchor = placed[int(rng.integers(0, len(placed)))]
            ang = float(rng.uniform(0.0, 2.0 * math.pi))
            d = cfg.overlap_depth * (r + anchor["r"])
            p = (
                anchor["center"][0] + d * math.cos(ang),
                anchor["center"][1] + d * math.sin(ang),
            )
            if _in_zone(p, r):
                placed.append({"center": p, "r": r, "contact": True})
                n_contact_placed += 1
                ok = True
                break
        if not ok:
            break  # 摆不进（活动区太小）——保留已得粒数

    n_placed = len(placed)
    if n_placed == 0:
        raise SynthComposeError(f"布局失败：一盘豆都没放下（n_target={n_target}，活动区 [{lo},{hi}]mm）")

    # ---- 稳定排序 + bean_id + 多边形真值 ------------------------------------
    order = sorted(range(n_placed), key=lambda i: (round(placed[i]["center"][1], 3), round(placed[i]["center"][0], 3)))
    beans: list[BeanPlacement] = []
    for k, idx in enumerate(order):
        pl = placed[idx]
        top, bottom = specs[idx]
        poly_t = bean_poly_mm(top, pl["center"])
        poly_b = bean_poly_mm(bottom, pl["center"])
        area = _shoelace_area_mm2(poly_t)
        beans.append(
            BeanPlacement(
                bean_id=f"b{k + 1:04d}",
                cls=classes[idx],
                center_mm=(float(pl["center"][0]), float(pl["center"][1])),
                spec_top=top,
                spec_bottom=bottom,
                poly_mm_top=poly_t,
                poly_mm_bottom=poly_b,
                area_mm2=area,
                eq_diameter_mm=2.0 * math.sqrt(max(area, 1e-9) / math.pi),
                bbox_mm=_bbox_mm(poly_t),
                centroid_mm=_centroid_mm(poly_t),
                contact_bean=bool(pl["contact"]),
                overlap_with=[],
            )
        )

    # ---- 接触/重叠判定：轮廓凸包相交面积 > 0.01 mm² -------------------------
    hulls = [cv2.convexHull(np.round(b.poly_mm_top, 3).astype(np.float32)) for b in beans]
    overlap_pairs: list[tuple[int, int]] = []
    for i in range(len(beans)):
        for j in range(i + 1, len(beans)):
            area_ij, _ = cv2.intersectConvexConvex(hulls[i], hulls[j])
            if float(area_ij) > 0.01:
                overlap_pairs.append((i, j))
                beans[i].overlap_with.append(j)
                beans[j].overlap_with.append(i)

    # ---- 渲染 ---------------------------------------------------------------
    sprites: dict[str, list[Sprite]] = {"top": [], "bottom": []}
    for side_i, side in enumerate(("top", "bottom")):
        for bi, b in enumerate(beans):
            spec = b.spec_top if side == "top" else b.spec_bottom
            srng = np.random.default_rng([int(seed), 7, side_i, bi])
            sprites[side].append(render_sprite(spec, ppm, srng))

    top_img = _render_side(
        seed, 0, "top", cfg, sprites["top"], beans, placed, order,
        ppm, ox, oy, tray_cfg,
    )
    bottom_img = _render_side(
        seed + 1, 1, "bottom", cfg, sprites["bottom"], beans, placed, order,
        ppm, ox, oy, tray_cfg,
    )

    scan_id = f"synth_{int(seed):06d}"
    return SynthTray(
        seed=int(seed),
        scan_id=scan_id,
        config=cfg,
        config_echo=config_to_dict(cfg),
        top_bgr=top_img,
        bottom_bgr=bottom_img,
        beans=beans,
        overlap_pairs=overlap_pairs,
        contact_target=contact_target,
        n_contact_placed=n_contact_placed,
        px_per_mm=float(ppm),
        origin_px=(float(ox), float(oy)),
        tray_mm=float(tray_mm),
        marker_mm=float(marker_mm),
        rle_grid_px=int(tray_cfg.grid_px),
    )


# ---------------------------------------------------------------------------
# 内部：小工具
# ---------------------------------------------------------------------------


def _replace(spec: BeanSpec, **kw: Any) -> BeanSpec:
    from dataclasses import replace as dc_replace

    return dc_replace(spec, **kw)


def _with_geometry(spec: BeanSpec, ref: BeanSpec) -> BeanSpec:
    """bottom 同 mm 约束：长轴/长宽比/弦切比例取参照粒（同一粒豆的两面）。"""
    return _replace(spec, length_mm=ref.length_mm, aspect=ref.aspect, cut=ref.cut)


def bean_poly_mm(spec: BeanSpec, center: tuple[float, float]) -> np.ndarray:
    """豆本地多边形（beans.bean_polygon_mm）→ 盘面 mm 坐标（平移到布局中心）。"""
    poly = bean_polygon_mm(spec)
    return poly + np.asarray(center, dtype=np.float64)[None, :]


def _shoelace_area_mm2(poly: np.ndarray) -> float:
    x = poly[:, 0]
    y = poly[:, 1]
    return float(abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2.0)


def _bbox_mm(poly: np.ndarray) -> tuple[float, float, float, float]:
    x0, y0 = poly.min(axis=0)
    x1, y1 = poly.max(axis=0)
    return (float(x0), float(y0), float(x1), float(y1))


def _centroid_mm(poly: np.ndarray) -> tuple[float, float]:
    m = cv2.moments(np.round(poly, 3).astype(np.float32))
    if m["m00"] > 0:
        return (float(m["m10"] / m["m00"]), float(m["m01"] / m["m00"]))
    return (float(poly[:, 0].mean()), float(poly[:, 1].mean()))


# ---------------------------------------------------------------------------
# 渲染：背景 → 逐豆（阴影 + 贴片）→ 四角码 → 光照/暗角/颗粒
# ---------------------------------------------------------------------------


def _render_side(
    seed: int,
    side_i: int,
    side: str,
    cfg: ComposeConfig,
    sprites: Sequence[Sprite],
    beans: Sequence[BeanPlacement],
    placed: Sequence[dict],
    order: Sequence[int],
    ppm: float,
    ox: float,
    oy: float,
    tray_cfg: Any,
) -> np.ndarray:
    h, w = cfg.height_px, cfg.width_px
    rng = np.random.default_rng([int(seed), 11, side_i])

    # 背景：亚克力底色 + 细噪声
    canvas = np.empty((h, w, 3), dtype=np.int16)
    canvas[:] = np.asarray(cfg.background_bgr, dtype=np.int16)[None, None, :]
    canvas += rng.integers(-3, 4, size=(h, w, 1), dtype=np.int16)
    img = np.clip(canvas, 0, 255).astype(np.uint8)

    # 亚克力反光简化：1/8 尺度上画两条斜向白带 → 模糊放大 → 低权重叠加
    if cfg.specular_streaks:
        sw, sh = max(32, w // 8), max(32, h // 8)
        streak = np.zeros((sh, sw), dtype=np.float32)
        for k in range(2):
            cxs = int(sw * (0.25 + 0.5 * k)) + int(rng.integers(-sw // 10, sw // 10 + 1))
            cv2.ellipse(
                streak, (cxs, sh // 2), (sw // 10, sh), 20 + 10 * k, 0, 360,
                1.0, -1,
            )
        streak = cv2.GaussianBlur(streak, (0, 0), 8.0)
        streak = cv2.resize(streak, (w, h), interpolation=cv2.INTER_LINEAR)[..., None]
        img = np.clip(img.astype(np.float32) + streak * (255.0 * 0.10), 0, 255).astype(np.uint8)

    # 逐豆：z 序 = 自由摆放先、接触/重叠后（后者在上层）
    z_order = [i for i in range(len(beans)) if not placed[order[i]]["contact"]] + [
        i for i in range(len(beans)) if placed[order[i]]["contact"]
    ]
    for bi in z_order:
        bean = beans[bi]
        sp = sprites[bi]
        px = ox + bean.center_mm[0] * ppm - sp.center_px[0]
        py = oy + bean.center_mm[1] * ppm - sp.center_px[1]
        pxi, pyi = int(round(px)), int(round(py))
        if cfg.shadow_enabled and cfg.shadow_strength > 0:
            _paste_shadow(
                img, sp.alpha,
                pxi + int(round(cfg.shadow_offset_mm[0] * ppm)),
                pyi + int(round(cfg.shadow_offset_mm[1] * ppm)),
                cfg.shadow_blur_px, cfg.shadow_strength,
            )
        _paste_sprite(img, sp, pxi, pyi)

    # 四角 ArUco（id=0..3，几何单一真源 configs/tray.yaml；码贴盘角，豆不进入码区）
    _draw_corner_markers(img, ppm, ox, oy, tray_cfg)

    # 全局光照：gamma → 增益（浮点链，末次钳制）
    out = img.astype(np.float32)
    gamma = float(rng.uniform(*cfg.light_gamma))
    gain = float(rng.uniform(*cfg.light_gain))
    lut = np.clip(np.round(255.0 * (np.arange(256, dtype=np.float64) / 255.0) ** (1.0 / gamma)), 0, 255).astype(np.uint8)
    out = cv2.LUT(out.astype(np.uint8), lut).astype(np.float32)
    out *= gain
    # 暗角（两个 1-D 距离场的外积和，避免 2048² int 网格开销）
    if cfg.vignette_strength > 0:
        fx = ((np.arange(w, dtype=np.float32) - w / 2.0) / (w / 2.0)) ** 2
        fy = ((np.arange(h, dtype=np.float32) - h / 2.0) / (h / 2.0)) ** 2
        d2 = fy[:, None] + fx[None, :]
        vig = (1.0 - cfg.vignette_strength * np.clip(d2 / 2.0, 0.0, 1.0)).astype(np.float32)
        out *= vig[..., None]
    # 颗粒噪声
    if cfg.grain_sigma > 0:
        out += rng.normal(0.0, cfg.grain_sigma, size=(h, w, 1)).astype(np.float32)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def _paste_sprite(canvas: np.ndarray, sp: Sprite, x0: int, y0: int) -> None:
    """sprite 以软边 alpha 贴入画布（alpha 真值本身保持二值，不参与渲染混合）。"""
    sh, sw = sp.alpha.shape
    ch_, cw_ = canvas.shape[:2]
    sx0 = max(0, -x0)
    sy0 = max(0, -y0)
    dx0 = max(0, x0)
    dy0 = max(0, y0)
    cw = min(sw - sx0, cw_ - dx0)
    chh = min(sh - sy0, ch_ - dy0)
    if cw <= 0 or chh <= 0:
        return
    soft = cv2.GaussianBlur(sp.alpha, (3, 3), 0).astype(np.float32) / 255.0
    a = soft[sy0 : sy0 + chh, sx0 : sx0 + cw][..., None]
    region = canvas[dy0 : dy0 + chh, dx0 : dx0 + cw].astype(np.float32)
    col = sp.bgr[sy0 : sy0 + chh, sx0 : sx0 + cw].astype(np.float32)
    canvas[dy0 : dy0 + chh, dx0 : dx0 + cw] = np.clip(
        region * (1.0 - a) + col * a + 0.5, 0, 255
    ).astype(np.uint8)


def _paste_shadow(
    canvas: np.ndarray, alpha: np.ndarray, x0: int, y0: int, blur_px: float, strength: float
) -> None:
    """投影：豆轮廓 alpha 偏移 + 模糊 → 暗化系数贴入画布。

    模糊在手动零填充的扩边数组上进行，且**扩边随模糊结果一起粘贴**——
    若裁回原 sprite 尺寸，σ 尾部在数组边界仍有 ~25% 幅值，会切出「矩形
    阴影」伪影（cv2 高斯模糊缺省 BORDER_REFLECT 亦会反射边缘能量，两坑
    同源，均实测踩坑）。
    """
    pad = int(3.0 * blur_px) + 1 if blur_px > 0 else 0
    if pad:
        padded = np.pad(alpha, pad, mode="constant")
        shadow = cv2.GaussianBlur(padded, (0, 0), blur_px)
    else:
        shadow = alpha
    sh_h, sh_w = shadow.shape[:2]
    ch_, cw_ = canvas.shape[:2]
    x0 -= pad
    y0 -= pad
    sx0 = max(0, -x0)
    sy0 = max(0, -y0)
    dx0 = max(0, x0)
    dy0 = max(0, y0)
    cw = min(sh_w - sx0, cw_ - dx0)
    chh = min(sh_h - sy0, ch_ - dy0)
    if cw <= 0 or chh <= 0:
        return
    a = (shadow[sy0 : sy0 + chh, sx0 : sx0 + cw].astype(np.float32) / 255.0 * strength)[..., None]
    region = canvas[dy0 : dy0 + chh, dx0 : dx0 + cw].astype(np.float32)
    canvas[dy0 : dy0 + chh, dx0 : dx0 + cw] = np.clip(region * (1.0 - a) + 0.5, 0, 255).astype(
        np.uint8
    )


def _draw_corner_markers(
    img: np.ndarray, ppm: float, ox: float, oy: float, tray_cfg: Any
) -> None:
    """四角 ArUco id=0..3（与 mock 采集源同款已验证 API；几何出自 tray.yaml）。"""
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    side_px = max(16, int(round(tray_cfg.marker_mm * ppm)))
    half_px = side_px // 2
    pad = max(4, side_px // 4)
    tile_side = 2 * (half_px + pad)
    h, w = img.shape[:2]
    for mid, (mx, my) in tray_cfg.centers_mm.items():
        marker = cv2.aruco.generateImageMarker(dictionary, int(mid), side_px)
        tile = np.full((tile_side, tile_side, 3), 255, dtype=np.uint8)
        tile[pad : pad + side_px, pad : pad + side_px] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        cx = int(round(ox + float(mx) * ppm))
        cy = int(round(oy + float(my) * ppm))
        x0, y0 = cx - half_px - pad, cy - half_px - pad
        dst = img[max(0, y0) : min(h, y0 + tile_side), max(0, x0) : min(w, x0 + tile_side)]
        src = tile[
            max(0, -y0) : tile_side - max(0, y0 + tile_side - h),
            max(0, -x0) : tile_side - max(0, x0 + tile_side - w),
        ]
        dst[...] = src


# ---------------------------------------------------------------------------
# 标注输出：labels JSON（M1 兼容 + COCO RLE）+ manifest.yaml + 落盘
# ---------------------------------------------------------------------------


def labels_to_json(tray: SynthTray, *, with_rle: bool = True) -> dict:
    """合成盘 → M1 兼容逐粒标注 dict（确定性；不含墙钟时间）。

    - 多边形/面积/质心/外接框全部先按 3 位小数取整再计算——JSON 往返后
      重算恒等（字节级复现与真值一致性检验的共同根）；
    - ``rle_top/rle_bottom`` 在托盘 mm 网格（configs/tray.yaml ``grid_px``）
      上由同一取整多边形栅格化而来：解码掩码与按标注多边形自栅格化
      **逐字节一致**（真值直出的可检验定义）。
    """
    beans_json: list[dict] = []
    rle_mask: np.ndarray | None = (
        np.zeros((tray.rle_grid_px, tray.rle_grid_px), dtype=np.uint8) if with_rle else None
    )
    for b in beans_iter(tray):
        poly_t = [[round(float(x), 3) for x in p] for p in b.poly_mm_top]
        poly_b = [[round(float(x), 3) for x in p] for p in b.poly_mm_bottom]
        entry: dict[str, Any] = {
            "bean_id": b.bean_id,
            "class_top": b.cls,
            "class_bottom": b.cls,  # M12 成对语义：重采样同 mm 同类另一粒
            "variant_top": b.variant_top,
            "variant_bottom": b.variant_bottom,
            "center_mm": [round(b.center_mm[0], 3), round(b.center_mm[1], 3)],
            "centroid_mm": [round(b.centroid_mm[0], 3), round(b.centroid_mm[1], 3)],
            "bbox_mm": [round(v, 3) for v in b.bbox_mm],
            "area_mm2": round(b.area_mm2, 3),
            "eq_diameter_mm": round(b.eq_diameter_mm, 3),
            "cie_lab_top": [round(v, 2) for v in b.spec_top.cie_lab],
            "cie_lab_bottom": [round(v, 2) for v in b.spec_bottom.cie_lab],
            "contact_bean": b.contact_bean,
            "overlap_with": list(b.overlap_with),
            "poly_mm_top": poly_t,
            "poly_mm_bottom": poly_b,
        }
        if with_rle and rle_mask is not None:
            for key, poly in (("rle_top", poly_t), ("rle_bottom", poly_b)):
                rasterize_poly_mm(poly, grid_px=tray.rle_grid_px, tray_mm=tray.tray_mm, out=rle_mask)
                entry[key] = rle_encode(rle_mask)
        beans_json.append(entry)

    return {
        "labels_version": _LABELS_VERSION,
        "generator": GENERATOR_ID,
        "scan_id": tray.scan_id,
        "seed": tray.seed,
        "tray": {
            "tray_mm": tray.tray_mm,
            "marker_mm": tray.marker_mm,
            "canvas_px": list(tray.canvas_size),
            "px_per_mm": round(tray.px_per_mm, 6),
            "origin_px": [round(v, 3) for v in tray.origin_px],
            "rle_grid_px": tray.rle_grid_px,
            "config_source": "configs/tray.yaml",
        },
        "config": tray.config_echo,
        "counts": {
            "n_target": len(tray.beans),
            "n_placed": len(tray.beans),
            "contact_target": tray.contact_target,
            "n_contact_placed": tray.n_contact_placed,
            "n_overlap_pairs": len(tray.overlap_pairs),
            "defect_rate": tray.config.defect_rate,
        },
        "overlap_pairs": [[i, j] for i, j in tray.overlap_pairs],
        "beans": beans_json,
    }


def beans_iter(tray: SynthTray):
    """按 bean_id 序遍历（labels 输出顺序 = 布局排序序）。"""
    return iter(tray.beans)


def write_batch(
    tray: SynthTray,
    out_dir: str | Path,
    *,
    index: int = 1,
    with_rle: bool = True,
) -> dict[str, Path]:
    """落盘一个合成 batch：整盘双面图 + labels JSON + manifest.yaml。

    manifest.yaml 与 configs/synth.yaml 同 schema（标准 YAML 输入格式），
    另带 seed/scan_id/文件清单——回读 :func:`load_compose_config` 后以同
    seed 可字节级复现本批。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{tray.scan_id}"
    top_p = out / f"top_{index:04d}.png"
    bottom_p = out / f"bottom_{index:04d}.png"
    labels_p = out / f"labels_{index:04d}.json"
    manifest_p = out / f"manifest_{index:04d}.yaml"

    imwrite_bgr(top_p, tray.top_bgr)
    imwrite_bgr(bottom_p, tray.bottom_bgr)
    labels = labels_to_json(tray, with_rle=with_rle)
    write_json(labels_p, labels)

    manifest = {
        "manifest_version": 1,
        "generator": GENERATOR_ID,
        "scan_id": tray.scan_id,
        "seed": tray.seed,
        "config": tray.config_echo,
        "files": {
            "top_image": top_p.name,
            "bottom_image": bottom_p.name,
            "labels": labels_p.name,
        },
    }
    manifest_p.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"top": top_p, "bottom": bottom_p, "labels": labels_p, "manifest": manifest_p}
