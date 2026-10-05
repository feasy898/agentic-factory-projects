"""真机工具链 bring-up 脚本包测试（B1；hw-toolchain spec §3 全部 planned 入口）。

运行（仓库根）::

    python -m pytest tests/test_hw_toolchain.py -q

覆盖（全部 --mock 通道 + fail-closed 用例；无硬件依赖）：
- eval_hw / eval_scoop / calibrate_handeye(scene,wrist) / camera_check /
  safety_drill 的 mock dry-run：exit 0、报告 JSON 字段规范（§10.2）、通过线；
- 真机分支 fail-closed：FeetechArm 骨架 HardwareUnavailable → exit 2，
  且不产出 pass=true 报告；
- 冻结契约不被破坏：ArmInterface 四方法签名、cs_schema v1.1、
  SafetyState 不变式、handeye npz 的 cs_orchestra 装载顺序（npz 优先）。
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from chengshao.cs_arm import (
    ArmInterface,
    FeetechArm,
    FeetechArmConfig,
    HardwareUnavailable,
)
from chengshao.cs_arm import eval_hw, eval_scoop
from chengshao.cs_schema import SCHEMA_VERSION

REPORT_FIELDS = {"module", "date", "cmd", "metrics", "thresholds", "pass"}


def _load_report(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---- FeetechArm 骨架：占位即契约（fail-closed 语义保持） -------------------------

def test_feetecharm_skeleton_fail_closed():
    arm = FeetechArm(FeetechArmConfig(port="COM3"))
    for name in ("read", "write", "enable", "disable", "halt", "connect"):
        with pytest.raises(HardwareUnavailable):
            if name == "write":
                getattr(arm, name)(None)  # type: ignore[arg-type]
            else:
                getattr(arm, name)()
    assert arm.is_connected is False
    assert arm.heartbeat_ns is None


def test_feetecharm_config_validation_preserved():
    with pytest.raises(ValueError):
        FeetechArmConfig(servo_ids=(1, 2, 3, 4, 5))  # 不是 6 个
    with pytest.raises(ValueError):
        FeetechArmConfig(servo_ids=(1, 1, 2, 3, 4, 5))  # 重复
    with pytest.raises(ValueError):
        FeetechArmConfig(baudrate=0)


def test_arm_interface_frozen_signature():
    sig = inspect.signature(ArmInterface.read)
    assert list(sig.parameters) == ["self"]
    for name in ("read", "write", "enable", "disable"):
        assert hasattr(ArmInterface, name)
    # SafetyState 不变式语义仍在包络层（violation != none → clear_to_move=False）
    from chengshao.cs_arm import SafetyEnvelope

    assert hasattr(SafetyEnvelope, "estop") and hasattr(SafetyEnvelope, "reset")
    assert SCHEMA_VERSION.startswith("1.1")


# ---- eval_hw（单臂冒烟） ---------------------------------------------------------

def test_eval_hw_mock_passes(tmp_path):
    report = tmp_path / "hw_smoke_eval.json"
    rc = eval_hw.main(["--mock", "--report", str(report)])
    assert rc == 0
    data = _load_report(report)
    assert REPORT_FIELDS <= set(data)
    assert data["pass"] is True and data["checks"]
    assert all(data["checks"].values())
    assert data["metrics"]["servos_online"] == 6
    assert data["metrics"]["gripper"]["cycles_completed"] >= 2
    assert data["real_machine_measured"] is False


def test_eval_hw_real_fail_closed_exit2(tmp_path):
    rc = eval_hw.main(["--report", str(tmp_path / "nope.json")])
    assert rc == 2
    assert not (tmp_path / "nope.json").exists()  # 不产出伪装成功的报告


# ---- eval_scoop（脚本舀取成功率） ------------------------------------------------

def test_eval_scoop_mock_config_recommended(tmp_path):
    report = tmp_path / "scoop_eval.json"
    rc = eval_scoop.main(["--food", "芋泥", "--trials", "50", "--mock",
                          "--report", str(report)])
    assert rc == 0
    data = _load_report(report)
    assert data["pass"] is True
    food = data["metrics"]["foods"]["芋泥"]
    assert food["trials"] >= 50
    assert food["first_attempt_rate"] >= data["thresholds"]["first_attempt_rate_min"]
    assert (food["final_success_rate"] >= data["thresholds"]["final_success_rate_min"]
            or food["hsv_detectable"] is False)
    assert food["kinematics_feasible"] is True
    assert food["exec_layer"]["ok"] is True
    assert food["params_source"].startswith("config:")
    assert data["success_rate_kind"] == "analytic_capture_model"
    assert data["real_machine_measured"] is False


def test_eval_scoop_mock_fallback_to_builtin_defaults(tmp_path):
    """config 缺失 → 内置默认参数兜底（不等待不空转），并如实标注来源。"""
    report = tmp_path / "scoop_eval.json"
    rc = eval_scoop.main(["--food", "芋泥", "--trials", "50", "--mock",
                          "--config", str(tmp_path / "missing.json"),
                          "--report", str(report)])
    assert rc == 0
    data = _load_report(report)
    assert data["metrics"]["foods"]["芋泥"]["params_source"] == "builtin_default"


def test_eval_scoop_real_fail_closed_exit2():
    rc = eval_scoop.main(["--food", "芋泥", "--trials", "3"])
    assert rc == 2


def test_eval_scoop_unknown_food_fail_closed(tmp_path):
    rc = eval_scoop.main(["--food", "披萨", "--trials", "5", "--mock",
                          "--report", str(tmp_path / "x.json")])
    assert rc == 2


# ---- calibrate_handeye（手眼标定，双模式 mock 闭环） -----------------------------

def test_calibrate_handeye_wrist_mock(tmp_path):
    from chengshao.scripts.calibrate_handeye import main as cal_main

    npz_path = tmp_path / "handeye_wrist.npz"
    report = tmp_path / "handeye_wrist_eval.json"
    rc = cal_main(["--cam", "wrist", "--mock", "--points", "8",
                   "--out", str(npz_path), "--report", str(report)])
    assert rc == 0
    with np.load(npz_path) as data:
        assert "T_flange_cam" in data and "reproj_err_mm" in data
        t = np.asarray(data["T_flange_cam"], dtype=float)
        err_mm = float(data["reproj_err_mm"])
        assert data["mock"].item() is True
    assert t.shape == (4, 4) and err_mm <= 3.0
    data = _load_report(report)
    assert data["pass"] is True and data["metrics"]["views_used"] >= 6
    assert data["metrics"]["est_vs_gt_mock_only"]["pos_err_mm"] < 20.0
    # cs_orchestra 装载顺序：npz 优先（标定产物可被真机链路按现有实现装载）
    from chengshao.cs_orchestra.core import load_t_flange_cam

    loaded = load_t_flange_cam(npz_path)
    assert np.allclose(loaded, t)


def test_calibrate_handeye_scene_mock(tmp_path):
    from chengshao.scripts.calibrate_handeye import main as cal_main

    npz_path = tmp_path / "handeye_scene.npz"
    report = tmp_path / "handeye_scene_eval.json"
    rc = cal_main(["--cam", "scene", "--mock", "--points", "8",
                   "--out", str(npz_path), "--report", str(report)])
    assert rc == 0
    with np.load(npz_path) as data:
        assert "T_base_cam" in data and "reproj_err_mm" in data
        assert float(data["reproj_err_mm"]) <= 3.0
    assert _load_report(report)["pass"] is True


def test_calibrate_handeye_mock_does_not_touch_config_calib(tmp_path, monkeypatch):
    """--mock 缺省输出进 reports/（合成外参不得被真机链路误装载）。

    本用例只断言**产物位置**（6 点小样运行的通过线裕量不稳定，通过线判定
    由上面 wrist/scene 两用例覆盖）：exit 0=达标 / 1=未达标 均可接受。
    """
    from chengshao.scripts import calibrate_handeye as cal_mod

    monkeypatch.chdir(tmp_path)  # 相对路径解析到临时目录
    rc = cal_mod.main(["--cam", "wrist", "--mock", "--points", "6"])
    assert rc in (0, 1)
    assert (tmp_path / "reports" / "mock_handeye_wrist.npz").is_file()
    assert (tmp_path / "reports" / "handeye_wrist_eval.json").is_file()
    assert not (tmp_path / "config" / "calib" / "handeye_wrist.npz").exists()


def test_calibrate_handeye_real_fail_closed_exit2(tmp_path):
    from chengshao.scripts.calibrate_handeye import main as cal_main

    rc = cal_main(["--cam", "scene", "--out", str(tmp_path / "x.npz")])
    assert rc == 2


def test_calibrate_handeye_failed_line_not_written_to_config_calib(tmp_path, monkeypatch):
    """独立复核高危项回归（2026-10-02）：解算返回但未达通过线时，npz 不得落
    config/calib/（load_t_flange_cam 无条件 npz 优先装载，失败外参落默认路径
    会被腕部口部链路静默采用 → 禁入区锚错位）。--out 显式指向 config/calib/
    同样要改道暂存路径。
    """
    from chengshao.scripts import calibrate_handeye as cal_mod
    import numpy as np

    class _FakeResult:
        T = np.eye(4)
        reproj_err_mm = 9.9
        reproj_err_px = 9.9
        n_views = 6
        method = "fake-fail"
        pass_line_met = False

    class _Sample:
        K = np.eye(3)

    monkeypatch.setattr(cal_mod, "solve_handeye", lambda *a, **k: _FakeResult())
    monkeypatch.setattr(cal_mod, "collect_samples_mock",
                        lambda *a, **k: ([_Sample()],
                                         {"collection": "mock",
                                          "ground_truth_T": np.eye(4).tolist()}))
    monkeypatch.chdir(tmp_path)

    out = tmp_path / "config" / "calib" / "handeye_scene.npz"
    rc = cal_mod.main(["--cam", "scene", "--mock", "--points", "6", "--out", str(out)])
    assert rc == 1  # 未达通过线
    assert not out.exists(), "失败标定不得写入 config/calib/"
    assert (tmp_path / "reports" / "handeye_scene_failed.npz").is_file()


def test_calibrate_handeye_usage_errors_exit2(tmp_path):
    from chengshao.scripts.calibrate_handeye import main as cal_main

    assert cal_main(["--cam", "scene", "--mode", "eye-in-hand"]) == 2
    assert cal_main(["--cam", "wrist", "--points", "3"]) == 2


def test_handeye_pass_line_logic():
    from chengshao.cs_arm.handeye import HandEyeResult

    base = dict(mode="eye-in-hand", T=np.eye(4), n_views=10,
                reproj_err_mm=3.1, reproj_err_px=1.5)
    assert HandEyeResult(**base).pass_line_met is True      # ≤2px 兜住
    assert HandEyeResult(**{**base, "reproj_err_px": 2.5}).pass_line_met is False
    assert HandEyeResult(**{**base, "reproj_err_mm": 2.9}).pass_line_met is True
    too_few = HandEyeResult(**{**base, "n_views": 5, "reproj_err_mm": 0.1})
    assert too_few.pass_line_met is False                    # 视角不足不判过


def test_calibrate_handeye_frozen_wrapper(tmp_path):
    """契约 §3.2 冻结签名 calibrate_handeye(cam, arm, points)->(T, mm) 可用，
    且不下发指令（采集样本由调用方经包络准备）。"""
    from chengshao.cs_arm.handeye import (
        board_mark_point,
        calibrate_handeye,
        chessboard_object_points,
    )

    # 复用 mock 采集（脚本模块内部函数；8 视角足够）；模型用脚本同一缓存实例
    from chengshao.scripts import calibrate_handeye as cal_script
    from chengshao.cs_sim import EnvelopeValidator

    cols, rows, sq = 6, 5, 0.015
    obj = chessboard_object_points(cols, rows, sq)
    model = cal_script.load_model_cached()
    samples, _info = cal_script.collect_samples_mock(
        "eye-in-hand", model, EnvelopeValidator(), obj, cols, rows, sq, 8, 20261002)
    assert len(samples) >= 6

    class _Cam:  # 最小 cam 协议：intrinsics（契约签名的 cam 形参）
        intrinsics = samples[0].K

    class _Arm:  # 最小 arm 协议：model.fk（ArmState 样本转换用；此处样本已是位姿）
        pass

    _Arm.model = model

    t, err_mm = calibrate_handeye(
        _Cam(), _Arm(), samples, mode="eye-in-hand",
        obj_points=obj, board_shape=(cols, rows),
        mark_point=board_mark_point(cols, rows, sq))
    assert t.shape == (4, 4)
    assert err_mm <= 3.0


# ---- camera_check（相机验收） ----------------------------------------------------

def test_camera_check_mock_passes(tmp_path):
    from chengshao.scripts.camera_check import main as cam_main

    report = tmp_path / "camera_check_eval.json"
    rc = cam_main(["--mock", "--report", str(report)])
    assert rc == 0
    data = _load_report(report)
    assert data["pass"] is True and all(data["checks"].values())
    assert set(data["metrics"]["wrist_face"]["per_distance"]) == {
        "0.20m", "0.30m", "0.40m", "0.50m"}
    focus = data["metrics"]["wrist_min_focus"]
    assert focus["var_laplacian_sharp"] >= data["thresholds"]["focus_min_var_laplacian"]
    assert focus["metric_discriminates"] is True
    assert data["metrics"]["wrist_exposure_recovery"]["recovery_s"] <= 1.0
    assert data["metrics"]["cable_clearance"]["operator_visual_check"] == \
        "mock_substituted"
    assert data["metrics"]["scene_aruco"]["bowls_seen"] == [0, 1, 2]
    assert data["mock"] is True


def test_camera_check_real_fail_closed_exit2(tmp_path):
    from chengshao.scripts.camera_check import main as cam_main

    rc = cam_main(["--report", str(tmp_path / "x.json")])
    assert rc == 2


# ---- safety_drill（安全演练） ----------------------------------------------------

def test_safety_drill_mock_passes(tmp_path):
    from chengshao.scripts.safety_drill import main as drill_main

    report = tmp_path / "safety_drill_eval.json"
    rc = drill_main(["--cases", "head_turn,estop,face_intrude", "--trials", "20",
                     "--mock", "--report", str(report)])
    assert rc == 0
    data = _load_report(report)
    assert data["pass"] is True and all(data["checks"].values())
    cases = data["metrics"]["cases"]
    for name in ("head_turn", "estop", "face_intrude"):
        assert cases[name]["passed"] == 20  # 20/20 停止或后撤
    assert cases["estop"]["max_latency_ms"] <= 100.0  # 急停 ≤100ms
    assert cases["face_intrude"]["zone_intrusions_total"] == 0  # 禁入区侵入 0 次
    assert cases["face_intrude"]["min_retreat_m"] >= 0.045
    assert data["real_machine_measured"] is False


def test_safety_drill_real_fail_closed_exit2():
    from chengshao.scripts.safety_drill import main as drill_main

    assert drill_main(["--cases", "estop", "--trials", "1"]) == 2


def test_safety_drill_usage_errors_exit2(tmp_path):
    from chengshao.scripts.safety_drill import main as drill_main

    assert drill_main(["--cases", "bogus", "--trials", "1", "--mock",
                       "--report", str(tmp_path / "x.json")]) == 2
