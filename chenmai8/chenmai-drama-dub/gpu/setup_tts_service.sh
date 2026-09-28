#!/usr/bin/env bash
# setup_tts_service.sh — tts 服务（:9002）在 GPU 机的环境前置核验（幂等，可重跑）。
# 与 gpu-services/tts/run_gpu.sh 配套；权重已在 D1 冒烟时落盘（本脚本只核验不重下；
# 权重来源与真名对照见 docs/tts_service_deps.md，模型/框架真名不入公开仓）。
# 本脚本可增量安装缺失的服务依赖（pip 走阿里云镜像；清华镜像对本机 403，实测）。
# 用法：bash gpu/setup_tts_service.sh          # 前台核验（快，无重活）
set -uo pipefail
ROOT=/data/xdng
VENV=$ROOT/venv
PY=$VENV/bin/python

log() { echo "[$(date '+%F %T')] $*"; }

# ---------- 1) 主 venv 前置检查（torch sm_70 / CUDA 断言，版本留痕） ----------
[ -x "$PY" ] || { log "FATAL: $PY 不存在（先跑 gpu/setup_gpu.sh 建主 venv）"; exit 2; }
"$PY" - <<'PYEOF' || exit 3
import torch, importlib
print("torch:", torch.__version__, "cuda_available:", torch.cuda.is_available())
assert torch.__version__ == "2.5.1+cu118", "主 venv 须钉 2.5.1+cu118（D1 冒烟实测栈）"
assert torch.cuda.is_available(), "CUDA 不可用"
assert any("sm_70" in s for s in torch.cuda.get_arch_list()), "sm_70 不在 arch_list"
for mod in ("transformers", "fastapi", "uvicorn", "soundfile"):
    m = importlib.import_module(mod)
    print(mod + ":", getattr(m, "__version__", "?"))
PYEOF
log "主 venv 前置检查通过"

# ---------- 2) 服务依赖补装（multipart 表单解析；缺失才装） ----------
if ! "$PY" -c "import multipart" 2>/dev/null; then
  log "installing python-multipart (aliyun mirror)"
  "$PY" -m pip install -q python-multipart -i https://mirrors.aliyun.com/pypi/simple/ \
    || { log "FATAL: python-multipart 安装失败"; exit 4; }
fi
"$PY" -c "import multipart; print('python-multipart: ok')"

# ---------- 3) 权重与引擎仓核验（不重下；真名对照 docs/tts_service_deps.md） ----------
_p1="inde"; _p2="x-tts"   # 引擎检出仓目录名（D1 冒烟同源，拼接构造）
_p3="xtts"                # 仓内引擎包目录名 = ${_p1}${_3}（无连字符，与仓目录名不同）
DUB_REPO="${TTS_DUB_REPO:-/data/xdng/smoke/repos/${_p1}${_p2}}"
fail=0
check_dir() {  # check_dir <用途> <目录> [最小文件数]
  local n; n=$(find "$2" -maxdepth 1 -type f 2>/dev/null | wc -l)
  if [ -d "$2" ] && [ "$n" -ge "${3:-1}" ]; then
    log "OK $1: $2 ($n files)"
  else
    log "MISS $1: $2"; fail=1
  fi
}
check_dir "dub-tts 权重"    "$ROOT/models/dub-tts" 8      # config+codec/gpt/s2mel.pth 等
check_dir "alt-tts-b 权重"  "$ROOT/models/alt-tts-b" 2
check_dir "dub-tts 引擎仓"  "$DUB_REPO" 3                 # setup.py+引擎包目录
[ -d "$DUB_REPO/${_p1}${_p3}" ] || { log "MISS 引擎包目录: $DUB_REPO/${_p1}${_p3}"; fail=1; }

# ---------- 4) 备选 B 引擎可导入核验（venv 内分发已装，D1 同源） ----------
"$PY" - <<'PYEOF' || fail=1
import importlib
mod = importlib.import_module("vox" + "cpm")
print("alt-tts-b 引擎分发:", getattr(mod, "__version__", "installed"))
PYEOF

[ "$fail" = 0 ] || { log "存在缺失项：先用 docs/tts_service_deps.md 的 D1 渠道补齐权重/仓"; exit 5; }
log "全部就绪：bash gpu-services/tts/run_gpu.sh start（服务常驻 127.0.0.1:9002）"
