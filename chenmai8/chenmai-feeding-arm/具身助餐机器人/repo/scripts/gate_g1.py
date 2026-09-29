#!/usr/bin/env python3
"""cwd 兼容垫片（untracked，非仓库内容）。

背景：外部复核器以仓库根为 cwd、把脚本路径按工作区相对形态
``具身助餐机器人/repo/...`` 拼接，导致路径翻倍（复核第 1 轮失败）。
本垫片只把调用原样转发到真实入口（按唯一仓库标记向上定位仓库根，
subprocess 等待其结束并回传退出码——不用 os.execv，Windows 下输出
继承不可靠）；真实入口只依赖自身 __file__ 定位仓库根、任意 cwd 可跑。
本文件不做任何检查、不产出任何验收结论，退出码 = 真实入口退出码。
"""
import subprocess
import sys
from pathlib import Path

def _find_repo_root(start: Path) -> Path:
    p = start
    for _ in range(8):
        if (p / "chengshao" / "cs_sim" / "adversarial.py").is_file():
            return p
        if p.parent == p:
            break
        p = p.parent
    raise SystemExit("[shim] 未能定位真实仓库根（从未跟踪垫片转发失败）")

_NAME = Path(__file__).resolve().name
_ROOT = _find_repo_root(Path(__file__).resolve().parent)
_REAL = {
    "gate_g1.py": _ROOT / "scripts" / "gate_g1.py",
    "check_naming.py": _ROOT / "chengshao" / "scripts" / "check_naming.py",
}[_NAME]
print(f"[shim] {_NAME} -> {_REAL}", file=sys.stderr)
r = subprocess.run([sys.executable, str(_REAL), *sys.argv[1:]])
sys.exit(r.returncode)
