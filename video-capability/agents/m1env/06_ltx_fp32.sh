#!/usr/bin/env bash
# M1-ENV step 06: fetch LTX diffusers-layout fp32 transformer + vae (self-consistent pair)
set -x
MS="https://modelscope.cn/api/v1/models/AI-ModelScope/LTX-Video/repo"
M=~/cradle/models/ltx-video-2b
dl() { local dst=$1 url=$2; if [ -f "$dst" ] && [ -s "$dst" ]; then echo "[skip] $dst"; return 0; fi
  curl -sS -L -C - --retry 3 --retry-delay 5 -o "$dst" "$url"; echo "rc=$? $(stat -c%s "$dst") $dst"; }
dl $M/transformer/diffusion_pytorch_model-00001-of-00002.safetensors "$MS?FilePath=transformer/diffusion_pytorch_model-00001-of-00002.safetensors&Revision=master"
dl $M/transformer/diffusion_pytorch_model-00002-of-00002.safetensors "$MS?FilePath=transformer/diffusion_pytorch_model-00002-of-00002.safetensors&Revision=master"
dl $M/transformer/diffusion_pytorch_model.safetensors.index.json "$MS?FilePath=transformer/diffusion_pytorch_model.safetensors.index.json&Revision=master"
dl $M/vae/diffusion_pytorch_model.safetensors "$MS?FilePath=vae/diffusion_pytorch_model.safetensors&Revision=master"
echo LTX_FP32_DONE
df -h / | tail -1
