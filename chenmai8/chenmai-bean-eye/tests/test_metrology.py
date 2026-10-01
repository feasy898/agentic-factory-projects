"""M8 计量 eval：目数分布 / 色差 ΔE / 估重（spec：plan/开发指令.md §4 M8）。

通过线（全用确定性合成数据，不依赖真实豆图/数据集/网络）：
- 直径误差 ≤2%（已知半径合成圆 → cv2 渲染 → 标定 px/mm 换算 → 计量）；
- 目数 100% 正确（已知直径手算筛号表 + 阈值两侧点）；
- ΔE 与手算参考值偏差 ≤1.0（手算字面量 + cv2 LAB8 标度往返）；
- 标定后估重误差 ≤15%（含 px_per_mm 残差 +1% 的标定误差场景）；
- ≤2s/盘 CPU（350 粒盘实测计时）。

运行（仓库根）::

    .venv/Scripts/python.exe -m pytest tests/test_metrology.py -q
"""

from __future__ import annotations

import math
import time
from itertools import count

import cv2
import numpy as np
import pytest

from beaneye.metrology import (
    DEFAULT_G_PER_MM2,
    DEFAULT_REFERENCE_LAB,
    MetrologyConfig,
    MetrologyError,
    cie_to_lab8,
    delta_e_cie76,
    lab8_to_cie,
    measure,
    merge_sides_lab,
    screen_mm,
    screen_of,
    screen_of_ratio,
)
from beaneye.schemas import (
    BeanMask,
    BeanObservation,
    CalibResult,
    Measurements,
    PairedBean,
)
from beaneye.taxonomy import load_taxonomy

TAX = load_taxonomy()
RANK = {k: TAX.severity_rank(k) for k in TAX.keys()}
REF = DEFAULT_REFERENCE_LAB  # (55.0, -12.0, 22.0) CIE 标度

_PX_PER_MM = 6.8267  # 2048 px / 300 mm（configs/tray.yaml 默认）


# ---------------------------------------------------------------------------
# 确定性构造器
# ---------------------------------------------------------------------------

_SEQ = count(1)


def _mask(mid: str, side: str, area_mm2: float) -> BeanMask:
    """占位多边形掩码：几何真值放 area_mm2 / 直径由观测携带。"""
    r = math.sqrt(area_mm2 / math.pi)
    return BeanMask(
        mask_id=mid,
        side=side,
        polygon=[[-r, -r], [r, -r], [r, r], [-r, r]],
        bbox_mm=(-r, -r, r, r),
        area_mm2=area_mm2,
        centroid_mm=(100.0, 100.0),
        source="oracle",
        conf=1.0,
    )


def _obs(side: str, d_mm: float, lab_cie, *, defect: str = "normal",
         area_mm2: float | None = None) -> BeanObservation:
    """已知直径 / 已知 CIE 颜色的单面观测（面积默认与直径自洽：圆）。"""
    if area_mm2 is None:
        area_mm2 = math.pi * (d_mm / 2.0) ** 2
    lab8 = cie_to_lab8(tuple(float(v) for v in lab_cie))
    n = next(_SEQ)
    return BeanObservation(
        obs_id=f"{side}_{n:04d}",
        side=side,  # type: ignore[arg-type]
        defect=defect,
        defect_conf=0.99 if defect == "normal" else 0.9,
        severity_rank=0 if defect == "normal" else RANK[defect],
        crop_path=f"out/crops/t/{side}_{n:04d}.png",
        mask=_mask(f"{side}_{n:04d}", side, area_mm2),
        color_lab=lab8,
        eq_diameter_mm=float(d_mm),
    )


def _bean(top: BeanObservation | None, bottom: BeanObservation | None = None,
          cost: float | None = None) -> PairedBean:
    # 契约：单面/空面豆 pairing_cost 必须 = -1
    if cost is None:
        cost = -1.0 if (top is None or bottom is None) else 1.0
    return PairedBean.from_sides(f"b{next(_SEQ):04d}", top, bottom, cost)


