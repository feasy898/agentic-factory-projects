#!/usr/bin/env bash
# setup_venv2.sh — 修复 venv pip(23.3.1 vendored cachecontrol 对阿里云 CDN 响应 TypeError 崩溃)
# 路径: get-pip.py 自带 wheel 重装 pip → 腾讯云镜像装 torch+diffusers 全家桶
set -x
export TMPDIR=/data/night/tmp
mkdir -p "$TMPDIR"
PY=/data/night/venv/bin/python3
INDEX_TENCENT=https://mirrors.cloud.tencent.com/pypi/simple
INDEX_ALIYUN=https://mirrors.aliyun.com/pypi/simple/

# 0. 自带 wheel 的 get-pip 重装 pip（不查 index，绕开 cachecontrol bug）
curl -sSL -o "$TMPDIR/get-pip.py" https://mirrors.aliyun.com/pypi/get-pip.py || exit 1
$PY "$TMPDIR/get-pip.py" -i "$INDEX_TENCENT" || { echo GETPIP_FAIL; exit 1; }
$PY -m pip --version || exit 1

# 1. torch 同 vllm venv 版本 (2.7.0+cu126, sm_70 含 V100S)
$PY -m pip install --no-input torch==2.7.0 torchvision==0.22.0 -i "$INDEX_TENCENT" && echo TORCH_OK || \
$PY -m pip install --no-input torch==2.7.0 torchvision==0.22.0 -i "$INDEX_ALIYUN" && echo TORCH_OK || { echo TORCH_FAIL; exit 1; }
$PY -c "import torch; print('TORCH_VER', torch.__version__, torch.version.cuda, torch.cuda.get_arch_list())"

# 2. diffusers 全家桶
$PY -m pip install --no-input "diffusers>=0.33.0" transformers==4.53.2 accelerate sentencepiece protobuf ftfy "numpy==2.2.6" imageio imageio-ffmpeg modelscope "huggingface_hub[cli]" -i "$INDEX_TENCENT" && echo PKGS_OK || \
$PY -m pip install --no-input "diffusers>=0.33.0" transformers==4.53.2 accelerate sentencepiece protobuf ftfy "numpy==2.2.6" imageio imageio-ffmpeg modelscope "huggingface_hub[cli]" -i "$INDEX_ALIYUN" && echo PKGS_OK || { echo PKGS_FAIL; exit 1; }
$PY -c "import diffusers, transformers, accelerate, numpy; print('PKGS_VER diffusers', diffusers.__version__, 'transformers', transformers.__version__, 'numpy', numpy.__version__)"
echo SETUP_DONE
