#!/usr/bin/env bash
# setup_venv3.sh — pip 已修复(26.2.1), 装 torch==2.7.0 (同 vllm venv, +cu126 sm_70) + diffusers 全家桶
set -x
export TMPDIR=/data/night/tmp
mkdir -p "$TMPDIR"
PY=/data/night/venv/bin/python3
IDX=https://mirrors.cloud.tencent.com/pypi/simple
$PY -m pip --version

# 1. torch 同 vllm venv 版本
$PY -m pip install --no-input torch==2.7.0 torchvision==0.22.0 -i "$IDX" && echo TORCH_OK || { echo TORCH_FAIL; exit 1; }
$PY -c "import torch; print('TORCH_VER', torch.__version__, torch.version.cuda, torch.cuda.get_arch_list())"

# 2. diffusers 全家桶
$PY -m pip install --no-input "diffusers>=0.33.0" transformers==4.53.2 accelerate sentencepiece protobuf ftfy "numpy==2.2.6" imageio imageio-ffmpeg modelscope "huggingface_hub[cli]" -i "$IDX" && echo PKGS_OK || { echo PKGS_FAIL; exit 1; }
$PY -c "import diffusers, transformers, accelerate, numpy; print('PKGS_VER diffusers', diffusers.__version__, 'transformers', transformers.__version__, 'numpy', numpy.__version__)"
echo SETUP_DONE
