"""M4 分割 eval（W4b · ClassicSeg）。

运行（仓库根）::

    pytest tests/test_segment.py -q

覆盖与通过线（plan/开发指令.md §4 M4 的 Classic 部分 + W4b 任务书）：

1. **稀疏盘**（40 粒无粘连，经 透视渲染→ArUco 标定→warp 全路径）：
   粒数误差 ≤5%、平均 IoU ≥0.85（任务书达标线）；
2. **接触对分离召回**：12 对粘连豆切分召回 ≥0.70（任务书要求考核该指标
   但未给线，此线为本任务自定并如实记录；M4 spec 已声明粘连是 ClassicSeg
   已知短板，NN 上线前另有宽松粒数线）；
3. **边缘豆**：贴边裁切条（部分出画）须以部分掩码检出、近缘完整豆正常
   IoU；
4. 角码不被报成豆；空盘 0 掩码；契约（SegResult/BeanMask 校验 + JSON 往返
   + 掩码有序稳定）；确定性；2048² 网格 ≤5s CPU（M4 spec 12MP ≤5s 线按
   管线实际分割输入口径执行：M13 管线喂给分割的是 2048² 正射网格，非
   12MP 原图）；``build_default`` 工厂被 M13 装配器零改动接线；配置加载
   与非法配置拒绝。

**夹具说明（依赖注记）**：W12 合成器（beaneye.synth）尚未提交，按任务书
改用简化程序化豆夹具（tests/_segment_synth.py：椭圆豆 + 四角定位码 +
逐豆像素真值，独立于被测模块构造真值）。W12 就绪后应换成真合成器输出
并保留同样的指标口径。
"""

from __future__ import annotations

import math
import re
import time

import cv2
import numpy as np
import pytest
from scipy.optimize import linear_sum_assignment

from _calib_views import ViewSpec, render_view
from _segment_synth import (
    GRID_PX,
    PPM,
    TRAY_MM,
    Bean,
    make_scene,
    place_sparse,
    place_touching_scene,
)

from beaneye.app.components import build_components
from beaneye.calibration import calibrate, load_tray_config, warp_to_tray
from beaneye.schemas import SegResult, TrayScan
from beaneye.segment import ClassicSeg, build_default
from beaneye.segment.config import (
    DEFAULT_CONFIG_PATH,
    SegmentConfigError,
    load_segment_config,
)

MM_PER_PX = TRAY_MM / GRID_PX
MASK_ID_RE = re.compile(r"^top_\d{4}$")


# ---------------------------------------------------------------------------
# 夹具与度量工具
# ---------------------------------------------------------------------------


def make_scan(scan_id: str = "seg-eval") -> TrayScan:
    """构造最小合法 TrayScan（分割只读 scan_id）。"""
    return TrayScan(
        scan_id=scan_id,
        sample_id="s-eval",
        tray_id="t-eval",
        top_image="img/top.png",
        bottom_image="img/bottom.png",
        calibration=None,
        captured_at="2026-09-29T10:00:00+00:00",
        source="synth",
    )


def run_full_path(scene, spec: ViewSpec) -> tuple[np.ndarray, np.ndarray]:
    """合成画布 → 透视视图 → 标定 → warp → (正射 RGB 图, 正射逐豆真值)。

    前半段复用既有 M3 基建（_calib_views + beaneye.calibration，均有独立
    eval 把关）；真值标签用与 warp_to_tray 完全相同的复合矩阵
    ``S·H_est·H_canvas``（INTER_NEAREST）搬到正射网格，与预测像素对齐。
    """
    view, H_mm_px = render_view(scene.canvas, TRAY_MM, 0.0, PPM, spec)
    st = calibrate(view)
    tray_cfg = load_tray_config()
    warped_rgb = warp_to_tray(view, np.asarray(st.H, dtype=np.float64), tray_cfg)
    s = tray_cfg.grid_px / tray_cfg.tray_mm
    S = np.array([[s, 0, 0], [0, s, 0], [0, 0, 1.0]])
    A = np.array([[1.0 / PPM, 0, 0], [0, 1.0 / PPM, 0], [0, 0, 1.0]])
    H_canvas = H_mm_px @ A  # 画布 px → 视图 px（_calib_views 同一公式）
    M = S @ np.asarray(st.H, dtype=np.float64) @ H_canvas
    lab = cv2.warpPerspective(
        scene.label.astype(np.float32),
        M,
        (GRID_PX, GRID_PX),
        flags=cv2.INTER_NEAREST,
    )
    return warped_rgb, np.rint(lab).astype(np.int32)


