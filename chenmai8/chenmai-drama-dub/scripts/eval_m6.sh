#!/usr/bin/env bash
# eval_m6.sh — M6 验收入口（mock 后端全离线：角色卡注入 / 预算候选生成 / C4 出口 schema）。
# local/api 后端的服务连通性冒烟归 T12 批（gpu-services/mt 部署后），
# 不在本脚本口径内 —— 本脚本零网络零 GPU 依赖。
# 用法: bash scripts/eval_m6.sh       （退出码即验收结果）
set -uo pipefail
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

cd "$REPO_ROOT"
if [ -x ".venv/Scripts/python.exe" ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
export PYTHONUTF8=1
exec "$PY" -m pytest tests/test_m6.py -v "$@"
