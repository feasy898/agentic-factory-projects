#!/usr/bin/env bash
# run_gpu.sh — GPU 机上 asr_align 服务的启动/停止/状态（nohup 常驻，PID+日志落盘）。
# 前置：gpu/setup_asr_venv.sh 已建好 /data/xdng/venv-asr 与权重目录。
# 服务只监听 127.0.0.1:9001；本机访问一律走 ops/tunnel_gpu.sh 隧道。
# 用法: bash run_gpu.sh [start|stop|restart|status]   （默认 start，幂等）
set -uo pipefail
ROOT=/data/xdng
VENV=$ROOT/venv-asr
PY=$VENV/bin/python
HERE=$(cd "$(dirname "$0")" && pwd)
PORT="${ASR_ALIGN_PORT:-9001}"
LOG_DIR=$ROOT/logs
LOG=$LOG_DIR/asr_align.log
PIDF=$LOG_DIR/asr_align.pid
mkdir -p "$LOG_DIR"

export ASR_CORE_DIR="${ASR_CORE_DIR:-$ROOT/models/asr-core}"
export ALIGN_CORE_DIR="${ALIGN_CORE_DIR:-$ROOT/models/align-core}"
export EMO_TAG_DIR="${EMO_TAG_DIR:-$ROOT/models/emo-tag}"
export ASR_ALIGN_DEVICE="${ASR_ALIGN_DEVICE:-cuda:0}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_DISABLE_XET=1   # 权重全在本地目录；此开关防 from_pretrained 意外联网时踩 Xet（hf-mirror 不代理）

health() { curl -sf -m 3 "http://127.0.0.1:$PORT/health" 2>/dev/null; }
is_up() { [ -n "$(health)" ]; }

running_pid() {
  [ -f "$PIDF" ] || return 1
  local p; p=$(cat "$PIDF" 2>/dev/null)
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null && echo "$p"
}

start() {
  if is_up; then echo "asr_align already UP on :$PORT"; return 0; fi
  local old; old=$(running_pid || true)
  if [ -n "${old:-}" ]; then echo "stale pid $old, killing"; kill "$old" 2>/dev/null; sleep 2; fi
  [ -x "$PY" ] || { echo "FATAL: $PY 不存在，先跑 gpu/setup_asr_venv.sh"; return 1; }
  nohup "$PY" -u "$HERE/service.py" --port "$PORT" >> "$LOG" 2>&1 &
  echo $! > "$PIDF"
  echo "asr_align starting pid $(cat "$PIDF") (log: $LOG)"
  for _ in $(seq 1 120); do  # 模型装载含首载缓存，最多等 2 分钟
    if is_up; then echo "asr_align UP: $(health | head -c 300)"; return 0; fi
    sleep 1
  done
  echo "FATAL: 120s 内未就绪，日志尾 30 行："; tail -30 "$LOG"; return 1
}

stop() {
  local p; p=$(running_pid || true)
  if [ -z "${p:-}" ]; then echo "asr_align not running (pidfile gone)"; rm -f "$PIDF"; return 0; fi
  kill "$p" && echo "stopped pid $p"; rm -f "$PIDF"
}

status() {
  if is_up; then echo "asr_align UP on :$PORT"; health; else echo "asr_align DOWN on :$PORT"; tail -5 "$LOG" 2>/dev/null; return 1; fi
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 1; start ;;
  status) status ;;
  *) echo "usage: $0 [start|stop|restart|status]"; exit 2 ;;
esac
