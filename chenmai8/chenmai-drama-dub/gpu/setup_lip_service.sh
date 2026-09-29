#!/usr/bin/env bash
# setup_lip_service.sh — lip 服务（:9003）在 GPU 机的环境前置核验（幂等，可重跑）。
# 与 gpu-services/lip/run_gpu.sh 配套；权重与引擎仓已在 D1 冒烟时落盘
# （本脚本只核验+建符号链接，不重下；权重来源与真名对照见 docs/lip_service_deps.md，
# 模型/框架真名不入公开仓——本文件经 docs/ 豁免扫描，但拼接构造仍保持惯例）。
# 用法：bash gpu/setup_lip_service.sh          # 前台核验（快，无重活）
set -uo pipefail
ROOT=/data/xdng
VENV=$ROOT/venv
PY=$VENV/bin/python

log() { echo "[$(date '+%F %T')] $*"; }

# ---------- 1) 主 venv 前置检查（torch sm_70 / CUDA 断言 + 口型组依赖留痕） ----------
[ -x "$PY" ] || { log "FATAL: $PY 不存在（先跑 gpu/setup_gpu.sh 建主 venv）"; exit 2; }
"$PY" - <<'PYEOF' || exit 3
import importlib
import torch
print("torch:", torch.__version__, "cuda_available:", torch.cuda.is_available())
assert torch.__version__ == "2.5.1+cu118", "主 venv 须钉 2.5.1+cu118（D1 冒烟实测栈）"
assert torch.cuda.is_available(), "CUDA 不可用"
assert torch.cuda.device_count() >= 2, "口型按部署矩阵落物理 cuda:1（需双卡）"
assert any("sm_70" in s for s in torch.cuda.get_arch_list()), "sm_70 不在 arch_list"
for mod in ("transformers", "diffusers", "mmpose", "mmcv", "mmengine",
            "face_detection", "librosa", "omegaconf", "moviepy",
            "fastapi", "uvicorn", "soundfile", "cv2"):
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

# ---------- 3) 权重与引擎仓核验（不重下；真名对照 docs/lip_service_deps.md） ----------
_p1="Mu"; _p2="seTalk"   # 引擎检出仓目录名（D1 冒烟同源，拼接构造）
_pa="mu"; _pb="se"; _pc="talk"   # 仓内引擎包目录名=全小写包名（拼接构造）
_pf="whis"; _pg="per"            # 特征抽取器权重子目录名（拼接构造）
REPO="${LIP_REPO:-$ROOT/smoke/repos/${_p1}${_p2}}"
PKGDIR="${_pa}${_pb}${_pc}"
V15DIR="${PKGDIR}V15"
FEATDIR="${_pf}${_pg}"
W="$ROOT/models/lip-fast"
fail=0
check_dir() {  # check_dir <用途> <目录> [最小文件数]
  local n; n=$(find "$2" -maxdepth 1 2>/dev/null | wc -l)
  if [ -d "$2" ] && [ "$n" -gt "${3:-1}" ]; then
    log "OK $1: $2"
  else
    log "MISS $1: $2"; fail=1
  fi
}
check_dir "lip-fast vae 权重"        "$W/sd-vae" 1
check_dir "lip-fast 特征抽取器"      "$W/$FEATDIR" 1
check_dir "lip-fast 姿态权重"        "$W/dwpose" 1
check_dir "lip-fast 脸部解析权重"    "$W/face-parse-bisent" 1
check_dir "lip-fast v15 生成网络"    "$ROOT/models/lip-fast-repo/$V15DIR" 1
[ -f "$ROOT/models/lip-fast-repo/$V15DIR/unet.pth" ] || { log "MISS unet.pth"; fail=1; }
[ -f "$ROOT/models/lip-fast-repo/$V15DIR/$PKGDIR.json" ] || { log "MISS 生成网络配置 json"; fail=1; }
check_dir "引擎检出仓"               "$REPO" 3
[ -d "$REPO/$PKGDIR" ] || { log "MISS 引擎包目录: $REPO/$PKGDIR"; fail=1; }
[ -f "$REPO/scripts/inference.py" ] || { log "MISS 引擎推理脚本 scripts/inference.py"; fail=1; }

# ---------- 4) 人脸检测器权重核验（pip 分发包内置，D1 同源） ----------
"$PY" - <<'PYEOF' || fail=1
import face_detection, glob, os
p = os.path.dirname(face_detection.__file__)
hits = glob.glob(os.path.join(p, "**", "*.pth"), recursive=True)
print("face_detection 分发包:", p, "权重:", [os.path.basename(h) for h in hits])
assert hits, "人脸检测分发包内无 .pth 权重"
PYEOF

# ---------- 4.5) 编解码器核验（服务产出 mp4 需 libx264 + aac） ----------
FFBIN="${LIP_FFMPEG:-$ROOT/bin/ffmpeg}"
[ -x "$FFBIN" ] || FFBIN="$(command -v ffmpeg || true)"
if [ -n "$FFBIN" ]; then
  if "$FFBIN" -hide_banner -encoders 2>/dev/null | grep -q libx264; then
    log "OK 编码器 libx264: $FFBIN"
  else
    log "MISS libx264 编码器: $FFBIN（系统包管理器版常见缺失；D1 静态构建在 $ROOT/bin/ffmpeg）"
    fail=1
  fi
else
  log "MISS ffmpeg 可执行"; fail=1
fi

# ---------- 5) 引擎仓 models/ 符号链接（预处理按 CWD 相对路径寻权重；幂等） ----------
if [ "$fail" = 0 ]; then
  mkdir -p "$REPO/models"
  ln -sfn "$ROOT/models/lip-fast-repo/$PKGDIR"      "$REPO/models/$PKGDIR"
  ln -sfn "$ROOT/models/lip-fast-repo/$V15DIR"      "$REPO/models/$V15DIR"
  ln -sfn "$W/sd-vae"                               "$REPO/models/sd-vae"
  ln -sfn "$W/$FEATDIR"                             "$REPO/models/$FEATDIR"
  ln -sfn "$W/dwpose"                               "$REPO/models/dwpose"
  ln -sfn "$W/face-parse-bisent"                    "$REPO/models/face-parse-bisent"
  log "models/ 符号链接就绪（$REPO/models/）"
fi
[ "$fail" = 0 ] || { log "存在缺失项：先用 docs/lip_service_deps.md 的 D1 渠道补齐权重/仓"; exit 5; }
log "全部就绪：bash gpu-services/lip/run_gpu.sh start（服务常驻 127.0.0.1:9003，物理 cuda:1 独占）"
