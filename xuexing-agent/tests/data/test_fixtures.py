"""知识库（数据）校验：图谱、题库、误解、母题四类资产的完整性。

知识库已从"七年级 4 章节簇"扩展为小学（1-6 年级）与初中（7-9 年级）全覆盖，
本文件与 tools/validate_knowledge.py 同口径：图谱按年级文件合并后检查，
题库 / 误解库 / 母题库分别扫描 data/ 下对应目录的全部文件。
验证器图谱口径为 1-9 年级（缺某年级文件时记 pending 不报错）；
本文件夹具按年级文件动态发现、覆盖库内现存数据，另对 math_all
合并视图单独做 1-9 年级检查（随学段扩张会从部分年级长到 1-9）。
断言一律下限式（非空、集合归属、数量下限），不锁定具体规模数字——
扩库只增不减时测试应保持通过。
"""
import glob
import json
import os

import pytest

from xuexing.itembank import itembank_from_dict
from xuexing.kpgraph import kpgraph_from_dict

# 课标（2022 年版）章节簇全集：按学段登记。
# 断言为"归属"而非"相等"——新增簇时在此登记即可，不锁簇数。
CURRICULUM_CLUSTERS = {
    # 第一、二学段（1-4 年级）
    "数与运算", "数量关系", "图形与几何", "统计与概率", "综合与实践",
    # 七年级（第四学段）
    "有理数", "整式加减", "一元一次方程", "图形初步", "实数",
    "相交线与平行线", "平面直角坐标系", "二元一次方程组",
    "不等式与不等式组", "数据的收集与整理",
    # 八年级（第四学段）
    "三角形", "全等三角形", "轴对称", "整式乘法与因式分解", "分式",
    "勾股定理", "平行四边形", "一次函数", "二次根式", "数据的分析",
    # 九年级（第四学段）
    "一元二次方程", "二次函数", "旋转", "圆", "概率初步",
    "反比例函数", "相似", "锐角三角函数",
}

# 年级文件动态发现（math_grade*.json）：随学段落库自然生长，避免跨批次改元组。
# 小学（grade<=6）与初中（grade>=7）分别给防截断下限。
def _discover_grade_files(root):
    found = {}
    for path in sorted(glob.glob(f"{root}/data/knowledge/math_grade*.json")):
        name = os.path.basename(path)  # math_grade7.json
        digits = name[len("math_grade"):-len(".json")]
        if digits.isdigit():
            found[int(digits)] = path
    return found


# 下限口径（现库远高于此；取值只防"文件被清空/大幅截断"）。
MIN_KPS_PER_GRADE = 20  # 初中任一年级文件的知识点数下限
MIN_KPS_PER_GRADE_ELEMENTARY = 10  # 小学任一年级文件的知识点数下限
MIN_KPS_MERGED = 60  # 合并图谱知识点数下限
MIN_CLUSTERS_MERGED = 8  # 合并图谱章节簇数下限
MIN_PRIMARY_ITEMS_PER_KP = 3  # 覆盖率口径与验收门默认一致
MIN_ARCHETYPES_PER_FILE = 6  # 每个母题文件的条数下限（与验收门一致）


# ---------- 夹具：与验收门同口径的合并视图 ----------


@pytest.fixture(scope="session")
def grade_kps(root):
    """按年级读原始图谱数据；顺带校验 id 跨文件不重复。"""
    out = {}
    seen = {}
    grade_files = _discover_grade_files(root)
    assert 7 in grade_files, "grade7 knowledge file missing"
    for grade, path in sorted(grade_files.items()):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        kps = data["knowledge_points"]
        floor = (MIN_KPS_PER_GRADE_ELEMENTARY if grade <= 6 else MIN_KPS_PER_GRADE)
        assert len(kps) >= floor, f"grade{grade}: only {len(kps)} kps (< {floor})"
        for kp in kps:
            assert kp["id"] not in seen, (
                f"duplicate kp id: {kp['id']} ({seen.get(kp['id'])} & grade{grade})"
            )
            seen[kp["id"]] = f"grade{grade}"
        out[grade] = kps
    return out


@pytest.fixture(scope="session")
def merged_graph(grade_kps):
    """合并已落库各年级的知识点图谱。"""
    merged = [kp for grade in sorted(grade_kps) for kp in grade_kps[grade]]
    assert len(merged) >= MIN_KPS_MERGED, f"merged graph only has {len(merged)} kps"
    return kpgraph_from_dict({"knowledge_points": merged})


@pytest.fixture(scope="session")
def merged_bank(root):
    """合并 data/items/*.json 的题库；先在原始 dict 层查重复 id / 重复题干
    （bank.add 按 id 覆盖，重复必须在入构前拦截）。"""
    paths = sorted(glob.glob(f"{root}/data/items/*.json"))
    assert paths, "no item files found under data/items/"
    seen_id, seen_stem = {}, {}
    items = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for it in data["items"]:
            assert it["id"] not in seen_id, f"duplicate item id: {it['id']}"
            seen_id[it["id"]] = os.path.basename(path)
            stem = str(it.get("stem", "")).strip()
            assert stem not in seen_stem, (
                f"duplicate stem: {it['id']} == {seen_stem.get(stem)}"
            )
            seen_stem[stem] = it["id"]
            items.append(it)
    return itembank_from_dict({"items": items})


# ---------- 图谱 ----------


def test_kpgraph_is_valid_dag(merged_graph):
    assert merged_graph.validate() == []
    order = merged_graph.topological_order()
    assert sorted(order) == sorted(kp.id for kp in merged_graph.kps())


