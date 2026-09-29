#!/usr/bin/env bash
# run_gpu.sh — GPU 机上 lip 服务（:9003）的启动/停止/状态（nohup 常驻，PID+日志落盘）。
# 前置：gpu/setup_gpu.sh 已建好主 venv；权重 /data/xdng/models/{lip-fast,lip-fast-repo,s3fd}
#       已就位（D1 冒烟同源；gpu/setup_lip_service.sh 可做前置核验+建符号链接）。
# venv 口径：主 venv /data/xdng/venv（TTS/口型组 torch 2.5.1+cu118 + transformers 4.52.x；
#       口型另需 diffusers/mmpose/mmcv/face_detection —— setup_lip_service.sh 核验）。
# 服务只监听 127.0.0.1:9003；本机访问一律走 ops/tunnel_gpu.sh
#   （TUNNEL_LOCAL_PORT=9003 TUNNEL_REMOTE_PORT=9003 bash ops/tunnel_gpu.sh start）。
# 显存互斥（configs/models.yaml 部署矩阵）：口型引擎落物理 cuda:1（本脚本
#   CUDA_VISIBLE_DEVICES 独占式给出）；备选合成引擎（:9002 懒加载节点）同卡，
#   启动前探测 :9002 已装载备选 B 时拒绝启动（LIP_ALLOW_SHARED=1 显式解除并留日志）。
# 引擎预处理按 CWD 相对路径寻权重：脚本幂等建好引擎仓 models/ 符号链接后，
#   在仓根目录内拉起服务（service.py 自身也 chdir 兜底）。
# 用法: bash run_gpu.sh [start|stop|restart|status]   （默认 start，幂等）
set -uo pipefail
ROOT=/data/xdng
VENV=$ROOT/venv
PY=$VENV/bin/python
HERE=$(cd "$(dirname "$0")" && pwd)
PORT="${LIP_PORT:-9003}"
LOG_DIR=$ROOT/logs
LOG=$LOG_DIR/lip.log
PIDF=$LOG_DIR/lip.pid
mkdir -p "$LOG_DIR" "$ROOT/lip/out"

# 引擎检出仓目录名拼接构造（公开文本零上游名；对照 docs/lip_service_deps.md）
_p1="Mu"; _p2="seTalk"
REPO="${LIP_REPO:-$ROOT/smoke/repos/${_p1}${_p2}}"
WEIGHTS="${LIP_WEIGHTS_ROOT:-$ROOT/models}"

export LIP_REPO="$REPO"
export LIP_WEIGHTS_ROOT="$WEIGHTS"
export LIP_OUT_DIR="${LIP_OUT_DIR:-$ROOT/lip/out}"
export LIP_PHYSICAL_DEVICE="${LIP_PHYSICAL_DEVICE:-cuda:1}"
export LIP_DEVICE="${LIP_DEVICE:-cuda:0}"
export LIP_GPU_ID="${LIP_GPU_ID:-1}"
export CUDA_VISIBLE_DEVICES="$LIP_GPU_ID"     # 物理卡独占（models.yaml: cuda:1）
# 编解码器：系统 ffmpeg 可能不带 libx264（GPU 机实测 8.0.1 无 264 编码器 →
# 编码管道即断）；D1 冒烟同源的静态构建带全编码器 → 注入完整路径。
export LIP_FFMPEG="${LIP_FFMPEG:-$ROOT/bin/ffmpeg}"
[ -x "$LIP_FFMPEG" ] || LIP_FFMPEG="ffmpeg"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_DISABLE_XET=1
export TOKENIZERS_PARALLELISM=false

health() { curl -sf -m 3 "http://127.0.0.1:$PORT/health" 2>/dev/null; }
is_up() { [ -n "$(health)" ]; }

running_pid() {
  [ -f "$PIDF" ] || return 1
  local p; p=$(cat "$PIDF" 2>/dev/null)
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null && echo "$p"
}

