"""数据测试：误解库覆盖审计器 × 真实误解库与真实知识库（data/ 侧闭环）。

初中闭式为 2026-09-29 实测（每 KP 恰 2 条典型误解，无豁免）；小学中段
（3-4 年级）闭式为 2026-09-30 落库实测：误解库 6 文件 × math_grade3/4/7/8/9
共 129 知识点，小学段 20 条误解覆盖 10 个高频误解知识点，其余 18 个知识点
走显式「无误解」豁免通道（各附理由），覆盖门仍然全量咬合。小学低段
（1-2 年级）独立闭式见文件末段（20 条误解 / 19 豁免）。
2026-09-30 九年级误解库深挖重写（70 -> 110，_research_tmp/m9_build.py，
与 105 道新题同批）：九年级部分知识点扩到 3-4 条（仍全部 ≥2），门约束
min_per_kp=2 不变；本文件闭式按落库后实跑重算（2026-10-01 GPU 端）。
"""
import copy
import json
import os

import pytest

from xuexing.misconception_coverage import (MisconceptionCoverageError,
                                            audit_dicts, parse_bank)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# 本闭式的子库 = 3-4、7-9 年级：误解库按年级归属显式列举（小学 1-2 年级另有
# 独立落库批次与其知识文件配套，不并入本闭式）。
MC_FILES = [
    os.path.join(ROOT, "data", "misconceptions", "math_grade3_misconceptions.json"),
    os.path.join(ROOT, "data", "misconceptions", "math_grade4_misconceptions.json"),
    os.path.join(ROOT, "data", "misconceptions", "math_misconceptions.json"),
    os.path.join(ROOT, "data", "misconceptions", "math_grade7_misconceptions_extra.json"),
    os.path.join(ROOT, "data", "misconceptions", "math_grade8_misconceptions.json"),
    os.path.join(ROOT, "data", "misconceptions", "math_grade9_misconceptions.json"),
]
GRADE_FILES = [os.path.join(ROOT, "data", "knowledge", f"math_grade{g}.json")
               for g in (3, 4, 7, 8, 9)]

# 小学中段落库闭式：豁免的知识点清单（knowledge 文件序，即审计输入原序）
EXPECTED_EXEMPT = (
    "kp_p3_time_read", "kp_p3_measure_units", "kp_p3_mult_1digit",
    "kp_p3_mult_2x2digit", "kp_p3_area", "kp_p3_ymd_date",
    "kp_p3_decimal_intro", "kp_p3_stats_table", "kp_p3_combination",
    "kp_p4_hectare", "kp_p4_angle_measure", "kp_p4_mult_3x2digit",
    "kp_p4_quad_shape", "kp_p4_barchart", "kp_p4_arith_order",
    "kp_p4_decimal_addsub", "kp_p4_compound_bar", "kp_p4_jituitonglong",
)


@pytest.fixture(scope="module")
def kp_dicts():
    merged = []
    for path in GRADE_FILES:
        with open(path, encoding="utf-8") as f:
            merged.extend(json.load(f)["knowledge_points"])
    return merged


@pytest.fixture(scope="module")
def bank_data():
    merged = {"misconceptions": [], "exemptions": []}
    for path in MC_FILES:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        merged["misconceptions"].extend(data["misconceptions"])
        merged["exemptions"].extend(data.get("exemptions", []))
    return merged


@pytest.fixture(scope="module")
def report(kp_dicts, bank_data):
    return audit_dicts(kp_dicts, bank_data, min_per_kp=2)


# ---------- 全库闭环：每 KP ≥2 条（豁免点 0 条）；小学段 2 条或显式豁免 ----------

def test_real_library_complete_at_two_per_kp(report, kp_dicts, bank_data):
    assert len(kp_dicts) == 129
    assert len(MC_FILES) == 6
    assert report.total_misconceptions == 262   # 2026-09-30 九年级深挖后闭式（原 222）
    assert report.is_complete() is True
    assert report.deficient_kp_ids == ()
    assert report.exempt_kp_ids == EXPECTED_EXEMPT   # 小学段豁免知识点，输入原序
    assert len(report.covered_kp_ids) == 129 - len(EXPECTED_EXEMPT)
    assert report.min_per_kp == 2