def rasterize_masks(masks) -> list[np.ndarray]:
    """BeanMask.polygon（mm）→ 正射网格布尔掩码（测试侧独立栅格化）。"""
    out = []
    for m in masks:
        poly = np.asarray(m.polygon, dtype=np.float32) / MM_PER_PX
        canvas = np.zeros((GRID_PX, GRID_PX), dtype=np.uint8)
        cv2.fillPoly(canvas, [np.round(poly).astype(np.int32)], 1)
        out.append(canvas.astype(bool))
    return out


def gt_masks_of(label: np.ndarray, n: int) -> list[np.ndarray]:
    return [label == k for k in range(1, n + 1)]


def iou(a: np.ndarray, b: np.ndarray) -> float:
    union = int((a | b).sum())
    return float((a & b).sum()) / union if union else 0.0


def match_greedy_hungarian(gts, preds) -> tuple[list[float], list[int]]:
    """一对一最大 IoU 匹配；返回 (逐 GT IoU, 配到的 pred 下标，未配=-1)。"""
    if not preds:
        return [0.0] * len(gts), [-1] * len(gts)
    mat = np.zeros((len(gts), len(preds)), dtype=np.float64)
    for i, g in enumerate(gts):
        for j, p in enumerate(preds):
            mat[i, j] = iou(g, p)
    row, col = linear_sum_assignment(1.0 - mat)
    best = [0.0] * len(gts)
    which = [-1] * len(gts)
    for r, c in zip(row, col):
        if mat[r, c] > 0.05:
            best[r] = float(mat[r, c])
            which[r] = int(c)
    return best, which


# ---------------------------------------------------------------------------
# 1) 稀疏盘：粒数误差 ≤5% + 平均 IoU ≥0.85（全路径：透视→标定→warp→分割）
# ---------------------------------------------------------------------------


def test_sparse_tray_count_error_and_mean_iou():
    scene = make_scene(place_sparse(40, seed=11), seed=7)
    warped, label = run_full_path(
        scene,
        ViewSpec(rx_deg=4.0, rz_deg=15.0, out_w=2400, out_h=1800, fill=0.9,
                 noise_sigma=2.5, seed=5),
    )
    res = ClassicSeg().predict(warped, make_scan())
    preds = rasterize_masks(res.masks)
    n_gt = len(scene.beans)

    count_err = abs(len(preds) - n_gt) / n_gt
    assert count_err <= 0.05, f"粒数误差 {count_err:.1%}（pred={len(preds)}, gt={n_gt}）"

    ious, _ = match_greedy_hungarian(gt_masks_of(label, n_gt), preds)
    mean_iou = float(np.mean(ious))
    assert mean_iou >= 0.85, f"稀疏盘平均 IoU {mean_iou:.3f} < 0.85"
    assert min(ious) > 0.5, f"存在完全失配的豆（最小逐豆 IoU={min(ious):.3f}）"


# ---------------------------------------------------------------------------
# 2) 接触对分离召回（自定线 ≥0.70，任务书未给线，如实记录）
# ---------------------------------------------------------------------------


def test_touching_pairs_separation_recall():
    beans, pairs = place_touching_scene(12, 10, seed=23)
    scene = make_scene(beans, seed=9)
    # 夹具自检：每对真值并集必须是单一连通域（真·接触）
    for i, j in pairs:
        union = (scene.label == (i + 1)) | (scene.label == (j + 1))
        n_comp = cv2.connectedComponents(union.astype(np.uint8), connectivity=8)[0] - 1
        assert n_comp == 1, f"夹具缺陷：第 {i}/{j} 对真值并集有 {n_comp} 个连通域"

    warped, label = run_full_path(
        scene,
        ViewSpec(rz_deg=8.0, out_w=2400, out_h=1800, fill=0.9, noise_sigma=2.0, seed=6),
    )
    res = ClassicSeg().predict(warped, make_scan())
    preds = rasterize_masks(res.masks)

    separated = 0
    for i, j in pairs:
        gi, gj = label == (i + 1), label == (j + 1)
        hits_i = [k for k, p in enumerate(preds) if iou(gi, p) >= 0.5]
        hits_j = [k for k, p in enumerate(preds) if iou(gj, p) >= 0.5]
        if any(hi != hj for hi in hits_i for hj in hits_j):
            separated += 1
    recall = separated / len(pairs)
    assert recall >= 0.70, f"接触对分离召回 {recall:.2f}（{separated}/{len(pairs)}）< 0.70"

    # 粒数护栏：切分不应把整盘切碎（34 理想；粘连切不开是已知短板允许少报，
    # 但单粒被误切/碎片多报不该发生）
    assert 30 <= len(preds) <= 40, f"全盘粒数 {len(preds)} 超出 [30,40]（理想 34）"


# ---------------------------------------------------------------------------
# 3) 边缘豆：裁切条以部分掩码检出；近缘完整豆正常 IoU
# ---------------------------------------------------------------------------


