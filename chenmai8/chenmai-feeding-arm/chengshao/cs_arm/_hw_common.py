"""真机工具链入口共享件（eval_hw / eval_scoop / bring-up 脚本内部用，私有模块）。

职责：
- 退出码约定（fail-closed：硬件缺失/未配置一律 exit 2，绝不伪装成功）；
- 模型缓存装载（mjcf 编译约 20s；同一进程内多个入口/用例共享一份 ArmModel，
  只读使用——MockArm/SafetyEnvelope 不修改模型）；
- 证据 JSON 落盘（开发指令 §10.2 字段：{module, date, cmd, metrics,
  thresholds, pass}；数字必须真实）。

设计约束（开发指令 §5.9 + hw-toolchain spec）：所有真机入口支持 ``--mock``
（合成数据 dry-run，exit 0）；真机分支在设备缺失时抛
:class:`cs_arm.feetech.HardwareUnavailable` 并映射为 exit 2。
"""

from __future__ import annotations

import json
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

_HERE = Path(__file__).resolve()
_PKG_ROOT = _HERE.parents[1]  # .../chengshao（包根）
_REPO_ROOT = _PKG_ROOT.parent

EXIT_OK = 0
EXIT_CHECKS_FAILED = 1
EXIT_HW_UNAVAILABLE = 2

__all__ = [
    "PKG_ROOT",
    "REPO_ROOT",
    "EXIT_OK",
    "EXIT_CHECKS_FAILED",
    "EXIT_HW_UNAVAILABLE",
    "load_model_cached",
    "write_report",
    "fail_closed",
    "resolve_path",
]


PKG_ROOT = _PKG_ROOT
REPO_ROOT = _REPO_ROOT


@lru_cache(maxsize=1)
def load_model_cached():
    """进程内共享一份 cs_sim ArmModel（只读；mjcf 编译一次）。

    缓存是**进程级**的：pytest 会话里多个入口 main() 复用，避免每个用例
    重付 ~20s 的模型编译。模型为不可变只读使用（FK/IK/限位查询）。
    """
    from cs_sim import load_arm

    return load_arm("auto")


def write_report(path: str | Path, *, module: str, cmd: str, metrics: dict,
                 thresholds: dict, pass_: bool, **extra) -> Path:
    """按 §10.2 字段规范落证据 JSON（额外字段允许：checks/notes/evidence_kind…）。"""
    report = {
        "module": module,
        "date": date.today().isoformat(),
        "cmd": cmd,
        "metrics": metrics,
        "thresholds": thresholds,
        "pass": bool(pass_),
    }
    report.update(extra)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return p


def fail_closed(exc: BaseException, what: str) -> int:
    """硬件缺失/未实现的 fail-closed 出口：如实打印原因并返回 exit 2。

    不写任何 pass=true 的报告、不产出任何"成功"表象（占位即契约）。
    """
    print(f"[fail-closed] {what}: {type(exc).__name__}: {exc}", file=sys.stderr)
    print("[fail-closed] 真机硬件未接入/未实现——本次按 HardwareUnavailable 处理，"
          "exit 2（不伪装成功）。--mock 通道可做无硬件 dry-run。", file=sys.stderr)
    return EXIT_HW_UNAVAILABLE


def resolve_path(p: str | Path, *, base: Path | None = None) -> Path:
    """相对路径解析：显式传参相对 cwd（spec 命令口径 cwd=包根 chengshao/）。"""
    path = Path(p)
    if path.is_absolute():
        return path
    return (base or Path.cwd()) / path