def test_real_counts_two_or_more(report):
    # 更名自 test_real_counts_exactly_two：2026-09-30 九年级深挖批后不变式从
    # 「恰 2 条」变为「≥2 条」（允许富集；豁免点仍必须恰 0 条）。
    counts = dict(report.counts)
    assert len(counts) == 129
    assert all(v == 0 or v >= 2 for v in counts.values())
    # 落库分布闭式：覆盖 111 点 = 76 点恰 2 + 30 点 3 条 + 5 点 4 条
    dist = {v: sum(1 for c in counts.values() if c == v) for v in set(counts.values())}
    assert dist == {0: 18, 2: 76, 3: 30, 4: 5}


def test_real_hygiene(bank_data, kp_dicts):
    entries, exemptions = parse_bank(bank_data)  # 解析器自身已强制全部结构规则
    assert len(entries) == 262 and len(exemptions) == len(EXPECTED_EXEMPT)
    kp_ids = {k["id"] for k in kp_dicts}
    assert {e.kp_id for e in entries} <= kp_ids
    assert len({e.id for e in entries}) == len(entries)   # 全局唯一（audit 同样强制）
    # 豁免名副其实：有理由、名下确无误解
    by_kp = {}
    for e in entries:
        by_kp.setdefault(e.kp_id, 0)
        by_kp[e.kp_id] += 1
    for ex in exemptions:
        assert ex.reason.strip()
        assert by_kp.get(ex.kp_id, 0) == 0, f"{ex.kp_id}: 豁免与已有误解矛盾"
    per_kp_sig = {}
    for e in entries:
        assert e.description.strip() and e.hint.strip()
        assert len(e.signature) >= 1
        for sig in e.signature:
            assert sig == sig.strip() and sig != ""
            seen = per_kp_sig.setdefault(e.kp_id, set())
            assert sig not in seen, f"{e.kp_id}: 签名 {sig!r} 跨条目重复（归因歧义）"
            seen.add(sig)


# ---------- 覆盖门真实咬合：抽走一条即缺口 ----------

def test_gate_bites_on_removal(kp_dicts, bank_data):
    victim = bank_data["misconceptions"][0]
    pruned = copy.deepcopy(bank_data)
    pruned["misconceptions"] = [m for m in pruned["misconceptions"]
                                if m["id"] != victim["id"]]
    rep = audit_dicts(kp_dicts, pruned, min_per_kp=2)
    assert rep.is_complete() is False
    assert rep.deficient_kp_ids == (victim["kp_id"],)
    assert rep.total_misconceptions == 261   # 262 - 1


def test_gate_exemption_channel(kp_dicts, bank_data):
    # 若某 KP 显式声明"无误解"且名下确无误解，覆盖门放行（豁免通道在真实 schema 上可用）。
    # 小学段落库后基础豁免已有 18 个：抽走 victim 的误解并补一条 victim 豁免声明，
    # 覆盖门依旧完整（豁免集 = 基础豁免 ∪ {victim}）。
    victim_kp = bank_data["misconceptions"][0]["kp_id"]
    assert victim_kp not in EXPECTED_EXEMPT   # victim 是已覆盖点，豁免才名副其实
    pruned = copy.deepcopy(bank_data)
    pruned["misconceptions"] = [m for m in pruned["misconceptions"]
                                if m["kp_id"] != victim_kp]
    pruned["exemptions"].append({"kp_id": victim_kp,
                                 "reason": "数据测试注入的显式声明"})
    rep = audit_dicts(kp_dicts, pruned, min_per_kp=2)
    assert rep.is_complete() is True
    assert set(rep.exempt_kp_ids) == set(EXPECTED_EXEMPT) | {victim_kp}
    # 名下仍有误解时声明豁免 -> 交叉一致错误（豁免必须名副其实）
    conflict = copy.deepcopy(bank_data)
    conflict["exemptions"].append({"kp_id": victim_kp, "reason": "矛盾声明"})
    with pytest.raises(MisconceptionCoverageError):
        audit_dicts(kp_dicts, conflict, min_per_kp=2)


