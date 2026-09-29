#!/usr/bin/env bash
# run_gpu.sh — GPU 机上 llm_openai 服务（:9004）的启动/停止/状态（nohup 常驻，PID+日志落盘）。
# 形态沿用本机已验证的 transformers fp16 直跑模式（Volta：fp16 + sdpa，无 bf16/无 FA2）。
# 前置：gpu/setup_llm_service.sh 已把权重放好（LLM_MODEL_DIR，默认 /data/xdng/models/llm-chat-8b）。
# 显存预算 ≤20G 单卡：默认走 1 号物理卡（CUDA_VISIBLE_DEVICES=1，0 号被既有服务占用），
#   服务内恒用 cuda:0（相对可见卡集合）；可用 LLM_CUDA_VISIBLE_DEVICES 覆盖。
# 服务只监听 127.0.0.1:9004；本机访问一律走 ops/tunnel_gpu.sh（默认 9004）。
# 模型真实名/来源不入仓库（审查 §E）：权重目录经环境变量或 setup 脚本预置的本地路径提供。
# 用法: bash run_gpu.sh [start|stop|restart|status]   （默认 start，幂等）
set -uo pipefail
ROOT=/data/xdng
VENV=$ROOT/venv
PY=$VENV/bin/python
HERE=$(cd "$(dirname "$0")" && pwd)
PORT="${LLM_PORT:-9004}"
LOG_DIR=$ROOT/logs
LOG=$LOG_DIR/llm_openai.log
PIDF=$LOG_DIR/llm_openai.pid
mkdir -p "$LOG_DIR"

export LLM_MODEL_DIR="${LLM_MODEL_DIR:-$ROOT/models/llm-chat-8b}"
export LLM_DEVICE="${LLM_DEVICE:-cuda:0}"
export LLM_SERVE_MODEL="${LLM_SERVE_MODEL:-local-chat-8b}"
export CUDA_VISIBLE_DEVICES="${LLM_CUDA_VISIBLE_DEVICES:-1}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_OFFLINE=1          # 权重全在本地目录；from_pretrained 不联网
export HF_HUB_DISABLE_XET=1

health() { curl -sf -m 3 "http://127.0.0.1:$PORT/health" 2>/dev/null; }
is_up() { [ -n "$(health)" ]; }

running_pid() {
  [ -f "$PIDF" ] || return 1
  local p; p=$(cat "$PIDF" 2>/dev/null)
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null && echo "$p"
}

start() {
  if is_up; then echo "llm_openai already UP on :$PORT"; return 0; fi
  local old; old=$(running_pid || true)
  if [ -n "${old:-}" ]; then echo "stale pid $old, killing"; kill "$old" 2>/dev/null; sleep 2; fi
  [ -x "$PY" ] || { echo "FATAL: $PY 不存在（主 venv 未就绪）"; return 1; }
  if [ ! -d "$LLM_MODEL_DIR" ]; then echo "FATAL: 权重目录不存在: $LLM_MODEL_DIR（先跑 gpu/setup_llm_service.sh）"; return 1; fi
  nohup "$PY" -u "$HERE/service.py" --port "$PORT" >> "$LOG" 2>&1 &
  echo $! > "$PIDF"
  echo "llm_openai starting pid $(cat "$PIDF") (log: $LOG)"
  for _ in $(seq 1 600); do  # 16G 级 fp16 装载+暖机，最多等 10 分钟
    if is_up; then echo "llm_openai UP: $(health | head -c 300)"; return 0; fi
    sleep 1
  done
  echo "FATAL: 600s 内未就绪，日志尾 30 行："; tail -30 "$LOG"; return 1
}

stop() {
  local p; p=$(running_pid || true)
  if [ -z "${p:-}" ]; then echo "llm_openai not running (pidfile gone)"; rm -f "$PIDF"; return 0; fi
  kill "$p" && echo "stopped pid $p"; rm -f "$PIDF"
}

status() {
  if is_up; then echo "llm_openai UP on :$PORT"; health; else echo "llm_openai DOWN on :$PORT"; tail -5 "$LOG" 2>/dev/null; return 1; fi
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  restart)
    stop >/dev/null 2>&1 || true
    for _ in $(seq 1 30); do  # 等旧进程真正退出（uvicorn 摘除有数秒延迟，防 is_up 误判 already UP）
      is_up || break
      sleep 1
    done
    start ;;
  status) status ;;
  *) echo "usage: $0 [start|stop|restart|status]"; exit 2 ;;
esac
