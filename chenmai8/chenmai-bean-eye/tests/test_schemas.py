"""M1 契约测试：往返序列化无损 + 不变式 + 非法输入拒绝。

运行（仓库根）::

    pytest tests/test_schemas.py -q
"""

from __future__ import annotations

import inspect
import json
import math
import typing
from pathlib import Path
from typing import Callable

import pytest
from pydantic import ValidationError

from beaneye import taxonomy as tax_mod
from beaneye.schemas import (
    BatchResult,
    BeanEyeBaseModel,
    BeanObservation,
    PairedBean,
    defect_counts_from_beans,
)
from _fixture_builders import (
    RANK_BLACK,
    RANK_BROKEN,
    RANK_NORMAL,
    all_fixtures,
    bean_observation_top_017,
    paired_bean_b0002,
)

FIXTURES = Path(__file__).parent / "fixtures"
ROUND_TRIP_CASES = sorted(FIXTURES.glob("*.json"))


def _mutated(model: BeanEyeBaseModel, updates: dict, nested: str | None = None):
    """model_copy 不触发校验器；要在「改坏」后验证校验器真的拒绝，
    必须走 dump → 改 JSON → model_validate 的完整校验路径。"""
    data = model.model_dump(mode="json")
    target = data if nested is None else data[nested]
    target.update(updates)
    return type(model).model_validate(data)


def _load_model(path: Path):
    """fixture 文件名 → 对应契约模型类 + 内容。"""
    builder: Callable[[], object] = all_fixtures()[path.stem]
    return type(builder()), path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 往返序列化：每个 schema 的 fixture 必须无损 JSON 往返
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ROUND_TRIP_CASES, ids=lambda p: p.stem)
def test_roundtrip_lossless(path: Path):
    """契约：每 schema 往返序列化无损。"""
    model_cls, raw = _load_model(path)
    model = model_cls.from_json(raw)
    again = model_cls.from_json(model.to_json())
    assert again == model, f"{path.stem} 往返后不等价"
    assert again.to_json() == model.to_json(), f"{path.stem} 二次序列化字节不稳定"


@pytest.mark.parametrize("path", ROUND_TRIP_CASES, ids=lambda p: p.stem)
def test_fixture_matches_builder(path: Path):
    """fixture 文件与 builder 构造保持同步（防止手改漂移）。"""
    model = all_fixtures()[path.stem]()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == json.loads(model.to_json())


def test_fixtures_cover_all_schemas():
    """契约：fixtures 覆盖全部 13 个 schema（达标线 8）。"""
    assert len(all_fixtures()) == 13
    assert {p.stem for p in ROUND_TRIP_CASES} == set(all_fixtures())


# ---------------------------------------------------------------------------
# 非法输入：缺字段 / 越界 / 非法枚举 → ValidationError
# ---------------------------------------------------------------------------


def test_missing_required_field_rejected():
    with pytest.raises(ValidationError):
        BeanObservation.model_validate({"side": "top"})


def _bean_mask():
    return all_fixtures()["bean_mask"]()


def test_conf_out_of_range_rejected():
    good = _bean_mask()
    with pytest.raises(ValidationError):
        _mutated(good, {"conf": 1.5})
    with pytest.raises(ValidationError):
        _mutated(good, {"conf": -0.1})


def test_bad_side_literal_rejected():
    with pytest.raises(ValidationError):
        _mutated(_bean_mask(), {"side": "left"})


def test_negative_area_and_bad_bbox_rejected():
    good = _bean_mask()
    with pytest.raises(ValidationError):
        _mutated(good, {"area_mm2": -1.0})
    with pytest.raises(ValidationError):
        _mutated(good, {"bbox_mm": (5.0, 20.0, 1.0, 27.0)})  # x0 > x1


def test_polygon_point_shape_rejected():
    good = _bean_mask()
    with pytest.raises(ValidationError):
        _mutated(good, {"polygon": [[1.0, 2.0, 3.0]]})  # 非 [x,y]
    with pytest.raises(ValidationError):
        _mutated(good, {"polygon": []})


def test_oracle_conf_must_be_one():
    good = _bean_mask()
    with pytest.raises(ValidationError):
        _mutated(good, {"source": "oracle", "conf": 0.9})


def test_obs_id_must_equal_mask_id():
    obs = bean_observation_top_017()
    with pytest.raises(ValidationError):
        _mutated(obs, {"mask_id": "top_999"}, nested="mask")


