#!/usr/bin/env bash
# eval_m2.sh — M2 验收入口（本机 CPU；无 GPU/远端服务依赖）。
# 步骤：合成 drawtext 中文字幕视频 → M1 摄取 → M2 采样 OCR + 投票校对 →
#       断言抽取行 CER ≤5%、起止时间误差 ≤0.3s（≥90% 命中）、C2 契约出口。
# 用法: bash scripts/eval_m2.sh        （退出码即验收结果）
set -uo pipefail
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

cd "$REPO_ROOT"
if [ -x ".venv/Scripts/python.exe" ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
export PYTHONUTF8=1
exec "$PY" -m pytest tests/test_m2.py -v "$@"