def _circle_obs_from_render(r_mm: float, px_per_mm: float) -> BeanObservation:
    """已知半径合成圆：渲染 → 阈值 → 像素面积 → 经标定换算 mm（M4 口径）。"""
    r_px = r_mm * px_per_mm
    size = int(2 * r_px + 41)
    canvas = np.full((size, size), 255, np.uint8)
    c = size // 2
    cv2.circle(canvas, (c, c), int(round(r_px)), 0, -1)
    _, th = cv2.threshold(canvas, 128, 255, cv2.THRESH_BINARY_INV)
    area_px = int(np.count_nonzero(th))
    area_mm2 = area_px / px_per_mm**2
    d_mm = 2.0 * math.sqrt(area_mm2 / math.pi)
    return _obs("top", d_mm, REF, area_mm2=area_mm2)


def _calib(px_per_mm: float = _PX_PER_MM) -> CalibResult:
    k = px_per_mm
    return CalibResult(
        px_per_mm=k,
        H_top=[[k, 0, 0], [0, k, 0], [0, 0, 1]],
        H_bottom=[[k, 0, 0], [0, k, 0], [0, 0, 1]],
        marker_ids=[0, 1, 2, 3],
        reproj_err_px=0.3,
    )


# ---------------------------------------------------------------------------
# 筛目：目=1/64 英寸（spec: screen = round(d_mm/25.4*64)）
# ---------------------------------------------------------------------------


class TestSieve:
    def test_known_diameter_table_100pct(self):
        # 手算表：d → round(d/25.4*64)；入参全为 1/64 英寸的精确二进制值
        cases = {
            25.4: 64,
            12.7: 32,
            screen_mm(16): 16,   # 6.35 mm
            6.0: 15,             # 15.118 → 15
            screen_mm(13): 13,   # 5.159375 mm（13 号筛孔径自身）
            5.0: 13,             # 12.598 → 13
            5.5: 14,             # 13.858 → 14
            screen_mm(12): 12,   # 4.7625 mm
            4.0: 10,             # 10.079 → 10
        }
        for d, want in cases.items():
            assert screen_of(d) == want, f"screen_of({d}) 应为 {want}"

    def test_boundary_half_up(self):
        # .5 进位（四舍五入），非 Python round 的银行家舍入
        assert screen_of_ratio(12.5) == 13
        assert screen_of_ratio(11.5) == 12
        assert screen_of_ratio(12.4999) == 12
        # 直径在筛号阈值两侧
        assert screen_of(4.96) == 12  # 12.494
        assert screen_of(4.97) == 13  # 12.520

    def test_screen_mm_roundtrip(self):
        for s in (10, 12, 13, 14, 16, 18):
            assert screen_of(screen_mm(s)) == s

    def test_invalid_inputs(self):
        with pytest.raises(MetrologyError):
            screen_of(0.0)
        with pytest.raises(MetrologyError):
            screen_of(-1.0)
        with pytest.raises(MetrologyError):
            screen_of_ratio(-0.1)

    def test_hist_exact_and_pass(self):
        beans = [
            _bean(_obs("top", 6.35, REF)),        # 16
            _bean(_obs("top", 5.159375, REF)),    # 13
            _bean(_obs("top", 5.0, REF)),         # 13
            _bean(_obs("top", 5.5, REF)),         # 14
            _bean(_obs("top", 4.7625, REF)),      # 12
        ]
        m = measure(beans, None, None)
        assert m.bean_count == 5
        assert m.sieve_hist == {"12": 1, "13": 2, "14": 1, "16": 1}
        # min_screen=13：1/5 低于 13
        assert m.sieve_pass is False  # max_below_frac 默认 0 → 不过
        m2 = measure(beans, None, {"metrology": {"sieve_targets": {"min_screen": 13,
                                                                   "max_below_frac": 0.3}}})
        assert m2.sieve_pass is True
        m3 = measure(beans, None, {"metrology": {"sieve_targets": {"min_screen": None}}})
        assert m3.sieve_pass is None

    def test_sieve_uses_mean_of_sides(self):
        b = _bean(_obs("top", 6.0, REF), _obs("bottom", 5.0, REF))
        m = measure([b], None, None)
        assert m.sieve_hist == {"14": 1}  # 均值 5.5mm → 14 目
        assert m.eq_diameter_mm_stats.mean == pytest.approx(5.5)


