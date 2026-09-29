"""数据测试：误解库覆盖审计器 × 真实误解库与真实知识库（data/ 侧闭环）。

闭式均为 2026-09-29 实测（误解库 4 文件 × math_grade7/8/9 共 101 知识点）：
误解库扩充管线落地后每 KP 恰 2 条典型误解（各带 signature 答案 + 教学提示），
无「无误解」豁免声明；覆盖门真实咬合（抽走任一条即产生缺口）。
"""
import copy
import glob
import json
import os

import pytest

from xuexing.misconception_coverage import (MisconceptionCoverageError,
                                            audit_dicts, parse_bank)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MC_FILES = sorted(glob.glob(os.path.join(ROOT, "data", "misconceptions", "*.json")))
GRADE_FILES = [os.path.join(ROOT, "data", "knowledge", f"math_grade{g}.json")
               for g in (7, 8, 9)]


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


# ---------- 全库闭环：每 KP 恰 2 条，无豁免 ----------

def test_real_library_complete_at_two_per_kp(report, kp_dicts, bank_data):
    assert len(kp_dicts) == 101
    assert len(MC_FILES) == 4
    assert report.total_misconceptions == 202
    assert report.is_complete() is True
    assert report.deficient_kp_ids == ()
    assert report.exempt_kp_ids == ()          # 全库无"无误解"声明
    assert report.covered_kp_ids == tuple(k["id"] for k in kp_dicts)  # 输入原序
    assert report.min_per_kp == 2


def test_real_counts_exactly_two(report):
    counts = dict(report.counts)
    assert len(counts) == 101
    assert set(counts.values()) == {2}         # 每个 KP 恰 2 条典型误解


def test_real_hygiene(bank_data, kp_dicts):
    entries, exemptions = parse_bank(bank_data)  # 解析器自身已强制全部结构规则
    assert exemptions == []                    # 真实数据不使用豁免通道
    kp_ids = {k["id"] for k in kp_dicts}
    assert {e.kp_id for e in entries} <= kp_ids
    assert len({e.id for e in entries}) == len(entries)   # 全局唯一（audit 同样强制）
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
    assert rep.total_misconceptions == 201


def test_gate_exemption_channel(kp_dicts, bank_data):
    # 若某 KP 显式声明"无误解"且名下确无误解，覆盖门放行（豁免通道在真实 schema 上可用）
    victim_kp = bank_data["misconceptions"][0]["kp_id"]
    pruned = copy.deepcopy(bank_data)
    pruned["misconceptions"] = [m for m in pruned["misconceptions"]
                                if m["kp_id"] != victim_kp]
    pruned["exemptions"].append({"kp_id": victim_kp,
                                 "reason": "数据测试注入的显式声明"})
    rep = audit_dicts(kp_dicts, pruned, min_per_kp=2)
    assert rep.is_complete() is True
    assert rep.exempt_kp_ids == (victim_kp,)
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
