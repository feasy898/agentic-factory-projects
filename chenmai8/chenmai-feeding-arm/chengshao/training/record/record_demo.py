"""拖动示教录制（training-plan §1 方案 B；延后资产——本机只做计划）。

无主臂方案的采数脚本：从臂扭矩关闭后手拖执行，以 30–50Hz 录关节流 +
双路相机帧（scene/wrist），输出回合原始布局（events.json + 帧），供
``spoon_cls.prepare_data`` 与策略训练（延后）使用。

- 缺省 dry-run：校验参数/输出路径/覆盖矩阵配置，打印采样计划，不写文件、
  不碰硬件；
- ``--execute``：需要真实硬件（cs_arm 接口 + 相机设备）。本仓库构建期
  fail-closed：未注入 ``CS_HW_SESSION=1`` 时拒绝执行（exit 2）。

退出码：0=成功；2=参数/硬件纪律拒绝。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chengshao.cs_schema import N_ARM_JOINTS  # noqa: E402
from chengshao.training.common import (  # noqa: E402
    dump_json,
    fail,
    safe_rel_output,
    utc_now_iso,
)

_MODULE = "training.record.record_demo"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m chengshao.training.record.record_demo",
        description="拖动示教录制（dry-run 缺省；--execute 需真实硬件 + CS_HW_SESSION=1）")
    parser.add_argument("--episode", required=True, help="回合名（如 taro_bowlA_full_001）")
    parser.add_argument("--output", type=Path, default=None,
                        help="录制根目录（仓库相对；缺省 data/recordings）")
    parser.add_argument("--fps", type=float, default=30.0,
                        help="采样频率 Hz（协议 30–50）")
    parser.add_argument("--cams", default="scene,wrist",
                        help="相机列表（逗号分隔，子集于 scene,wrist）")
    parser.add_argument("--duration-s", type=float, default=15.0,
                        help="单回合时长上限（协议：舀取回合 10–20s）")
    parser.add_argument("--execute", action="store_true",
                        help="真实录制（需硬件；构建期 fail-closed）")
    args = parser.parse_args(argv)

    if not (10.0 <= float(args.fps) <= 50.0):
        fail(f"--fps 必须在 30–50 协议带内（录制协议 §1.2）：{args.fps}")
    if args.duration_s > 30.0:
        fail(f"--duration-s 过长（协议 10–20s/回合）：{args.duration_s}")
    cams = [c.strip() for c in args.cams.split(",") if c.strip()]
    if not cams or not set(cams) <= {"scene", "wrist"}:
        fail(f"--cams 必须为 scene/wrist 的非空子集：{cams}")
    try:
        out_root = safe_rel_output(
            str(args.output) if args.output else "data/recordings", field="--output")
    except Exception as exc:  # noqa: BLE001
        fail(f"--output 非法：{exc}")
    episode_dir = out_root / args.episode

    plan = {
        "episode": args.episode,
        "episode_dir": str(episode_dir),
        "fps": float(args.fps),
        "duration_s": float(args.duration_s),
        "expected_samples": int(float(args.fps) * float(args.duration_s)),
        "cams": cams,
        "joint_channels": N_ARM_JOINTS,
        "layout": {
            "frames/": "scene 相机帧（f*.png，录制时刻戳命名）",
            "wrist/": "腕部相机帧",
            "joints.csv": f"{N_ARM_JOINTS} 通道关节角 + 时间戳（30–50Hz）",
            "events.json": "帧清单 + scoop_done/bite_end 事件下标（人工半自动标注）",
        },
        "policy": "拖动示教（方案 B）：从臂扭矩关闭、手拖执行；手部入镜条目按协议裁剪/重录",
    }
    if args.execute:
        if os.environ.get("CS_HW_SESSION") != "1":
            print("[training] 拒绝：真实录制需硬件会话放行（CS_HW_SESSION=1）+ "
                  "cs_arm 接口与相机就绪；构建期本机不录数。", file=sys.stderr)
            return 2
        fail("--execute 的录制循环属延后资产：硬件到位（D4）后按 runbook_gpu.md §采数 "
             "实现；本仓库交付到「计划/布局/纪律门」为止")

    print("PLAN:", plan)
    print(f"NOTE: dry-run @ {utc_now_iso()}；未写文件未碰硬件。")
    if os.environ.get("CS_DEMO_DUMP") == "1":  # 测试钩子：允许把计划写到临时目录
        dump_json(Path(os.environ["CS_DEMO_DUMP"]) / "record_demo_plan.json",
                  {"module": _MODULE, "plan": plan})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