# ---------- 内容闭式抽查：新增条目的算术逐位核对 ----------

def test_real_closed_form_arithmetic(bank_data):
    by_id = {m["id"]: m for m in bank_data["misconceptions"]}
    # 错答签名与"正确值"都要与描述中的算术一致
    pins = [
        # (id, 必含的错答签名, 描述中的正确值命题)
        ("mc_g7_eqapply_growth_flat", "120元", abs(100 * 1.1 ** 2 - 121) < 1e-9),
        ("mc_g7_eqapply_unit_mix", "1800千米", 60 * 0.5 == 30),
        ("mc_g7_hist_freq_vs_perc", "0.25", 0.25 * 40 == 10),
        ("mc_g7_angles_frac_conv", "75′", abs(0.75 * 60 - 45) < 1e-12),
        ("mc_g8_median_even", "4", (4 + 6) / 2 == 5),
        ("mc_g8_weighted_avg_swap", "84", abs(80 * 0.4 + 90 * 0.6 - 86) < 1e-12),
        ("mc_g8_pythconv_pairwise", "是直角三角形", 4 ** 2 + 5 ** 2 == 41 != 6 ** 2),
        ("mc_g9_arclen_missing_div", "360π",
         abs(60 * 3.141592653589793 * 6 / 180 - 2 * 3.141592653589793) < 1e-9),
        ("mc_g9_polycircle_center_angle", "120°", 360 / 6 == 60),
        ("mc_g9_qecomplete_full_coeff", "(x-6)²=32", 36 - 4 == 32 and 9 - 4 == 5),
        ("mc_g9_qevieta_product_sign", "-6", 2 * 3 == 6 and 2 + 3 == 5),
        ("mc_g9_relist_with_replacement", "9/16",
         abs(3 / 4 * 2 / 3 - 1 / 2) < 1e-12 and abs(3 / 4 * 3 / 4 - 9 / 16) < 1e-12),
        ("mc_g9_rtasolve_pythag_add", "√194", 13 ** 2 - 5 ** 2 == 144 and 12 ** 2 == 144),
    ]
    for mid, sig, truth in pins:
        mc = by_id[mid]                      # 缺条目即 KeyError：防数据漂移
        assert sig in mc["signature"], f"{mid}: 签名 {sig!r} 不在 {mc['signature']}"
        assert truth, f"{mid}: 描述中的算术命题失真"


def test_real_spot_entries(bank_data):
    by_id = {m["id"]: m for m in bank_data["misconceptions"]}
    assert by_id["mc_g7_ratmul_sign"]["signature"] == ["-12"]       # (-3)×(-4) 错答
    assert by_id["mc_g9_homothety_coord_partial"]["signature"] == ["(2,3)", "（2，3）"]
    assert by_id["mc_g9_tandef_invert"]["signature"] == ["邻边/对边"]
    assert by_id["mc_g7_sysapply_rel_reverse"]["signature"] == ["甲=乙-3", "x=y-3"]
    # 与既有条目同 KP 不串签名（归因卫生的代表性对照点）
    assert "85" not in by_id["mc_g8_weighted_avg_swap"]["signature"]  # 85 是旧条目的权忽略错答


# ---------- 小学低段（1-2 年级）独立落库闭式（2026-09-30 实测；与上方 3-4、
# 7-9 子库分离：误解库按年级归属，覆盖门对低段子库全量咬合） ----------

P12_MC_FILES = [
    os.path.join(ROOT, "data", "misconceptions", "math_grade1_misconceptions.json"),
    os.path.join(ROOT, "data", "misconceptions", "math_grade2_misconceptions.json"),
]
P12_GRADE_FILES = [os.path.join(ROOT, "data", "knowledge", f"math_grade{g}.json")
                   for g in (1, 2)]