def test_edge_beans_partial_masks_at_tray_border():
    beans = [
        Bean(cx=1.5, cy=150.0, semi_a=3.4, semi_b=2.6, angle_deg=25.0),   # 左缘裁切
        Bean(cx=298.5, cy=150.0, semi_a=3.2, semi_b=2.8, angle_deg=-40.0),  # 右缘裁切
        Bean(cx=80.0, cy=1.2, semi_a=3.6, semi_b=2.7, angle_deg=60.0),    # 上缘裁切
        Bean(cx=150.0, cy=298.8, semi_a=3.3, semi_b=3.0, angle_deg=0.0),  # 下缘裁切
        Bean(cx=12.0, cy=100.0, semi_a=3.8, semi_b=2.9, angle_deg=10.0),  # 近缘完整
        Bean(cx=285.0, cy=210.0, semi_a=3.5, semi_b=3.1, angle_deg=80.0),  # 近缘完整
    ]
    scene = make_scene(beans, seed=13)
    # 恒等 warp 的正射图也是合法分割输入（mm 线性映射不变）
    res = ClassicSeg().predict(scene.canvas, make_scan())
    preds = rasterize_masks(res.masks)
    assert len(preds) == len(beans), f"期望每豆一掩码（{len(beans)}），得到 {len(preds)}"

    gts = gt_masks_of(scene.label, len(beans))
    ious, which = match_greedy_hungarian(gts, preds)

    # 裁切条：对「画面内可见部分」的 IoU ≥0.7，质心距 ≤3mm（以部分掩码检出）
    for k in range(4):
        assert ious[k] >= 0.70, f"裁切条 {k} IoU={ious[k]:.3f} < 0.70"
        assert which[k] >= 0, f"裁切条 {k} 未匹配到任何输出掩码"
        gt_cx = float(np.mean(np.nonzero(gts[k])[1])) * MM_PER_PX
        gt_cy = float(np.mean(np.nonzero(gts[k])[0])) * MM_PER_PX
        m = res.masks[which[k]]
        dist = math.hypot(m.centroid_mm[0] - gt_cx, m.centroid_mm[1] - gt_cy)
        assert dist <= 3.0, f"裁切条 {k} 质心偏差 {dist:.2f}mm > 3mm"

    # 近缘完整豆：与全豆真值 IoU ≥0.8
    for k in range(4, 6):
        assert ious[k] >= 0.80, f"近缘完整豆 {k} IoU={ious[k]:.3f} < 0.80"


# ---------------------------------------------------------------------------
# 4) 角码不是豆；空盘 0 掩码
# ---------------------------------------------------------------------------


def test_markers_alone_and_blank_scene_report_zero_beans():
    scan = make_scan()
    markers_only = make_scene([], markers=True, seed=1)
    res = ClassicSeg().predict(markers_only.canvas, scan)
    assert len(res.masks) == 0, f"角码被误报为豆：{len(res.masks)} 个掩码"

    blank = make_scene([], markers=False, seed=2)
    res2 = ClassicSeg().predict(blank.canvas, scan)
    assert len(res2.masks) == 0


# ---------------------------------------------------------------------------
# 5) 契约：SegResult/BeanMask 校验、JSON 往返、有序稳定
# ---------------------------------------------------------------------------


def test_contract_segresult_beans_and_json_roundtrip():
    scene = make_scene(place_sparse(8, seed=17), seed=3)
    res = ClassicSeg().predict(scene.canvas, make_scan())
    assert isinstance(res, SegResult)
    assert res.side == "top" and res.scan_id == "seg-eval"
    assert len(res.masks) == 8
    assert res.runtime_s >= 0.0

    for i, m in enumerate(res.masks):
        assert MASK_ID_RE.match(m.mask_id), f"mask_id 格式：{m.mask_id!r}"
        assert m.mask_id == f"top_{i:04d}"  # 质心 y,x 排序后顺序编号
        assert m.side == "top" and m.source == "classic"
        assert 0.0 < m.conf <= 1.0
        assert len(m.polygon) >= 3 and all(len(p) == 2 for p in m.polygon)
        assert m.area_mm2 > 0
        x0, y0, x1, y1 = m.bbox_mm
        assert x0 <= x1 and y0 <= y1
        cx, cy = m.centroid_mm
        assert x0 - 1e-6 <= cx <= x1 + 1e-6 and y0 - 1e-6 <= cy <= y1 + 1e-6
        assert -1e-6 <= x0 and x1 <= TRAY_MM + 1e-6  # 盘面范围内

    # JSON 无损往返
    revived = SegResult.from_json(res.to_json())
    assert revived == res


# ---------------------------------------------------------------------------
# 6) 耗时：2048² 网格一次 predict ≤5s（M4 spec ≤5s 线，按管线实际输入口径）
# ---------------------------------------------------------------------------


