#!/usr/bin/env bash
# eval_m9.sh — M9 验收入口（T15 自验收口径：B1 合成样本，全离线零 GPU）。
#
# 断言集（tests/test_m9.py）：合成样本 = 分离背景（稳态 150Hz bgm.wav）+ 占位人声
# （C5/C2 摆放；含故意超窗句/异采样率 22050Hz 重采样句/nonverbal keep_original 句）
# → ① 时长差 ≤0.2s（mix/dubbed/成片 vs master）；② loudnorm 复测 I∈[-17,-15]
# （±1LU）；③ 对白区间背景电平实测达标（报告实测 core≈-9dB/pad≈-6dB + 交付文件
# 150Hz 频段对拍关-ducking 对照混音）；人声/bg 峰值比 ≥8dB；成片含 ASS + AI
# 隐式标识元数据位（ffprobe 回读精确匹配）+ M11 成品接入路径（-c:v copy）；
# CLI exit 0 / 缺输入 exit 1 / --strict-missing / --no-compose / 幂等重跑。
# 用法: bash scripts/eval_m9.sh       （退出码即验收结果）
set -uo pipefail
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

cd "$REPO_ROOT"
if [ -x ".venv/Scripts/python.exe" ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
export PYTHONUTF8=1
exec "$PY" -m pytest tests/test_m9.py -v "$@"
