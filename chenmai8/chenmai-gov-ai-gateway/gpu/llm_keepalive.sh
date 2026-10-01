#!/usr/bin/env bash
# llm_keepalive.sh — GPU 机侧 llm_openai（:9004）常驻保活循环（nohup 后台跑在本机）。
# 形态沿用本机隧道保活的成功经验（间隔探测，断则幂等拉起；单实例锁防连锁拉起）。
# 关键护栏：/health 未就绪但 pidfile 进程仍在位 = 装载中（16G 级 fp16 需数分钟），
#   此时只等待不杀进程（否则会把装载中的服务反复杀死形成死循环）。
# 用法（GPU 机上）:
#   nohup bash llm_keepalive.sh >> /data/xdng/logs/llm_keepalive.log 2>&1 &
# 环境变量: LLM_PORT（默认 9004）、KA_INTERVAL_S（默认 30）。
set -uo pipefail
ROOT=/data/xdng
LOG_DIR=$ROOT/logs
PIDF=$LOG_DIR/llm_openai.pid
RUN="$ROOT/llm_openai/run_gpu.sh"   # 部署位（repo 路径 gpu-services/llm_openai/run_gpu.sh 平铺到 $ROOT 下）
LOCK="$HOME/.llm_keepalive.lock"
PORT="${LLM_PORT:-9004}"

health() { curl -sf -m 5 "http://127.0.0.1:$PORT/health" 2>/dev/null; }

if [ -f "$LOCK" ]; then
  other=$(cat "$LOCK" 2>/dev/null)
  if [ -n "$other" ] && kill -0 "$other" 2>/dev/null; then
    echo "keepalive already running (pid $other)"; exit 0
  fi
fi
echo $$ > "$LOCK"
echo "[$(date '+%F %T')] llm keepalive loop start (interval ${KA_INTERVAL_S:-30}s, pid $$)"
while true; do
  if ! health >/dev/null 2>&1; then
    alive=""
    if [ -f "$PIDF" ]; then
      p=$(cat "$PIDF" 2>/dev/null)
      [ -n "$p" ] && kill -0 "$p" 2>/dev/null && alive="$p"
    fi
    if [ -n "$alive" ]; then
      echo "[$(date '+%F %T')] health down but pid $alive alive (装载中) -> wait"
    else
      echo "[$(date '+%F %T')] health down, no live pid -> run_gpu.sh start"
      bash "$RUN" start || true   # 幂等：已在位则 no-op；失败交由下一轮重试
    fi
  fi
  sleep "${KA_INTERVAL_S:-30}"
done
