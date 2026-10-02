"""标准数值回填线测试（轨2/轨3 + DB46 法定表一致性）。

运行（仓库根）::

    .venv/Scripts/python.exe -m pytest tests/test_standards_values.py -q

覆盖（全部离线、合成数据）：
1. **DB46/T 642—2024 法定表与 PDF 抄录一致**：把印刷稿第 6/7 页表 1/表 2
   的抄录值固化为本文件的 Python 常量，断言 configs/standards/db46_t642.yaml
   的 legal 节与其逐值一致（双重复核：pymupdf 文本层 + 表格页 150 dpi 位图
   人工核对）；法定数值与引擎阈值同文件（单一来源）；
2. **大中小筛段（轨2）**：边界语义（16.99→medium / 17.00→large）、逐粒
   归属直方与 sieve_hist 聚合恒一致、占比、非法配置（重复键/不无缝）拒绝；
3. **精品/普通判定层（轨3）**：恰好 5 个次缺陷=精品、6 个=降级、1 个主
   缺陷=普通；理由模板键格式；warnings 透传；PremiumDecision JSON 往返；
4. **DB46 法定等级**：缺陷 % 边界（≤4.0 一级 / 区间落二级 / >7.0 三级）、
   「一级无严重缺陷」、6.5.4 粒度 5% 容差边界（恰 5% 过 / 6% 降级 / 低于
   下一级主档即否）、水分占位（None 不阻断、提供超限判等外）、外来杂质。
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest
import yaml

from beaneye.metrology import (
    aggregate_sieve_hist,
    band_of_screen,
    load_size_bands,
    measure,
    size_band_histogram,
)
from beaneye.metrology.size_bands import SizeBandError
from beaneye.schemas import (
    BeanMask,
    BeanObservation,
    Measurements,
    PairedBean,
    PremiumDecision,
    StatsSummary,
)
from beaneye.severity import adjudicate_pairs
from beaneye.standards import (
    DB46LegalError,
    StandardEngineV1,
    db46_legal_grade,
    load_db46_legal,
    load_standard,
)

TAX_KEYS_ORDER = [
    "normal", "broken", "faded", "brocade", "immature", "peaberry", "shell",
    "elephant", "insect", "dried", "sour", "mold", "black",
]
RANK = {k: i for i, k in enumerate(TAX_KEYS_ORDER)}
SEQ = itertools.count(1)

REASON_RE = re.compile(r"^[A-Za-z0-9_.]+(:\S.*)?$")

LEGAL_YAML_PATH = Path(__file__).resolve().parents[1] / "configs" / "standards" / "db46_t642.yaml"


# ---------------------------------------------------------------------------
# 确定性构造器（与 test_standards.py 同模式，自包含）
# ---------------------------------------------------------------------------


def _mask(mid: str, side: str = "top") -> BeanMask:
    return BeanMask(
        mask_id=mid,
        side=side,  # type: ignore[arg-type]
        polygon=[[10.0, 20.0], [16.0, 20.0], [16.0, 26.0], [10.0, 26.0]],
        bbox_mm=(10.0, 20.0, 16.0, 26.0),
        area_mm2=36.0,
        centroid_mm=(13.0, 23.0),
        source="oracle",
        conf=1.0,
    )


def _obs(side: str, defect: str, eq_mm: float = 6.0, conf: float = 0.90) -> BeanObservation:
    mid = f"{side}_{next(SEQ):03d}"
    return BeanObservation(
        obs_id=mid,
        side=side,  # type: ignore[arg-type]
        defect=defect,
        defect_conf=conf,
        severity_rank=RANK[defect],
        crop_path=f"out/crops/scan_values/{mid}.png",
        mask=_mask(mid, side),
        color_lab=(132.6, 120.0, 148.0),
        eq_diameter_mm=eq_mm,
    )


def _bean(top_defect: str, bottom_defect: str | None = None, eq_mm: float = 6.0) -> PairedBean:
    bottom = _obs("bottom", bottom_defect, eq_mm) if bottom_defect is not None else None
    cost = 1.5 if bottom is not None else -1.0
    return adjudicate_pairs([(f"b{next(SEQ):04d}", _obs("top", top_defect, eq_mm), bottom, cost)])[0]


def make_beans(spec: dict[str, int], eq_mm: float = 6.0) -> list[PairedBean]:
    """{缺陷类(或 normal) → 粒数} → 单面 PairedBean 列表（id 稳定）。"""
    out: list[PairedBean] = []
    for defect, n in spec.items():
        for _ in range(n):
            out.append(_bean(defect, eq_mm=eq_mm))
    return out


def make_measurements(
    *,
    sieve_hist: dict[str, int] | None = None,
    delta_e: float = 3.0,
    bean_count: int = 100,
) -> Measurements:
    return Measurements(
        bean_count=bean_count,
        sieve_hist=sieve_hist if sieve_hist is not None else {"15": 90, "16": 60},
        sieve_pass=None,
        eq_diameter_mm_stats=StatsSummary(min=5.9, max=6.2, mean=6.0, median=6.0),
        color_lab_mean=(132.6, 120.0, 148.0),
        delta_e_mean=delta_e,
        delta_e_hist={"2-4": bean_count},
        est_weight_g=90.0,
        weight_model="area_linear:v1",
    )


# ---------------------------------------------------------------------------
# 1. DB46/T 642—2024 法定表 ↔ PDF 抄录一致性（抄录固化 = 本文件常量）
# ---------------------------------------------------------------------------

# 抄录来源：DB46/T 642—2024 印刷稿第 6 页（表 1、表 2）与第 7 页（表 2 续）。
# 抄录方式：pymupdf 文本层全文抽取 + 表格页 150 dpi 位图逐页人工复核（一致）。
# 元组语义：杯品（名称, 得分下限, 得分上限|None）；理化（名称, 缺陷豆%上限,
# 缺陷豆%下限|None, 外来杂质%上限, 外来杂质%下限|None, 筛号下限, 筛号上限|None,
# 一级无严重缺陷）。
PDF_TABLE1_CUP: tuple[tuple[str, float, float | None], ...] = (
    ("杯品一级", 80.0, None),   # 4.2 表 1：最终得分 ≥80
    ("杯品二级", 70.0, 79.0),   # 70～79
    ("杯品三级", 60.0, 69.0),   # 60～69
)
PDF_TABLE2_PHYS: tuple[tuple[str, float, float | None, float, float | None, int, int | None, bool], ...] = (
    ("一级", 4.0, None, 0.5, None, 16, None, True),    # ≤4.0 / ≤0.5 / ≥16 / 无严重缺陷
    ("二级", 7.0, 4.1, 0.8, 0.6, 14, 15, False),       # 4.1～7.0 / 0.6～0.8 / 14～15
    ("三级", 10.0, 7.1, 1.2, 0.9, 12, 13, False),      # 7.1～10.0 / 0.9～1.2 / 12～13
)
PDF_GLOBAL_PHYS = {"moisture_pct_max": 12.0, "ash_pct_max": 5.5, "caffeine_pct_min": 1.5}
PDF_TOLERANCE_FRAC = 0.05          # 6.5.4：各级允许 5% 粒度不符本级
PDF_SENSORY_SAMPLE_G = 300         # 5.1 感官取样 300 g


def test_db46_legal_yaml_matches_pdf_transcription():
    """configs/standards/db46_t642.yaml 的 legal 节与 PDF 抄录常量逐值一致。"""
    raw = yaml.safe_load(LEGAL_YAML_PATH.read_text(encoding="utf-8"))["legal"]
    # 表 1 杯品等级（4.2）
    cup = raw["cup_grades"]
    assert [(c["name"], float(c["final_score_min"]), c.get("final_score_max")) for c in cup] == [
        (n, lo, hi) for n, lo, hi in PDF_TABLE1_CUP
    ]
    # 表 2 理化等级（4.3）
    phys = raw["phys_grades"]
    got = [
        (
            g["name"],
            float(g["defect_pct_max"]),
            g.get("defect_pct_min"),
            float(g["foreign_matter_pct_max"]),
            g.get("foreign_matter_pct_min"),
            int(g["sieve_min"]),
            g.get("sieve_max"),
            bool(g.get("no_serious_defect", False)),
        )
        for g in phys
    ]
    assert got == [tuple(row) for row in PDF_TABLE2_PHYS]
    # 表 2 全局（水分/灰分/咖啡因，跨等级合并单元格）与 6.5.4 容差、5.1 取样量
    assert float(raw["phys_global"]["moisture_pct_max"]) == PDF_GLOBAL_PHYS["moisture_pct_max"]
    assert float(raw["phys_global"]["ash_pct_max"]) == PDF_GLOBAL_PHYS["ash_pct_max"]
    assert float(raw["phys_global"]["caffeine_pct_min"]) == PDF_GLOBAL_PHYS["caffeine_pct_min"]
    assert float(raw["sieve_tolerance"]["frac_allowed_off_grade"]) == PDF_TOLERANCE_FRAC
    assert int(raw["methods"]["sensory_sample_g"]) == PDF_SENSORY_SAMPLE_G
    # 附录 B 杯品法锚点（烘焙 150 g、每杯 8.25 g、5 杯、92 ℃）
    cb = raw["cupping_method"]
    assert int(cb["roast_sample_g"]) == 150 and int(cb["cups"]) == 5
    assert float(cb["dose_g_per_cup"]) == 8.25 and float(cb["water_temp_c"]) == 92.0


def test_db46_legal_loader_view_consistent():
    """load_db46_legal 的内存视图与抄录常量一致 + 单调放宽。"""
    leg = load_db46_legal()
    assert [g.name for g in leg.phys_grades] == [r[0] for r in PDF_TABLE2_PHYS]
    for g, row in zip(leg.phys_grades, PDF_TABLE2_PHYS):
        assert g.defect_pct_max == row[1]
        assert g.foreign_matter_pct_max == row[3]
        assert g.sieve_min == row[5]
        assert g.no_serious_defect is row[7]
    assert leg.moisture_pct_max == PDF_GLOBAL_PHYS["moisture_pct_max"]
    assert leg.ash_pct_max == PDF_GLOBAL_PHYS["ash_pct_max"]
    assert leg.caffeine_pct_min == PDF_GLOBAL_PHYS["caffeine_pct_min"]
    assert leg.sieve_tolerance_frac == PDF_TOLERANCE_FRAC
    assert leg.sensory_sample_g == PDF_SENSORY_SAMPLE_G


def test_db46_legal_loader_rejects_non_monotonic(tmp_path: Path):
    """法定表等级必须从优到劣单调放宽（与标准 YAML loader 同纪律）。"""
    p = tmp_path / "db46_bad.yaml"
    src = LEGAL_YAML_PATH.read_text(encoding="utf-8")
    # 把 legal 节一级的缺陷上限改得比二级更松 → 非单调（legal 节首个 4.0）
    broken = src.replace("      defect_pct_max: 4.0", "      defect_pct_max: 8.0", 1)
    assert broken != src
    p.write_text(broken, encoding="utf-8")
    with pytest.raises(DB46LegalError, match="单调放宽"):
        load_db46_legal(p)
    with pytest.raises(DB46LegalError, match="不存在"):
        load_db46_legal(tmp_path / "nope.yaml")


# ---------------------------------------------------------------------------
# 2. 大中小筛段（轨2）
# ---------------------------------------------------------------------------


def test_size_band_boundaries_16_99_17_00():
    """筛段边界（简报指定）：16.99 → 中，17.00 → 大；整目数 16/17 同语义。"""
    sb = load_size_bands()
    assert band_of_screen(16.99, sb) == "medium"
    assert band_of_screen(17.00, sb) == "large"
    assert band_of_screen(16, sb) == "medium"
    assert band_of_screen(17, sb) == "large"
    # 连续域左闭右开：14.99 仍属小，15.00 起属中
    assert band_of_screen(14.99, sb) == "small"
    assert band_of_screen(15.00, sb) == "medium"


def test_size_band_per_bean_hist_matches_sieve_hist_aggregation():
    """逐粒归属直方 ≡ sieve_hist 聚合（同目数口径），且占比和为 1。"""
    # 6.0mm→15 目(中)、5.0mm→13 目(小)、6.6mm→17 目(大)（round_half_up 口径）
    beans = [
        _bean("normal", eq_mm=6.0),
        _bean("normal", eq_mm=6.0),
        _bean("normal", eq_mm=5.0),
        _bean("normal", eq_mm=6.6),
    ]
    m = measure(beans, None, None)
    per_bean = size_band_histogram(beans)
    agg = aggregate_sieve_hist(m.sieve_hist)
    assert per_bean.hist == agg == {"large": 1, "medium": 2, "small": 1}
    assert per_bean.bean_count == m.bean_count == 4
    assert per_bean.per_bean == ("medium", "medium", "small", "large")
    assert abs(sum(per_bean.frac.values()) - 1.0) < 1e-9
    # m.sieve_hist 与逐粒目数同源：{"13":1,"15":2,"17":1}
    assert m.sieve_hist == {"13": 1, "15": 2, "17": 1}


def test_size_band_empty_tray_fracs_zero():
    beans: list[PairedBean] = []
    h = size_band_histogram(beans)
    assert h.hist == {"large": 0, "medium": 0, "small": 0}
    assert h.frac == {"large": 0.0, "medium": 0.0, "small": 0.0}
    assert h.bean_count == 0


def test_size_band_loader_rejects_bad_configs(tmp_path: Path):
    """重复键 / 区间不无缝 / 未知键 → SizeBandError（含来源路径）。"""
    good = (Path(__file__).resolve().parents[1] / "configs" / "size_bands.yaml").read_text(encoding="utf-8")
    cases = [
        # 区间留洞：中段改 16~16，与 17 之间 16.5 悬空（整域差 >1）
        ("gap", good.replace("min_screen: 15", "min_screen: 16", 1), "不无缝"),
        # 键重复
        ("dup", good.replace("key: medium", "key: large", 1), "重复"),
        # 未知键（追加 zhx：missing 校验过后由 extra 校验命中）
        ("typo", good.replace("zh: 大粒", "zh: 大粒\n    zhx: 大粒", 1), "未知键"),
    ]
    for name, text, fragment in cases:
        p = tmp_path / f"bands_{name}.yaml"
        p.write_text(text, encoding="utf-8")
        with pytest.raises(SizeBandError, match=fragment):
            load_size_bands(p)


# ---------------------------------------------------------------------------
# 3. 精品/普通判定层（轨3）
# ---------------------------------------------------------------------------


def test_premium_boundary_5_secondary_in_6_out():
    """简报边界样例：恰好 5 个次缺陷 = 精品；6 个 = 降级。"""
    d5 = StandardEngineV1.load("cqi_fine_robusta").evaluate_premium(
        make_beans({"broken": 5}), make_measurements(bean_count=5)
    )
    d6 = StandardEngineV1.load("cqi_fine_robusta").evaluate_premium(
        make_beans({"broken": 6}), make_measurements(bean_count=6)
    )
    assert d5.verdict == "premium" and d5.secondary_count == 5
    assert d6.verdict == "commercial" and d6.secondary_count == 6


def test_premium_any_primary_is_commercial():
    """0 严重是精品前提：1 粒主缺陷（即使次缺陷 0）→ 普通。"""
    d = StandardEngineV1.load("cqi_fine_robusta").evaluate_premium(
        make_beans({"black": 1}), make_measurements(bean_count=1)
    )
    assert d.verdict == "commercial" and d.primary_count == 1


def test_premium_peaberry_not_counted_and_size_bands_recorded():
    """peaberry 不计缺陷；大中小直方随结论透出。"""
    eng = StandardEngineV1.load("cqi_fine_robusta")
    beans = make_beans({"peaberry": 7, "normal": 5}, eq_mm=6.0)
    m = measure(beans, None, None)
    d = eng.evaluate_premium(beans, m)
    assert d.verdict == "premium" and d.primary_count == 0 and d.secondary_count == 0
    assert d.size_band_hist == {"large": 0, "medium": 12, "small": 0}
    assert d.bean_count == 12


def test_premium_reasons_format_and_warnings_passthrough():
    """理由模板键格式合法；CQI 基准的未核对告警（4 条）透传。"""
    d = StandardEngineV1.load("cqi_fine_robusta").evaluate_premium(
        make_beans({"broken": 6}), make_measurements(bean_count=6)
    )
    assert d.reasons
    for r in d.reasons:
        assert REASON_RE.match(r), f"reason 格式非法: {r!r}"
    keys = [r.split(":", 1)[0] for r in d.reasons]
    assert "premium.reason.primary_within" in keys
    assert "premium.reason.secondary_over" in keys
    assert "premium.reason.verdict" in keys
    assert "premium.reason.size_bands" in keys
    assert "premium.reason.moisture_placeholder" in keys  # 水分占位注明
    # warnings 沿用 GradingDecision.warnings 机制（基准标准未核对 → 4 条）
    std = load_standard("cqi_fine_robusta")
    assert d.warnings == list(std.warnings) and len(d.warnings) == 4


def test_premium_thresholds_from_basis_best_grade():
    """阈值取基准标准最优级（CQI Fine：0 主 / 5 次），并写入结论。"""
    d = StandardEngineV1.load("cqi_fine_robusta").evaluate_premium(
        make_beans({"broken": 5}), make_measurements(bean_count=5)
    )
    assert d.standard_id == "cqi_fine_robusta"
    assert d.primary_limit == 0 and d.secondary_equiv_limit == 5.0
    assert d.secondary_equiv_count == 5.0  # v0 等效 1:1


def test_premium_basis_fixed_to_cqi_even_on_db46_engine():
    """精品口径恒为 CQI：db46 引擎（法定百分比档，粒数轴为 None）调用
    evaluate_premium 不崩、阈值回退 CQI 基准（0/5）——轨3 spec 口径。"""
    eng = StandardEngineV1.load("db46_t642")
    d = eng.evaluate_premium(make_beans({"broken": 5}), make_measurements(bean_count=5))
    assert d.standard_id == "cqi_fine_robusta"
    assert d.primary_limit == 0 and d.secondary_equiv_limit == 5.0
    assert d.verdict == "premium"


def test_premium_decision_json_roundtrip_and_validation():
    """PremiumDecision：JSON 往返无损；负计数被拒（契约校验器）。"""
    d = StandardEngineV1.load("cqi_fine_robusta").evaluate_premium(
        make_beans({"broken": 6}), make_measurements(bean_count=6)
    )
    again = PremiumDecision.from_json(d.to_json())
    assert again == d and again.to_json() == d.to_json()
    data = d.model_dump(mode="json")
    data["size_band_hist"]["large"] = -1
    with pytest.raises(Exception, match="计数必须 >= 0"):
        PremiumDecision.model_validate(data)


# ---------------------------------------------------------------------------
# 4. DB46 法定等级（轨3 · DB46 口径）
# ---------------------------------------------------------------------------


class TestDb46LegalGrade:
    """表 2 口径判定：缺陷 % 边界 + 一级无严重缺陷 + 6.5.4 容差 + 水分占位。"""

    LEG = load_db46_legal()
    FULL_OK = {str(s): 60 for s in range(16, 19)}  # 180 粒全部 ≥16 目

    def test_exact_4pct_no_serious_is_grade1(self):
        # 180 粒中 7 粒缺陷 = 3.89% ≤4.0 → 理化一级（0 主）
        grade, _ = db46_legal_grade(0, 7, 180, self.FULL_OK, self.LEG)
        assert grade == "理化一级"

    def test_defect_boundary_4pct_passes_4p01_lands_g2(self):
        # 恰好 4.0%（250 粒 × 4% = 10 粒）→ 一级
        grade, _ = db46_legal_grade(0, 10, 250, {"16": 125, "17": 125}, self.LEG)
        assert grade == "理化一级"
        # 4.4%（250×0.044=11 粒）>4.0 → 一级不达 → 二级（区间表现：连续量取上限档）
        grade2, _ = db46_legal_grade(0, 11, 250, {"16": 125, "17": 125}, self.LEG)
        assert grade2 == "理化二级"

    def test_over_7pct_is_grade3(self):
        # 7.33% > 7.0 → 三级（≤10.0）
        grade, _ = db46_legal_grade(0, 22, 300, {"16": 300}, self.LEG)
        assert grade == "理化三级"

    def test_serious_defect_blocks_grade1(self):
        # 缺陷总量 ≤4.0% 但含 1 粒严重缺陷 → 一级「应无严重缺陷」不达 → 二级
        grade, reasons = db46_legal_grade(1, 6, 180, self.FULL_OK, self.LEG)
        assert grade == "理化二级"

    def test_sieve_tolerance_5pct_boundary(self):
        # 恰 5% 低于 16 目（但 ≥14）：6.5.4 容差内 → 一级
        hist5 = {"16": 285, "15": 15}
        assert db46_legal_grade(0, 12, 300, hist5, self.LEG)[0] == "理化一级"
        # 6% 低于 16 目（均 ≥14）→ 超容差 → 二级
        hist6 = {"16": 282, "15": 18}
        assert db46_legal_grade(0, 12, 300, hist6, self.LEG)[0] == "理化二级"

    def test_below_next_grade_floor_rejects_higher_grade(self):
        # 5% 内但含低于 14 目 → 不符「下一级要求」→ 一级否决 → 二级（低于 12 同理再降）
        hist = {"16": 286, "15": 13, "13": 1}
        assert db46_legal_grade(0, 12, 300, hist, self.LEG)[0] == "理化二级"
        hist2 = {"16": 286, "15": 13, "11": 1}
        # 低于 12 目：一级（下一级 14）否、二级（下一级 12）否 → 三级（容差内、无下一级）
        assert db46_legal_grade(0, 12, 300, hist2, self.LEG)[0] == "理化三级"

    def test_over_5pct_below_grade3_floor_is_fail(self):
        # 6.7% 低于 12 目 → 三级也不达 → 理化等外
        hist = {"13": 280, "11": 20}
        assert db46_legal_grade(0, 0, 300, hist, self.LEG)[0] == "理化等外"

    def test_moisture_placeholder_and_over_limit(self):
        # 未提供水分 → 占位理由、不阻断
        grade, reasons = db46_legal_grade(0, 7, 180, self.FULL_OK, self.LEG, moisture_pct=None)
        assert grade == "理化一级"
        assert any(r.startswith("db46.reason.moisture_placeholder") for r in reasons)
        # 提供超限水分（表 2 全局 ≤12.0）→ 等外 + 理由
        grade2, reasons2 = db46_legal_grade(0, 0, 180, self.FULL_OK, self.LEG, moisture_pct=12.5)
        assert grade2 == "理化等外"
        assert any(r.startswith("db46.reason.moisture_over") for r in reasons2)

    def test_foreign_matter_over_limit_fails(self):
        grade, reasons = db46_legal_grade(
            0, 7, 180, self.FULL_OK, self.LEG, foreign_matter_pct=1.5
        )
        assert grade == "理化等外"
        assert any(r.startswith("db46.reason.foreign_matter_over") for r in reasons)

    def test_empty_tray_returns_none_with_reason(self):
        grade, reasons = db46_legal_grade(0, 0, 0, {}, self.LEG)
        assert grade is None and "db46.reason.empty_tray" in reasons


def test_evaluate_premium_db46_legal_annotation():
    """evaluate_premium(db46_legal=True)：同一输入附带 DB46 法定等级 + 理由。"""
    eng = StandardEngineV1.load("cqi_fine_robusta")
    beans = make_beans({"broken": 5})
    # sieve_hist 全 ≥16：缺陷 5/60 = 8.3% → 三级；精品档达成（CQI 口径）
    m = make_measurements(sieve_hist={"16": 60}, bean_count=60)
    d = eng.evaluate_premium(beans, m, db46_legal=True)
    assert d.verdict == "premium"
    assert d.grade_legal_db46 == "理化三级"
    assert any(r.startswith("db46.reason.grade_selected") for r in d.reasons)
    assert any(r.startswith("db46.reason.count_to_mass_approx") for r in d.reasons)
