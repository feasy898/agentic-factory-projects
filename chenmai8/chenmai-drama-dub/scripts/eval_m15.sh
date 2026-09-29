#!/usr/bin/env bash
# eval_m15.sh — M15 指标体系验收入口（任务 T21 自验收口径）。
#
# 断言集（tests/test_m15_metrics.py）：
#   离线：WER/CER 编辑距离与分语种口径、Pearson 退化、RMS 包络、声纹嵌入同源
#   余弦=1（真权重）、时长对齐率实测口径四类路径、口型评分动嘴/静止敏感性对照、
#   桩服务情绪一致率与回听 WER 精确断言、CLI --allow-degraded 与缺输入退出码；
#   在线（:9001/:9002 可达时）：SAPI 参考 + TTS 真配音工作区六项全出数 exit 0。
#   服务不可达时在线组整组 skip（test_m4/test_m7 同口径）。
# 数值不做规划线门禁（T21 定案：数值如实、无基准则记 baseline v0）。
# 用法: bash scripts/eval_m15.sh       （退出码即验收结果）
set -uo pipefail
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

cd "$REPO_ROOT"
if [ -x ".venv/Scripts/python.exe" ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
export PYTHONUTF8=1
exec "$PY" -m pytest tests/test_m15_metrics.py -v "$@"
