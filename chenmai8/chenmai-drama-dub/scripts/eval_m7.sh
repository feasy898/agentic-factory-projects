#!/usr/bin/env bash
# eval_m7.sh — M7 验收入口（本机，经 ssh 隧道调 GPU tts 服务 :9002）。
# 步骤：①确保隧道（ops/tunnel_gpu.sh，幂等，9002 端口）；②pytest tests/test_m7_tts.py。
# 前置：GPU 侧服务已由 gpu-services/tts/run_gpu.sh 启动。
# 用法: bash scripts/eval_m7.sh        （退出码即验收结果）
set -uo pipefail
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

echo "== [1/2] 隧道就绪检查（127.0.0.1:9002 -> GPU 机 :9002） =="
TUNNEL_LOCAL_PORT=9002 TUNNEL_REMOTE_PORT=9002 bash "$REPO_ROOT/ops/tunnel_gpu.sh" start || exit 1

echo "== [2/2] pytest tests/test_m7_tts.py =="
cd "$REPO_ROOT"
if [ -x ".venv/Scripts/python.exe" ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
export PYTHONUTF8=1
exec "$PY" -m pytest tests/test_m7_tts.py -v "$@"