def test_kpgraph_metadata_and_clusters(merged_graph):
    kps = merged_graph.kps()
    assert len(kps) >= MIN_KPS_MERGED
    clusters = set()
    for kp in kps:
        assert kp.name and kp.cluster and kp.standard_ref, f"{kp.id} missing metadata"
        assert str(kp.description).strip(), f"{kp.id}: empty description"
        assert 1 <= kp.grade <= 9, f"{kp.id}: grade {kp.grade} out of 1-9"
        assert kp.cluster in CURRICULUM_CLUSTERS, f"{kp.id}: unknown cluster {kp.cluster!r}"
        clusters.add(kp.cluster)
    assert len(clusters) >= MIN_CLUSTERS_MERGED


def test_grade_files_scope(grade_kps):
    """各年级文件的知识点都归属本年级，且章节簇属于课标集合、非空。"""
    for grade, kps in grade_kps.items():
        clusters = set()
        for kp in kps:
            assert int(kp["grade"]) == grade, f"{kp['id']}: grade {kp['grade']} in grade{grade} file"
            assert kp.get("cluster") in CURRICULUM_CLUSTERS, f"{kp['id']}: unknown cluster"
            assert str(kp.get("standard_ref", "")).strip(), f"{kp['id']}: empty standard_ref"
            assert str(kp.get("description", "")).strip(), f"{kp['id']}: empty description"
            clusters.add(kp["cluster"])
        assert clusters, f"grade{grade}: no clusters"


# ---------- 合并视图 math_all.json ----------


def test_math_all_merged_view_within_1_9(root, grade_kps):
    """math_all 是年级文件的合并视图：年级全部落在 1-9（随学段扩张
    逐段长到 1-9），且不丢已落库年级文件中的任何知识点。"""
    with open(f"{root}/data/knowledge/math_all.json", encoding="utf-8") as f:
        data = json.load(f)
    kps = data["knowledge_points"]
    assert kps, "math_all.json has no knowledge points"
    bad = [
        (kp["id"], kp.get("grade"))
        for kp in kps
        if not 1 <= int(kp.get("grade", 0)) <= 9
    ]
    assert bad == [], f"math_all kps grade out of 1-9: {bad}"
    core_ids = {kp["id"] for g_kps in grade_kps.values() for kp in g_kps}
    missing = sorted(core_ids - {kp["id"] for kp in kps})
    assert not missing, f"math_all lost grade kps: {missing}"


# ---------- 题库 ----------


def test_items_schema_and_kp_refs(merged_bank, merged_graph):
    errs = merged_bank.validate_all(valid_kp_ids={kp.id for kp in merged_graph.kps()})
    assert errs == [], errs


def test_every_kp_meets_primary_item_floor(merged_bank, merged_graph):
    below = [
        (kp.id, len(merged_bank.by_kp(kp.id, primary_only=True)))
        for kp in merged_graph.kps()
        if len(merged_bank.by_kp(kp.id, primary_only=True)) < MIN_PRIMARY_ITEMS_PER_KP
    ]
    assert below == [], f"kps below {MIN_PRIMARY_ITEMS_PER_KP} primary items: {below}"


# ---------- 误解库（data/misconceptions/ 全量文件）----------


def test_misconception_refs_valid(root, merged_graph, merged_bank):
    kp_ids = {kp.id for kp in merged_graph.kps()}
    mc_ids = set()
    paths = sorted(glob.glob(f"{root}/data/misconceptions/*.json"))
    assert paths, "no misconception files found"
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for mc in data["misconceptions"]:
            assert mc["id"] not in mc_ids, f"duplicate misconception {mc['id']}"
            mc_ids.add(mc["id"])
            assert mc["kp_id"] in kp_ids, mc["id"]
            assert str(mc.get("hint", "")).strip(), f"{mc['id']} missing hint"
            assert str(mc.get("signature", "")).strip(), f"{mc['id']} missing signature"
    for it in merged_bank.items():
        for m in it.misconceptions:
            assert m in mc_ids, f"{it.id}: unknown misconception {m}"


# ---------- 母题库（data/archetypes/ 全量文件）----------


def test_archetypes_valid(root, merged_graph):
    kp_ids = {kp.id for kp in merged_graph.kps()}
    seen = set()
    paths = sorted(glob.glob(f"{root}/data/archetypes/*.json"))
    assert paths, "no archetype files found"
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        arcs = data.get("archetypes", [])
        assert len(arcs) >= MIN_ARCHETYPES_PER_FILE, (
            f"{os.path.basename(path)}: only {len(arcs)} archetypes"
        )
        for a in arcs:
            assert a["id"] not in seen, f"duplicate archetype {a['id']}"
            seen.add(a["id"])
            for field in ("name", "pattern", "example"):
                assert str(a.get(field, "")).strip(), f"{a['id']}: empty {field}"
            assert a.get("kp_ids"), f"{a['id']}: no kp_ids"
            unknown = [k for k in a["kp_ids"] if k not in kp_ids]
            assert not unknown, f"{a['id']}: unknown kps {unknown}"
            assert a.get("variant_axes"), f"{a['id']}: no variant_axes"


# ---------- 教学策略库（conftest 注入的 strategies 夹具）----------


def test_strategies_have_evidence_and_fallback(strategies):
    all_s = strategies.strategies()
    assert len(all_s) >= 5
    for s in all_s:
        assert s.evidence, f"{s.id} missing evidence"
    # 兜底策略：任意 (mastery, grade) 都能选出策略
    for m in (0.05, 0.5, 0.95):
        for g in (3, 7, 9):
            strategies.select(m, g)
