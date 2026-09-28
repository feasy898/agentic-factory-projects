#!/usr/bin/env bash
# run_gpu.sh — GPU 机上 tts 服务（:9002）的启动/停止/状态（nohup 常驻，PID+日志落盘）。
# 前置：gpu/setup_gpu.sh 已建好主 venv；权重 /data/xdng/models/{dub-tts,alt-tts-b}
#       已就位（D1 冒烟同源；gpu/setup_tts_service.sh 可做前置核验）。
# venv 口径：主 venv /data/xdng/venv（TTS/口型组 torch 2.5.1+cu118 + transformers 4.52.x）。
# 服务只监听 127.0.0.1:9002；本机访问一律走 ops/tunnel_gpu.sh
#   （TUNNEL_LOCAL_PORT=9002 TUNNEL_REMOTE_PORT=9002 bash ops/tunnel_gpu.sh start）。
# 显存互斥（configs/models.yaml B2 提示）：备选 B 引擎按 models.yaml 落 cuda:1，
#   与 lip-pro 互斥 —— lip-pro 起来前先停本服务。
# 用法: bash run_gpu.sh [start|stop|restart|status]   （默认 start，幂等）
set -uo pipefail
ROOT=/data/xdng
VENV=$ROOT/venv
PY=$VENV/bin/python
HERE=$(cd "$(dirname "$0")" && pwd)
PORT="${TTS_PORT:-9002}"
LOG_DIR=$ROOT/logs
LOG=$LOG_DIR/tts.log
PIDF=$LOG_DIR/tts.pid
mkdir -p "$LOG_DIR" "$ROOT/tts/out"

export TTS_WEIGHTS_ROOT="${TTS_WEIGHTS_ROOT:-$ROOT/models}"
export TTS_OUT_DIR="${TTS_OUT_DIR:-$ROOT/tts/out}"
export TTS_DEVICE="${TTS_DEVICE:-cuda:0}"
export TTS_ALT_B_DEVICE="${TTS_ALT_B_DEVICE:-cuda:1}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_DISABLE_XET=1   # 权重全在本地目录；此开关防意外联网时踩 Xet（hf-mirror 不代理）
export TOKENIZERS_PARALLELISM=false

health() { curl -sf -m 3 "http://127.0.0.1:$PORT/health" 2>/dev/null; }
is_up() { [ -n "$(health)" ]; }

running_pid() {
  [ -f "$PIDF" ] || return 1
  local p; p=$(cat "$PIDF" 2>/dev/null)
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null && echo "$p"
}

start() {
  if is_up; then echo "tts already UP on :$PORT"; return 0; fi
  local old; old=$(running_pid || true)
  if [ -n "${old:-}" ]; then echo "stale pid $old, killing"; kill "$old" 2>/dev/null; sleep 2; fi
  [ -x "$PY" ] || { echo "FATAL: $PY 不存在（主 venv 未就绪，先跑 gpu/setup_gpu.sh）"; return 1; }
  nohup "$PY" -u "$HERE/service.py" --port "$PORT" >> "$LOG" 2>&1 &
  echo $! > "$PIDF"
  echo "tts starting pid $(cat "$PIDF") (log: $LOG)"
  for _ in $(seq 1 180); do  # 主力引擎 fp32 装载 D1 实测约 21–26s，留首载缓存余量
    if is_up; then echo "tts UP: $(health | head -c 300)"; return 0; fi
    sleep 1
  done
  echo "FATAL: 180s 内未就绪，日志尾 30 行："; tail -30 "$LOG"; return 1
}

stop() {
  local p; p=$(running_pid || true)
  if [ -z "${p:-}" ]; then echo "tts not running (pidfile gone)"; rm -f "$PIDF"; return 0; fi
  kill "$p" && echo "stopped pid $p"; rm -f "$PIDF"
}

status() {
  if is_up; then echo "tts UP on :$PORT"; health; else echo "tts DOWN on :$PORT"; tail -5 "$LOG" 2>/dev/null; return 1; fi
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  restart) stop >/dev/null 2>&1 || true; start ;;
  status) status ;;
  *) echo "usage: $0 [start|stop|restart|status]"; exit 2 ;;
esac
