#!/usr/bin/env bash
# tunnel_gpu.sh — 本机 127.0.0.1:9001 → GPU 机 asr_align(:9001) 的 ssh 隧道（幂等，可重跑）。
#
# 背景：GPU 机服务只监听其 127.0.0.1（该机有公网出口，不对外开端口）；tailnet 数据面
# 本机→GPU 机方向实测不通 → 隧道走 ssh config 里的公网 Host 条目（dev-env-with-gpu）。
# 用法:
#   bash ops/tunnel_gpu.sh            # start（先清理同端口旧隧道再拉起，幂等）
#   bash ops/tunnel_gpu.sh status     # 健康检查
#   bash ops/tunnel_gpu.sh stop       # 停止
#   bash ops/tunnel_gpu.sh restart
# 日志: tmp/tunnel_gpu.log（tmp/ 不入库）。环境变量: TUNNEL_GPU_HOST / TUNNEL_LOCAL_PORT。
set -uo pipefail
HOST="${TUNNEL_GPU_HOST:-dev-env-with-gpu}"
LOCAL="${TUNNEL_LOCAL_PORT:-9001}"
REMOTE="${TUNNEL_REMOTE_PORT:-9001}"
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
# T10 增补（只增不改行为）：多服务隧道（如 mt :9004）复用本脚本时，非默认端口的
# 日志/keepalive 锁按端口区分；默认 9001 的文件名与历史完全一致（存量
# keepalive 单实例锁 ~/.tunnel_keepalive.lock 不受影响，防双实例竞争）。
if [ "$LOCAL" = "9001" ]; then
  LOG="$REPO_ROOT/tmp/tunnel_gpu.log"
  KA_LOCK="$HOME/.tunnel_keepalive.lock"
else
  LOG="$REPO_ROOT/tmp/tunnel_gpu.$LOCAL.log"
  KA_LOCK="$HOME/.tunnel_keepalive.$LOCAL.lock"
fi
mkdir -p "$REPO_ROOT/tmp"

health() { curl -sf -m 3 "http://127.0.0.1:$LOCAL/health" 2>/dev/null; }

pids_on_port() {  # Windows netstat：抓占用本地端口的 PID（去重）
  netstat -ano -p tcp 2>/dev/null | awk -v p=":$LOCAL" '
    $2 ~ p"$" && $4 == "LISTENING" { print $5 }' | sort -u
}

do_stop() {
  local pids; pids=$(pids_on_port)
  if [ -z "$pids" ]; then echo "no tunnel on 127.0.0.1:$LOCAL"; return 0; fi
  for p in $pids; do
    echo "stopping pid $p"
    taskkill //F //PID "$p" >/dev/null 2>&1 || kill -9 "$p" 2>/dev/null || true
  done
  sleep 1
  [ -z "$(pids_on_port)" ] && echo "stopped" || { echo "WARN: 端口仍被占用"; return 1; }
}

do_start() {
  if [ -n "$(health)" ]; then echo "tunnel already UP (127.0.0.1:$LOCAL)"; return 0; fi
  do_stop >/dev/null 2>&1 || true
  echo "opening tunnel 127.0.0.1:$LOCAL -> $HOST:127.0.0.1:$REMOTE (log: $LOG)"
  nohup ssh -N \
    -L "127.0.0.1:$LOCAL:127.0.0.1:$REMOTE" \
    -o BatchMode=yes -o ConnectTimeout=15 \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=4 \
    -o ControlMaster=no -o ControlPath=none \
    "$HOST" >> "$LOG" 2>&1 &
  local pid=$!
  for _ in $(seq 1 20); do
    if [ -n "$(health)" ]; then
      echo "tunnel UP (ssh pid $pid): $(health | head -c 200)"
      return 0
    fi
    sleep 1
  done
  echo "FATAL: 隧道未就绪，日志尾 20 行："; tail -20 "$LOG"; return 1
}

do_status() {
  if [ -n "$(health)" ]; then
    echo "tunnel UP (127.0.0.1:$LOCAL)"
    health
    return 0
  fi
  echo "tunnel DOWN (127.0.0.1:$LOCAL)"; return 1
}

# keepalive —— 每 KA_INTERVAL_S 秒探测一次，断则自动拉起（幂等）。
# 背景（B1 收口 2026-09-29）：公网 ssh 链路周期性 reset，reset→重建有 ~10s 愈合窗，
# 期间经隧道的服务用例会瞬时 GpuServiceError/skip。本循环把窗口收敛为秒级自愈。
# v2：单实例锁（~/.tunnel_keepalive.lock，防多实例竞争连锁 bind 失败）；
#     拉起失败不并发叠加，交由下一轮探测重试。
# 用法: nohup bash ops/tunnel_gpu.sh keepalive >> tmp/tunnel_keepalive.log 2>&1 &
# （KA_LOCK 在文件头按端口取值：9001 用历史锁名，其他端口加端口后缀）
do_keepalive() {
  if [ -f "$KA_LOCK" ]; then
    other=$(cat "$KA_LOCK" 2>/dev/null)
    if [ -n "$other" ] && kill -0 "$other" 2>/dev/null; then
      echo "keepalive already running (pid $other)"; exit 0
    fi
  fi
  echo $$ > "$KA_LOCK"
  echo "[$(date '+%F %T')] keepalive loop start (interval ${KA_INTERVAL_S:-5}s, pid $$)"
  while true; do
    if ! health >/dev/null 2>&1; then
      echo "[$(date '+%F %T')] health probe failed -> do_start"
      do_start || true
      health >/dev/null 2>&1 || sleep 2   # 未就绪交由下一轮重试，不并发拉起
    fi
    sleep "${KA_INTERVAL_S:-5}"
  done
}

case "${1:-start}" in
  start) do_start ;;
  stop) do_stop ;;
  restart) do_stop >/dev/null 2>&1 || true; do_start ;;
  status) do_status ;;
  keepalive) do_keepalive ;;
  *) echo "usage: $0 [start|stop|restart|status|keepalive]"; exit 2 ;;
esac