def test_severity_rank_normal_zero_rule():
    obs = bean_observation_top_017()  # black, rank 12
    with pytest.raises(ValidationError):
        _mutated(obs, {"defect": "normal", "severity_rank": 5})
    with pytest.raises(ValidationError):
        _mutated(obs, {"severity_rank": 0})  # black + rank 0
    with pytest.raises(ValidationError):
        _mutated(obs, {"eq_diameter_mm": 0.0})


def test_homography_must_be_3x3_and_markers_complete():
    calib = all_fixtures()["calib_result"]()
    with pytest.raises(ValidationError):
        _mutated(calib, {"H_top": [[1.0, 0.0], [0.0, 1.0]]})
    with pytest.raises(ValidationError):
        _mutated(calib, {"marker_ids": [0, 1, 2]})  # 少一个角
    with pytest.raises(ValidationError):
        _mutated(calib, {"px_per_mm": 0.0})


def test_captured_at_must_be_iso8601():
    scan = all_fixtures()["tray_scan"]()
    with pytest.raises(ValidationError):
        _mutated(scan, {"captured_at": "昨天上午"})
    with pytest.raises(ValidationError):
        _mutated(scan, {"source": "webcam"})  # 非法枚举


def test_hist_negative_count_rejected():
    m = all_fixtures()["measurements"]()
    with pytest.raises(ValidationError):
        _mutated(m, {"sieve_hist": {"13": -5}})
    with pytest.raises(ValidationError):
        _mutated(m, {"delta_e_mean": -0.1})
    with pytest.raises(ValidationError):
        _mutated(m, {"weight_model": ""})


def test_sha256_format_enforced():
    g = all_fixtures()["grading_decision"]()
    with pytest.raises(ValidationError):
        _mutated(g, {"standard_yaml_sha": "deadbeef"})
    p = all_fixtures()["passport_report"]()
    with pytest.raises(ValidationError):
        _mutated(p, {"sha256": "E3B0" * 16})  # 大写不收（规范化为小写 hex）
    with pytest.raises(ValidationError):
        _mutated(p, {"langs": []})


def test_paired_bean_final_inconsistency_rejected():
    """不变式的反向面：final_* 与两面观测不一致 → ValidationError。"""
    b = paired_bean_b0002()  # 平级 both/broken/1
    with pytest.raises(ValidationError):
        _mutated(b, {"final_defect": "normal"})
    with pytest.raises(ValidationError):
        _mutated(b, {"worst_side": "top"})
    with pytest.raises(ValidationError):
        _mutated(b, {"final_severity_rank": RANK_BLACK})
    single = PairedBean.from_sides(  # 单面豆
        "t7", None, _obs("bottom", "t7b", "normal", RANK_NORMAL, 0.9), -1.0
    )
    with pytest.raises(ValidationError):
        _mutated(single, {"pairing_cost": 2.0})  # 单面必须 -1


def test_batch_result_counts_mismatch_rejected():
    """不变式的反向面：defect_counts 与逐粒直方不符 → ValidationError。"""
    br: BatchResult = all_fixtures()["batch_result"]()
    with pytest.raises(ValidationError):
        _mutated(br, {"defect_counts": {"black": 2}}, nested="grading")
    with pytest.raises(ValidationError):
        _mutated(br, {"defect_counts": {"black": 1}}, nested="grading")  # 漏计 broken


# ---------------------------------------------------------------------------
# W13 修复：构造期校验补强（defect 查 taxonomy / side 一致 / 双面 cost≥0 /
# 主次与 bean_count 一致 / color_lab 单一 lab8 标度）
# ---------------------------------------------------------------------------


def test_defect_must_be_taxonomy_key():
    """defect 不在 taxonomy → ValidationError（原仅非空字符串约束）。"""
    obs = bean_observation_top_017()
    with pytest.raises(ValidationError, match="不在 taxonomy"):
        _mutated(obs, {"defect": "unicorn_disease"})
    # 全部 taxonomy key 均可构造（合法面）
    tax = tax_mod.load_taxonomy()
    for key in tax.keys():
        rank = tax.severity_rank(key)
        assert type(obs).model_validate(
            {**obs.model_dump(mode="json"), "defect": key, "severity_rank": rank}
        ).defect == key


def test_side_must_match_mask_side():
    obs = bean_observation_top_017()
    with pytest.raises(ValidationError, match="mask.side"):
        _mutated(obs, {"side": "bottom"})
    with pytest.raises(ValidationError, match="mask.side"):
        _mutated(obs, {"side": "bottom"}, nested="mask")


