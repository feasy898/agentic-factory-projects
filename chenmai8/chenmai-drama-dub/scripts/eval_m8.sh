#!/usr/bin/env bash
# eval_m8.sh — M8 验收入口（T14 自验收口径：全离线零 GPU）。
#
# 断言集（tests/test_m8.py）：M6 mock 候选故意超长译法（句窗按候选项估长
# 1.00/0.62/0.52/0.43 压窗）→ 对齐后逐句预测时长落入原句窗 ±10%；
# 覆盖 in-budget / df-bisect / switch-df / atempo-final / keep-original /
# no-translation / unresolved 七类路径 + CLI exit 0 + C5 契约校验 +
# 多语种分文件与幂等。纯函数层单测二分与 atempo 收口的边界行为。
# 用法: bash scripts/eval_m8.sh       （退出码即验收结果）
set -uo pipefail
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

cd "$REPO_ROOT"
if [ -x ".venv/Scripts/python.exe" ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
export PYTHONUTF8=1
exec "$PY" -m pytest tests/test_m8.py -v "$@"
