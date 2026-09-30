#!/usr/bin/env bash
# setup_venv.sh — /data/night/venv: torch 与 vllm venv 同版本(2.7.0+cu126, sm_70 含 V100S) + 视频生成全家桶
# 实测: 清华镜像对本机 403, 改用阿里云 https://mirrors.aliyun.com/pypi/simple/ (200 OK)
set -x
export TMPDIR=/data/night/tmp
mkdir -p "$TMPDIR"
PY=/data/night/venv/bin/python3
PIP="$PY -m pip"
INDEX=https://mirrors.aliyun.com/pypi/simple/

# 0. pip 自身修复/升级
$PY -m ensurepip --upgrade 2>&1 | tail -1 || true
$PIP install --no-input --upgrade pip -i "$INDEX" 2>&1 | tail -2 || true
$PIP --version || exit 1

# 1. torch 同版本（vllm venv 实测 torch==2.7.0+cu126, arch 含 sm_70）
$PIP install torch==2.7.0 torchvision==0.22.0 -i "$INDEX" || { echo TORCH_FAIL; exit 1; }
$PY -c "import torch; print('TORCH_OK', torch.__version__, torch.version.cuda, torch.cuda.get_arch_list())"

# 2. diffusers 全家桶
$PIP install "diffusers>=0.33.0" transformers==4.53.2 accelerate sentencepiece protobuf ftfy "numpy==2.2.6" imageio imageio-ffmpeg modelscope "huggingface_hub[cli]" -i "$INDEX" || { echo PKGS_FAIL; exit 1; }
$PY -c "import diffusers, transformers, accelerate, numpy; print('PKGS_OK diffusers', diffusers.__version__, 'transformers', transformers.__version__, 'numpy', numpy.__version__)"
echo SETUP_DONE