def test_paired_bean_dual_side_negative_cost_rejected():
    """双面豆 pairing_cost < 0 → ValidationError（-1 保留给单面/占位）。"""
    b = paired_bean_b0002()  # 两面都在
    with pytest.raises(ValidationError, match="pairing_cost 必须 >= 0"):
        _mutated(b, {"pairing_cost": -1})
    with pytest.raises(ValidationError, match="pairing_cost 必须 >= 0"):
        _mutated(b, {"pairing_cost": -3.5})


def test_batch_result_primary_secondary_bean_count_consistency():
    """主/次分计与 bean_count 必须与豆列表一致（W13 契约校验）。"""
    br: BatchResult = all_fixtures()["batch_result"]()
    assert br.measurements.bean_count == len(br.beans) == 3
    # peaberry（counts_as_defect=false）不计次缺陷：把 b0002 换成 peaberry 平级仍不计
    with pytest.raises(ValidationError, match="主/次归属的分计"):
        _mutated(br, {"primary_count": 0}, nested="grading")
    with pytest.raises(ValidationError, match="主/次归属的分计"):
        _mutated(br, {"secondary_count": 2}, nested="grading")
    with pytest.raises(ValidationError, match="bean_count"):
        _mutated(br, {"bean_count": 350}, nested="measurements")


def test_color_lab_single_lab8_scale_rejected_out_of_range():
    """color_lab 单一 lab8 标度：三通道 ∈[0,255]，CIE 量纲（a/b 可负）拒绝。"""
    obs = bean_observation_top_017()
    with pytest.raises(ValidationError, match="lab8"):
        _mutated(obs, {"color_lab": [52.0, -10.0, 20.0]})  # CIE a<0
    with pytest.raises(ValidationError, match="lab8"):
        _mutated(obs, {"color_lab": [260.0, 128.0, 128.0]})  # L 越界
    m = all_fixtures()["measurements"]()
    with pytest.raises(ValidationError, match="lab8"):
        _mutated(m, {"color_lab_mean": [52.1, -10.5, 20.3]})


# ---------------------------------------------------------------------------
# 不变式：「每粒只计最严重缺陷」
# ---------------------------------------------------------------------------


def _obs(side: str, oid: str, defect: str, rank: int, conf: float) -> BeanObservation:
    obs = bean_observation_top_017()
    return obs.model_copy(
        update={
            "obs_id": oid,
            "side": side,
            "defect": defect,
            "severity_rank": rank,
            "defect_conf": conf,
            "mask": obs.mask.model_copy(update={"mask_id": oid, "side": side}),
        }
    )


def test_worst_side_wins_by_rank():
    """rank 高者胜：top=black(12) vs bottom=normal(0) → final black / worst=top。"""
    b = PairedBean.from_sides(
        "t1",
        _obs("top", "t1a", "black", RANK_BLACK, 0.8),
        _obs("bottom", "t1b", "normal", RANK_NORMAL, 0.99),
        3.0,
    )
    assert (b.worst_side, b.final_defect, b.final_severity_rank) == ("top", "black", RANK_BLACK)
    b2 = PairedBean.from_sides(
        "t2",
        _obs("top", "t2a", "normal", RANK_NORMAL, 0.99),
        _obs("bottom", "t2b", "mold", 11, 0.6),
        3.0,
    )
    assert (b2.worst_side, b2.final_defect, b2.final_severity_rank) == ("bottom", "mold", 11)


def test_tie_rank_higher_conf_wins_and_worst_side_both():
    """平级取 conf 高者，且 worst_side 记 both（契约原文语义）。"""
    b = paired_bean_b0002()  # broken(1) conf 0.70 vs 0.90
    assert b.worst_side == "both"
    assert b.final_defect == "broken"
    assert b.final_severity_rank == RANK_BROKEN


def test_single_face_bean():
    top_only = PairedBean.from_sides(
        "t3", _obs("top", "t3a", "insect", 8, 0.7), None, -1.0
    )
    assert (top_only.worst_side, top_only.final_defect) == ("top", "insect")
    assert top_only.pairing_cost == -1
    bottom_only = PairedBean.from_sides(
        "t4", None, _obs("bottom", "t4b", "normal", RANK_NORMAL, 0.9), -1.0
    )
    assert (bottom_only.worst_side, bottom_only.final_defect, bottom_only.final_severity_rank) == (
        "bottom", "normal", RANK_NORMAL,
    )


