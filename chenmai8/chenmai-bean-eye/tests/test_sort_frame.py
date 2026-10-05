"""分拣线 eval · 像素 → 桌面毫米映射数学。

覆盖：ArUco 单应（含透视项）→ 托盘 mm、外参旋转/平移、px↔桌面 mm 往返、
从标定产物装配（SingleCalib / 契约 CalibResult）、三点仿射求解与退化拒绝。

运行（仓库根）::

    .venv/Scripts/python.exe -m pytest tests/test_sort_frame.py -q
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from beaneye.sort import (
    Affine2D,
    Extrinsic2D,
    FrameMappingError,
    FrameToTable,
    fit_residual,
    frame_to_table_from_calib,
    solve_affine,
)


# 合成单应：px = 6.8267·mm + 平移 + 轻微透视项（w 行 [1e-4, -2e-5, 1]）
# 等价地，这里直接给 px→mm 的 H：H_mm_from_px = inv(H_px_from_mm) 由数值求逆
_PX_PER_MM = 6.8267
_PX_OFFSET = (12.0, 8.0)
_PERSP = np.array([1e-5, -2e-6, 1.0])  # px 齐次 w 行


def _h_px_from_mm() -> np.ndarray:
    m = np.array(
        [[_PX_PER_MM, 0.0, _PX_OFFSET[0]], [0.0, _PX_PER_MM, _PX_OFFSET[1]], _PERSP],
        dtype=np.float64,
    )
    return np.linalg.inv(m)  # mm→px 的逆 = px→mm


@pytest.fixture()
def mapper():
    return FrameToTable(H=_h_px_from_mm(), extrinsic=Extrinsic2D(yaw_deg=0.0, offset_mm=(0.0, 0.0)))


# ---------------------------------------------------------------------------
# px → 托盘 mm（H 变换本身）
# ---------------------------------------------------------------------------


def test_px_to_tray_mm_matches_closed_form(mapper):
    """无外参时 px→托盘 mm 与手算闭合式一致（含透视除法）。"""
    px = np.array([100.0, 200.0])
    # mm = (px - offset) / px_per_mm（透视项在 mm→px 方向，逆映射后仍需数值解；
    # 用本类结果对照同一矩阵的手工齐次乘法）
    H = mapper.H
    v = H @ np.array([100.0, 200.0, 1.0])
    expected = v[:2] / v[2]
    got = mapper.px_to_tray_mm(px)
    assert got[0] == pytest.approx(expected[0], abs=1e-9)
    assert got[1] == pytest.approx(expected[1], abs=1e-9)


def test_px_to_tray_mm_batch_shape(mapper):
    pts = np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 200.0]])
    out = mapper.px_to_tray_mm(pts)
    assert out.shape == (3, 2)


def test_px_to_table_mm_composes_extrinsic():
    """外参 = 先 H 到托盘 mm，再 yaw 旋转 + 平移。"""
    H = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])  # px==mm 恒等
    mapper = FrameToTable(H=H, extrinsic=Extrinsic2D(yaw_deg=90.0, offset_mm=(100.0, 5.0)))
    # 托盘 (10, 0) → 旋转 90°(逆时针) → (0, 10) → 平移 → (100, 15)
    got = mapper.px_to_table_mm([10.0, 0.0])
    assert got[0] == pytest.approx(100.0, abs=1e-9)
    assert got[1] == pytest.approx(15.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 往返一致性（正/逆映射互逆）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("yaw", [0.0, 30.0, -90.0, 180.0])
@pytest.mark.parametrize("offset", [(0.0, 0.0), (150.0, -40.0)])
def test_table_to_px_roundtrip(yaw: float, offset: tuple):
    mapper = FrameToTable(H=_h_px_from_mm(), extrinsic=Extrinsic2D(yaw_deg=yaw, offset_mm=offset))
    table_pts = np.array([[80.0, -30.0], [150.0, 60.0], [10.0, 5.0]])
    px = mapper.table_to_px(table_pts)
    back = mapper.px_to_table_mm(px)
    assert np.allclose(back, table_pts, atol=1e-8)


def test_tray_roundtrip_via_extrinsic_inverse():
    ex = Extrinsic2D(yaw_deg=37.0, offset_mm=(120.0, -55.0))
    tray_pts = np.array([[10.0, 20.0], [200.0, 150.0]])
    table = ex.apply(tray_pts)
    back = ex.inverse().apply(table)
    assert np.allclose(back, tray_pts, atol=1e-9)


# ---------------------------------------------------------------------------
# 构造校验
# ---------------------------------------------------------------------------


def test_rejects_bad_homography():
    with pytest.raises(FrameMappingError):
        FrameToTable(H=np.zeros((3, 3)), extrinsic=Extrinsic2D())
    with pytest.raises(FrameMappingError):
        FrameToTable(H=np.eye(2), extrinsic=Extrinsic2D())
    with pytest.raises(FrameMappingError):
        FrameToTable(H=np.full((3, 3), np.nan), extrinsic=Extrinsic2D())


def test_perspective_w_zero_rejected():
    """点落在 w≈0 退化区（地平线）须显式报错而非产出 inf。"""
    bad = FrameToTable.__new__(FrameToTable)  # 绕过 __post_init__ 注入退化 H
    object.__setattr__(bad, "H", np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 0.0]]))
    object.__setattr__(bad, "extrinsic", Extrinsic2D())
    with pytest.raises(FrameMappingError):
        bad.px_to_tray_mm([1.0, 1.0])


# ---------------------------------------------------------------------------
# 从既有标定产物装配
# ---------------------------------------------------------------------------


def test_from_calib_single_calib_uses_H():
    class FakeSingleCalib:  # 只带 H 属性的最小替身（duck typing 装配）
        H = _h_px_from_mm()

    mapper = frame_to_table_from_calib(FakeSingleCalib(), Extrinsic2D())
    assert np.allclose(mapper.H, _h_px_from_mm())


def test_from_calib_contract_result_side_selects_homography():
    """契约 CalibResult：按 side 取 H_top / H_bottom。"""
    from beaneye.schemas import CalibResult

    h_top = [[6.8267, 0.0, 12.0], [0.0, 6.8267, 8.0], [0.0, 0.0, 1.0]]
    h_bot = [[6.8267, 0.0, 10.0], [0.0, 6.8267, 9.0], [0.0, 0.0, 1.0]]
    calib = CalibResult(
        px_per_mm=6.8267, H_top=h_top, H_bottom=h_bot,
        marker_ids=[0, 1, 2, 3], reproj_err_px=0.4,
    )
    m_top = frame_to_table_from_calib(calib, Extrinsic2D(), side="top")
    m_bot = frame_to_table_from_calib(calib, Extrinsic2D(), side="bottom")
    assert np.allclose(m_top.H, np.array(h_top))
    assert np.allclose(m_bot.H, np.array(h_bot))
    with pytest.raises(FrameMappingError, match="side"):
        frame_to_table_from_calib(calib, Extrinsic2D(), side="left")


def test_from_calib_accepts_config_extrinsic_params():
    """extrinsic 直接给配置对象（ExtrinsicParams）自动包装。"""
    from beaneye.sort import load_sort_config
    cfg = load_sort_config()

    class FakeSingleCalib:
        H = np.eye(3)

    mapper = frame_to_table_from_calib(FakeSingleCalib(), cfg.extrinsic)
    assert mapper.extrinsic.yaw_deg == cfg.extrinsic.yaw_deg
    assert mapper.extrinsic.offset_mm == cfg.extrinsic.offset_mm


# ---------------------------------------------------------------------------
# 三点标定（solve_affine）
# ---------------------------------------------------------------------------


def test_solve_affine_three_point_exact_translation_scale():
    src = [[0.0, 0.0], [100.0, 0.0], [0.0, 100.0]]
    dst = [[50.0, 60.0], [150.0, 60.0], [50.0, 160.0]]  # 纯平移 + 等比 1.0
    aff = solve_affine(src, dst)
    assert aff.apply([37.0, 42.0]) == pytest.approx([87.0, 102.0], abs=1e-9)


def test_solve_affine_with_rotation_and_shear():
    """一般仿射（旋转 + 剪切 + 缩放）3 点精确恢复，第 4 点验证。"""
    m = np.array([[0.9, 0.2, 30.0], [-0.1, 1.1, -20.0]])
    src = np.array([[0.0, 0.0], [80.0, 0.0], [10.0, 90.0]])
    dst = (m[:, :2] @ src.T).T + m[:, 2]
    aff = solve_affine(src, dst)
    assert np.allclose(aff.matrix, m, atol=1e-9)
    probe = [55.0, 33.0]
    assert aff.apply(probe) == pytest.approx(m[:, :2] @ np.array(probe) + m[:, 2], abs=1e-9)


def test_solve_affine_overdetermined_least_squares():
    """>3 点最小二乘：带小噪声时残差有限且最小。"""
    rng = np.random.default_rng(20261002)
    m = np.array([[1.0, 0.0, 10.0], [0.0, 1.0, -5.0]])
    src = rng.uniform(0, 200, size=(8, 2))
    dst = src @ m[:, :2].T + m[:, 2] + rng.normal(0, 0.1, size=(8, 2))
    aff = solve_affine(src, dst)
    residual = fit_residual(aff, src, dst)
    assert 0.0 < residual < 0.3  # 噪声水平量级（2D RMS）
    # n=8、σ=0.1 下截距标准误 ~0.07，个别种子波动到 ~0.3 仍属统计正常
    assert np.allclose(aff.matrix, m, atol=0.5)


def test_solve_affine_point_count_mismatch_rejected():
    with pytest.raises(FrameMappingError, match="等长"):
        solve_affine([[0, 0], [1, 0], [0, 1]], [[0, 0], [1, 1]])


def test_affine2d_degenerate_linear_part_rejected():
    with pytest.raises(FrameMappingError, match="退化"):
        Affine2D(matrix=np.array([[1.0, 1.0, 0.0], [2.0, 2.0, 0.0]]))  # 行秩 1
