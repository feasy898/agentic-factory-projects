#!/usr/bin/env bash
# eval_m4.sh — M4 验收入口（本机，经 ssh 隧道调 GPU asr_align 服务）。
# 步骤：①确保隧道（ops/tunnel_gpu.sh，幂等）；②pytest tests/test_m4.py。
# 前置：GPU 侧服务已由 gpu-services/asr_align/run_gpu.sh 启动。
# 用法: bash scripts/eval_m4.sh        （退出码即验收结果）
set -uo pipefail
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

echo "== [1/2] 隧道就绪检查 =="
bash "$REPO_ROOT/ops/tunnel_gpu.sh" start || exit 1

echo "== [2/2] pytest tests/test_m4.py =="
cd "$REPO_ROOT"
if [ -x ".venv/Scripts/python.exe" ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
export PYTHONUTF8=1
exec "$PY" -m pytest tests/test_m4.py -v "$@"