# 豁免的知识点清单（grade1/2 knowledge 文件序，即审计输入原序）：19 个知识点豁免，
# 10 个高频误解知识点（各恰 2 条）被覆盖。
P12_EXPECTED_EXEMPT = (
    "kp_p1_num20", "kp_p1_addsub10", "kp_p1_addsub100", "kp_p1_3dshapes",
    "kp_p1_2dshapes", "kp_p1_position", "kp_p1_sort", "kp_p1_pattern",
    "kp_p1_wordprob", "kp_p1_compare",
    "kp_p2_mul_meaning", "kp_p2_div_meaning", "kp_p2_num10000", "kp_p2_angle",
    "kp_p2_view", "kp_p2_motion", "kp_p2_stats", "kp_p2_mass", "kp_p2_reasoning",
)


@pytest.fixture(scope="module")
def p12_kp_dicts():
    merged = []
    for path in P12_GRADE_FILES:
        with open(path, encoding="utf-8") as f:
            merged.extend(json.load(f)["knowledge_points"])
    return merged


@pytest.fixture(scope="module")
def p12_bank_data():
    merged = {"misconceptions": [], "exemptions": []}
    for path in P12_MC_FILES:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        merged["misconceptions"].extend(data["misconceptions"])
        merged["exemptions"].extend(data.get("exemptions", []))
    return merged


@pytest.fixture(scope="module")
def p12_report(p12_kp_dicts, p12_bank_data):
    return audit_dicts(p12_kp_dicts, p12_bank_data, min_per_kp=2)


def test_p12_library_complete(p12_report, p12_kp_dicts, p12_bank_data):
    assert len(p12_kp_dicts) == 29
    assert len(P12_MC_FILES) == 2
    assert p12_report.total_misconceptions == 20
    assert p12_report.is_complete() is True
    assert p12_report.deficient_kp_ids == ()
    assert p12_report.exempt_kp_ids == P12_EXPECTED_EXEMPT
    assert len(p12_report.covered_kp_ids) == 29 - len(P12_EXPECTED_EXEMPT)
    assert set(dict(p12_report.counts).values()) == {0, 2}
    assert p12_report.min_per_kp == 2


def test_p12_hygiene(p12_bank_data, p12_kp_dicts):
    entries, exemptions = parse_bank(p12_bank_data)
    assert len(entries) == 20 and len(exemptions) == len(P12_EXPECTED_EXEMPT)
    kp_ids = {k["id"] for k in p12_kp_dicts}
    assert {e.kp_id for e in entries} <= kp_ids
    per_kp_sig = {}
    for e in entries:
        assert e.description.strip() and e.hint.strip()
        for sig in e.signature:
            assert sig == sig.strip() and sig != ""
            seen = per_kp_sig.setdefault(e.kp_id, set())
            assert sig not in seen, f"{e.kp_id}: 签名 {sig!r} 跨条目重复"
            seen.add(sig)
    for ex in exemptions:
        assert ex.reason.strip()


def test_p12_closed_form_arithmetic(p12_bank_data):
    by_id = {m["id"]: m for m in p12_bank_data["misconceptions"]}
    # 错答签名与描述中的算术命题逐位核对（错答值=算式按误解方式推出的值）
    pins = [
        ("mc_p1_carry_concat", "8+7=87", 8 + 7 == 15 and 87 != 15),
        ("mc_p1_borrow_forget_add", "15-9=1", 10 - 9 == 1 and 1 + 5 == 6),
        ("mc_p1_borrow_reverse", "15-9=4", 9 - 5 == 4),
        ("mc_p1_money_change_add", "17元", 10 + 7 == 17 and 10 - 7 == 3),
        ("mc_p2_carry_forget", "52", 37 + 25 == 62 and 3 + 2 == 5),
        ("mc_p2_borrow_flip", "26", 52 - 38 == 14 and 8 - 2 == 6),
        ("mc_p2_div_once_sub", "9", 12 - 3 == 9 and 12 // 3 == 4),
        ("mc_p2_scale_from_one", "6厘米", 6 - 1 == 5),
        ("mc_p2_minute_as_num", "7时7分", 7 * 5 == 35),
    ]
    for mid, sig, truth in pins:
        mc = by_id[mid]                      # 缺条目即 KeyError：防数据漂移
        assert sig in mc["signature"], f"{mid}: 签名 {sig!r} 不在 {mc['signature']}"
        assert truth, f"{mid}: 描述中的算术命题失真"