def test_runtime_2048_grid_under_5s():
    scene = make_scene(place_sparse(60, min_gap=9.0, seed=19), seed=2)
    seg = ClassicSeg()
    t0 = time.perf_counter()
    res = seg.predict(scene.canvas, make_scan())
    dt = time.perf_counter() - t0
    assert len(res.masks) == 60
    assert dt <= 5.0, f"2048² 60 粒 predict 耗时 {dt:.2f}s > 5s"
    assert res.runtime_s <= dt + 1e-6  # runtime_s 口径自洽


# ---------------------------------------------------------------------------
# 7) 确定性 + M13 工厂接线
# ---------------------------------------------------------------------------


def test_determinism_same_input_same_output():
    scene = make_scene(place_sparse(15, seed=29), seed=4)
    scan = make_scan()
    a = ClassicSeg().predict(scene.canvas, scan)
    b = ClassicSeg().predict(scene.canvas, scan)
    # runtime_s 是计时量、逐次不同；确定性口径 = 掩码集合逐字段一致
    assert [m.to_json() for m in a.masks] == [m.to_json() for m in b.masks]


def test_build_default_factory_autowired_by_app_components():
    impl = build_default()
    assert isinstance(impl, ClassicSeg)
    comps = build_components(allow_probe=True)  # M13 装配器探测 beaneye.segment
    assert not comps.segment.degraded, (
        f"beaneye.segment 未被 M13 装配器接入：{comps.segment.reason}"
    )
    assert isinstance(comps.segment.impl, ClassicSeg)
    # 装配出的实现可用：空盘合法返回
    blank = make_scene([], markers=False, seed=8)
    seg_res = comps.segment.impl.predict(blank.canvas, make_scan("via-box"))
    assert seg_res.scan_id == "via-box" and len(seg_res.masks) == 0


# ---------------------------------------------------------------------------
# 8) 配置：默认值、仓库 YAML 与默认一致、非法配置拒绝
# ---------------------------------------------------------------------------


def test_config_defaults_and_repo_yaml_consistent():
    cfg = load_segment_config(None)
    assert cfg.source == "defaults"
    assert cfg.channel == "gray" and cfg.side == "top"
    assert cfg.bg_delta_gray == 25.0 and cfg.max_component_frac == 0.5
    assert cfg.min_area_mm2 == 6.0 and cfg.conf_single == 0.9 and cfg.conf_split == 0.72
    assert cfg.mask_markers is True

    from_repo = load_segment_config(DEFAULT_CONFIG_PATH)
    assert from_repo.channel == cfg.channel
    assert from_repo.blur_sigma_px == cfg.blur_sigma_px
    assert from_repo.open_ksize == cfg.open_ksize and from_repo.close_ksize == cfg.close_ksize
    assert from_repo.bg_delta_gray == cfg.bg_delta_gray
    assert from_repo.max_component_frac == cfg.max_component_frac
    assert from_repo.min_area_mm2 == cfg.min_area_mm2
    assert from_repo.peak_min_mm == cfg.peak_min_mm
    assert from_repo.peak_min_dist_mm == cfg.peak_min_dist_mm
    assert from_repo.seed_dominance == cfg.seed_dominance
    assert from_repo.seed_dominance_radius_mm == cfg.seed_dominance_radius_mm
    assert from_repo.mask_markers == cfg.mask_markers
    assert from_repo.conf_single == cfg.conf_single and from_repo.conf_split == cfg.conf_split
    assert from_repo.side == cfg.side


@pytest.mark.parametrize(
    "content",
    [
        "channel: bogus\n",  # 未知通道
        "open_ksize: 4\n",  # 偶数核
        "close_ksize: 0\n",  # <1
        "bg_delta_gray: 0\n",  # <1
        "max_component_frac: 1.5\n",  # 越界
        "min_area_mm2: 0\n",  # 非正
        "peak_min_mm: 0\n",  # 非正
        "peak_min_dist_mm: 0.5\npeak_min_mm: 1.0\n",  # 间距 ≤ 深度
        "seed_dominance: 1.5\n",  # 支配度越界
        "seed_dominance_radius_mm: 1.0\npeak_min_dist_mm: 1.8\n",  # 半径 ≤ 间距
        "conf_single: 2.0\n",  # conf 越界
        "side: left\n",  # 非法面
        "blur_sigma_px: -1\n",  # 负 σ
        "not a mapping",  # 顶层非映射
    ],
)
def test_config_rejects_invalid(tmp_path, content):
    p = tmp_path / "segment.yaml"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(SegmentConfigError):
        load_segment_config(p)
    with pytest.raises(SegmentConfigError):
        load_segment_config(tmp_path / "missing.yaml")
