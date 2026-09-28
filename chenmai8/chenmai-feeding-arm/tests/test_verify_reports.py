"""verify_g1_reports 独立复核器测试（审查 B8 回归锁）。

用手工构造的报告验证：指标被改小/自报 pass 失真/合成集写 pass 字段，
复核器都必须 FAIL；真实结构的干净报告必须 PASS。不 import 任何
chengshao 模块（与复核器同口径：只读 JSON）。

运行（仓库根）：python -m pytest tests/test_verify_reports.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import verify_g1_reports as V  # noqa: E402


def _failures_of(fn, path: Path) -> list[str]:
    f = V._Failures()
    fn(path, f)
    return f.items


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(V.json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# food（合成集）：pass 字段纪律（审查 B10）+ 指标重算
# ---------------------------------------------------------------------------

def _food_metrics(spoon_acc: float = 1.0) -> dict:
    return {
        "module": "cs_food", "source": "synthetic",
        "metrics": {"spoon_accuracy": spoon_acc, "aruco_registered_detected": 3,
                    "aruco_select_correct": True, "aruco_none_on_empty": True,
                    "aruco_ignore_unregistered": True},
        "thresholds": {"synthetic_spoon_accuracy_min": 1.0,
                       "aruco_registered_detected_min": 3},
    }


def test_food_synthetic_with_pass_field_fails(tmp_path):
    payload = _food_metrics()
    payload["self_check"] = True
    payload["pass"] = True  # 合成集不许写 pass（审查 B10）
    fails = _failures_of(V.verify_food, _write(tmp_path, "food.json", payload))
    assert any("pass 字段" in m for m in fails)


def test_food_synthetic_clean_ok(tmp_path):
    payload = _food_metrics()
    payload["self_check"] = True
    assert _failures_of(V.verify_food, _write(tmp_path, "food.json", payload)) == []


def test_food_synthetic_low_accuracy_fails(tmp_path):
    payload = _food_metrics(spoon_acc=0.98)
    payload["self_check"] = True
    fails = _failures_of(V.verify_food, _write(tmp_path, "food.json", payload))
    assert any("spoon_accuracy" not in m and "重算不达标" in m for m in fails)


# ---------------------------------------------------------------------------
# voice：指标重算 + 自报 pass 交叉核对（审查 B8 核心）
# ---------------------------------------------------------------------------

def _voice_report(n_correct: int = 20, accuracy: float = 1.0, max_lat: float = 0.5,
                  outbound: int = 0, self_pass: bool = True) -> dict:
    return {
        "module": "cs_voice",
        "metrics": {"n_correct": n_correct, "accuracy": accuracy,
                    "latency": {"max_s": max_lat},
                    "offline": {"outbound_connect_attempts": outbound}},
        "thresholds": {"min_correct": 18, "min_accuracy": 0.9, "max_latency_s": 2.5},
        "pass": self_pass,
    }


def test_voice_green_report_ok(tmp_path):
    assert _failures_of(V.verify_voice, _write(tmp_path, "v.json", _voice_report())) == []


def test_voice_tampered_metric_fails(tmp_path):
    fails = _failures_of(V.verify_voice, _write(tmp_path, "v.json", _voice_report(n_correct=10)))
    assert any("正确条数" in m for m in fails)


def test_voice_self_reported_pass_lie_fails(tmp_path):
    fails = _failures_of(V.verify_voice,
                         _write(tmp_path, "v.json", _voice_report(self_pass=False)))
    assert any("不一致" in m for m in fails)


def test_voice_outbound_violation_fails(tmp_path):
    fails = _failures_of(V.verify_voice,
                         _write(tmp_path, "v.json", _voice_report(outbound=3)))
    assert any("外联" in m for m in fails)


# ---------------------------------------------------------------------------
# sim：结构缺失与篡改
# ---------------------------------------------------------------------------

def _sim_report(success_rate: float = 0.995) -> dict:
    ik = {"targets": 200, "success_rate": success_rate, "pos_err_max_m": 0.0005,
          "ori_err_max_rad": 0.005, "manip_rejects": 0, "manip_sigma_min": 0.006}
    return {
        "module": "cs_sim",
        "metrics": {
            "ik": ik,
            "ik_mouth_front": {"targets": 60, "success_rate": 1.0, "manip_sigma_min": 0.05},
            "safety_envelope": {"violating_total": 500, "violating_rejection_rate": 1.0,
                                "benign_acceptance_rate": 1.0},
            "adversarial": {"total": 124, "rejection_rate": 1.0, "predicted_kind_hit_rate": 1.0,
                            "by_category": {
                                "joint_speed_over_limit": {"n": 60},
                                "link_capsule_sweep": {"n": 24},
                                "tcp_arc_zone_intrusion": {"n": 40}}},
            "delivery": {"stop_outside_sphere": True, "exemptions_registered": 0,
                         "margin": {"margin_m": 0.02, "pass": True},
                         "corridor": {"cart": {"rejected": False},
                                      "joint": {"tracked": True, "rejected": False}}},
            "reachability": {"png": "reports/reach_map.png"},
        },
        "thresholds": {
            "ik_targets_min": 200, "ik_success_rate_min": 0.98, "ik_pos_err_max_m": 0.005,
            "ik_ori_err_max_rad": 0.05, "ik_manip_sigma_min": 0.005,
            "ik_mouth_front_targets_min": 60, "ik_mouth_front_success_rate_min": 0.95,
            "ik_mouth_front_manip_sigma_min": 0.02,
            "violating_traj_min": 500, "violating_rejection_rate_min": 1.0,
            "adversarial_traj_min": 120, "adversarial_rejection_rate_min": 1.0,
            "adversarial_predicted_kind_hit_rate_min": 1.0,
            "delivery_margin_min_m": 0.005,
            "benign_acceptance_rate_min": 1.0,
        },
        "checks": {"all": True},
        "pass": True,
    }


def test_sim_green_report_ok(tmp_path):
    assert _failures_of(V.verify_sim, _write(tmp_path, "s.json", _sim_report())) == []


def test_sim_tampered_success_rate_fails(tmp_path):
    fails = _failures_of(V.verify_sim, _write(tmp_path, "s.json", _sim_report(0.5)))
    assert any("IK 成功率" in m for m in fails)


def test_sim_missing_field_fails(tmp_path):
    payload = _sim_report()
    del payload["metrics"]["delivery"]
    p = _write(tmp_path, "s.json", payload)
    f = V._Failures()
    try:
        V.verify_sim(p, f)
    except ValueError:
        pass  # 缺字段以 ValueError 暴露，main() 捕获记 FAIL
    else:
        assert f.items, "缺 delivery 字段必须暴露"


def test_main_missing_report_fails(tmp_path):
    r = V.main(["--report-dir", str(tmp_path)])
    assert r == 1
