"""M9 标准引擎 eval：表驱动（不同瑕疵组合 → 各级别判定正确）
+ verified 标志传递 + 错误信息含文件路径与行号。

运行（仓库根）::

    .venv/Scripts/python.exe -m pytest tests/test_standards.py -q

表驱动 GradeCase 覆盖（spec：≥20 用例）：
- CQI：0 主 +5 次 = 层级达 Fine（verified:false → passed=False，W13 ⑤）/
  0 主 +6 次 = 不过 / 1 主 = 不过 / peaberry 不计缺陷；
- NY/T：一/二/三级阈值与筛目降级链；DB46：特/一/合格阈值 + 全局色差条件；
- 引擎横切：sha256、warnings 传递、reasons 模板键格式、BatchResult 不变式、
  未知 id / 非法 YAML（解析 + 语义 + 重复键）的路径行号报错、count_rule。
"""

from __future__ import annotations

import hashlib
import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

from beaneye.schemas import (
    BatchResult,
    BeanMask,
    BeanObservation,
    GradingDecision,
    Measurements,
    PairedBean,
    StatsSummary,
)
from beaneye.severity import adjudicate_pairs
from beaneye.standards import (
    DEFAULT_STANDARDS_DIR,
    StandardsError,
    StandardEngineV1,
    list_standards,
    load_standard,
)
from beaneye.taxonomy import load_taxonomy

TAX = load_taxonomy()
RANK = {k: TAX.severity_rank(k) for k in TAX.keys()}
SEQ = itertools.count(1)

SHIPPED = ("cqi_fine_robusta", "nyt_604", "db46_t642")

REASON_RE = re.compile(r"^[A-Za-z0-9_.]+(:\S.*)?$")


# ---------------------------------------------------------------------------
# 确定性构造器（合成数据，不依赖真实豆图/数据集）
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


def _obs(side: str, defect: str, conf: float = 0.90) -> BeanObservation:
    mid = f"{side}_{next(SEQ):03d}"
    return BeanObservation(
        obs_id=mid,
        side=side,
        defect=defect,
        defect_conf=conf,
        severity_rank=RANK[defect],  # 三套标准 YAML v0 均用 taxonomy 默认序
        crop_path=f"out/crops/scan_standards/{mid}.png",
        mask=_mask(mid, side),  # W13 契约：side 必须与 mask.side 一致
        color_lab=(132.6, 120.0, 148.0),  # lab8 标度（契约单一标度，W13）
        eq_diameter_mm=6.0,
    )


def _bean(bean_id: str, top_defect: str, bottom_defect: str | None = None) -> PairedBean:
    bottom = _obs("bottom", bottom_defect) if bottom_defect is not None else None
    cost = 1.5 if bottom is not None else -1.0
    return adjudicate_pairs([(bean_id, _obs("top", top_defect), bottom, cost)])[0]


def make_beans(spec: dict[str, int]) -> list[PairedBean]:
    """{缺陷类(或 normal) → 粒数} → 单面 PairedBean 列表（id 稳定）。"""
    out: list[PairedBean] = []
    for defect, n in spec.items():
        for _ in range(n):
            out.append(_bean(f"b{next(SEQ):04d}", defect))
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
        color_lab_mean=(132.6, 120.0, 148.0),  # lab8 标度
        delta_e_mean=delta_e,
        delta_e_hist={"2-4": bean_count},
        est_weight_g=90.0,
        weight_model="area_linear:v1",
    )


def evaluate_case(
    standard: str,
    spec: dict[str, int],
    *,
    sieve_hist: dict[str, int] | None = None,
    delta_e: float = 3.0,
) -> GradingDecision:
    engine = StandardEngineV1.load(standard)
    return engine.evaluate(make_beans(spec), make_measurements(sieve_hist=sieve_hist, delta_e=delta_e))


