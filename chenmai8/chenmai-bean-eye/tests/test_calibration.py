"""M3 标定 eval（plan/开发指令.md §4 M3）。

素材：scripts/make_aruco.py 合成的带 ArUco 托盘图（子进程真实执行一次 CLI，
其余用例进程内复用 build_board），再经针孔投影（tests/_calib_views.py）加
透视/盘面旋转/亮度噪点扰动。真值 H_mm_px 由生成侧解析给出，被测模块不可见。

通过线（§4 M3 原文）：
  1. marker 中心反投影误差 ≤ 0.5 mm；
  2. px_per_mm 相对误差 ≤ 1%（真值 = 生成投影在盘面中心的局部 px/mm 尺度）；
  3. 四角顺序任意摆放仍正确配对（整体旋转 43/90/180/270° + id-角位置换布局）；
  4. 单张 12MP 处理 ≤ 3 s CPU；
  5. <4 码抛 CalibrationError（v1 无单码兜底）。

运行（仓库根）::

    pytest tests/test_calibration.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

import _calib_views as cvw
from beaneye.calibration import (
    CalibrationError,
    TrayConfig,
    TrayConfigError,
    calibrate,
    calibrate_pair,
    load_tray_config,
    mm_to_px,
    px_to_mm,
    warp_to_tray,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import make_aruco  # noqa: E402

TRAY_MM = 300.0
MARKER_MM = 60.0
P0 = 8  # 素材板分辨率 px/mm（make_aruco.build_board 要求 int，thickness 计算用）
MARGIN_MM = 10.0
MM_TOL = 0.5          # 通过线 1：marker 中心反投影误差
PPM_REL_TOL = 0.01    # 通过线 2：px_per_mm 相对误差
GRID_MM_AUX_TOL = 1.0 # 辅助：盘面任意点反投影（通过线只卡 marker 中心）


@pytest.fixture(scope="module")
def cfg() -> TrayConfig:
    return load_tray_config()


@pytest.fixture(scope="module")
def board_bgr() -> np.ndarray:
    canvas, _layout = make_aruco.build_board(TRAY_MM, MARKER_MM, P0, MARGIN_MM)
    return cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)


def _render(board_bgr: np.ndarray, spec: cvw.ViewSpec) -> tuple[np.ndarray, np.ndarray]:
    return cvw.render_view(board_bgr, TRAY_MM, MARGIN_MM, P0, spec)


def _assert_view(view: np.ndarray, H_gt: np.ndarray, cfg: TrayConfig) -> dict:
    """跑 calibrate 并断言通过线 1/2，返回误差与耗时摘要。"""
    t0 = time.perf_counter()
    cal = calibrate(view, cfg)
    dt = time.perf_counter() - t0

    errs = []
    for mid, c_gt in cfg.centers_mm.items():
        est = px_to_mm(cal.centers_px[mid], cal.H)
        errs.append(float(np.linalg.norm(np.asarray(est) - np.asarray(c_gt))))
    max_err = max(errs)

    ppm_gt = cvw.gt_scale_at(H_gt, (TRAY_MM / 2, TRAY_MM / 2))
    ppm_rel = abs(cal.px_per_mm - ppm_gt) / ppm_gt

    assert max_err <= MM_TOL, f"marker 中心反投影最大误差 {max_err:.3f}mm > {MM_TOL}mm"
    assert ppm_rel <= PPM_REL_TOL, f"px_per_mm 相对误差 {ppm_rel * 100:.2f}% > {PPM_REL_TOL * 100:.0f}%"
    assert cal.marker_ids == [0, 1, 2, 3]
    assert cal.reproj_err_px < 2.0, f"角点重投影 RMS 异常: {cal.reproj_err_px:.3f}px"
    return {"max_err_mm": max_err, "ppm_rel": ppm_rel, "reproj_px": cal.reproj_err_px, "seconds": dt}


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


def test_config_defaults_match_plan():
    """规划默认值：300mm 盘 / 60mm 码 / 2048 网格 / DICT_4X4_50，角位公式中心。"""
    cfg = load_tray_config()
    assert cfg.tray_mm == 300.0
    assert cfg.grid_px == 2048
    assert cfg.marker_mm == 60.0
    assert cfg.dictionary == "DICT_4X4_50"
    m2, T2 = cfg.marker_mm / 2, cfg.tray_mm - cfg.marker_mm / 2
    assert cfg.centers_mm == {
        0: (m2, m2),
        1: (T2, m2),
        2: (T2, T2),
        3: (m2, T2),
    }
    assert cfg.mm_per_px == pytest.approx(300.0 / 2048.0)  # ≈0.1465 mm/px


def test_config_accepts_explicit_centres(tmp_path):
    """异形布局覆盖：centers_mm 显式给出即生效（置换 id-角位）。"""
    p = tmp_path / "tray_perm.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "tray_mm": 300.0,
                "grid_px": 1024,
                "aruco": {
                    "dictionary": "DICT_4X4_50",
                    "marker_mm": 60.0,
                    "corner_ids": {"lt": 2, "rt": 3, "rb": 0, "lb": 1},
                    "centers_mm": {"2": [30, 30], "3": [270, 30], "0": [270, 270], "1": [30, 270]},
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_tray_config(p)
    assert cfg.centers_mm[0] == (270.0, 270.0)
    assert cfg.grid_px == 1024


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda d: d.pop("grid_px"), "grid_px"),
        (lambda d: d.update(tray_mm=0), "tray_mm"),
        (lambda d: d["aruco"].update(marker_mm=200), "重叠"),  # 2×200 ≥ 300
        (lambda d: d["aruco"].update(dictionary="4x4_50"), "dictionary"),
        (lambda d: d["aruco"]["centers_mm"].pop("3"), "centers_mm"),
        (
            lambda d: d["aruco"].update(
                centers_mm={"0": [40, 40], "1": [100, 100], "2": [200, 200], "3": [30, 270]}
            ),
            "共线",
        ),
        (lambda d: d["warp"].update(interp="lanczos"), "interp"),
        (lambda d: d["warp"].update(border_value=999), "border_value"),
    ],
)
def test_config_rejects_invalid(tmp_path, mutate, needle):
    base = {
        "tray_mm": 300.0,
        "grid_px": 2048,
        "aruco": {
            "dictionary": "DICT_4X4_50",
            "marker_mm": 60.0,
            "corner_ids": {"lt": 0, "rt": 1, "rb": 2, "lb": 3},
            "centers_mm": {"0": [30, 30], "1": [270, 30], "2": [270, 270], "3": [30, 270]},
        },
        "warp": {"interp": "linear", "border_value": 235},
    }
    mutate(base)
    p = tmp_path / "tray_bad.yaml"
    p.write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(TrayConfigError) as ei:
        load_tray_config(p)
    assert needle in str(ei.value)


def test_config_missing_file():
    with pytest.raises(TrayConfigError):
        load_tray_config(Path("Z:/不存在/tray.yaml"))


# ---------------------------------------------------------------------------
# 通过线 1/2：合成视图（透视 / 旋转 ±30° / 亮度扰动）
# ---------------------------------------------------------------------------


def test_make_aruco_cli_material(tmp_path, cfg):
    """子进程真实执行 make_aruco.py 产素材；布局 JSON 与 tray.yaml 互核对后整链标定。"""
    out_base = tmp_path / "board"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "make_aruco.py"),
            "--out", str(out_base),
            "--board-mm", "300",
            "--marker-mm", "60",
            "--px-per-mm", "8",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    png, jsn = out_base.with_suffix(".png"), out_base.with_suffix(".json")
    assert png.is_file() and jsn.is_file()
    img = cv2.imdecode(np.fromfile(png, dtype=np.uint8), cv2.IMREAD_COLOR)  # 中文路径安全读法
    assert img is not None and img.shape[0] == int((300 + 2 * MARGIN_MM) * P0)

    layout = json.loads(jsn.read_text(encoding="utf-8"))
    for m in layout["markers"]:  # 生成器 ↔ 配置互核对
        assert m["center_mm"] == list(cfg.centers_mm[m["marker_id"]])
    assert layout["marker_mm"] == cfg.marker_mm

    view, H_gt = _render(img, cvw.ViewSpec(rx_deg=20, ry_deg=15, rz_deg=-12, noise_sigma=4))
    _assert_view(view, H_gt, cfg)


@pytest.mark.parametrize(
    "spec",
    [
        cvw.ViewSpec(),  # 正射无扰动
        cvw.ViewSpec(rx_deg=28, noise_sigma=4),  # 纵向俯仰 28°
        cvw.ViewSpec(ry_deg=-26, rz_deg=10, noise_sigma=4),  # 横向俯仰 26° + 旋 10°
        cvw.ViewSpec(rx_deg=18, ry_deg=22, rz_deg=-30, gain=0.8, bias=-15, noise_sigma=5),
        cvw.ViewSpec(rx_deg=5, rz_deg=29, gain=1.2, bias=10, noise_sigma=3),
        cvw.ViewSpec(rx_deg=-24, ry_deg=-24, rz_deg=22, gain=0.78, noise_sigma=6),
    ],
    ids=["nominal", "tilt-x28", "tilt-y26-rot10", "tilt-xy-rot30-dark", "rot29-bright", "tilt-xy24-rot22-noisy"],
)
def test_calibrate_perturbed_views(board_bgr, cfg, spec):
    view, H_gt = _render(board_bgr, spec)
    _assert_view(view, H_gt, cfg)


def test_grid_points_back_projection(board_bgr, cfg):
    """辅助：盘面任意点（5×5 网格）px→mm 误差（通过线只卡 marker 中心，此项更严视野）。"""
    view, H_gt = _render(board_bgr, cvw.ViewSpec(rx_deg=22, ry_deg=-18, rz_deg=17, noise_sigma=4))
    cal = calibrate(view, cfg)
    pts_mm = np.array(
        [[x, y] for x in np.linspace(30, 270, 5) for y in np.linspace(30, 270, 5)],
        dtype=np.float64,
    )
    px_gt = cvw.apply_h(H_gt, pts_mm)
    est = px_to_mm(px_gt, cal.H)
    err = np.linalg.norm(est - pts_mm, axis=1).max()
    assert err <= GRID_MM_AUX_TOL, f"盘面网格点反投影最大误差 {err:.3f}mm"


# ---------------------------------------------------------------------------
# 通过线 3：四角任意摆放
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rz", [43, 90, 180, 270])
def test_arbitrary_inplane_rotation(board_bgr, cfg, rz):
    """托盘整盘旋转任意角度（含 90/180/270），按 id 配对仍正确标定。"""
    view, H_gt = _render(board_bgr, cvw.ViewSpec(rx_deg=8, rz_deg=rz, noise_sigma=3))
    _assert_view(view, H_gt, cfg)


def test_permuted_marker_layout(tmp_path):
    """id-角位置换布局（id0 在右下…），配用相应 centers_mm 的配置仍正确标定。"""
    perm = {0: (270, 270), 1: (30, 270), 2: (30, 30), 3: (270, 30)}  # 整体旋转 90° 的等价摆法
    board = cvw.build_board_custom(perm, MARKER_MM, TRAY_MM, P0, MARGIN_MM)
    cfg = TrayConfig(
        tray_mm=TRAY_MM,
        grid_px=2048,
        dictionary="DICT_4X4_50",
        marker_mm=MARKER_MM,
        centers_mm=perm,
        corner_ids={"lt": 2, "rt": 3, "rb": 0, "lb": 1},
    )
    view, H_gt = _render(board, cvw.ViewSpec(rx_deg=15, ry_deg=-10, rz_deg=7, noise_sigma=3))
    t0 = time.perf_counter()
    cal = calibrate(view, cfg)
    assert time.perf_counter() - t0 < 3.0
    errs = [
        float(np.linalg.norm(px_to_mm(cal.centers_px[m], cal.H) - np.asarray(c)))
        for m, c in perm.items()
    ]
    assert max(errs) <= MM_TOL, f"置换布局中心误差 {max(errs):.3f}mm"
    ppm_gt = cvw.gt_scale_at(H_gt, (TRAY_MM / 2, TRAY_MM / 2))
    assert abs(cal.px_per_mm - ppm_gt) / ppm_gt <= PPM_REL_TOL


# ---------------------------------------------------------------------------
# 通过线 4：12MP 性能
# ---------------------------------------------------------------------------


def test_perf_12mp(cfg):
    """单张 4000×3000（12MP）处理 ≤3s CPU，且毫米误差不放宽。"""
    canvas, _ = make_aruco.build_board(TRAY_MM, MARKER_MM, 10, MARGIN_MM)
    board = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    view, H_gt = cvw.render_view(
        board,
        TRAY_MM,
        MARGIN_MM,
        10,
        cvw.ViewSpec(rx_deg=25, ry_deg=15, rz_deg=8, out_w=4000, out_h=3000, fill=0.9, noise_sigma=4),
    )
    assert view.shape == (3000, 4000, 3)
    t0 = time.perf_counter()
    cal = calibrate(view, cfg)
    dt = time.perf_counter() - t0
    errs = [
        float(np.linalg.norm(px_to_mm(cal.centers_px[m], cal.H) - np.asarray(c)))
        for m, c in cfg.centers_mm.items()
    ]
    ppm_gt = cvw.gt_scale_at(H_gt, (TRAY_MM / 2, TRAY_MM / 2))
    assert max(errs) <= MM_TOL, f"12MP 中心误差 {max(errs):.3f}mm"
    assert abs(cal.px_per_mm - ppm_gt) / ppm_gt <= PPM_REL_TOL
    assert dt <= 3.0, f"12MP 标定耗时 {dt:.2f}s > 3s"


# ---------------------------------------------------------------------------
# 通过线 5：失败语义
# ---------------------------------------------------------------------------


def _cover_marker(board: np.ndarray, mid: int, cfg: TrayConfig) -> None:
    cx, cy = cfg.centers_mm[mid]
    half_px = int(MARKER_MM * 1.2 * P0 / 2)
    x = int((cx + MARGIN_MM) * P0)
    y = int((cy + MARGIN_MM) * P0)
    board[y - half_px : y + half_px, x - half_px : x + half_px] = 255  # 白色贴片盖码


def test_missing_markers_raises(board_bgr, cfg):
    board = board_bgr.copy()
    for mid in (2, 3):  # 盖掉两码 → 只剩 2/4
        _cover_marker(board, mid, cfg)
    view, _ = _render(board, cvw.ViewSpec(rx_deg=10, rz_deg=5))
    with pytest.raises(CalibrationError) as ei:
        calibrate(view, cfg)
    msg = str(ei.value)
    assert "2/4" in msg and "缺失" in msg and "[2, 3]" in msg


def test_single_missing_marker_raises(board_bgr, cfg):
    board = board_bgr.copy()
    _cover_marker(board, 0, cfg)
    view, _ = _render(board, cvw.ViewSpec(rx_deg=10, rz_deg=5))
    with pytest.raises(CalibrationError) as ei:
        calibrate(view, cfg)
    assert "3/4" in str(ei.value)


def test_blank_image_raises(cfg):
    blank = np.full((1200, 1600, 3), 128, dtype=np.uint8)
    with pytest.raises(CalibrationError, match="未检测到任何"):
        calibrate(blank, cfg)


# ---------------------------------------------------------------------------
# 变换工具与契约组装
# ---------------------------------------------------------------------------


def test_warp_to_tray_geometry(board_bgr, cfg):
    """正射网格上复检测：码中心应落在 canonical mm × (grid/tray) px，≤0.5mm。

    注：角码静区在打印板上延伸到盘面外约 7.5mm，2048 网格只含 0..300mm 会裁掉
    外侧静区导致边缘码不可检——检测前补一圈白边恢复静区（几何验证不受影响）。
    """
    view, _ = _render(board_bgr, cvw.ViewSpec(rx_deg=22, ry_deg=18, rz_deg=14, noise_sigma=3))
    cal = calibrate(view, cfg)
    warped = warp_to_tray(view, cal.H, cfg)
    assert warped.shape == (cfg.grid_px, cfg.grid_px, 3)

    pad = 24  # ≈3.5mm 白边，恢复被网格边界裁掉的静区
    padded = cv2.copyMakeBorder(warped, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    found = cvw.detect_centers(padded)
    assert sorted(found) == [0, 1, 2, 3]
    s = cfg.grid_px / cfg.tray_mm
    for mid, c_gt in cfg.centers_mm.items():
        est_mm = (np.asarray(found[mid]) - pad) / s
        err = float(np.linalg.norm(est_mm - np.asarray(c_gt)))
        assert err <= MM_TOL, f"正射网格码 id{mid} 偏差 {err:.3f}mm"


def test_warp_interp_variants(board_bgr, cfg):
    view, _ = _render(board_bgr, cvw.ViewSpec(rz_deg=11))
    cal = calibrate(view, cfg)
    for interp in ("linear", "nearest", "cubic"):
        cfg_i = TrayConfig(
            tray_mm=cfg.tray_mm, grid_px=512, dictionary=cfg.dictionary, marker_mm=cfg.marker_mm,
            centers_mm=cfg.centers_mm, corner_ids=cfg.corner_ids, interp=interp, border_value=200,
        )
        w = warp_to_tray(view, cal.H, cfg_i)
        assert w.shape == (512, 512, 3)


def test_px_mm_roundtrip(board_bgr, cfg):
    view, _ = _render(board_bgr, cvw.ViewSpec(rx_deg=20, ry_deg=-12, rz_deg=9))
    cal = calibrate(view, cfg)
    rng = np.random.default_rng(11)
    pts = rng.uniform(20, 280, size=(50, 2))
    back = px_to_mm(mm_to_px(pts, cal.H), cal.H)
    assert np.linalg.norm(back - pts, axis=1).max() < 1e-3


def test_calibrate_pair_contract(board_bgr, cfg):
    """双面各解 → 契约 CalibResult（M2 写 TrayScan.calibration 的形态）。"""
    vt, _ = _render(board_bgr, cvw.ViewSpec(rx_deg=10, rz_deg=6, seed=1))
    vb, _ = _render(board_bgr, cvw.ViewSpec(ry_deg=12, rz_deg=-9, seed=2))
    res = calibrate_pair(vt, vb, cfg)

    assert res.marker_ids == [0, 1, 2, 3]
    assert res.px_per_mm > 0 and res.reproj_err_px >= 0
    Ht, Hb = np.asarray(res.H_top), np.asarray(res.H_bottom)
    assert Ht.shape == (3, 3) and Hb.shape == (3, 3)
    assert not np.allclose(Ht, Hb)  # 两面几何不同则单应不同

    res2 = type(res).from_json(res.to_json())  # 契约往返无损
    assert np.allclose(np.asarray(res2.H_top), Ht)
    assert np.allclose(np.asarray(res2.H_bottom), Hb)
    assert res2.px_per_mm == res.px_per_mm


def test_calibrate_accepts_path_cfg(board_bgr):
    """cfg 参数允许直接传配置路径。"""
    view, _ = _render(board_bgr, cvw.ViewSpec(rz_deg=6))
    cal = calibrate(view, str(ROOT / "configs" / "tray.yaml"))
    assert cal.marker_ids == [0, 1, 2, 3]