def test_each_bean_counted_once_at_most():
    """每粒只计最严重缺陷：一粒两面各有缺陷 → 只按 final_defect 计一次。"""
    bean = PairedBean.from_sides(
        "t5",
        _obs("top", "t5a", "black", RANK_BLACK, 0.9),
        _obs("bottom", "t5b", "broken", RANK_BROKEN, 0.95),
        1.0,
    )
    assert bean.final_defect == "black"  # 只计最严重的 black，不计 broken
    counts = defect_counts_from_beans([bean])
    assert counts == {"black": 1}  # broken 没有被重复计数
    normal_bean = PairedBean.from_sides(
        "t6", None, _obs("bottom", "t6b", "normal", RANK_NORMAL, 0.9), -1.0
    )
    counts_all = defect_counts_from_beans([bean, normal_bean])
    assert counts_all == {"black": 1}  # normal(好豆) 不进缺陷直方


def test_batch_result_grading_consistent_with_beans():
    """整盘级不变式：grading.defect_counts == 逐粒 final_defect 直方。"""
    br: BatchResult = all_fixtures()["batch_result"]()
    assert defect_counts_from_beans(br.beans) == br.grading.defect_counts == {"black": 1, "broken": 1}
    # 主/次分计与 taxonomy 类别归属一致（black=primary, broken=secondary；
    # counts_as_defect=false 的 peaberry 不计，W13 契约校验同口径）
    tax = tax_mod.load_taxonomy()
    assert tax.get("black").kind == "primary" and tax.get("broken").kind == "secondary"
    assert br.grading.primary_count == sum(
        1 for b in br.beans
        if tax.is_valid_key(b.final_defect) and tax.get(b.final_defect).kind == "primary" and tax.get(b.final_defect).counts_as_defect
    )
    assert br.grading.secondary_count == sum(
        1 for b in br.beans
        if tax.is_valid_key(b.final_defect) and tax.get(b.final_defect).kind == "secondary" and tax.get(b.final_defect).counts_as_defect
    )


def test_fixture_observation_severity_matches_taxonomy():
    """fixture 的 severity_rank 必须与 taxonomy 默认序一致。"""
    tax = tax_mod.load_taxonomy()
    for name in ("bean_observation", "paired_bean", "batch_result"):
        model = all_fixtures()[name]()
        if isinstance(model, BeanObservation):
            obs_list = [model]
        elif isinstance(model, PairedBean):
            obs_list = [o for o in (model.top, model.bottom) if o]
        elif isinstance(model, BatchResult):
            obs_list = [o for b in model.beans for o in (b.top, b.bottom) if o]
        else:
            obs_list = []
        for obs in obs_list:
            assert obs.severity_rank == tax.severity_rank(obs.defect), (
                f"{name}: {obs.obs_id} defect={obs.defect} rank={obs.severity_rank}"
            )
            assert obs.defect_conf >= 0.0


def test_eq_diameter_consistent_with_area():
    """等效直径约定：d = 2*sqrt(area/pi)（M8 面积→直径）。"""
    obs = all_fixtures()["bean_observation"]()
    d = 2.0 * math.sqrt(obs.mask.area_mm2 / math.pi)
    assert abs(obs.eq_diameter_mm - d) <= 0.15


# ---------------------------------------------------------------------------
# taxonomy.yaml 本体
# ---------------------------------------------------------------------------


def test_taxonomy_loads_and_matches_contract():
    tax = tax_mod.load_taxonomy()
    assert tax.severity_order == [
        "normal", "broken", "faded", "brocade", "immature", "peaberry",
        "shell", "elephant", "insect", "dried", "sour", "mold", "black",
    ]
    assert set(tax.primary_keys()) == {"black", "mold", "sour", "insect", "dried"}
    assert set(tax.secondary_keys()) == {
        "broken", "brocade", "shell", "elephant", "peaberry", "immature", "faded",
    }
    assert len(tax.keys()) == 13


def test_taxonomy_special_classes():
    tax = tax_mod.load_taxonomy()
    assert tax.severity_rank("normal") == 0
    pb = tax.get("peaberry")
    assert pb.kind == "secondary" and pb.counts_as_defect is False  # 计量不计缺陷
    assert tax.get("normal").counts_as_defect is False
    assert "black" in tax.counting_defect_keys() and "peaberry" not in tax.counting_defect_keys()


