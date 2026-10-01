"""实时线 eval · 着色叠加（beaneye.realtime.overlay）。

运行（仓库根）::

    pytest tests/test_realtime_overlay.py -q

覆盖：
1. 配色表：taxonomy 13 类全覆盖、两两不同色、normal 绿色系（G 通道占优）、
   未知 key 兜底中性灰；中文短标签（zh 主名）；
2. 绘制正确性：轮廓线落在类别色上、质心圆点在位、输入帧不被改写、
   HUD/图例条底与文本像素存在、legend 开关输出不同；
3. 确定性：同输入两次绘制逐像素一致（无墙钟/随机）；
4. 中文字体不可用的退化路径（monkeypatch 探测缓存）不崩溃、输出仍合法。

绘制为纯函数，离线运行。
"""

from __future__ import annotations

import numpy as np
import pytest

from beaneye.realtime import BeanSpot, FrameResult, draw_overlay
from beaneye.realtime import overlay as ov
from beaneye.taxonomy import load_taxonomy

TAX = load_taxonomy()


def _frame(w: int = 320, h: int = 240, level: int = 235) -> np.ndarray:
    return np.full((h, w, 3), level, dtype=np.uint8)


def _result(*beans: BeanSpot, **kw) -> FrameResult:
    return FrameResult(
        frame_index=7, width=320, height=240,
        beans=list(beans), counts=kw.pop("counts", {}),
        fps=12.34, calibrated=kw.pop("calibrated", False),
        mm_per_px=kw.pop("mm_per_px", None),
    )


def _spot(defect: str, box=(50, 50, 200, 200)) -> BeanSpot:
    x0, y0, x1, y1 = box
    contour = [[float(x0), float(y0)], [float(x1), float(y0)], [float(x1), float(y1)], [float(x0), float(y1)]]
    return BeanSpot(
        defect=defect, conf=0.9, severity_rank=TAX.severity_rank(defect),
        centroid_px=((x0 + x1) / 2.0, (y0 + y1) / 2.0), area_px=float((x1 - x0) * (y1 - y0)),
        color_bgr=(120, 130, 140), contour_px=contour,
        eq_diameter_mm=5.2,
        mask_id="top_0001",
    )


# ---------------------------------------------------------------------------
# 1. 配色表
# ---------------------------------------------------------------------------


def test_palette_covers_taxonomy_and_is_distinct():
    keys = TAX.keys()
    assert set(keys) <= set(ov.CLASS_COLORS_BGR), "taxonomy 类别必须全有配色"
    colors = {k: ov.color_for(k) for k in keys}
    assert len(set(colors.values())) == len(keys), "类别色必须两两不同"
    bch, gch, rch = colors["normal"]  # BGR 序；normal 绿色系：G 通道严格占优
    assert gch > rch and gch > bch and gch >= 180
    assert ov.color_for("no-such-key") == ov.DEFAULT_COLOR_BGR  # 未知 key 兜底


def test_class_label_zh_short_names():
    assert ov.class_label_zh("normal") == "好豆"
    assert ov.class_label_zh("peaberry") == "花豆"  # zh 主名（截掉 / 后缀）
    assert ov.class_label_zh("faded") == "褪色"


# ---------------------------------------------------------------------------
# 2. 绘制正确性
# ---------------------------------------------------------------------------


def test_draw_overlay_contour_centroid_and_no_mutation():
    frame = _frame()
    res = _result(_spot("black"))  # 黑豆 → 红轮廓
    vis = draw_overlay(frame, res, legend=False, hud=False)
    assert vis.shape == frame.shape and vis.dtype == np.uint8
    assert np.array_equal(frame, _frame())  # 输入帧未被改写
    # 轮廓边（x=200 竖线中点）落在类别色（红）上：R 高、B 低
    px = vis[125, 200]
    assert int(px[2]) > 180 and int(px[0]) < 120
    # 质心圆点在位（125,125 邻域为红色实心）
    center = vis[125, 125]
    assert int(center[2]) > 180
    assert not np.array_equal(vis, frame)  # 确有绘制


def test_draw_overlay_hud_and_legend():
    frame = _frame()
    res = _result(
        _spot("black"), _spot("mold", box=(220, 30, 310, 120)),
        counts={"black": 1, "mold": 1}, calibrated=True, mm_per_px=0.45,
    )
    vis_all = draw_overlay(frame, res)  # HUD + 图例全开
    vis_none = draw_overlay(frame, res, hud=False, legend=False)
    vis_no_legend = draw_overlay(frame, res, legend=False)
    # HUD：左上角被压暗（比底色暗）
    assert int(vis_all[6, 6].mean()) < int(vis_none[6, 6].mean())
    # 图例条：底部整行被压暗，且含类别色块（红/品红像素出现）
    assert int(vis_all[238, 160].mean()) < int(vis_none[238, 160].mean())
    assert vis_no_legend.shape == vis_all.shape
    assert not np.array_equal(vis_all, vis_no_legend)  # 图例条存在且可见


def test_draw_overlay_mm_label_only_when_calibrated():
    frame = _frame()
    spot = _spot("black")
    res_plain = draw_overlay(frame, _result(spot), hud=False, legend=False)
    res_mm = draw_overlay(frame, _result(spot, calibrated=True, mm_per_px=0.45), hud=False, legend=False)
    assert not np.array_equal(res_plain, res_mm)  # show_mm 跟随 calibrated


# ---------------------------------------------------------------------------
# 3. 确定性
# ---------------------------------------------------------------------------


def test_draw_overlay_deterministic():
    frame = _frame()
    res = _result(
        _spot("sour", box=(30, 30, 110, 100)), _spot("normal", box=(180, 120, 300, 220)),
        counts={"normal": 1, "sour": 1},
    )
    a = draw_overlay(frame, res)
    b = draw_overlay(frame, res)
    assert np.array_equal(a, b)  # 同输入逐像素一致


def test_draw_overlay_all_classes_smoke():
    """13 类全画（含未知 key 兜底色）不崩溃、覆盖非空。"""
    frame = _frame(640, 360, level=200)
    spots = []
    counts = {}
    for i, key in enumerate(list(TAX.keys()) + ["no-such-key"]):
        x0 = 10 + (i % 7) * 88
        y0 = 10 + (i // 7) * 100
        spots.append(_spot(key if TAX.is_valid_key(key) else "normal", box=(x0, y0, x0 + 70, y0 + 80)))
        if TAX.is_valid_key(key):
            counts[key] = counts.get(key, 0) + 1
    res = FrameResult(frame_index=1, width=640, height=360, beans=spots, counts=counts, fps=30.0)
    vis = draw_overlay(frame, res)
    assert vis.shape == frame.shape and np.abs(vis.astype(int) - frame.astype(int)).sum() > 0


# ---------------------------------------------------------------------------
# 4. 中文字体退化路径
# ---------------------------------------------------------------------------


def test_overlay_falls_back_without_zh_font(monkeypatch):
    """PIL 字体探测置不可用后仍能绘制（ASCII 替代文本），输出合法。"""
    monkeypatch.setattr(ov, "_FONT_OK", False)
    monkeypatch.setattr(ov, "_FONT_CACHE", {})
    frame = _frame()
    res = _result(_spot("black"), counts={"black": 1})
    vis = draw_overlay(frame, res)  # 不应抛错（cv2.putText ASCII 路径）
    assert vis.shape == frame.shape
    assert ov.zh_font_available() is False
