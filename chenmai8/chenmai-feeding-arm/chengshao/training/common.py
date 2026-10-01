"""训练资产包共享工具（chengshao.training.common）。

职责：
- 仓库/包路径定位：任何 cwd、任何入口方式（``python -m`` / 直接路径执行）一致；
- JSON 配置装载：UTF-8，错误统一抛 ConfigError；
- 开发指令 §10.2 证据报告落盘：``{module, date, cmd, metrics, thresholds, pass}``；
- 统一 CLI 退出码约定：0=成功；1=执行未达标（阈值未过）；2=参数/路径/配置错误
  （argparse 用法错误天然也是 2）。

命名纪律（开发指令 §2/§10.5）：本包代码与文档用中性名「训练框架」指代
requirements-gpu.txt 声明的策略训练依赖栈；其 CLI 入口名不写入仓库文本
（scripts/check_naming.py 把关），运行期经 --train-cmd / 环境变量
CS_TRAIN_CMD / training/config/train.local.json（已 gitignore）注入。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

# common.py 位于 <仓库根>/chengshao/training/common.py（v3.1 审查补丁：
# parents[3] 指到仓库外一层，REPO_ROOT 与数据落盘全部越界；回归锁定见
# tests/test_training_scripts.py）
REPO_ROOT = Path(__file__).resolve().parents[2]
PKG_ROOT = REPO_ROOT / "chengshao"
TRAINING_ROOT = PKG_ROOT / "training"
TRAINING_CONFIG_DIR = TRAINING_ROOT / "config"
REPORTS_DIR = PKG_ROOT / "reports"
DATA_DIR = PKG_ROOT / "data"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class ConfigError(ValueError):
    """配置/数据结构不合法（对应 CLI 退出码 2）。"""


def fail(message: str, code: int = 2) -> NoReturn:
    """向 stderr 打印错误并以约定退出码终止（main 直接 return/fail，不经异常）。"""
    print(f"[training] 错误：{message}", file=sys.stderr)
    raise SystemExit(code)


def load_json(path: Path | str) -> dict[str, Any]:
    """读 UTF-8 JSON；失败统一 ConfigError（带路径与原因）。"""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"配置文件无法读取：{p}（{exc}）") from exc
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"JSON 解析失败：{p}:{exc.lineno}:{exc.colno}（{exc.msg}）") from exc
    if not isinstance(obj, dict):
        raise ConfigError(f"配置顶层必须是 JSON object：{p}")
    return obj


def dump_json(path: Path | str, obj: Any) -> Path:
    """写 UTF-8 JSON（ensure_ascii=False，parents 自动创建），返回路径。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def utc_now_iso() -> str:
    """UTC ISO8601 时间戳（报告用，秒级精度）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_report(
    path: Path | str,
    *,
    module: str,
    cmd: str,
    metrics: dict[str, Any],
    thresholds: dict[str, Any],
    passed: bool,
) -> Path:
    """按开发指令 §10.2 规范落证据报告 JSON，返回路径。"""
    report = {
        "module": module,
        "date": datetime.now().astimezone().date().isoformat(),
        "cmd": cmd,
        "metrics": metrics,
        "thresholds": thresholds,
        "pass": bool(passed),
    }
    return dump_json(path, report)


def repo_rel(path: Path | str) -> str:
    """相对仓库根的 posix 路径（仓库外路径原样返回绝对 posix 串）。"""
    p = Path(path)
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.resolve().as_posix()


def safe_rel_output(value: str, *, field: str) -> Path:
    """校验"仓库内相对输出目录"：禁止绝对路径与 ``..`` 越界（训练产物默认落 data/）。"""
    p = Path(value)
    if p.is_absolute() or ".." in p.parts:
        raise ConfigError(f"{field} 必须是仓库内相对路径（禁止绝对路径与 ..）：{value!r}")
    return REPO_ROOT / p


def dir_size_bytes(path: Path) -> int:
    """递归统计目录字节数（跳过无法读取的项；不存在返回 0）。"""
    total = 0
    if not path.is_dir():
        return 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return total