# ---------------------------------------------------------------------------
# LAB 标度与色差（CIE76，留 ΔE00 升级位）
# ---------------------------------------------------------------------------


class TestColor:
    def test_lab8_cie_conversion(self):
        assert lab8_to_cie((140.25, 116.0, 150.0)) == pytest.approx((55.0, -12.0, 22.0))
        assert cie_to_lab8((55.0, -12.0, 22.0)) == pytest.approx((140.25, 116.0, 150.0))
        lab8 = (100.0, 30.0, 250.0)
        assert lab8_to_cie(cie_to_lab8(lab8_to_cie(lab8))) == pytest.approx(
            lab8_to_cie(lab8)
        )

    def test_delta_e_hand_values(self):
        # 手算字面量（CIE76 = 欧氏距离）
        assert delta_e_cie76(REF, REF) == 0.0
        assert delta_e_cie76((40.0, -12.0, 22.0), REF) == pytest.approx(15.0)
        assert delta_e_cie76((55.0, 8.0, 42.0), REF) == pytest.approx(math.sqrt(800.0))
        assert delta_e_cie76((60.0, -20.0, 30.0), REF) == pytest.approx(math.sqrt(153.0))

    def test_cv2_lab8_scale_roundtrip_within_1(self):
        # 合成色块：LAB8(CIE 目标色) → cv2 Lab→BGR→Lab 往返 → 均值 → ΔE ≤ 1.0
        # （钉死「逐粒 color_lab=OpenCV 8-bit LAB、参考色=CIE」的标度约定）
        for lab_cie in [(55.0, -12.0, 22.0), (52.0, -10.0, 20.0), (30.0, 18.0, 9.0)]:
            lab8 = np.array([[cie_to_lab8(lab_cie)]], np.uint8)
            bgr = cv2.cvtColor(lab8, cv2.COLOR_LAB2BGR)
            back = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
            mean8 = tuple(float(v) for v in back.reshape(3))
            got = lab8_to_cie(mean8)
            assert delta_e_cie76(got, lab_cie) <= 1.0, f"{lab_cie} → {got}"

    def test_delta_e_mean_matches_hand_within_1(self):
        # 已知 LAB 的三粒合成豆 → 手算 ΔE 均值 vs 模块输出，偏差 ≤1.0
        targets = [(55.0, -12.0, 22.0), (40.0, -12.0, 22.0), (55.0, 8.0, 42.0)]
        beans = [_bean(_obs("top", 6.0, t)) for t in targets]
        hand = sum(delta_e_cie76(t, REF) for t in targets) / 3.0
        m = measure(beans, None, None)
        assert abs(m.delta_e_mean - hand) <= 1.0
        assert m.delta_e_mean == pytest.approx(hand, rel=1e-9)

    def test_delta_e_hist_buckets(self):
        # ΔE = 0 / 1.0 / 3.5 / 4.5 / 21 → 桶 "0-2","2-4","4-6","20+"
        labs = [REF, (56.0, -12.0, 22.0), (58.5, -12.0, 22.0), (59.5, -12.0, 22.0),
                (76.0, -12.0, 22.0)]
        beans = [_bean(_obs("top", 6.0, l)) for l in labs]
        m = measure(beans, None, None)
        assert m.delta_e_hist == {"0-2": 2, "2-4": 1, "4-6": 1, "20+": 1}

    def test_merge_sides_severity_weight(self):
        # severity 高侧权重 0.7（契约 §4 M8）；lab8 上加权与 CIE 上加权一致
        top = _obs("top", 6.0, (30.0, 18.0, 9.0), defect="black")  # rank 12
        bot = _obs("bottom", 6.0, (55.0, -12.0, 22.0))             # rank 0
        got = merge_sides_lab(top, bot)
        assert got == pytest.approx(tuple(0.7 * t + 0.3 * b for t, b in
                                          zip(top.color_lab, bot.color_lab)))
        # 平级（同 rank 同缺陷）0.5/0.5；单面取该面
        tie = merge_sides_lab(top, _obs("bottom", 6.0, (30.0, 18.0, 9.0),
                                       defect="black"))
        assert tie == pytest.approx(tuple(top.color_lab))
        assert merge_sides_lab(None, bot) == pytest.approx(tuple(bot.color_lab))
        with pytest.raises(MetrologyError):
            merge_sides_lab(None, None)

    def test_color_lab_mean_is_lab8_scale(self):
        beans = [
            _bean(_obs("top", 6.0, (55.0, -12.0, 22.0))),
            _bean(_obs("top", 6.0, (51.4, -9.8, 19.6))),
        ]
        m = measure(beans, None, None)
        l8a, l8b = cie_to_lab8((55.0, -12.0, 22.0)), cie_to_lab8((51.4, -9.8, 19.6))
        want = tuple((a + c) / 2 for a, c in zip(l8a, l8b))
        assert m.color_lab_mean == pytest.approx(want, rel=1e-9)