# ---------------------------------------------------------------------------
# 表驱动用例（不同瑕疵组合 → 各级别判定正确）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GradeCase:
    id: str
    standard: str
    spec: dict[str, int]                  # final_defect → 粒数
    sieve_hist: dict[str, int] | None = None
    delta_e: float = 3.0
    expect_grade: str = ""
    # W13 修复（评审 A/M 项）：出厂三套 YAML 全部 verified:false，引擎对未
    # 核对阈值一律不给 passed=True（grade 名仍记录实际达到的层级）。默认即
    # False；全部键置 verified:true 后才可能 passed=True（见
    # test_all_verified_yields_pass_possible）。显式 expect_passed=False
    # 的条目保留作审计。
    expect_passed: bool = False
    expect_primary: int = 0
    expect_secondary: int = 0
    expect_counts: dict[str, int] = field(default_factory=dict)


C = GradeCase  # 简写
CASES: list[GradeCase] = [
    # --- CQI Fine Robusta：Fine = 0 主 + ≤5 次（开发指令 §3.3 基线）------
    C("cqi_0p0s_all_normal_pass", "cqi_fine_robusta", {"normal": 12},
      expect_grade="Fine", expect_primary=0, expect_secondary=0),
    C("cqi_0p5s_boundary_pass", "cqi_fine_robusta", {"broken": 5},
      expect_grade="Fine", expect_secondary=5),
    C("cqi_0p6s_boundary_fail", "cqi_fine_robusta", {"broken": 6},
      expect_grade="未达 Fine", expect_passed=False, expect_secondary=6),
    C("cqi_1p0s_fail", "cqi_fine_robusta", {"black": 1},
      expect_grade="未达 Fine", expect_passed=False, expect_primary=1),
    C("cqi_1p5s_fail_primary_dominates", "cqi_fine_robusta", {"mold": 1, "broken": 5},
      expect_grade="未达 Fine", expect_passed=False, expect_primary=1, expect_secondary=5,
      expect_counts={"mold": 1, "broken": 5}),
    C("cqi_mix_5s_pass", "cqi_fine_robusta", {"broken": 2, "faded": 3},
      expect_grade="Fine", expect_secondary=5,
      expect_counts={"broken": 2, "faded": 3}),
    C("cqi_peaberry_not_a_defect", "cqi_fine_robusta", {"peaberry": 7},
      expect_grade="Fine", expect_primary=0, expect_secondary=0,
      expect_counts={"peaberry": 7}),
    # --- NY/T 604（占位基线：一级 0/8/筛15，二级 2/16/筛14，三级 5/30/筛13）--
    C("nyt_g1_zero_defect", "nyt_604", {},
      expect_grade="一级"),
    C("nyt_g1_secondary_boundary", "nyt_604", {"broken": 8},
      expect_grade="一级", expect_secondary=8),
    C("nyt_g2_one_primary", "nyt_604", {"insect": 1, "broken": 5},
      expect_grade="二级", expect_primary=1, expect_secondary=5),
    C("nyt_g2_both_boundary", "nyt_604", {"black": 2, "faded": 16},
      expect_grade="二级", expect_primary=2, expect_secondary=16),
    C("nyt_g3_boundary", "nyt_604", {"sour": 5, "broken": 30},
      expect_grade="三级", expect_primary=5, expect_secondary=30),
    C("nyt_over_all_fail", "nyt_604", {"sour": 6},
      expect_grade="等外", expect_passed=False, expect_primary=6),
    C("nyt_sieve_downgrade_g1_to_g2", "nyt_604", {},
      sieve_hist={"14": 4, "15": 40},
      expect_grade="二级"),  # 一级筛 15：4 粒 14 目 → 降二级
    C("nyt_sieve_downgrade_g2_to_g3", "nyt_604", {},
      sieve_hist={"13": 2, "14": 10},
      expect_grade="三级"),  # 二级筛 14 仍有 13 目 → 降三级
    C("nyt_sieve_below_all_fail", "nyt_604", {},
      sieve_hist={"12": 1, "15": 30},
      expect_grade="等外", expect_passed=False),  # 三级筛 13：1 粒 12 目 → 等外
    # --- DB46/T 642（占位基线：特级 0/4/筛14，一级 1/8/筛13，合格 3/18/无筛；
    #     全局色差条件 delta_e_max=10.0）-----------------------------------
    C("db46_special_zero_defect", "db46_t642", {},
      expect_grade="特级"),
    C("db46_special_secondary_boundary", "db46_t642", {"brocade": 4},
      expect_grade="特级", expect_secondary=4),
    C("db46_secondary_over_to_g1", "db46_t642", {"brocade": 5},
      expect_grade="一级", expect_secondary=5),
    C("db46_g1_primary_boundary", "db46_t642", {"insect": 1, "broken": 7},
      expect_grade="一级", expect_primary=1, expect_secondary=7),
    C("db46_hege_boundary", "db46_t642", {"black": 3, "broken": 18},
      expect_grade="合格", expect_primary=3, expect_secondary=18),
    C("db46_over_all_fail", "db46_t642", {"insect": 4},
      expect_grade="等外", expect_passed=False, expect_primary=4),
    C("db46_delta_e_boundary_pass", "db46_t642", {}, delta_e=10.0,
      expect_grade="特级"),  # ≤10.0 恰好达标
    C("db46_delta_e_over_all_fail", "db46_t642", {}, delta_e=10.01,
      expect_grade="等外", expect_passed=False),  # 全局色差条件压过所有级别
    C("db46_delta_e_over_even_at_hege", "db46_t642", {"insect": 2, "broken": 16},
      delta_e=12.0, expect_grade="等外", expect_passed=False,
      expect_primary=2, expect_secondary=16),
    C("db46_sieve_downgrade_special_to_g1", "db46_t642", {},
      sieve_hist={"13": 6, "16": 40},
      expect_grade="一级"),  # 特级筛 14：6 粒 13 目 → 降一级
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_grade_case_table(case: GradeCase):
    """表驱动：瑕疵组合 → (grade, passed, 主/次计数, defect_counts) 全对。"""
    decision = evaluate_case(case.standard, case.spec, sieve_hist=case.sieve_hist, delta_e=case.delta_e)
    assert decision.standard_id == case.standard
    assert decision.grade == case.expect_grade, decision.reasons
    assert decision.passed is case.expect_passed
    assert decision.primary_count == case.expect_primary
    assert decision.secondary_count == case.expect_secondary
    if case.expect_counts:
        assert decision.defect_counts == case.expect_counts


def test_table_size_meets_spec():
    """spec：表驱动 ≥20 用例。"""
    assert len(CASES) >= 20


def test_severity_pairing_interplay_counts_once():
    """与 M7 衔接：一面 normal 一面 broken → final=broken，只计一次次缺陷。"""
    beans = [_bean("b0001", "normal", "broken")]
    engine = StandardEngineV1.load("cqi_fine_robusta")
    d = engine.evaluate(beans, make_measurements(bean_count=1))
    assert d.defect_counts == {"broken": 1}
    assert d.secondary_count == 1 and d.primary_count == 0
    # W13 ⑤：标准阈值 verified:false → 达标也不给 passed=True
    assert not d.passed and d.grade == "Fine"
    assert "grading.reason.pass_blocked_unverified" in [r.split(":", 1)[0] for r in d.reasons]


# ---------------------------------------------------------------------------
# 引擎横切：sha / warnings / reasons / 协议 / 不变式 / 确定性
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sid", SHIPPED)
def test_sha256_matches_file_bytes(sid: str):
    std = load_standard(sid)
    digest = hashlib.sha256((DEFAULT_STANDARDS_DIR / f"{sid}.yaml").read_bytes()).hexdigest()
    assert std.sha256 == digest
    assert re.fullmatch(r"[0-9a-f]{64}", std.sha256)
    engine = StandardEngineV1(std)
    d = engine.evaluate([], make_measurements())
    assert d.standard_yaml_sha == digest


def test_list_standards_contains_shipped_three():
    listed = set(list_standards())
    assert set(SHIPPED) <= listed
    for sid in SHIPPED:
        std = load_standard(sid)  # 三套 YAML 全部能加载
        assert std.standard_id == sid


def test_verified_false_collected_as_warnings():
    """verified 标志传递：三套出厂 YAML 全部 verified:false → warnings 非空。"""
    for sid in SHIPPED:
        std = load_standard(sid)
        assert std.warnings, sid
    cqi = load_standard("cqi_fine_robusta")
    assert list(cqi.warnings) == [
        "verified:false @ grades[0](name=Fine)",
        "verified:false @ metrology.sieve_targets(min_screen)",
        "verified:false @ metrology.reference_lab",
        "verified:false @ weight",
    ]
    nyt = load_standard("nyt_604")
    assert any("grades[2](name=三级)" in w for w in nyt.warnings)
    # warnings 进入 GradingDecision（M10 页脚角标数据源）
    d = StandardEngineV1(cqi).evaluate([], make_measurements())
    assert d.warnings == list(cqi.warnings)


def _tmp_standard(tmp_path: Path, stem: str, mutate=None) -> Path:
    """以出厂 cqi YAML 为模板生成临时标准文件（可注入变异）。"""
    raw = yaml.safe_load((DEFAULT_STANDARDS_DIR / "cqi_fine_robusta.yaml").read_text(encoding="utf-8"))
    raw["standard"] = stem
    if mutate is not None:
        mutate(raw)
    p = tmp_path / f"{stem}.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def _set_all_verified(raw: dict) -> None:
    raw["grades"][0]["verified"] = True
    raw["metrology"]["sieve_targets"]["verified"] = True
    raw["metrology"]["reference_lab_verified"] = True
    raw["weight"]["verified"] = True


def test_all_verified_yields_no_warnings(tmp_path: Path):
    p = _tmp_standard(tmp_path, "all_ok", _set_all_verified)
    std = load_standard(p)
    assert std.warnings == ()
    d = StandardEngineV1(std).evaluate([], make_measurements())
    assert d.warnings == []
    # W13 ⑤：全部键核对后阻断解除——0 主 0 次（空盘）可达 Fine 且 passed=True
    assert d.passed is True and d.grade == "Fine"
    assert "grading.reason.pass_blocked_unverified" not in [r.split(":", 1)[0] for r in d.reasons]


def test_unverified_blocks_pass_and_sample_g_annotation():
    """W13 ⑤：verified:false 时即使层级达标 passed 也为 False + 阻断理由；
    每份判定都注明「本盘粒数，非 sample_g 当量」（评审 A 项 sample_g 口径）。"""
    d = evaluate_case("cqi_fine_robusta", {"normal": 12})  # 0 主 0 次：层级达 Fine
    assert d.grade == "Fine" and d.passed is False
    keys = [r.split(":", 1)[0] for r in d.reasons]
    assert "grading.reason.pass_blocked_unverified" in keys
    ann = next(r for r in d.reasons if r.startswith("grading.reason.tray_count_vs_sample_g:"))
    assert "sample_g=350" in ann and f"bean_count={12}" in ann
    # 同一批豆在全部 verified:true 的临时标准上 → passed=True（阻断解除）
    import yaml as _yaml
    raw = _yaml.safe_load((DEFAULT_STANDARDS_DIR / "cqi_fine_robusta.yaml").read_text(encoding="utf-8"))
    raw["standard"] = "all_verified_probe"
    raw["grades"][0]["verified"] = True
    raw["metrology"]["sieve_targets"]["verified"] = True
    raw["metrology"]["reference_lab_verified"] = True
    raw["weight"]["verified"] = True
    import tempfile
    from pathlib import Path as _P
    with tempfile.TemporaryDirectory() as td:
        fp = _P(td) / "all_verified_probe.yaml"
        fp.write_text(_yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
        std = load_standard(fp)
        d2 = StandardEngineV1(std).evaluate(make_beans({"normal": 12}), make_measurements(bean_count=12))
    assert d2.passed is True and d2.grade == "Fine"


def test_single_unverified_flag_yields_exactly_one_warning(tmp_path: Path):
    def only_grade_unverified(raw: dict) -> None:
        _set_all_verified(raw)
        raw["grades"][0]["verified"] = False

    p = _tmp_standard(tmp_path, "one_flag", only_grade_unverified)
    std = load_standard(p)
    assert std.warnings == ("verified:false @ grades[0](name=Fine)",)


def test_engine_satisfies_frozen_protocol():
    engine = StandardEngineV1.load("cqi_fine_robusta")
    assert callable(getattr(engine, "evaluate"))  # StandardEngine Protocol
    d = engine.evaluate([], make_measurements())  # 空盘：0 主 0 次 → Fine
    assert isinstance(d, GradingDecision)
    # W13 ⑤：verified:false 阻断 passed（层级名照常记录）
    assert d.grade == "Fine" and not d.passed


def test_decision_embeds_in_batch_result_invariant():
    """evaluate 输出必须满足契约 BatchResult 不变式（defect_counts 与逐粒直方一致）。"""
    beans = make_beans({"black": 1, "broken": 5, "peaberry": 2, "normal": 40})
    engine = StandardEngineV1.load("cqi_fine_robusta")
    d = engine.evaluate(beans, make_measurements(bean_count=len(beans)))
    br = BatchResult(
        result_id="r-standards-1",
        sample_id="s1",
        scan_ids=["scan1"],
        beans=beans,
        measurements=make_measurements(bean_count=len(beans)),
        grading=d,
        agent_report=None,
        timings_s={},
        pipeline_versions={"standard": "cqi_fine_robusta"},
    )
    assert br.grading.defect_counts == {"black": 1, "broken": 5, "peaberry": 2}


def test_reasons_template_key_format_and_content():
    d = evaluate_case("db46_t642", {"brocade": 5})
    assert d.reasons, "应有 reasons"
    for r in d.reasons:
        assert REASON_RE.match(r), f"reason 格式非法: {r!r}"
    keys = [r.split(":", 1)[0] for r in d.reasons]
    assert "grading.reason.grade_selected" in keys
    assert "grading.reason.primary_within_limit" in keys
    assert any(r.endswith("grade=一级;index=1") for r in d.reasons)
    # 全部未达：no_grade_matched + 相对第一级的越限理由
    d2 = evaluate_case("nyt_604", {"sour": 6})
    keys2 = [r.split(":", 1)[0] for r in d2.reasons]
    assert keys2[0] == "grading.reason.primary_over_limit"
    assert "grading.reason.no_grade_matched" in keys2
    # W13 ⑤：判定尾部固定注明计数口径（本盘粒数，非 sample_g 当量）
    assert keys2[-1] == "grading.reason.tray_count_vs_sample_g"


def test_evaluate_deterministic():
    beans = make_beans({"broken": 3})
    engine = StandardEngineV1.load("nyt_604")
    m = make_measurements()
    a, b = engine.evaluate(beans, m), engine.evaluate(beans, m)
    assert a.to_json() == b.to_json()


def test_sieve_hist_non_numeric_key_rejected():
    engine = StandardEngineV1.load("nyt_604")
    bad = make_measurements(sieve_hist={"screen15": 10})
    with pytest.raises(StandardsError, match="screen15"):
        engine.evaluate([], bad)


def test_count_rule_per_side_rejected_by_engine(tmp_path: Path):
    """count_rule=per_side：加载可过（合法声明），evaluate 明确报错（契约冲突）。"""
    p = _tmp_standard(tmp_path, "per_side_std", lambda raw: raw.update(count_rule="per_side"))
    std = load_standard(p)
    assert std.count_rule == "per_side"
    with pytest.raises(StandardsError, match="per_side.*most_severe_per_bean"):
        StandardEngineV1(std).evaluate([], make_measurements())


# ---------------------------------------------------------------------------
# 加载错误：未知 id / 解析错误 / 语义错误（信息含文件路径与行号）
# ---------------------------------------------------------------------------


def test_unknown_standard_id_lists_available():
    with pytest.raises(StandardsError) as ei:
        load_standard("no_such_std")
    msg = str(ei.value)
    assert "no_such_std" in msg
    assert str(DEFAULT_STANDARDS_DIR) in msg
    for sid in SHIPPED:
        assert sid in msg


def test_parse_error_reports_path_and_line(tmp_path: Path):
    p = tmp_path / "broken.yaml"
    p.write_text("standard: broken\ndisplay: {zh: a, en: b, vi: c\n", encoding="utf-8")  # 未闭合 flow
    with pytest.raises(StandardsError) as ei:
        load_standard(p)
    msg = str(ei.value)
    assert str(p) in msg
    assert "line 2" in msg  # PyYAML mark 携带行号


def test_semantic_error_reports_exact_line(tmp_path: Path):
    """severity_order 缺类别：报错必须指到该键所在行（完整合法模板上注入）。"""
    p = _tmp_standard(tmp_path, "sem_bad", lambda raw: raw.update(severity_order=["normal", "broken"]))
    text_lines = p.read_text(encoding="utf-8").splitlines()
    want_line = next(i + 1 for i, ln in enumerate(text_lines) if ln.startswith("severity_order:"))
    with pytest.raises(StandardsError) as ei:
        load_standard(p)
    msg = str(ei.value)
    assert str(p) in msg
    assert f":{want_line}: " in msg
    assert "black" in msg  # 指出缺失的类别


def test_duplicate_key_rejected_with_line(tmp_path: Path):
    text = "standard: dup\ndisplay: {zh: a, en: b, vi: c}\nsample_g: 1\nsample_g: 2\n"
    p = tmp_path / "dup.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(StandardsError) as ei:
        load_standard(p)
    msg = str(ei.value)
    assert str(p) in msg and "重复键" in msg and "line 4" in msg


def test_unknown_top_level_key_reports_line(tmp_path: Path):
    p = _tmp_standard(tmp_path, "typo_std", lambda raw: raw.update(gradez=raw.pop("grades")))
    with pytest.raises(StandardsError) as ei:
        load_standard(p)
    msg = str(ei.value)
    assert "gradez" in msg and str(p) in msg


def test_standard_id_must_match_stem(tmp_path: Path):
    p = _tmp_standard(tmp_path, "good_stem")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["standard"] = "mismatch_id"  # 内容 id ≠ 文件名 stem
    p2 = tmp_path / "other.yaml"
    p2.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(StandardsError, match="mismatch_id.*other"):
        load_standard(p2)


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda raw: raw.update(defect_classes={"normal": raw["defect_classes"]["normal"]}), "与 taxonomy 类别不一致"),
        (lambda raw: raw["defect_classes"]["black"].update(kind="secondary"), "与 taxonomy"),
        (lambda raw: raw.update(grades=[]), "grades"),
        (lambda raw: raw["grades"].append(dict(raw["grades"][0], name="Fine")), "重复"),
        (lambda raw: raw["grades"][0].update(primary_max=9) or raw["grades"].append(dict(raw["grades"][0], name="Low", primary_max=0)), "单调放宽"),
        (lambda raw: raw.update(fail_grade="Fine"), "重名"),
        (lambda raw: raw["metrology"].update(reference_lab=[1.0, 2.0]), "3 个数字"),
        (lambda raw: raw["weight"].update(g_per_mm2=-1.0), "正数"),
    ],
    ids=[
        "classes_missing",
        "kind_mismatch",
        "grades_empty",
        "grade_name_dup",
        "grade_not_monotonic",
        "fail_grade_dup",
        "reference_lab_shape",
        "weight_negative",
    ],
)
def test_semantic_validation_errors(tmp_path: Path, mutate, fragment: str):
    p = _tmp_standard(tmp_path, f"bad_{abs(hash(fragment)) % 10000}", mutate)
    with pytest.raises(StandardsError) as ei:
        load_standard(p)
    msg = str(ei.value)
    assert fragment in msg
    assert str(p) in msg  # 错误信息含文件路径


def test_semantic_error_line_number_is_key_line(tmp_path: Path):
    """primary_max 越界的行号 = 该键所在行（逐键行号校验）。"""
    p = _tmp_standard(tmp_path, "line_probe", lambda raw: raw["grades"][0].update(primary_max=-1))
    text_lines = p.read_text(encoding="utf-8").splitlines()
    want_line = next(i + 1 for i, ln in enumerate(text_lines) if "primary_max: -1" in ln)
    with pytest.raises(StandardsError) as ei:
        load_standard(p)
    assert f":{want_line}: " in str(ei.value)
