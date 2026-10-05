"""cs_arm.eval_scoop：脚本化舀取成功率 eval（开发指令 §5.9 第 7 行）。

用法（cwd=包根 chengshao/）::

    python -m cs_arm.eval_scoop --food 芋泥 --trials 50            # 真机口径（无硬件 → exit 2）
    python -m cs_arm.eval_scoop --food 芋泥 --trials 50 --mock     # cs_sim 仿真臂（当前唯一可跑通道）
    python -m cs_arm.eval_scoop --trials 50 --mock                 # 缺省 = 注册表全食物

通过线（§5.9）：每食物 50 次，最终成功率（含闭环重试）≥90%、首次 ≥70%，
分食物报告。

当前无硬件 → ``--mock`` 用 cs_sim 仿真臂跑：运动学/安全面为真（RouteSim 走
cs_sim IK + EnvelopeValidator 同一校验器，另经 MockArm+SafetyEnvelope 执行层
真链路复核），**舀取成功率为解析捕获模型口径**（cs_sim.scoop_sweep.simulate_food：
球冠勺碗几何 + config 登记的流变先验），不是物理仿真、更不是真机实测——报告
显式标注 ``success_rate_kind="analytic_capture_model"``、
``real_machine_measured=false``。§5.9 的 90%/70% 通过线只能由真机 50 次实测回答。

参数来源（B2 交付 config/scoop_params.json，可能未就绪——本入口不等待不空转）：
1) 配置存在 → 读 ``foods``（捕获卡）与 ``recommended``（推荐参数，缺该食物回退内置默认）；
2) 配置缺失/损坏 → **内置默认参数兜底**（与 cs_sim.scoop_params 校验器同一套
   私有装载器构造，保证字段与不变式一致），报告标注 ``params_source="builtin_default"``。
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

import numpy as np

try:  # 包根直跑形态 / 仓库根集成形态双兼容
    from cs_arm._hw_common import (
        EXIT_CHECKS_FAILED,
        EXIT_HW_UNAVAILABLE,
        EXIT_OK,
        PKG_ROOT,
        fail_closed,
        load_model_cached,
        resolve_path,
        write_report,
    )
    from cs_arm.clock import VirtualClock
    from cs_arm.feetech import FeetechArm, FeetechArmConfig, HardwareUnavailable
    from cs_arm.interface import ArmCommandRejected
    from cs_arm.mock_arm import MockArm
    from cs_arm.safety import SafetyEnvelope
    from cs_schema import ArmCommand, CommandMode
    from cs_schema.constants import DEFAULT_DISH_REGISTRY
    from cs_sim import EnvelopeValidator
except ImportError:  # pragma: no cover - 仓库根形态
    from chengshao.cs_arm._hw_common import (
        EXIT_CHECKS_FAILED,
        EXIT_HW_UNAVAILABLE,
        EXIT_OK,
        PKG_ROOT,
        fail_closed,
        load_model_cached,
        resolve_path,
        write_report,
    )
    from chengshao.cs_arm.clock import VirtualClock
    from chengshao.cs_arm.feetech import FeetechArm, FeetechArmConfig, HardwareUnavailable
    from chengshao.cs_arm.interface import ArmCommandRejected
    from chengshao.cs_arm.mock_arm import MockArm
    from chengshao.cs_arm.safety import SafetyEnvelope
    from chengshao.cs_schema import ArmCommand, CommandMode
    from chengshao.cs_schema.constants import DEFAULT_DISH_REGISTRY
    from chengshao.cs_sim import EnvelopeValidator

DEFAULT_CONFIG_PATH = PKG_ROOT / "config" / "scoop_params.json"

#: §5.9 通过线
THRESHOLDS: dict = {
    "trials_per_food": 50,
    "final_success_rate_min": 0.90,
    "first_attempt_rate_min": 0.70,
    "max_attempts_per_trial": 3,  # scoop_retries_max=2 → 共 ≤3 次行程
    "kinematics_must_be_feasible": True,
    "exec_layer_must_be_clean": True,
}

#: 内置默认扫参组合（config 缺失时的兜底；五维与 ScriptedScoop 构造参数同名）。
#: dip_offset 取值口径：入勺后勺碗最低点高于碗底参考面 ≥2mm（防刮底），同时
#: 相对食物液面留 ≥2mm 浸没余量（防空勺）——与 BUILTIN_RAW 几何配套。
BUILTIN_COMBO: dict = {
    "dip_offset_m": 0.034,
    "tilt_deg": 0.0,
    "approach_speed_mps": 0.05,
    "retract_speed_mps": 0.03,
    "bowl_rim_scrape": False,
}

#: 内置默认逐食物捕获卡（工程先验，未实测；B2 config 交付后由 recommended 覆盖）
BUILTIN_FOOD_CARDS: dict[str, dict] = {
    "芋泥": {
        "display_name": "芋泥", "rheology": "viscous_paste", "hsv_detectable": True,
        "hsv_note": "内置兜底卡：浅紫-米白色黏稠膏体，HSV 可检出（食物色段覆盖）",
        "fill_factor": 0.90, "push_speed_mps": 0.10, "retention_speed_mps": 0.09,
        "tilt_knee_deg": 25.0, "tilt_fail_deg": 45.0, "scrape_extra_ml": 1.5,
        "surface_jitter_m": 0.002, "entry_lateral_error_m": 0.010,
        "bowl_place_error_m": 0.006, "closed_loop_gain": 0.50,
        "provenance": "内置兜底参数（工程先验，未实测；非 B2 config 交付值）",
    },
    "南瓜粥": {
        "display_name": "南瓜粥", "rheology": "thin_porridge", "hsv_detectable": True,
        "hsv_note": "内置兜底卡：橙色稀粥，HSV 可检出（暖色段覆盖）",
        "fill_factor": 0.70, "push_speed_mps": 0.055, "retention_speed_mps": 0.055,
        "tilt_knee_deg": 15.0, "tilt_fail_deg": 35.0, "scrape_extra_ml": 0.8,
        "surface_jitter_m": 0.0025, "entry_lateral_error_m": 0.010,
        "bowl_place_error_m": 0.006, "closed_loop_gain": 0.45,
        "provenance": "内置兜底参数（工程先验，未实测；非 B2 config 交付值）",
    },
    "椰子冻": {
        "display_name": "椰子冻", "rheology": "solid_gel", "hsv_detectable": True,
        "hsv_note": "内置兜底卡：半透明白色凝胶块，HSV 可检出（低饱和亮色段覆盖）",
        "fill_factor": 0.85, "push_speed_mps": 0.12, "retention_speed_mps": 0.12,
        "tilt_knee_deg": 30.0, "tilt_fail_deg": 55.0, "scrape_extra_ml": 1.0,
        "surface_jitter_m": 0.0015, "entry_lateral_error_m": 0.010,
        "bowl_place_error_m": 0.006, "closed_loop_gain": 0.55,
        "provenance": "内置兜底参数（工程先验，未实测；非 B2 config 交付值）",
    },
}

#: 内置默认几何/网格/搜索段（经 cs_sim.scoop_params 同一套校验器构造，字段与
#  config/scoop_params.json 完全同构；B2 交付后整体被配置覆盖）
BUILTIN_RAW: dict = {
    "version": "builtin-fallback-1",
    "_note": "eval_scoop 内置兜底参数（config/scoop_params.json 缺失时使用；"
             "系数为工程先验，未实测）",
    "spoon_geometry": {
        "spoon_bowl_radius_m": 0.020, "spoon_bowl_depth_m": 0.006,
        "spoon_tip_drop_m": 0.030, "bowl_interior_radius_m": 0.055,
        "bowl_rim_offset_m": 0.050, "food_fill_depth_m": 0.012,
        "min_food_ratio": 0.15,        # 与 config/food_hsv.json 同值
        "full_spoon_mask_ratio": 0.35,
    },
    "grid": {
        "dip_offset_m": [0.032, 0.038, 0.044],
        "tilt_deg": [0.0],
        "approach_speed_mps": [0.04, 0.05, 0.06],
        "retract_speed_mps": [0.02, 0.03, 0.04],
        "bowl_rim_scrape": [False, True],
    },
    "search": {
        "trials_per_food": 50, "max_attempts": 3,
        "seed": 20261002, "entry_lateral_correction_m": 0.008,
    },
}


def _builtin_scoop_config(allowed_foods):
    """内置兜底 ScoopConfig：走 cs_sim.scoop_params 私有装载器，保证校验同口径。"""
    from cs_sim.scoop_params import (
        _load_foods,
        _load_geometry,
        _load_grid,
        _load_search,
        FoodCard,
        ScoopConfig,
    )

    geom = _load_geometry(BUILTIN_RAW["spoon_geometry"])
    grid = _load_grid(BUILTIN_RAW["grid"])
    search = _load_search(BUILTIN_RAW["search"])
    foods_raw = {name: BUILTIN_FOOD_CARDS[name] for name in allowed_foods
                 if name in BUILTIN_FOOD_CARDS}
    if not foods_raw:
        raise ValueError("内置兜底卡不覆盖请求的食物集合")
    foods = _load_foods(foods_raw, geom)
    return ScoopConfig(
        version=str(BUILTIN_RAW["version"]),
        food_set_source="cs_schema.constants.DEFAULT_DISH_REGISTRY",
        geometry=geom, grid=grid, search=search, foods=foods,
        recommended={}, note=str(BUILTIN_RAW["_note"]),
    )


def _load_config_with_fallback(allowed_foods, path: Path | None = None
                               ) -> tuple[object, str]:
    """装载 config/scoop_params.json；缺失/损坏即用内置兜底（不等待不空转）。

    返回 (ScoopConfig, params_source)。
    """
    from cs_sim.scoop_params import load_scoop_config

    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        cfg = load_scoop_config(cfg_path, allowed_foods=allowed_foods)
        return cfg, f"config:{cfg_path.name}"
    except (OSError, ValueError) as exc:
        print(f"[eval_scoop] {cfg_path.name} 不可用（{type(exc).__name__}: {exc}）"
              "→ 使用内置默认参数兜底（B2 交付后由配置覆盖）")
        return _builtin_scoop_config(allowed_foods), "builtin_default"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python -m cs_arm.eval_scoop",
        description="脚本化舀取成功率（§5.9：每食物 50 次，最终 ≥90% / 首次 ≥70%）",
    )
    ap.add_argument("--food", action="append", default=None,
                    help="食物名（可多次/逗号分隔；缺省 = 注册表全食物）")
    ap.add_argument("--trials", type=int, default=50,
                    help="每食物试验次数（§5.9 为 50；上限 500）")
    ap.add_argument("--mock", action="store_true",
                    help="无硬件通道：cs_sim 仿真臂 + 解析捕获模型（当前唯一可跑路径）")
    ap.add_argument("--config", default=None,
                    help="舀取参数配置（缺省 config/scoop_params.json；缺失即内置兜底）")
    ap.add_argument("--port", default="", help="真机串口（骨架阶段 fail-closed）")
    ap.add_argument("--report", default=None,
                    help="报告 JSON（缺省 reports/scoop_eval.json）")
    return ap.parse_args(argv)


def _expand_foods(raw: list[str] | None) -> list[str]:
    names: list[str] = []
    for item in (raw or []):
        names.extend(part.strip() for part in str(item).split(",") if part.strip())
    if not names:
        names = list(DEFAULT_DISH_REGISTRY)
    # 去重保序
    seen: set[str] = set()
    out = [n for n in names if not (n in seen or seen.add(n))]
    return out


# ---- 执行层真链路复核（MockArm + SafetyEnvelope；与 RouteFollower 同下发口径） ---

def _exec_layer_route(model, validator, params, scoop, bowl) -> dict:
    """把 plan_round 首轮路线经包络真链路执行一遍（bowl[0]），返回拒绝统计。"""
    clock = VirtualClock()
    mock = MockArm(model, clock=clock, validator=validator)
    env = SafetyEnvelope(mock, model=model, validator=validator, clock=clock)
    env.enable()

    from cs_sim.ik_solver import solve_with_restarts

    res = solve_with_restarts(model._backend, list(params.home_point_m), np.eye(3),
                              seed=np.zeros(model.n_joints), pos_only=True)
    if res is None or not res.converged:
        return {"ok": False, "rejected": ["home_ik_no_solution"], "written": 0}
    mock.teleport(np.clip(res.q, model.joint_lower, model.joint_upper))

    def settle() -> None:
        while mock.in_motion:
            clock.advance_s(float(params.tick_s))
            env.read()

    rejected: list[str] = []
    written = 0
    journal: list[np.ndarray] = []
    try:
        for item in scoop.plan_round(1, np.asarray(bowl, dtype=float), 1):
            kind = item[0]
            if kind == "cart":
                _, point, speed, step = item
                target = np.asarray(point, dtype=float)
                pos0 = np.asarray(env.read().ee_pos, dtype=float)
                n = max(1, int(np.ceil(float(np.linalg.norm(target - pos0))
                                       / max(float(step), 1e-4))))
                for k in range(1, n + 1):
                    sp = pos0 + (target - pos0) * (k / n)
                    env.write(ArmCommand(mode=CommandMode.CARTESIAN,
                                         target=[float(v) for v in sp],
                                         max_speed=float(speed),
                                         timeout_s=float(params.cmd_timeout_s)))
                    written += 1
                    settle()
                    journal.append(np.asarray(env.read().joint_pos, dtype=float))
            elif kind == "grip":
                _, value, _s = item
                q_cur = np.asarray(env.read().joint_pos, dtype=float).copy()
                q_cur[-1] = float(value)
                env.write(ArmCommand(mode=CommandMode.JOINTS, target=[float(v) for v in q_cur],
                                     max_speed=1.0,
                                     timeout_s=float(params.cmd_timeout_s)))
                written += 1
                settle()
                journal.append(q_cur)
            elif kind == "jtrack_reverse":
                for qt in reversed(journal):
                    env.write(ArmCommand(mode=CommandMode.JOINTS,
                                         target=[float(v) for v in qt],
                                         max_speed=0.5,
                                         timeout_s=float(params.cmd_timeout_s)))
                    written += 1
                    settle()
            else:  # pragma: no cover
                raise ValueError(f"未知路线项 {kind!r}")
    except ArmCommandRejected as exc:
        rejected.append(exc.reason)
    state = env.safety_state()
    return {
        "ok": not rejected and state.violation.value == "none",
        "written": written,
        "rejected": rejected,
        "sim_seconds": round(clock.s, 3),
        "violation": str(state.violation),
    }


def _stable_seed_offset(name: str) -> int:
    """按食物名生成跨进程稳定的种子偏移（str hash 按进程随机化，不可用于复现）。"""
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 10_000


def _eval_food_mock(food: str, cfg, combo: dict, params_source: str,
                    trials: int, model, validator, params) -> dict:
    """单食物 --mock 评估：运动学可行 + 执行层真链路 + 解析捕获模型闭环。"""
    from cs_orchestra.runtime import ScriptedScoop
    from cs_sim.scoop_sweep import RouteSim, ScoopCombo, simulate_food
    from cs_sim.scoop_params import MAX_TRIALS_PER_FOOD

    trials = int(max(1, min(trials, MAX_TRIALS_PER_FOOD)))
    max_attempts = int(cfg.search["max_attempts"])
    combo_obj = ScoopCombo.from_dict(combo)
    scoop = ScriptedScoop(params, **combo_obj.as_dict())
    sim = RouteSim(model, validator, params)

    # 1) 运动学/安全面：三个碗位实跑（cs_sim IK + 包络校验器，真 cs_sim 口径）
    runs = [sim.run(scoop, bowl) for bowl in params.bowls_m()]
    feasible = all(r["ok"] for r in runs)

    # 2) 执行层真链路：MockArm + SafetyEnvelope + ArmCommand 逐条下发（bowl[0]）
    exec_res = _exec_layer_route(model, validator, params, scoop, params.bowls_m()[0])

    # 3) 闭环重试蒙特卡洛（解析捕获模型，非物理仿真）
    mc = simulate_food(cfg, cfg.foods[food], combo_obj, trials=trials,
                       max_attempts=max_attempts,
                       seed=int(cfg.search["seed"]) + _stable_seed_offset(food))

    return {
        "food": food,
        "rheology": cfg.foods[food].rheology,
        "hsv_detectable": bool(cfg.foods[food].hsv_detectable),
        "params_source": params_source,
        "params": dict(combo),
        "trials": trials,
        "max_attempts_per_trial": max_attempts,
        "kinematics_feasible": bool(feasible),
        "kinematics_reject_reasons": sorted({str(r.get("reason")) for r in runs
                                             if not r["ok"]}),
        "min_zone_clearance_m": round(min(r["min_zone_clearance_m"] for r in runs), 4),
        "exec_layer": exec_res,
        "first_attempt_rate": round(float(mc["first_attempt_rate"]), 4),
        "final_success_rate": round(float(mc["final_success_rate"]), 4),
        "mean_attempts_per_trial": round(float(mc["mean_attempts_per_trial"]), 3),
        "empty_spoon_checks": int(mc["empty_spoon_checks"]),
        "mean_retained_ml_when_ok": round(float(mc["mean_retained_ml_when_ok"]), 3),
    }


def _run_mock(foods: list[str], trials: int,
              config_path: str | None = None) -> tuple[dict, dict, list[str]]:
    model = load_model_cached()
    validator = EnvelopeValidator()
    from cs_orchestra.core import OrchestraParams

    params = OrchestraParams.load()
    allowed = tuple(dict.fromkeys(list(DEFAULT_DISH_REGISTRY) + foods))
    cfg, params_source_cfg = _load_config_with_fallback(
        allowed, Path(config_path) if config_path else None)

    unknown = [f for f in foods
               if f not in cfg.foods and f not in DEFAULT_DISH_REGISTRY]
    if unknown:
        raise ValueError(f"未注册食物：{unknown}（注册表={list(DEFAULT_DISH_REGISTRY)}，"
                         f"config 食物={cfg.food_names()}）")

    per_food = []
    for food in foods:
        # cfg_food：逐食物局部配置。曾把 cfg 整体替换为内置兜底（cfg=cfg_builtin），
        # 混合传入"未注册食物+注册食物"时后续注册食物会被静默换成内置卡——
        # 独立复核低危项（2026-10-02 修）：只让当前食物用兜底卡，不动全局 cfg。
        rec = getattr(cfg, "recommended", {}).get(food)
        if rec:
            combo = {k: rec[k] for k in BUILTIN_COMBO}
            src = f"{params_source_cfg}:recommended"
            cfg_food = cfg
        elif food in cfg.foods:
            combo = dict(BUILTIN_COMBO)
            src = (f"{params_source_cfg}:card_present"
                   if params_source_cfg.startswith("config") else "builtin_default")
            cfg_food = cfg
        else:  # config 有但该食物无卡（如自定义注册集）→ 仅本食物用兜底卡
            cfg_food = _builtin_scoop_config(tuple({food} | set(DEFAULT_DISH_REGISTRY)))
            combo = dict(BUILTIN_COMBO)
            src = "builtin_default"
        per_food.append(_eval_food_mock(food, cfg_food, combo, src, trials,
                                        model, validator, params))

    metrics = {
        "backend": "cs_sim(RouteSim+EnvelopeValidator) + MockArm+SafetyEnvelope "
                   "+ analytic_capture_model",
        "trials_per_food": trials,
        "foods": {r["food"]: r for r in per_food},
    }
    checks = {}
    for r in per_food:
        # HSV 不可检出食物：解析模型的勺上检查恒 False（与 cs_sim.scoop_sweep
        # 的验收口径一致：final ≥ 0.9 或 not hsv_detectable）——该项如实记录，
        # 真机 §5.9 由勺检阈值/检测器覆盖后复测。
        rate_ok = (r["final_success_rate"] >= THRESHOLDS["final_success_rate_min"]
                   or not r["hsv_detectable"])
        first_ok = (r["first_attempt_rate"] >= THRESHOLDS["first_attempt_rate_min"]
                    or not r["hsv_detectable"])
        ok = (rate_ok
              and first_ok
              and r["trials"] >= THRESHOLDS["trials_per_food"]
              and (r["kinematics_feasible"]
                   or not THRESHOLDS["kinematics_must_be_feasible"])
              and (r["exec_layer"]["ok"]
                   or not THRESHOLDS["exec_layer_must_be_clean"]))
        checks[f"scoop:{r['food']}"] = ok
    notes = [
        "仿真/模型结论不等于真机结论：成功率来自解析捕获模型（球冠勺碗几何 + "
        "config/内置流变先验），运动学与安全面为真（cs_sim 同一校验器）；"
        "§5.9 的 90%/70% 通过线以真机每食物 50 次实测为准（M5）",
        "参数来源回退链：config/scoop_params.json:recommended → "
        "config 捕获卡 + 内置默认组合 → 全内置默认（B2 交付后覆盖）",
        "hsv_detectable=false 的食物：解析模型勺上检查恒 False，通过判据按 "
        "scoop_sweep 同口径放宽为记录项（真机复测须覆盖该检测盲区）",
    ]
    return metrics, checks, notes


def _run_real(port: str, foods: list[str], trials: int) -> int:
    """真机舀取实测：骨架阶段 connect() 即 HardwareUnavailable → exit 2（fail-closed）。"""
    cfg = FeetechArmConfig(port=port)
    arm = FeetechArm(cfg)
    try:
        arm.connect()
    except HardwareUnavailable as exc:
        return fail_closed(exc, f"FeetechArm.connect(port={port!r}) "
                                f"(eval_scoop real: foods={foods}, trials={trials})")
    raise HardwareUnavailable("舀取真机实测链路（ScriptedScoop + 腕部闭环 + 50 次统计）"
                              "随 T10 bring-up 实现")  # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    t0 = time.perf_counter()
    foods = _expand_foods(args.food)
    if not args.mock:
        return _run_real(args.port, foods, args.trials)

    from cs_sim.scoop_params import MAX_TRIALS_PER_FOOD

    if not (1 <= args.trials <= MAX_TRIALS_PER_FOOD):
        print(f"[eval_scoop] --trials 须在 1..{MAX_TRIALS_PER_FOOD}，得到 {args.trials}",
              file=sys.stderr)
        return EXIT_CHECKS_FAILED

    try:
        metrics, checks, notes = _run_mock(foods, args.trials, args.config)
    except ValueError as exc:
        print(f"[eval_scoop] {exc}", file=sys.stderr)
        return EXIT_HW_UNAVAILABLE  # 未注册食物等用法错误：fail-closed，不假装成功
    metrics["elapsed_s"] = round(time.perf_counter() - t0, 2)
    passed = all(checks.values())
    report_path = resolve_path(args.report) if args.report else \
        resolve_path("reports/scoop_eval.json")
    write_report(
        report_path,
        module="cs_arm.eval_scoop",
        cmd=("python -m cs_arm.eval_scoop --food " + ",".join(foods)
             + f" --trials {args.trials} --mock  (cwd=包根 chengshao/)"),
        metrics=metrics,
        thresholds=THRESHOLDS,
        pass_=passed,
        checks=checks,
        notes=notes,
        evidence_kind="simulation_mock",
        real_machine_measured=False,
        success_rate_kind="analytic_capture_model",
    )
    print(f"cs_arm.eval_scoop(mock): pass={passed} foods={foods} trials={args.trials}")
    for food, r in metrics["foods"].items():
        print(f"  [{('PASS' if checks['scoop:' + food] else 'FAIL')}] {food}: "
              f"first={r['first_attempt_rate']:.2f} final={r['final_success_rate']:.2f} "
              f"feasible={r['kinematics_feasible']} params={r['params_source']}")
    print(f"report -> {report_path}")
    return EXIT_OK if passed else EXIT_CHECKS_FAILED


if __name__ == "__main__":
    sys.exit(main())