# ---------------------------------------------------------------------------
# 直径与估重（合成圆 + 标定误差场景）
# ---------------------------------------------------------------------------


class TestDiameter:
    def test_synthetic_circles_within_2pct(self):
        # 已知半径合成圆 → 渲染/阈值 → 标定 px_per_mm 换算 → 计量
        radii = [4.5, 5.159375, 6.0, 7.0, 8.0]
        beans = [_bean(_circle_obs_from_render(r, _PX_PER_MM)) for r in radii]
        m = measure(beans, _calib(), None)
        assert m.bean_count == len(radii)
        for got, want in zip(
            [m.eq_diameter_mm_stats.min, m.eq_diameter_mm_stats.max], [9.0, 16.0]
        ):
            assert got == pytest.approx(want, rel=0.02)
        assert m.eq_diameter_mm_stats.mean == pytest.approx(
            sum(2 * r for r in radii) / len(radii), rel=0.02
        )
        med = sorted(2 * r for r in radii)[len(radii) // 2]
        assert m.eq_diameter_mm_stats.median == pytest.approx(med, rel=0.02)


class TestWeight:
    def test_area_linear_exact_hand(self):
        # Σ area × g_per_mm2，手算：面积 28.2743+50.2655+78.5398 = 157.0796 mm²
        areas = [9.0 * math.pi, 16.0 * math.pi, 25.0 * math.pi]
        beans = [_bean(_obs("top", 2 * math.sqrt(a / math.pi), REF, area_mm2=a))
                 for a in areas]
        m = measure(beans, None, None)
        hand = sum(areas) * 0.00042
        assert m.est_weight_g == pytest.approx(hand, rel=1e-9)
        assert m.weight_model == "area_linear:v1"

    def test_area_linear_configurable(self):
        beans = [_bean(_obs("top", 7.0, REF))]  # area = 12.25π = 38.4845
        g = 0.00050
        m = measure(beans, None, {"weight": {"model": "area_linear", "g_per_mm2": g}})
        assert m.weight_model == "area_linear:v1"
        assert m.est_weight_g == pytest.approx(12.25 * math.pi * g, rel=1e-9)

    def test_area_thickness_prior_configurable(self):
        beans = [_bean(_obs("top", 7.0, REF), _obs("bottom", 7.0, REF))]
        cfg = {"weight": {"model": "area_thickness", "thickness_mm": 3.5,
                          "g_per_mm3": 0.0011}}
        m = measure(beans, None, cfg)
        assert m.weight_model == "area_thickness:v1"
        area = 12.25 * math.pi  # 两面均值仍 38.4845
        assert m.est_weight_g == pytest.approx(area * 3.5 * 0.0011, rel=1e-9)
        # 系数可配：换系数即换结果
        m2 = measure(beans, None, {"weight": {"model": "area_thickness",
                                              "thickness_mm": 4.0, "g_per_mm3": 0.0012}})
        assert m2.est_weight_g == pytest.approx(area * 4.0 * 0.0012, rel=1e-9)

    def test_unknown_model_rejected(self):
        with pytest.raises(MetrologyError, match="weight.model"):
            measure([_bean(_obs("top", 7.0, REF))], None,
                    {"weight": {"model": "magic_scale"}})

    def test_calibrated_weight_within_15pct(self):
        # 标定后估重：真值=圆面积×真系数；恢复的 px_per_mm 带 +1% 残差
        # （面积高估 ≈ 2.01%，远低于 15% 通过线）
        radii = [4.5, 5.0, 6.0, 7.0, 8.0]
        g_true = 0.00042
        px_calib = _PX_PER_MM * 1.01
        beans = [_bean(_circle_obs_from_render(r, px_calib)) for r in radii]
        m = measure(beans, _calib(px_calib), {"weight": {"g_per_mm2": g_true}})
        truth = sum(math.pi * r**2 for r in radii) * g_true
        assert m.est_weight_g > 0
        assert abs(m.est_weight_g - truth) / truth <= 0.15

    def test_two_sided_area_uses_mean(self):
        # 两面面积均值口径：top 38.4845 / bottom 19.6350 → 均值 29.06
        top = _obs("top", 7.0, REF)
        bot = _obs("bottom", 5.0, REF, area_mm2=6.25 * math.pi)
        m = measure([_bean(top, bot)], None, None)
        want = (top.mask.area_mm2 + bot.mask.area_mm2) / 2 * 0.00042
        assert m.est_weight_g == pytest.approx(want, rel=1e-9)


# ---------------------------------------------------------------------------
# 输入/输出契约与边界
# ---------------------------------------------------------------------------


class TestContractAndEdges:
    def test_measure_output_is_valid_measurements_and_roundtrips(self):
        beans = [
            _bean(_obs("top", 6.0, REF), _obs("bottom", 5.9, (52.0, -10.0, 20.0))),
            _bean(None, _obs("bottom", 5.0, (48.0, -8.0, 18.0), defect="sour")),
        ]
        m = measure(beans, _calib(), None)
        assert isinstance(m, Measurements)
        m2 = Measurements.from_json(m.to_json())
        assert m2 == m

    def test_empty_tray(self):
        m = measure([], None, None)
        assert m.bean_count == 0
        assert m.sieve_hist == {} and m.delta_e_hist == {}
        assert m.sieve_pass is None
        assert m.est_weight_g == 0.0
        assert m.eq_diameter_mm_stats.min == 0.0
        assert m.weight_model == "area_linear:v1"

    def test_both_none_placeholder_skipped(self):
        placeholder = PairedBean.from_sides("b0001", None, None, -1)
        real = _bean(_obs("top", 6.0, REF))
        m = measure([placeholder, real], None, None)
        assert m.bean_count == 1
        assert m.sieve_hist == {"15": 1}

    def test_single_side_stats(self):
        b = _bean(None, _obs("bottom", 5.2, REF, defect="broken"))
        m = measure([b], None, None)
        assert m.eq_diameter_mm_stats.mean == pytest.approx(5.2)

    def test_invalid_inputs_rejected(self):
        with pytest.raises(MetrologyError, match="PairedBean"):
            measure(["not-a-bean"], None, None)
        with pytest.raises(MetrologyError, match="calib"):
            measure([], "bad-calib", None)
        with pytest.raises(MetrologyError, match="std_yaml"):
            measure([], None, 123)

    def test_std_yaml_variants_dict_path_none(self, tmp_path):
        beans = [_bean(_obs("top", 6.0, (52.0, -10.0, 20.0)))]
        cfg_dict = {
            "standard": "cqi_fine_robusta",
            "metrology": {"reference_lab": [55.0, -12.0, 22.0],
                          "sieve_targets": {"min_screen": 15}},
            "weight": {"model": "area_linear", "g_per_mm2": 0.00042},
        }
        m_dict = measure(beans, None, cfg_dict)
        assert m_dict.sieve_pass is True  # 6.0mm → 15 目 ≥ 15
        p = tmp_path / "标准_cqi.yaml"  # 中文路径不回避（配置读取走 Path.read_text utf-8）
        p.write_text(
            "metrology:\n  reference_lab: [55, -12, 22]\n"
            "  sieve_targets: {min_screen: 16}\n"
            "weight: {model: area_linear, g_per_mm2: 0.00042}\n",
            encoding="utf-8",
        )
        m_path = measure(beans, None, p)
        assert m_path.sieve_pass is False  # 15 < 16
        # 路径与等价 dict 配置产出完全一致
        assert m_path == measure(beans, None, {
            "metrology": {"reference_lab": [55, -12, 22],
                          "sieve_targets": {"min_screen": 16}},
            "weight": {"model": "area_linear", "g_per_mm2": 0.00042},
        })
        # None → 契约模板默认（与上面同值配置一致）
        assert m_dict == measure(beans, None, None)

    def test_reference_lab_scale_lab8_accepted(self):
        # 配置方也可直接给 lab8 标度参考色，加载期归一
        cfg = {"metrology": {"reference_lab": [140.25, 116.0, 150.0],
                             "reference_lab_scale": "lab8"}}
        beans = [_bean(_obs("top", 6.0, (55.0, -12.0, 22.0)))]
        m1 = measure(beans, None, cfg)
        m2 = measure(beans, None, {"metrology": {"reference_lab": [55.0, -12.0, 22.0]}})
        assert m1.delta_e_mean == pytest.approx(m2.delta_e_mean)

    def test_config_injection_equals_std_yaml(self):
        beans = [_bean(_obs("top", 6.0, REF))]
        cfg = MetrologyConfig(reference_lab=(55.0, -12.0, 22.0), min_screen=13,
                              weight_model="area_linear", g_per_mm2=0.00042)
        assert measure(beans, None, None, config=cfg) == measure(beans, None, None)

    def test_bad_reference_lab_rejected(self):
        with pytest.raises(MetrologyError, match="reference_lab"):
            measure([], None, {"metrology": {"reference_lab": [55.0, -12.0]}})
        with pytest.raises(MetrologyError, match="reference_lab_scale"):
            measure([], None, {"metrology": {"reference_lab_scale": "rgb"}})
        with pytest.raises(MetrologyError, match="L\\*"):
            measure([], None, {"metrology": {"reference_lab": [300.0, 0.0, 0.0]}})

    def test_bad_sieve_targets_rejected(self):
        with pytest.raises(MetrologyError, match="min_screen"):
            measure([], None, {"metrology": {"sieve_targets": {"min_screen": 0}}})
        with pytest.raises(MetrologyError, match="max_below_frac"):
            measure([], None, {"metrology": {"sieve_targets": {"max_below_frac": 1.5}}})


# ---------------------------------------------------------------------------
# 性能：≤2s/盘（350 粒）
# ---------------------------------------------------------------------------


def test_tray_of_350_beans_within_2s():
    # 规模盘：350 粒、尺寸/颜色/缺陷/单面混杂（M14 规模口径）
    diam_range = [4.5 + 0.05 * i for i in range(40)]
    lab_range = [(50.0 + i, -12.0 + 0.5 * i, 20.0 + 0.2 * i) for i in range(10)]
    defects = ["normal", "normal", "normal", "sour", "broken"]
    beans = []
    for i in range(350):
        d = diam_range[i % len(diam_range)]
        lab = lab_range[i % len(lab_range)]
        defect = defects[i % len(defects)]
        if i % 17 == 0:  # 6% 单面豆
            beans.append(_bean(None, _obs("bottom", d, lab, defect=defect)))
        else:
            beans.append(_bean(_obs("top", d, lab, defect=defect),
                               _obs("bottom", d * 0.99, lab)))
    t0 = time.perf_counter()
    m = measure(beans, _calib(), None)
    dt = time.perf_counter() - t0
    assert m.bean_count == 350
    assert dt < 2.0, f"350 粒盘计量耗时 {dt:.3f}s，超过 2s 通过线"
