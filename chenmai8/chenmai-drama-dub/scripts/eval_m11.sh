#!/usr/bin/env bash
# eval_m11.sh — M11 验收入口（本机 CPU；无 GPU/远端服务依赖）。
# 步骤：合成 drawtext 中文硬字幕 + 顶部 AI 标识视频 → M1 摄取 → M2 采样 OCR →
#       擦除（delogo 默认 + inpaint 备选，label_zone 排除）→ 重跑 OCR 断言
#       中文字符命中 = 0（3 段素材）→ 标识区像素哈希一致 → C2×C4 装配 ASS
#       （en 左下 / ar 右下 RTL）→ ffmpeg 压制抽帧断言（ar bidi 方向 + 连接）。
# 用法: bash scripts/eval_m11.sh        （退出码即验收结果）
set -uo pipefail
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

cd "$REPO_ROOT"
if [ -x ".venv/Scripts/python.exe" ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
export PYTHONUTF8=1
exec "$PY" -m pytest tests/test_m11.py -v "$@"
