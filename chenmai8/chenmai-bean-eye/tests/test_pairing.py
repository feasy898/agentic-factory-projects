"""M6 上下配对测试（W6 eval）。

运行（仓库根）::

    pytest tests/test_pairing.py -q

覆盖：
1. 三类合成上下框对 fixture（tests/fixtures/pairing/cases_v1.json）：
   可配对 / 遮挡单面 / 边缘漏检；
2. 门限语义（恰在门限=可配对、越门限=两条单面记录）、单面快路径、
   不可行实例不崩、非法输入拒绝；
3. bean_id 稳定可复现（同输入同输出、乱序输入同结果）；
4. 大规模合成统计（spec §4 M6）：200 粒、抖动 σ=3mm（相对位移分解到两面
   各 3/√2，等价于单面 σ=3 另一面无抖动）、10% 随机丢面、每面 5% 伪观测；
   另加整体平移 5mm 标定误差场景。通过线：precision ≥0.98、recall ≥0.95
   （标定误差场景 ≥0.95）、≤1s CPU。
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

import pytest

from beaneye.pairing import (
    DEFAULT_GATE_MM,
    PairingError,
    pair_observations,
    robust_shift_mm,
    summarize,
)
from beaneye.schemas import BeanMask, BeanObservation, PairedBean
from beaneye.taxonomy import load_taxonomy
from _pairing_cases import build_cases

TAX = load_taxonomy()
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "pairing" / "cases_v1.json"


# ---------------------------------------------------------------------------
# 合成观测构造
# ---------------------------------------------------------------------------


def synth_obs(obs_id: str, side: str, cx: float, cy: float, *, defect: str = "normal", conf: float = 0.99) -> BeanObservation:
    """半径 3mm 正六边形豆观测（盘面 mm 坐标）。"""
    r = 3.0
    polygon = [[cx + r * math.cos(math.radians(60 * k)), cy + r * math.sin(math.radians(60 * k))] for k in range(6)]
    mask = BeanMask(
        mask_id=obs_id,
        side=side,
        polygon=polygon,
        bbox_mm=(cx - r, cy - r, cx + r, cy + r),
        area_mm2=math.pi * r * r,
        centroid_mm=(cx, cy),
        source="oracle",
        conf=1.0,
    )
    return BeanObservation(
        obs_id=obs_id,
        side=side,
        defect=defect,
        defect_conf=conf,
        severity_rank=TAX.severity_rank(defect),
        crop_path=f"out/crops/synth/{obs_id}.png",
        mask=mask,
        color_lab=(52.0, -10.0, 20.0),
        eq_diameter_mm=6.0,
    )


def _dist2d(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ---------------------------------------------------------------------------
# 1) fixture 三类用例：可配对 / 遮挡单面 / 边缘漏检
# ---------------------------------------------------------------------------


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_file_matches_builder():
    """fixture 文件与构造器保持同步（沿袭契约 fixture 的做法）。"""
    assert json.loads(FIXTURE_PATH.read_text(encoding="utf-8")) == build_cases()


@pytest.mark.parametrize(
    "case", _load_fixture()["cases"], ids=lambda c: c["case_id"]
)
def test_fixture_case(case: dict):
    """逐用例：单独跑配对，必须恰好产出 1 条记录且符合 expect 块。"""
    top = [BeanObservation.model_validate(case["top"])] if case["top"] else []
    bottom = [BeanObservation.model_validate(case["bottom"])] if case["bottom"] else []
    beans = pair_observations(top, bottom, gate_mm=_load_fixture()["gate_mm"])
    assert len(beans) == 1, f"{case['case_id']} 应恰好 1 条记录，得到 {len(beans)}"
    bean = beans[0]
    exp = case["expect"]

    if exp["paired"]:
        t, b = case["top"], case["bottom"]
        want_cost = _dist2d(tuple(t["mask"]["centroid_mm"]), tuple(b["mask"]["centroid_mm"]))
        assert bean.top is not None and bean.bottom is not None
        assert bean.pairing_cost == pytest.approx(want_cost, abs=1e-6)
        assert 0 <= bean.pairing_cost <= DEFAULT_GATE_MM
    else:
        kept = exp["kept_side"]
        other = bean.top if kept == "bottom" else bean.bottom
        assert (bean.top is None) != (bean.bottom is None)
        assert other is None, f"{case['case_id']} 只应保留 {kept} 面观测"
        assert bean.pairing_cost == -1, f"{case['case_id']} 单面记录 pairing_cost 必须 -1"
    assert bean.worst_side == exp["worst_side"]
    assert bean.final_defect == exp["final_defect"]
    assert bean.bean_id == "b0001"


def test_fixture_geometry_semantics():
    """fixture 自检：遮挡单面在盘中部、边缘漏检在盘边。"""
    fx = _load_fixture()
    tray, band, mid = fx["tray_mm"], fx["edge_band_mm"], fx["mid_min_mm"]
    for case in fx["cases"]:
        obs = case["top"] or case["bottom"]
        x, y = obs["mask"]["centroid_mm"]
        d_edge = min(x, y, tray - x, tray - y)
        if case["kind"] == "occlusion_single_side":
            assert d_edge >= mid, f"{case['case_id']} 遮挡单面应在盘中部（距边 {d_edge:.1f}mm）"
        elif case["kind"] == "edge_miss":
            assert d_edge <= band, f"{case['case_id']} 边缘漏检应在盘边（距边 {d_edge:.1f}mm）"


def test_fixture_three_kinds_covered():
    kinds = {c["kind"] for c in _load_fixture()["cases"]}
    assert kinds == {"pairable", "occlusion_single_side", "edge_miss"}


# ---------------------------------------------------------------------------
# 2) 门限语义 / 快路径 / 非法输入 / 不可行实例
# ---------------------------------------------------------------------------


def test_gate_exactly_at_threshold_pairs():
    """恰在门限上（12.0mm）视为可配对（门限含等号）。"""
    top = [synth_obs("top_001", "top", 100.0, 100.0)]
    bottom = [synth_obs("bottom_001", "bottom", 112.0, 100.0)]
    beans = pair_observations(top, bottom)
    assert len(beans) == 1
    assert beans[0].pairing_cost == pytest.approx(12.0)
    assert beans[0].top is not None and beans[0].bottom is not None


def test_gate_beyond_threshold_yields_two_singles():
    """越门限（12.5mm）：不得成对，两侧各成一条单面记录并标记。"""
    top = [synth_obs("top_001", "top", 100.0, 100.0)]
    bottom = [synth_obs("bottom_001", "bottom", 112.5, 100.0)]
    beans = pair_observations(top, bottom)
    assert len(beans) == 2
    for b in beans:
        assert b.pairing_cost == -1
        assert (b.top is None) != (b.bottom is None)
    s = summarize(beans)
    assert (s.n_paired, s.n_top_only, s.n_bottom_only) == (0, 1, 1)


def test_empty_and_single_side_fast_paths():
    assert pair_observations([], []) == []
    top = [synth_obs("top_001", "top", 10.0, 10.0), synth_obs("top_002", "top", 50.0, 10.0)]
    beans = pair_observations(top, [])
    assert len(beans) == 2
    assert all(b.pairing_cost == -1 and b.bottom is None for b in beans)
    assert [b.bean_id for b in beans] == ["b0001", "b0002"]  # 按 x 排序
    bottom = [synth_obs("bottom_009", "bottom", 30.0, 80.0)]
    beans2 = pair_observations([], bottom)
    assert len(beans2) == 1 and beans2[0].worst_side == "bottom"


def test_infeasible_instance_does_not_crash():
    """两个 top 都只落在同一 bottom 的门限圈内：scipy inf 矩阵会抛
    "cost matrix is infeasible"，本实现须退化为 1 对 + 1 单面而非崩溃。"""
    top = [
        synth_obs("top_001", "top", 100.0, 100.0),  # 距 bottom 2.12mm（更近）
        synth_obs("top_002", "top", 104.0, 103.0),  # 距 bottom 2.92mm
    ]
    bottom = [synth_obs("bottom_001", "bottom", 101.5, 101.5)]
    beans = pair_observations(top, bottom)
    s = summarize(beans)
    assert s.n_paired == 1 and s.n_top_only == 1 and s.n_bottom_only == 0
    paired = next(b for b in beans if b.bottom is not None)
    assert paired.top is not None and paired.top.obs_id == "top_001"  # 全局最优取更近者
    assert paired.pairing_cost == pytest.approx(_dist2d((100.0, 100.0), (101.5, 101.5)))
    single = next(b for b in beans if b.bottom is None)
    assert single.top is not None and single.top.obs_id == "top_002"
    assert single.pairing_cost == -1 and single.worst_side == "top"


def test_robust_shift_median_rejects_outliers():
    """配准残差估计：逐分量中位数对少数离群位移（错配/伪观测融合）鲁棒。"""
    good = [(5.0 + 0.3 * math.sin(i), -0.2 + 0.3 * math.cos(i)) for i in range(12)]
    outliers = [(40.0, 0.0), (-30.0, 5.0), (0.0, -25.0), (12.0, 33.0)]
    mu = robust_shift_mm(good + outliers)
    assert mu is not None
    assert mu[0] == pytest.approx(5.0, abs=0.5)
    assert mu[1] == pytest.approx(-0.2, abs=0.5)


def test_robust_shift_needs_min_samples():
    assert robust_shift_mm([(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]) is None


def test_side_mismatch_rejected():
    obs_bottom_side = synth_obs("bottom_001", "bottom", 10.0, 10.0)
    with pytest.raises(PairingError, match="side"):
        pair_observations([obs_bottom_side], [])


def test_duplicate_obs_id_rejected():
    dup = synth_obs("top_001", "top", 10.0, 10.0)
    other = synth_obs("top_001", "top", 40.0, 10.0)
    with pytest.raises(PairingError, match="重复"):
        pair_observations([dup, other], [])


def test_bad_gate_rejected():
    top = [synth_obs("top_001", "top", 10.0, 10.0)]
    with pytest.raises(PairingError):
        pair_observations(top, [], gate_mm=0.0)
    with pytest.raises(PairingError):
        pair_observations(top, [], gate_mm=float("inf"))


# ---------------------------------------------------------------------------
# 3) bean_id 稳定可复现
# ---------------------------------------------------------------------------


def _stable_dataset():
    top = [
        synth_obs("top_003", "top", 50.0, 20.0, defect="black", conf=0.9),
        synth_obs("top_001", "top", 10.0, 100.0),
        synth_obs("top_002", "top", 30.0, 60.0, defect="broken", conf=0.8),
    ]
    bottom = [
        synth_obs("bottom_002", "bottom", 30.8, 60.5, defect="broken", conf=0.7),
        synth_obs("bottom_001", "bottom", 10.4, 100.3),
        synth_obs("bottom_004", "bottom", 90.0, 90.0),  # 无 top 伙伴 → 单面
    ]
    return top, bottom


def test_same_input_same_output():
    top, bottom = _stable_dataset()
    r1 = pair_observations(top, bottom)
    r2 = pair_observations(top, bottom)
    assert [b.to_json() for b in r1] == [b.to_json() for b in r2]


def test_shuffled_input_same_output_and_sorted_by_anchor_xy():
    """输入顺序无关：乱序喂入结果完全一致；bean_id 按锚定质心 (x,y) 编号。"""
    top, bottom = _stable_dataset()
    baseline = [b.to_json() for b in pair_observations(top, bottom)]
    shuffled = pair_observations(list(reversed(top)), list(reversed(bottom)))
    assert [b.to_json() for b in shuffled] == baseline

    anchors = [
        (b.top if b.top is not None else b.bottom).mask.centroid_mm for b in shuffled
    ]
    assert anchors == sorted(anchors), "输出必须按锚定观测质心 (x,y) 升序"
    assert [b.bean_id for b in shuffled] == [f"b{i+1:04d}" for i in range(len(shuffled))]


# ---------------------------------------------------------------------------
# 4) 大规模合成统计（spec §4 M6 通过线）
# ---------------------------------------------------------------------------

N_BEANS = 200
JITTER_SIGMA_MM = 3.0  # 相对位移 σ：分解到两面各 3/√2（等价单面 σ=3）
MIN_SPACING_MM = 16.0
DROP_RATE = 0.10
N_PSEUDO_PER_SIDE = 5  # 伪观测按豆数 5%（与「10% 随机丢面」平行口径），两侧均摊
OFFSET_MM = (5.0, 0.0)  # 标定误差场景：bottom 整体平移
SEED = 20260928


def _sample_tray_positions(rng: random.Random, n: int, min_spacing: float) -> list[tuple[float, float]]:
    """盘面 [10,290]² 拒绝采样：任意两豆间距 ≥ min_spacing。"""
    pts: list[tuple[float, float]] = []
    attempts = 0
    while len(pts) < n:
        attempts += 1
        assert attempts < 200_000, "拒绝采样失败：间距约束过紧"
        p = (rng.uniform(10.0, 290.0), rng.uniform(10.0, 290.0))
        if all(_dist2d(p, q) >= min_spacing for q in pts):
            pts.append(p)
    return pts


def _build_scenario(
    seed: int,
    *,
    offset_mm: tuple[float, float] = (0.0, 0.0),
    drop_rate: float = DROP_RATE,
) -> tuple[list[BeanObservation], list[BeanObservation], list[dict]]:
    """合成 top/bottom 观测 + 真值表。

    真值表每条：{idx, both, side}——both=两面都在（配对目标），
    side=被留下的那一面（单面真值）。
    """
    rng = random.Random(seed)
    positions = _sample_tray_positions(rng, N_BEANS, MIN_SPACING_MM)
    s = JITTER_SIGMA_MM / math.sqrt(2.0)  # 每面各向同性抖动
    top_obs: list[BeanObservation] = []
    bottom_obs: list[BeanObservation] = []
    truth: list[dict] = []

    defects = ["normal"] * 8 + ["black", "broken", "sour"]
    for i, (x, y) in enumerate(positions):
        defect = rng.choice(defects)
        has_top, has_bottom = True, True
        if rng.random() < drop_rate:
            if rng.random() < 0.5:
                has_top = False
            else:
                has_bottom = False
        truth.append({"idx": i, "both": has_top and has_bottom,
                      "side": "top" if has_top else "bottom"})
        if has_top:
            top_obs.append(synth_obs(f"top_{i:04d}", "top",
                                     x + rng.gauss(0.0, s), y + rng.gauss(0.0, s),
                                     defect=defect))
        if has_bottom:
            bottom_obs.append(synth_obs(f"bottom_{i:04d}", "bottom",
                                        x + offset_mm[0] + rng.gauss(0.0, s),
                                        y + offset_mm[1] + rng.gauss(0.0, s),
                                        defect=defect))

    n_pseudo = N_PSEUDO_PER_SIDE
    for j in range(n_pseudo):
        top_obs.append(synth_obs(f"top_p{j:03d}", "top", rng.uniform(5.0, 295.0), rng.uniform(5.0, 295.0)))
    for j in range(n_pseudo):
        bottom_obs.append(synth_obs(f"bottom_p{j:03d}", "bottom", rng.uniform(5.0, 295.0), rng.uniform(5.0, 295.0)))

    rng.shuffle(top_obs)
    rng.shuffle(bottom_obs)
    return top_obs, bottom_obs, truth


def _is_pseudo(obs_id: str) -> bool:
    return "_p" in obs_id


def _bean_gt_idx(obs: BeanObservation) -> int | None:
    """观测 → 真值豆下标；伪观测返回 None。"""
    if _is_pseudo(obs.obs_id):
        return None
    return int(obs.obs_id.split("_", 1)[1])


def _pairing_metrics(beans: list[PairedBean], truth: list[dict]) -> dict[str, float]:
    gt_both = {t["idx"] for t in truth if t["both"]}
    emitted = [b for b in beans if b.top is not None and b.bottom is not None]
    correct = sum(
        1
        for b in emitted
        if _bean_gt_idx(b.top) is not None and _bean_gt_idx(b.top) == _bean_gt_idx(b.bottom)
    )
    return {
        "precision": correct / len(emitted),
        "recall": correct / len(gt_both),
        "n_emitted_pairs": len(emitted),
        "n_correct": correct,
        "n_gt_both": len(gt_both),
    }


def _assert_full_coverage(beans: list[PairedBean], top_obs: list[BeanObservation], bottom_obs: list[BeanObservation]):
    """不变式：每条输入观测恰好出现在一条记录里（不丢不重）。"""
    seen: list[str] = []
    for b in beans:
        seen += [o.obs_id for o in (b.top, b.bottom) if o is not None]
    want = sorted(o.obs_id for o in list(top_obs) + list(bottom_obs))
    assert sorted(seen) == want


def _assert_no_pair_over_gate(beans: list[PairedBean]):
    for b in beans:
        if b.top is not None and b.bottom is not None:
            assert b.pairing_cost <= DEFAULT_GATE_MM + 1e-9
        else:
            assert b.pairing_cost == -1


def _run_scenario(seed: int, offset_mm: tuple[float, float], label: str) -> dict[str, float]:
    top_obs, bottom_obs, truth = _build_scenario(seed, offset_mm=offset_mm)
    t0 = time.perf_counter()
    beans = pair_observations(top_obs, bottom_obs)
    dt = time.perf_counter() - t0
    metrics = _pairing_metrics(beans, truth)
    metrics["runtime_s"] = dt
    metrics["label"] = label  # type: ignore[assignment]
    _assert_full_coverage(beans, top_obs, bottom_obs)
    _assert_no_pair_over_gate(beans)
    s = summarize(beans)
    assert s.n_beans == len(beans)
    assert s.n_paired + s.n_top_only + s.n_bottom_only == s.n_beans
    metrics["n_top_only"] = float(s.n_top_only)  # type: ignore[assignment]
    metrics["n_bottom_only"] = float(s.n_bottom_only)  # type: ignore[assignment]
    return metrics


def test_statistical_200_beans_jitter():
    """基线场景：P ≥0.98、R ≥0.95、≤1s。"""
    m = _run_scenario(SEED, (0.0, 0.0), "baseline")
    print(f"\n[M6-STAT] baseline: {m}")
    assert m["precision"] >= 0.98, f"precision={m['precision']:.4f}"
    assert m["recall"] >= 0.95, f"recall={m['recall']:.4f}"
    assert m["runtime_s"] <= 1.0, f"runtime={m['runtime_s']:.3f}s"


def test_statistical_calibration_offset_5mm():
    """标定误差场景（bottom 整体平移 5mm）：P ≥0.98、R ≥0.95、≤1s。"""
    m = _run_scenario(SEED, OFFSET_MM, "offset5mm")
    print(f"\n[M6-STAT] offset5mm: {m}")
    assert m["precision"] >= 0.98, f"precision={m['precision']:.4f}"
    assert m["recall"] >= 0.95, f"recall={m['recall']:.4f}"
    assert m["runtime_s"] <= 1.0, f"runtime={m['runtime_s']:.3f}s"


def test_statistical_single_side_beans_kept_marked():
    """单面保留与标记：每条观测恰好进一条记录；单面记录 pairing_cost=-1
    且 worst_side=所在面；真值单面豆的记录要么单面、要么与伪观测融合
    （伪观测恰落入其门限圈内时不可分辨，属信息论极限，计数留档）。"""
    top_obs, bottom_obs, truth = _build_scenario(SEED)
    beans = pair_observations(top_obs, bottom_obs)

    # 1) 全部输出记录的标记正确性
    for b in beans:
        if (b.top is None) != (b.bottom is None):
            assert b.pairing_cost == -1
            assert b.worst_side == ("top" if b.top is not None else "bottom")
        elif b.top is not None:
            assert 0 <= b.pairing_cost <= DEFAULT_GATE_MM

    # 2) 真值单面豆：观测恰好落一条记录；若被配对，对象只能是伪观测
    n_fused_with_pseudo = 0
    for t in truth:
        if t["both"]:
            continue
        kept_id = f"{t['side']}_{t['idx']:04d}"
        recs = [
            b for b in beans
            if (b.top and b.top.obs_id == kept_id) or (b.bottom and b.bottom.obs_id == kept_id)
        ]
        assert len(recs) == 1, f"真值单面豆 {kept_id} 应恰好 1 条记录，得到 {len(recs)}"
        rec = recs[0]
        if rec.pairing_cost != -1:
            mate = rec.bottom if t["side"] == "top" else rec.top
            assert mate is not None and _is_pseudo(mate.obs_id), (
                f"{kept_id} 与真实豆 {mate.obs_id if mate else None} 错误融合"
            )
            n_fused_with_pseudo += 1
    n_gt_singles = sum(1 for t in truth if not t["both"])
    print(
        f"\n[M6-STAT] gt_singles={n_gt_singles} fused_with_pseudo={n_fused_with_pseudo} "
        f"(伪观测落入单面豆门限圈内，不可分辨)"
    )
