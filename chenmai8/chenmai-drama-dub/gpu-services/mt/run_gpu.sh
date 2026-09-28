#!/usr/bin/env bash
# run_gpu.sh — GPU 机上 mt 服务（:9004）的启动/停止/状态（nohup 常驻，PID+日志落盘）。
# 状态：T10 预置 —— 部署与冒烟归 T12 批；本脚本与 gpu/setup_mt_service.sh 配套。
# 前置：gpu/setup_mt_service.sh 已把 mt-core 权重放好（/data/xdng/models/mt-core）。
# venv 口径：主 venv /data/xdng/venv（TTS/口型组 4.52.x 同组；transformers 兼容性
#   由 T12 实测核实并钉版，见 docs/mt_service_deps.md；若需独立 venv 再拆）。
# 服务只监听 127.0.0.1:9004；本机访问一律走 ops/tunnel_gpu.sh（TUNNEL_LOCAL_PORT=9004）。
# 用法: bash run_gpu.sh [start|stop|restart|status]   （默认 start，幂等）
set -uo pipefail
ROOT=/data/xdng
VENV=$ROOT/venv
PY=$VENV/bin/python
HERE=$(cd "$(dirname "$0")" && pwd)
PORT="${MT_PORT:-9004}"
LOG_DIR=$ROOT/logs
LOG=$LOG_DIR/mt.log
PIDF=$LOG_DIR/mt.pid
mkdir -p "$LOG_DIR"

export MT_CORE_DIR="${MT_CORE_DIR:-$ROOT/models/mt-core}"
export MT_DEVICE="${MT_DEVICE:-cuda:0}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_DISABLE_XET=1   # 权重全在本地目录；防 from_pretrained 意外联网时踩 Xet

health() { curl -sf -m 3 "http://127.0.0.1:$PORT/health" 2>/dev/null; }
is_up() { [ -n "$(health)" ]; }

running_pid() {
  [ -f "$PIDF" ] || return 1
  local p; p=$(cat "$PIDF" 2>/dev/null)
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null && echo "$p"
}

start() {
  if is_up; then echo "mt already UP on :$PORT"; return 0; fi
  local old; old=$(running_pid || true)
  if [ -n "${old:-}" ]; then echo "stale pid $old, killing"; kill "$old" 2>/dev/null; sleep 2; fi
  [ -x "$PY" ] || { echo "FATAL: $PY 不存在（主 venv 未就绪，先跑 gpu/setup_gpu.sh）"; return 1; }
  nohup "$PY" -u "$HERE/service.py" --port "$PORT" >> "$LOG" 2>&1 &
  echo $! > "$PIDF"
  echo "mt starting pid $(cat "$PIDF") (log: $LOG)"
  for _ in $(seq 1 120); do  # 模型装载含首载缓存，最多等 2 分钟
    if is_up; then echo "mt UP: $(health | head -c 300)"; return 0; fi
    sleep 1
  done
  echo "FATAL: 120s 内未就绪，日志尾 30 行："; tail -30 "$LOG"; return 1
}

stop() {
  local p; p=$(running_pid || true)
  if [ -z "${p:-}" ]; then echo "mt not running (pidfile gone)"; rm -f "$PIDF"; return 0; fi
  kill "$p" && echo "stopped pid $p"; rm -f "$PIDF"
}

status() {
  if is_up; then echo "mt UP on :$PORT"; health; else echo "mt DOWN on :$PORT"; tail -5 "$LOG" 2>/dev/null; return 1; fi
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  restart) stop >/dev/null 2>&1 || true; start ;;
  status) status ;;
  *) echo "usage: $0 [start|stop|restart|status]"; exit 2 ;;
esac
