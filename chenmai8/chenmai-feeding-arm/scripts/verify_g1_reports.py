#!/usr/bin/env python3
"""G1 报告独立复核（审查 B8）：回读各模块 eval 证据 JSON，独立重算指标。

定位：``gate_g1.py`` 此前只认 eval 子进程退出码——``pass`` 由写报告的同一段
代码赋值，阈值写错或分子被合成帧灌满时退出码仍为 0。本脚本**只读 JSON**，
用独立的比较逻辑从 ``metrics`` 与 ``thresholds`` 重算每一项检查，并与模块
自报的 ``pass``/``checks``/``self_check`` 交叉核对：

- 任一重算检查不达标 => FAIL；
- 模块自报 pass=True 而重算为 False（或反之）=> FAIL；
- 报告缺失 / 字段缺失 / 结构不符 => FAIL。

独立性约定：本脚本只用标准库，不 import 任何 ``chengshao`` 模块，不读
各模块源码——比较规则按开发指令 §5 的验收定义独立编码。

用法（任意 cwd）::

    python scripts/verify_g1_reports.py                # 全部报告
    python scripts/verify_g1_reports.py --report-dir PATH

退出码：0 = 全部重算一致且达标；1 = 存在FAIL。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = REPO_ROOT / "chengshao" / "reports"


def _load(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"报告不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"报告顶层必须是 JSON object: {path}")
    return data


def _need(d: dict, key: str, where: str):
    if key not in d:
        raise ValueError(f"{where}: 缺少字段 {key!r}")
    return d[key]


def _num(d: dict, key: str, where: str) -> float:
    v = _need(d, key, where)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{where}: {key!r} 不是数值: {v!r}")
    return float(v)


class _Failures:
    def __init__(self) -> None:
        self.items: list[str] = []

    def check(self, ok: bool, message: str) -> bool:
        if not ok:
            self.items.append(message)
        return bool(ok)


# ---------------------------------------------------------------------------
# 各报告的独立重算规则
# ---------------------------------------------------------------------------
def verify_sim(path: Path, f: _Failures) -> dict:
    rep = _load(path)
    m = _need(rep, "metrics", path.name)
    t = _need(rep, "thresholds", path.name)

    ik = _need(m, "ik", "sim.metrics")
    ik_targets = _num(ik, "targets", "sim.ik")
    ik_rate = _num(ik, "success_rate", "sim.ik")
    f.check(ik_targets >= _num(t, "ik_targets_min", "sim.thresholds"),
            f"sim: IK 目标数 {ik_targets} < ik_targets_min")
    f.check(ik_rate >= _num(t, "ik_success_rate_min", "sim.thresholds"),
            f"sim: IK 成功率 {ik_rate} < ik_success_rate_min")
    f.check(_num(ik, "pos_err_max_m", "sim.ik") <= _num(t, "ik_pos_err_max_m", "sim.thresholds"),
            "sim: IK pos_err_max_m 超线")
    f.check(_num(ik, "ori_err_max_rad", "sim.ik") <= _num(t, "ik_ori_err_max_rad", "sim.thresholds"),
            "sim: IK ori_err_max_rad 超线")
    # 可操作度（审查 A2）：成功解的 sigma_min 必须达标，且奇异剔除有计数
    mf_thresh = _num(t, "ik_manip_sigma_min", "sim.thresholds")
    f.check(_num(ik, "manip_sigma_min", "sim.ik") >= mf_thresh,
            "sim: IK 成功解 sigma_min 低于奇异保护线")
    f.check(_num(ik, "manip_rejects", "sim.ik") >= 0, "sim: manip_rejects 缺失")

    mfk = _need(m, "ik_mouth_front", "sim.metrics")
    f.check(_num(mfk, "targets", "sim.ik_mouth_front")
            >= _num(t, "ik_mouth_front_targets_min", "sim.thresholds"),
            "sim: 口前专项目标数不足")
    f.check(_num(mfk, "success_rate", "sim.ik_mouth_front")
            >= _num(t, "ik_mouth_front_success_rate_min", "sim.thresholds"),
            "sim: 口前专项目标批成功率不达标")
    f.check(_num(mfk, "manip_sigma_min", "sim.ik_mouth_front")
            >= _num(t, "ik_mouth_front_manip_sigma_min", "sim.thresholds"),
            "sim: 口前专项目标批可操作度不达标")

    safety = _need(m, "safety_envelope", "sim.metrics")
    f.check(_num(safety, "violating_total", "sim.safety_envelope")
            >= _num(t, "violating_traj_min", "sim.thresholds"), "sim: 违规轨迹数不足")
    f.check(_num(safety, "violating_rejection_rate", "sim.safety_envelope")
            >= _num(t, "violating_rejection_rate_min", "sim.thresholds"),
            "sim: 违规轨迹拒绝率 < 100%")
    f.check(_num(safety, "benign_acceptance_rate", "sim.safety_envelope")
            >= _num(t, "benign_acceptance_rate_min", "sim.thresholds"),
            "sim: 良性轨迹被误拒")

    adv = _need(m, "adversarial", "sim.metrics")
    f.check(_num(adv, "total", "sim.adversarial")
            >= _num(t, "adversarial_traj_min", "sim.thresholds"), "sim: 对抗样本数不足")
    f.check(_num(adv, "rejection_rate", "sim.adversarial")
            >= _num(t, "adversarial_rejection_rate_min", "sim.thresholds"),
            "sim: 对抗样本拒绝率 < 100%")
    f.check(_num(adv, "predicted_kind_hit_rate", "sim.adversarial")
            >= _num(t, "adversarial_predicted_kind_hit_rate_min", "sim.thresholds"),
            "sim: 对抗样本预定类别命中率 < 100%")
    by_cat = _need(adv, "by_category", "sim.adversarial")
    for cat in ("joint_speed_over_limit", "link_capsule_sweep", "tcp_arc_zone_intrusion"):
        c = _need(by_cat, cat, "sim.adversarial.by_category")
        f.check(_num(c, "n", f"sim.adversarial.{cat}") >= 1,
                f"sim: 对抗类别 {cat} 无样本")

    dlv = _need(m, "delivery", "sim.metrics")
    margin = _need(dlv, "margin", "sim.delivery")
    f.check(_need(dlv, "stop_outside_sphere", "sim.delivery") is True,
            "sim: 送达停点未严格落在面部球外")
    f.check(_num(margin, "margin_m", "sim.delivery.margin")
            >= _num(t, "delivery_margin_min_m", "sim.thresholds"),
            "sim: 送达数值安全余量 ≤ 0（或低于下限）")
    f.check(_need(margin, "pass", "sim.delivery.margin") is True, "sim: 余量自报未过")
    f.check(_num(dlv, "exemptions_registered", "sim.delivery") == 0,
            "sim: 名义送达登记了豁免（不允许）")
    corridor = _need(dlv, "corridor", "sim.delivery")
    cart = _need(corridor, "cart", "sim.delivery.corridor")
    joint = _need(corridor, "joint", "sim.delivery.corridor")
    f.check(_need(cart, "rejected", "sim.delivery.corridor.cart") is False,
            "sim: 碗→停点笛卡尔走廊被拒")
    f.check(_need(joint, "tracked", "sim.delivery.corridor.joint") is True,
            "sim: 碗→停点关节空间走廊 IK 跟踪失败")
    f.check(_need(joint, "rejected", "sim.delivery.corridor.joint") is False,
            "sim: 碗→停点关节空间走廊被拒")

    reach = _need(m, "reachability", "sim.metrics")
    png = _need(reach, "png", "sim.reachability")
    f.check(isinstance(png, str) and len(png) > 0, "sim: reach_map.png 未生成")

    return _crosscheck(rep, f, "sim", recomputed_ok=True)


def verify_mouth(path: Path, f: _Failures) -> dict:
    rep = _load(path)
    m = _need(rep, "metrics", path.name)
    t = _need(rep, "thresholds", path.name)

    detect = m.get("detect_rate")
    reject = m.get("face_false_reject_rate")
    jaw_acc = m.get("jaw_accuracy")
    jaw_auc = m.get("jaw_auc")
    turn = m.get("turn_trigger_rate")
    lat = m.get("latency_ms_p95")

    f.check(detect is not None and float(detect) >= float(t["detect_rate_min"]),
            f"mouth: detect_rate {detect} < {t['detect_rate_min']}")
    f.check(reject is not None and float(reject) >= float(t["face_false_reject_rate_min"]),
            f"mouth: face_false_reject_rate {reject} < {t['face_false_reject_rate_min']}")
    jaw_ok = ((jaw_acc is not None and float(jaw_acc) >= float(t["jaw_accuracy_min"]))
              or (jaw_auc is not None and float(jaw_auc) >= float(t["jaw_auc_min"])))
    f.check(jaw_ok, "mouth: 张闭嘴判据（accuracy 或 AUC）不达标")
    f.check(turn is not None and float(turn) >= float(t["turn_trigger_rate_min"]),
            f"mouth: turn_trigger_rate {turn} < {t['turn_trigger_rate_min']}")
    f.check(lat is not None and float(lat) == float(lat) and float(lat) <= float(t["latency_p95_ms_max"]),
            f"mouth: latency_p95 {lat} > {t['latency_p95_ms_max']}")

    checks = rep.get("checks")
    if isinstance(checks, dict):
        f.check(all(bool(v) for v in checks.values()),
                f"mouth: 自报 checks 存在 False: {checks}")
    return _crosscheck(rep, f, "mouth", recomputed_ok=True)


def verify_voice(path: Path, f: _Failures) -> dict:
    rep = _load(path)
    m = _need(rep, "metrics", path.name)
    t = _need(rep, "thresholds", path.name)

    n_correct = _num(m, "n_correct", "voice.metrics")
    accuracy = _num(m, "accuracy", "voice.metrics")
    latency = _need(m, "latency", "voice.metrics")
    max_lat = _num(latency, "max_s", "voice.metrics.latency")
    # 离线红线：eval 期零外联（与 cs_voice.eval 的 offline_ok 同义，独立读取）
    offline = _need(m, "offline", "voice.metrics")
    outbound = _need(offline, "outbound_connect_attempts", "voice.metrics.offline")

    f.check(n_correct >= float(t["min_correct"]),
            f"voice: 正确条数 {n_correct} < {t['min_correct']}")
    f.check(accuracy >= float(t["min_accuracy"]),
            f"voice: 准确率 {accuracy} < {t['min_accuracy']}")
    f.check(max_lat <= float(t["max_latency_s"]),
            f"voice: 最大时延 {max_lat}s > {t['max_latency_s']}s")
    f.check(outbound == 0, f"voice: eval 期外联尝试 {outbound} 次（离线红线）")
    return _crosscheck(rep, f, "voice", recomputed_ok=True)


def verify_food(path: Path, f: _Failures) -> dict:
    rep = _load(path)
    m = _need(rep, "metrics", path.name)
    t = _need(rep, "thresholds", path.name)
    source = _need(rep, "source", path.name)

    if source == "synthetic":
        # 审查 B10：合成自检只许 self_check，不许称 pass
        f.check("pass" not in rep,
                "food: 合成集报告写了 pass 字段（审查 B10：只许 self_check）")
        sc = rep.get("self_check")
        ok = (sc is True
              and _num(m, "spoon_accuracy", "food.metrics") >= float(t["synthetic_spoon_accuracy_min"])
              and _num(m, "aruco_registered_detected", "food.metrics")
              >= float(t["aruco_registered_detected_min"])
              and m.get("aruco_select_correct") is True
              and m.get("aruco_none_on_empty") is True
              and m.get("aruco_ignore_unregistered") is True)
        f.check(ok, "food: 合成自检指标重算不达标或 self_check 非真")
        return {"pass": bool(ok), "self_check": bool(ok)}
    if source == "real_frames":
        # 真实帧路径才允许 pass（有人工标签时启用硬线）
        f.check(rep.get("pass") is not None, "food: 真实帧报告缺 pass 字段")
        return {"pass": bool(rep.get("pass"))}
    raise ValueError(f"food: 未知 source {source!r}")


def verify_food_interface(path: Path, f: _Failures) -> dict:
    rep = _load(path)
    m = _need(rep, "metrics", path.name)
    passed = _num(m, "passed", "food_interface.metrics")
    failed = _num(m, "failed", "food_interface.metrics")
    errors = _num(m, "errors", "food_interface.metrics")
    exit_status = _num(m, "exit_status", "food_interface.metrics")
    ok = passed > 0 and failed == 0 and errors == 0 and exit_status == 0
    f.check(ok, f"food_interface: passed={passed} failed={failed} errors={errors} "
                f"exit={exit_status}")
    return {"pass": bool(ok)}


def verify_schema(path: Path, f: _Failures) -> dict:
    rep = _load(path)
    m = _need(rep, "metrics", path.name)
    ok = (_num(m, "passed", "schema.metrics") > 0
          and _num(m, "failed", "schema.metrics") == 0
          and _num(m, "errors", "schema.metrics") == 0
          and _num(m, "exit_status", "schema.metrics") == 0)
    f.check(ok, "schema: pytest 结果非全绿")
    return {"pass": bool(ok)}


def verify_dashboard(path: Path, f: _Failures) -> dict:
    rep = _load(path)
    m = _need(rep, "metrics", path.name)
    ok = (_num(m, "failed", "dashboard.metrics") == 0
          and _num(m, "errors", "dashboard.metrics") == 0
          and _num(m, "exit_status", "dashboard.metrics") == 0)
    f.check(ok, "dashboard: pytest 结果非全绿")
    return {"pass": bool(ok)}


def _crosscheck(rep: dict, f: _Failures, name: str, *, recomputed_ok: bool) -> dict:
    """模块自报与独立重算交叉核对：不一致即 FAIL（审查 B8 核心）。"""
    checks = rep.get("checks")
    if isinstance(checks, dict):
        f.check(all(bool(v) for v in checks.values()),
                f"{name}: 自报 checks 存在 False: {[k for k, v in checks.items() if not v]}")
    self_pass = rep.get("pass")
    if self_pass is None:
        f.check(False, f"{name}: 缺 pass 字段")
    else:
        f.check(bool(self_pass) == bool(recomputed_ok),
                f"{name}: 自报 pass={self_pass} 与独立重算结果不一致"
                if not self_pass else f"{name}: 自报 pass={self_pass} 但重算存在 FAIL")
    return {"pass": bool(self_pass) and recomputed_ok}


VERIFIERS = [
    ("sim_eval.json", verify_sim),
    ("mouth_eval.json", verify_mouth),
    ("voice_eval.json", verify_voice),
    ("food_eval.json", verify_food),
    ("food_interface_eval.json", verify_food_interface),
    ("schema_eval.json", verify_schema),
    ("dashboard_eval.json", verify_dashboard),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G1 报告独立复核（只读 JSON，独立重算）")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR,
                        help="eval 报告目录（缺省 chengshao/reports）")
    parser.add_argument("--allow-missing", action="store_true",
                        help="缺失的报告记 WARNING 而非 FAIL（局部复核用）")
    args = parser.parse_args(argv)

    failures = _Failures()
    results: dict[str, dict] = {}
    for filename, verifier in VERIFIERS:
        path = args.report_dir / filename
        try:
            results[filename] = verifier(path, failures)
            print(f"[OK]   {filename}")
        except ValueError as exc:
            if args.allow_missing:
                print(f"[SKIP] {filename}: {exc}")
                results[filename] = {"skipped": True}
            else:
                failures.items.append(str(exc))
                print(f"[FAIL] {filename}: {exc}")
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            failures.items.append(f"{filename}: 结构不符: {type(exc).__name__}: {exc}")
            print(f"[FAIL] {filename}: 结构不符: {exc}")

    for item in failures.items:
        print(f"FAIL: {item}")
    print(f"verify_g1_reports: reports={len(results)} failures={len(failures.items)}")
    return 1 if failures.items else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
