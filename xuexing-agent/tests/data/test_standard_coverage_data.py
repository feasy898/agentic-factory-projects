"""数据测试：课标覆盖检查器 × 真实知识库与真实课标清单（data/ 侧闭环）。

闭式均为 2026-09-29 实测（真实清单 28 条 × math_grade7/8/9 共 101 知识点）：
全库可归属（无归属缺口）、清单全覆盖（无覆盖缺口）、恰 7 个多归属知识点。
kp_rta_apply 的 standard_ref 曾截断为「能用相关知识解决一些简单的实际问题」（检查器
由此显形），已按课标原句补全前半「能用锐角三角函数解直角三角形，」。
"""
import glob
import json
import os

import pytest

from xuexing.standard_coverage import check_coverage_dicts, parse_topics

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CURRICULUM = os.path.join(ROOT, "data", "curriculum", "math_standard_2022_topics.json")
GRADE_FILES = [os.path.join(ROOT, "data", "knowledge", f"math_grade{g}.json")
               for g in (7, 8, 9)]


@pytest.fixture(scope="module")
def curriculum():
    with open(CURRICULUM, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def kp_dicts():
    merged = []
    for path in GRADE_FILES:
        with open(path, encoding="utf-8") as f:
            merged.extend(json.load(f)["knowledge_points"])
    return merged


@pytest.fixture(scope="module")
def report(curriculum, kp_dicts):
    return check_coverage_dicts(kp_dicts, curriculum)


# ---------- 全库闭环 ----------

def test_real_library_fully_attributed_and_covered(report, kp_dicts, curriculum):
    assert len(kp_dicts) == 101
    assert len(curriculum["domains"]) == 3
    assert len(report.topics) == 28
    assert report.unmatched_kp_ids == ()  # 全部 standard_ref 可归属
    assert report.uncovered_topic_ids == ()  # 清单条目全覆盖
    assert report.coverage_rate == 1.0
    assert report.is_complete() is True
    assert [m.kp_id for m in report.matches] == [k["id"] for k in kp_dicts]  # 输入原序


def test_real_topic_domains(curriculum):
    topics = parse_topics(curriculum)
    by_domain = {}
    for t in topics:
        by_domain.setdefault(t.domain, []).append(t.id)
    assert {d: len(ids) for d, ids in sorted(by_domain.items())} == {
        "数与代数": 14, "图形与几何": 11, "统计与概率": 3,
    }
    assert by_domain["数与代数"][:6] == ["num_rational", "num_real", "num_algexpr",
                                        "num_integral", "num_fraction", "num_radical2"]


# ---------- 已知多归属（诚实并列，逐位闭式，清单原序） ----------

def test_real_multi_matches_closed_form(report):
    by_kp = {m.kp_id: m.topic_ids for m in report.matches}
    expected = {
        "kp_fraction_equation": ("num_fraction", "eq_linear"),
        # 可化为一元一次方程的分式方程：分式条目 + 一元一次方程条目
        "kp_linear_apply": ("eq_linear", "ineq", "fn_linear"),
        # 一次函数与一元一次方程、一元一次不等式的联系：三个条目并列
        "kp_qe_factor": ("num_integral", "eq_quadratic"),
        # 因式分解法解一元二次方程：整式（因式分解）+ 一元二次方程
        "kp_qf_zeros": ("eq_quadratic", "fn_quadratic"),
        # 二次函数与一元二次方程的联系
        "kp_axis_symmetry": ("g_triangle", "g_axis"),
        # 垂直平分线属课标三角形条目；轴对称属图形的变化
        "kp_coord_apply": ("g_translation", "g_coord"),
        # 图形平移与对应点坐标变化：平移条目 + 图形与坐标条目
        "kp_trig_def": ("g_similar", "g_trig"),
        # 利用相似的直角三角形认识锐角三角函数
    }
    multi = {kp: ids for kp, ids in by_kp.items() if len(ids) > 1}
    assert multi == expected


def test_real_spot_attribution(report):
    by_kp = {m.kp_id: m.topic_ids for m in report.matches}
    assert by_kp["kp_rta_apply"] == ("g_trig",)  # 截断 ref 修复后可归属
    assert by_kp["kp_triangle_midsegment"] == ("g_quad",)  # 中位线在课标属四边形条目
    assert by_kp["kp_eq_concept"] == ("eq_linear",)
    circles = sorted(kp for kp, ids in by_kp.items() if ids == ("g_circle",))
    assert circles == ["kp_circle_arc", "kp_circle_basic", "kp_circle_inscribed",
                       "kp_circle_perp_chord", "kp_circle_poly", "kp_circle_position",
                       "kp_circle_tangent"]


# ---------- 清单数据卫生（alias 全局唯一、无空白、条目非空） ----------

def test_real_alias_hygiene(curriculum):
    topics = parse_topics(curriculum)  # 解析器自身已强制：重复/空白 alias 抛错
    seen = []
    for t in topics:
        assert t.id and t.name and t.requirement
        assert len(t.aliases) >= 1
        for a in t.aliases:
            assert a == a.strip() and a != ""
            seen.append(a)
    assert len(seen) == len(set(seen))


def test_real_grade7_subset_reports_honest_gaps(curriculum):
    # 7 年级子库（37 KP）对照全库清单：必有覆盖缺口（诚实报告而非静默通过），
    # 且缺口闭式 = 全部 8-9 年级专属条目。
    with open(GRADE_FILES[0], encoding="utf-8") as f:
        grade7 = json.load(f)["knowledge_points"]
    rep = check_coverage_dicts(grade7, curriculum)
    assert len(grade7) == 37
    assert rep.unmatched_kp_ids == ()  # 7 年级 ref 均可归属
    assert set(rep.uncovered_topic_ids) == {
        "num_fraction", "num_radical2", "eq_quadratic", "fn_concept", "fn_linear",
        "fn_inverse", "fn_quadratic", "g_triangle", "g_quad", "g_circle", "g_axis",
        "g_rotation", "g_similar", "g_trig", "sp_analysis", "sp_prob",
    }
    assert rep.coverage_rate == pytest.approx(12 / 28)
    assert rep.is_complete() is False
