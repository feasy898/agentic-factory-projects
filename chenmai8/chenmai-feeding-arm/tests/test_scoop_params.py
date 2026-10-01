"""B2 舀取扫参配置与推荐参数静态断言。

运行（仓库根）::

    python -m pytest tests/test_scoop_params.py -q

覆盖（任务 B2 验收面）：
1. config/scoop_params.json 装载与校验惯例——未知键拒绝、网格每维 ≤3 值、
   试验数上限、食物集合与 cs_schema.constants.DEFAULT_DISH_REGISTRY 一致；
2. recommended（扫参产出）逐食物在**关节限位/安全包络内**的静态断言——
   每食物推荐参数经 cs_sim RouteSim（位置 IK + EnvelopeValidator
   check_joint_trajectory，与执行层 SafetyEnvelope 同一校验器）逐碗实跑；
3. recommended 与 reports/scoop_sweep.json 的一致性（报告存在时）。

环境前提：cs_sim 参考模型件（_vendor / D:/upstream-refs/robot-vendor /
CS_VENDOR_ROOT，见 cs_sim spec §8）。缺失时模型回退 tier3 内置链（5 关节，
与契约 6 关节不匹配），路线级断言按 test_sim.py 同一惯例跳过（skip），
config 级断言不受影响。

注意：recommended 的仿真成功率为**仿真预扫结论（解析捕获模型）**，
不代表真机 §5.9 通过线；本文件不断言其真机含义。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chengshao.cs_schema.constants import DEFAULT_DISH_REGISTRY
from chengshao.cs_sim.scoop_params import (
    MAX_GRID_VALUES_PER_DIM,
    MAX_TRIALS_PER_FOOD,
    GRID_DIMS,
    load_scoop_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "chengshao" / "config" / "scoop_params.json"
REPORT_PATH = REPO_ROOT / "chengshao" / "reports" / "scoop_sweep.json"

#: 任务 B2 契约：单轮 sweep 每食物模拟试验 ≤200 次
B2_TRIALS_CAP = 200


@pytest.fixture(scope="module")
def cfg():
    return load_scoop_config(CONFIG_PATH, allowed_foods=DEFAULT_DISH_REGISTRY)


# ---------------------------------------------------------------------------
# 1) config 校验
# ---------------------------------------------------------------------------

def test_config_loads_and_food_set_matches_schema_registry(cfg):
    assert cfg.version
    assert cfg.food_set_source == "cs_schema.constants.DEFAULT_DISH_REGISTRY"
    assert sorted(cfg.food_names()) == sorted(DEFAULT_DISH_REGISTRY)
    # 三类流变各一（演示计划：粥/面条代之以仓库登记的稠稀两档粥品+凝胶块）
    assert {card.rheology for card in cfg.foods.values()} == {
        "viscous_paste", "thin_porridge", "solid_gel"}


def test_grid_dims_within_task_cap(cfg):
    assert tuple(cfg.grid.values) == GRID_DIMS  # 五个扫参维度，一不少
    for dim, vals in cfg.grid.values.items():
        assert 1 <= len(vals) <= MAX_GRID_VALUES_PER_DIM, dim
        assert len(set(vals)) == len(vals), dim  # 取值不重复
    assert {False, True} <= set(cfg.grid.values["bowl_rim_scrape"])


def test_search_within_b2_contract(cfg):
    assert 1 <= cfg.search["trials_per_food"] <= B2_TRIALS_CAP
    assert cfg.search["trials_per_food"] <= MAX_TRIALS_PER_FOOD
    assert 1 <= cfg.search["max_attempts"] <= 8
    assert cfg.search["seed"] >= 0


def test_unknown_top_key_rejected(tmp_path):
    import json as _json
    data = _json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    data["grid_typo"] = data.pop("grid")
    bad = tmp_path / "bad.json"
    bad.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="未声明字段"):
        load_scoop_config(bad, allowed_foods=DEFAULT_DISH_REGISTRY)


def test_unknown_food_card_key_rejected(tmp_path):
    import json as _json
    data = _json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    data["foods"]["芋泥"]["fill_factor_typo"] = 0.9
    bad = tmp_path / "bad.json"
    bad.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="未声明字段"):
        load_scoop_config(bad, allowed_foods=DEFAULT_DISH_REGISTRY)


def test_grid_dim_over_cap_rejected(tmp_path):
    import json as _json
    data = _json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    data["grid"]["tilt_deg"] = [0.0, 10.0, 20.0, 30.0]
    bad = tmp_path / "bad.json"
    bad.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="超过上限"):
        load_scoop_config(bad, allowed_foods=DEFAULT_DISH_REGISTRY)


def test_food_set_deviation_rejected(tmp_path):
    import json as _json
    data = _json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    data["foods"]["面条"] = dict(data["foods"]["芋泥"])
    bad = tmp_path / "bad.json"
    bad.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="不一致"):
        load_scoop_config(bad, allowed_foods=DEFAULT_DISH_REGISTRY)


def test_geometry_min_food_ratio_matches_food_hsv(cfg):
    """min_food_ratio 与 config/food_hsv.json 同值（改动须两边同步，scoop_params 模块 docstring）。"""
    hsv = _json_load(REPO_ROOT / "chengshao" / "config" / "food_hsv.json")
    assert cfg.geometry.min_food_ratio == float(hsv["min_food_ratio"])


def _json_load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 2) recommended：静态断言（参数在网格内 + 路线在关节限位/安全包络内）
# ---------------------------------------------------------------------------

def test_recommended_covers_all_foods_when_present(cfg):
    if not cfg.recommended:
        pytest.skip("recommended 段未产出（扫参未跑或未 --write-config）")
    assert sorted(cfg.recommended) == sorted(DEFAULT_DISH_REGISTRY)
    for name, rec in cfg.recommended.items():
        for dim in GRID_DIMS:
            assert dim in rec, (name, dim)
        # 推荐参数必须取自本网格（扫参产物不得私设值）
        for dim in ("dip_offset_m", "tilt_deg",
                    "approach_speed_mps", "retract_speed_mps"):
            assert rec[dim] in cfg.grid.values[dim], (name, dim)
        assert rec["bowl_rim_scrape"] in cfg.grid.values["bowl_rim_scrape"]
        assert rec["grid_size"] == cfg.grid.size()  # 与当前网格一致（过期拒载已由 loader 保证）
        assert 0.0 <= rec["sim_first_attempt_rate"] <= 1.0
        assert 0.0 <= rec["sim_final_success_rate"] <= 1.0
        assert 1 <= rec["sim_trials"] <= B2_TRIALS_CAP
        assert "仿真" in rec["source_report"] or "scoop_sweep" in rec["source_report"]


@pytest.fixture(scope="module")
def _route_sim():
    """cs_sim 模型 + 包络校验器（与执行层 SafetyEnvelope 同一校验器）。"""
    from chengshao.cs_orchestra.core import OrchestraParams
    from chengshao.cs_sim.arm_model import load_arm
    from chengshao.cs_sim.safety_envelope import EnvelopeValidator
    from chengshao.cs_sim.scoop_sweep import RouteSim

    model = load_arm("auto")
    if getattr(model, "tier", "") == "chain_builtin":
        pytest.skip("cs_sim 参考模型件缺失（tier3 内置链 5 关节，与契约 6 关节"
                    "不匹配；路线级断言需 _vendor/CS_VENDOR_ROOT，见 cs_sim spec §8）")
    params = OrchestraParams.load()
    validator = EnvelopeValidator()
    return RouteSim(model, validator, params), params


def test_recommended_routes_within_joint_limits_and_envelope(cfg, _route_sim):
    """每食物推荐参数逐碗实跑：IK 可解、关节限位内、禁入区/限速/连杆扫掠零违规。"""
    if not cfg.recommended:
        pytest.skip("recommended 段未产出（扫参未跑或未 --write-config）")
    from chengshao.cs_orchestra.runtime import ScriptedScoop
    from chengshao.cs_sim.scoop_sweep import ScoopCombo

    sim, params = _route_sim
    assert sim.model.n_joints == 6  # 契约 N_ARM_JOINTS=6（5 臂关节 + 夹爪）
    bowls = params.bowls_m()
    assert len(bowls) == 3
    for name, rec in cfg.recommended.items():
        combo = ScoopCombo.from_dict(rec)
        scoop = ScriptedScoop(params, **combo.as_dict())
        assert scoop.params_dict() == combo.as_dict()  # 参数经冻结运行时类往返一致
        for bowl in bowls:
            res = sim.run(scoop, bowl)
            assert res["ok"], (
                f"{name} @ bowl {bowl.tolist()}: reason={res['reason']} "
                f"stage={res['stage']} violations={res.get('violations')}")
            assert res["joints_in_limits"]
            assert res["max_joint_speed_rad_s"] <= res["joint_speed_limit_rad_s"] + 1e-9
            assert res["min_zone_clearance_m"] >= 0.0
            assert res["min_link_clearance_m"] >= 0.0


# ---------------------------------------------------------------------------
# 3) 报告一致性（reports/scoop_sweep.json 存在时）
# ---------------------------------------------------------------------------

def test_report_matches_config_recommended(cfg):
    if not cfg.recommended or not REPORT_PATH.is_file():
        pytest.skip("recommended 或 reports/scoop_sweep.json 未产出")
    report = _json_load(REPORT_PATH)
    for field in ("module", "date", "cmd", "metrics", "thresholds", "pass"):
        assert field in report, field  # 开发指令 §10.2 报告字段规范
    assert report["module"] == "cs_sim.scoop_sweep"
    assert report["metrics"]["grid_size"] == cfg.grid.size()
    foods = report["metrics"]["foods"]
    for name, rec in cfg.recommended.items():
        rep_food = foods[name]
        assert rep_food["recommended"]["dip_offset_m"] == rec["dip_offset_m"]
        assert rep_food["recommended"]["tilt_deg"] == rec["tilt_deg"]
        assert rep_food["recommended"]["sim_final_success_rate"] == \
            rec["sim_final_success_rate"]
    # 结论口径：报告必须显式声明"非真机实测"
    assert report.get("real_machine_measured") is False
    assert report.get("success_rate_kind") == "analytic_capture_model"
