#!/usr/bin/env bash
# eval_m10.sh — M10 验收入口（本机，经 ssh 隧道调 GPU lip 服务 :9003）。
# 步骤：①确保隧道（ops/tunnel_gpu.sh，幂等，9003 端口）；②pytest tests/test_m10_lipsync.py。
# 前置：GPU 侧服务已由 gpu-services/lip/run_gpu.sh 启动（物理 cuda:1，
#       与 :9002 备选合成引擎同卡互斥，run_gpu.sh 启动前自检）。
# 用法: bash scripts/eval_m10.sh        （退出码即验收结果）
set -uo pipefail
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

echo "== [1/2] 隧道就绪检查（127.0.0.1:9003 -> GPU 机 :9003） =="
TUNNEL_LOCAL_PORT=9003 TUNNEL_REMOTE_PORT=9003 bash "$REPO_ROOT/ops/tunnel_gpu.sh" start || exit 1

echo "== [2/2] pytest tests/test_m10_lipsync.py =="
cd "$REPO_ROOT"
if [ -x ".venv/Scripts/python.exe" ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
export PYTHONUTF8=1
exec "$PY" -m pytest tests/test_m10_lipsync.py -v "$@"