def test_taxonomy_public_tree_carries_no_upstream_mapping():
    """公开树不携带素材来源映射（W13 清理，评审 E 项）。

    原标签属上游数据集命名，映射只留在不入库内部文件
    ``configs/upstream_mapping.internal.yaml``（gitignore；内部素材管线用）。
    公开 taxonomy 加载后 upstream_mapping 为空、map_upstream 一律 None。
    """
    tax = tax_mod.load_taxonomy()
    assert tax.upstream_sources() == []
    assert tax.map_upstream("poly12", "any_label") is None
    assert tax.map_upstream("grade4", "any_label") is None


def test_taxonomy_upstream_mapping_targets_valid(tmp_path: Path):
    """含 upstream_mapping 的 taxonomy 仍可加载：目标 key 必须在 classes、
    null = 明确不映射、未登记来源 → None（loader 校验语义保留）。"""
    good = tmp_path / "taxonomy.yaml"
    good.write_text(
        "version: 1\n"
        "classes:\n"
        "  normal: {kind: normal, zh: hao, en: normal, vi: x, counts_as_defect: false}\n"
        "  black: {kind: primary, zh: hei, en: black, vi: x, counts_as_defect: true}\n"
        "severity_order: [normal, black]\n"
        "upstream_mapping:\n"
        "  src_a: {up1: black, up2: null}\n"
        "  src_b: {up1: normal}\n",
        encoding="utf-8",
    )
    tax = tax_mod.load_taxonomy(good)
    assert tax.map_upstream("src_a", "up1") == "black"
    assert tax.map_upstream("src_a", "up2") is None
    assert tax.map_upstream("src_b", "up1") == "normal"
    assert tax.map_upstream("src_unknown", "up1") is None
    assert set(tax.upstream_sources()) == {"src_a", "src_b"}


def test_taxonomy_uncertain_items_marked_unverified():
    """不确定项必须标 verified:false：越南语译名未核对。"""
    tax = tax_mod.load_taxonomy()
    for key, item in tax._raw["classes"].items():
        assert item.get("vi_verified") is False, f"{key} 的越南语译名未经核对，必须保持 false"
        assert item.get("verified") is True  # 主/次归属与中英名契约已定


def test_taxonomy_rejects_inconsistent_yaml(tmp_path: Path):
    good = tmp_path / "taxonomy.yaml"
    good.write_text(
        "version: 1\n"
        "classes:\n"
        "  normal: {kind: normal, zh: hao, en: normal, vi: x, counts_as_defect: false}\n"
        "  black: {kind: primary, zh: hei, en: black, vi: x, counts_as_defect: true}\n"
        "severity_order: [normal, black]\n",
        encoding="utf-8",
    )
    assert tax_mod.load_taxonomy(good).severity_rank("black") == 1

    dup = tmp_path / "dup.yaml"
    dup.write_text(
        "version: 1\n"
        "classes:\n"
        "  normal: {kind: normal, zh: hao, en: normal, vi: x, counts_as_defect: false}\n"
        "severity_order: [normal, normal]\n",
        encoding="utf-8",
    )
    with pytest.raises(tax_mod.TaxonomyError):
        tax_mod.load_taxonomy(dup)

    bad_target = tmp_path / "bad_target.yaml"
    bad_target.write_text(
        "version: 1\n"
        "classes:\n"
        "  normal: {kind: normal, zh: hao, en: normal, vi: x, counts_as_defect: false}\n"
        "upstream_mapping:\n"
        "  poly12: {ghost: black}\n"
        "severity_order: [normal]\n",
        encoding="utf-8",
    )
    with pytest.raises(tax_mod.TaxonomyError):
        tax_mod.load_taxonomy(bad_target)

    with pytest.raises(tax_mod.TaxonomyError):
        tax_mod.load_taxonomy(tmp_path / "missing.yaml")


# ---------------------------------------------------------------------------
# §3.2 接口 Protocol 存在性（接口冻结）
# ---------------------------------------------------------------------------


def test_protocols_exist():
    from beaneye.schemas import (
        CameraSource,
        ClsModel,
        RootCauseAgent,
        SegModel,
        StandardEngine,
    )

    for proto in (SegModel, ClsModel, StandardEngine, RootCauseAgent, CameraSource):
        assert inspect.isclass(proto)
        assert issubclass(proto, typing.Protocol)
        assert len(getattr(proto, "__protocol_attrs__", ())) >= 1