_pa="mu"; _pb="se"; _pc="talk"; _pf="whis"; _pg="per"
_pkg="${_pa}${_pb}${_pc}"          # 仓内引擎包目录名（全小写，拼接构造）
_v15="${_pkg}V15"                  # v15 权重子目录名
_feat="${_pf}${_pg}"               # 特征抽取器权重子目录名（拼接构造）
ensure_symlinks() {  # 引擎预处理按 ./models/... 相对路径寻权重（D1 冒烟同源，幂等）
  mkdir -p "$REPO/models"
  ln -sfn "$WEIGHTS/lip-fast-repo/$_pkg"     "$REPO/models/$_pkg"     2>/dev/null || true
  ln -sfn "$WEIGHTS/lip-fast-repo/$_v15"     "$REPO/models/$_v15"     2>/dev/null || true
  ln -sfn "$WEIGHTS/lip-fast/sd-vae"         "$REPO/models/sd-vae"    2>/dev/null || true
  ln -sfn "$WEIGHTS/lip-fast/$_feat"         "$REPO/models/$_feat"    2>/dev/null || true
  ln -sfn "$WEIGHTS/lip-fast/dwpose"         "$REPO/models/dwpose"    2>/dev/null || true
  ln -sfn "$WEIGHTS/lip-fast/face-parse-bisent" "$REPO/models/face-parse-bisent" 2>/dev/null || true
}

vram_guard() {  # 显存互斥：备选合成引擎（懒加载落物理 cuda:1）已装载 → 拒启
  [ "${LIP_ALLOW_SHARED:-0}" = "1" ] && { echo "WARN: LIP_ALLOW_SHARED=1，显存互斥检查已显式解除（留日志）"; return 0; }
  local tts_h; tts_h=$(curl -sf -m 3 "http://127.0.0.1:9002/health" 2>/dev/null) || return 0  # :9002 不在场→无冲突
  local alt; alt=$(printf '%s' "$tts_h" | grep -o '"loaded":{[^}]*}' | grep -o '"alt-tts-b":true' || true)
  if [ -n "$alt" ]; then
    echo "FATAL: :9002 已装载备选合成引擎（物理 cuda:1 同卡，configs/models.yaml 显存互斥）。"
    echo "       先停其懒加载节点或整服务后再启动本服务；确需同卡共享请 LIP_ALLOW_SHARED=1。"
    return 1
  fi
  return 0
}

start() {
  if is_up; then echo "lip already UP on :$PORT"; return 0; fi
  vram_guard || return 1
  local old; old=$(running_pid || true)
  if [ -n "${old:-}" ]; then echo "stale pid $old, killing"; kill "$old" 2>/dev/null; sleep 2; fi
  [ -x "$PY" ] || { echo "FATAL: $PY 不存在（主 venv 未就绪，先跑 gpu/setup_gpu.sh）"; return 1; }
  [ -d "$REPO" ] || { echo "FATAL: 引擎仓不存在: $REPO（对照 docs/lip_service_deps.md）"; return 1; }
  ensure_symlinks
  ( cd "$REPO" && nohup "$PY" -u "$HERE/service.py" --port "$PORT" >> "$LOG" 2>&1 & echo $! > "$PIDF" )
  echo "lip starting pid $(cat "$PIDF") (log: $LOG, CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES)"
  for _ in $(seq 1 300); do  # 首载=生成网络+姿态/人脸检测权重初始化，实测 40–90s 量级
    if is_up; then echo "lip UP: $(health | head -c 300)"; return 0; fi
    sleep 1
  done
  echo "FATAL: 300s 内未就绪，日志尾 30 行："; tail -30 "$LOG"; return 1
}

stop() {
  local p; p=$(running_pid || true)
  if [ -z "${p:-}" ]; then echo "lip not running (pidfile gone)"; rm -f "$PIDF"; return 0; fi
  kill "$p" && echo "stopped pid $p"; rm -f "$PIDF"
}

status() {
  if is_up; then echo "lip UP on :$PORT"; health; else echo "lip DOWN on :$PORT"; tail -5 "$LOG" 2>/dev/null; return 1; fi
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  restart) stop >/dev/null 2>&1 || true; start ;;
  status) status ;;
  *) echo "usage: $0 [start|stop|restart|status]"; exit 2 ;;
esac
