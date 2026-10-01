#!/usr/bin/env bash
# M1-ENV step 04: download all models (resumable curl), disk-checked
set -x
M=~/cradle/models
mkdir -p $M/{ltx-video-2b/{scheduler,tokenizer,text_encoder,vae,transformer,flux_t5},sdxl-base-1.0-fp16/{unet,vae,text_encoder,text_encoder_2,tokenizer,tokenizer_2,scheduler},wan-fun-1.3b-inp/google/umt5-xxl,wan-fun-1.3b-inp/xlm-roberta-large,clip,yolo}
LOG=~/cradle/workdir/logs/04_models.log
exec >> $LOG 2>&1

MS="https://modelscope.cn/api/v1/models"
HF="https://hf-mirror.com"

dl() { # dl <dst> <url>
  local dst=$1 url=$2
  if [ -f "$dst" ] && [ -s "$dst" ]; then echo "[skip] $dst exists"; return 0; fi
  echo "[$(date +%T)] GET $url -> $dst"
  curl -sS -L -C - --retry 3 --retry-delay 5 -o "$dst" "$url"
  local rc=$?
  echo "[$(date +%T)] rc=$rc size=$(stat -c%s "$dst" 2>/dev/null || echo 0) $dst"
  return $rc
}

diskcheck() {
  local avail=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
  echo "[diskcheck] avail=${avail}G"
  if [ "$avail" -lt 20 ]; then
    echo "!!! DISK FLOOR BREACH (<20G) — STOPPING per D-001"
    exit 42
  fi
}

# ---------- 1) LTX-Video 2B (single-file fp16 DiT+VAE) + tiny configs + FLUX T5-XXL fp16 ----------
dl $M/ltx-video-2b/ltx-video-2b-v0.9.1.safetensors "$MS/AI-ModelScope/LTX-Video/repo?FilePath=ltx-video-2b-v0.9.1.safetensors&Revision=master"
diskcheck
dl $M/ltx-video-2b/model_index.json "$HF/Lightricks/ltx-video-2b-v0.9/resolve/main/model_index.json"
dl $M/ltx-video-2b/scheduler/scheduler_config.json "$HF/Lightricks/ltx-video-2b-v0.9/resolve/main/scheduler/scheduler_config.json"
dl $M/ltx-video-2b/transformer/config.json "$MS/AI-ModelScope/LTX-Video/repo?FilePath=transformer/config.json&Revision=master"
dl $M/ltx-video-2b/vae/config.json "$MS/AI-ModelScope/LTX-Video/repo?FilePath=vae/config.json&Revision=master"
dl $M/ltx-video-2b/text_encoder/config.json "$MS/AI-ModelScope/LTX-Video/repo?FilePath=text_encoder/config.json&Revision=master"
for f in spiece.model tokenizer_config.json added_tokens.json special_tokens_map.json; do
  dl $M/ltx-video-2b/tokenizer/$f "$MS/AI-ModelScope/LTX-Video/repo?FilePath=tokenizer/$f&Revision=master"
done
# FLUX T5-XXL fp16 (used as LTX text encoder; arch google/t5-v1_1-xxl)
dl $M/ltx-video-2b/flux_t5/model-00001-of-00002.safetensors "$MS/AI-ModelScope/FLUX.1-dev/repo?FilePath=text_encoder_2/model-00001-of-00002.safetensors&Revision=master"
dl $M/ltx-video-2b/flux_t5/model-00002-of-00002.safetensors "$MS/AI-ModelScope/FLUX.1-dev/repo?FilePath=text_encoder_2/model-00002-of-00002.safetensors&Revision=master"
dl $M/ltx-video-2b/flux_t5/model.safetensors.index.json "$MS/AI-ModelScope/FLUX.1-dev/repo?FilePath=text_encoder_2/model.safetensors.index.json&Revision=master"
dl $M/ltx-video-2b/flux_t5/config.json "$MS/AI-ModelScope/FLUX.1-dev/repo?FilePath=text_encoder_2/config.json&Revision=master"
diskcheck

# ---------- 2) SDXL base fp16 (diffusers layout) ----------
B=$MS/AI-ModelScope/stable-diffusion-xl-base-1.0/repo
dl $M/sdxl-base-1.0-fp16/model_index.json "$HF/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/model_index.json"
dl $M/sdxl-base-1.0-fp16/scheduler/scheduler_config.json "$HF/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/scheduler/scheduler_config.json"
dl $M/sdxl-base-1.0-fp16/unet/config.json "$B?FilePath=unet/config.json&Revision=master"
dl $M/sdxl-base-1.0-fp16/vae/config.json "$B?FilePath=vae/config.json&Revision=master"
dl $M/sdxl-base-1.0-fp16/text_encoder/config.json "$B?FilePath=text_encoder/config.json&Revision=master"
dl $M/sdxl-base-1.0-fp16/text_encoder_2/config.json "$B?FilePath=text_encoder_2/config.json&Revision=master"
for f in tokenizer/tokenizer_config.json tokenizer/vocab.json tokenizer/merges.txt tokenizer/special_tokens_map.json tokenizer_2/tokenizer_config.json tokenizer_2/vocab.json tokenizer_2/merges.txt tokenizer_2/special_tokens_map.json; do
  dl $M/sdxl-base-1.0-fp16/$f "$B?FilePath=$f&Revision=master"
done
dl $M/sdxl-base-1.0-fp16/unet/diffusion_pytorch_model.fp16.safetensors "$B?FilePath=unet/diffusion_pytorch_model.fp16.safetensors&Revision=master"
diskcheck
dl $M/sdxl-base-1.0-fp16/text_encoder/model.fp16.safetensors "$B?FilePath=text_encoder/model.fp16.safetensors&Revision=master"
dl $M/sdxl-base-1.0-fp16/text_encoder_2/model.fp16.safetensors "$B?FilePath=text_encoder_2/model.fp16.safetensors&Revision=master"
dl $M/sdxl-base-1.0-fp16/vae/diffusion_pytorch_model.fp16.safetensors "$B?FilePath=vae/diffusion_pytorch_model.fp16.safetensors&Revision=master"
diskcheck

# ---------- 3) Wan2.1-Fun-1.3B-InP (I2V production model) ----------
W=$MS/PAI/Wan2.1-Fun-1.3B-InP/repo
dl $M/wan-fun-1.3b-inp/models_t5_umt5-xxl-enc-bf16.pth "$W?FilePath=models_t5_umt5-xxl-enc-bf16.pth&Revision=master"
diskcheck
dl $M/wan-fun-1.3b-inp/models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth "$W?FilePath=models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth&Revision=master"
dl $M/wan-fun-1.3b-inp/diffusion_pytorch_model.safetensors "$W?FilePath=diffusion_pytorch_model.safetensors&Revision=master"
dl $M/wan-fun-1.3b-inp/Wan2.1_VAE.pth "$W?FilePath=Wan2.1_VAE.pth&Revision=master"
for f in tokenizer_config.json special_tokens_map.json spiece.model tokenizer.json; do
  dl $M/wan-fun-1.3b-inp/google/umt5-xxl/$f "$W?FilePath=google/umt5-xxl/$f&Revision=master"
done
dl $M/wan-fun-1.3b-inp/xlm-roberta-large/tokenizer.json "$W?FilePath=xlm-roberta-large/tokenizer.json&Revision=master"
dl $M/wan-fun-1.3b-inp/xlm-roberta-large/sentencepiece.bpe.model "$W?FilePath=xlm-roberta-large/sentencepiece.bpe.model&Revision=master"
diskcheck

# ---------- 4) CLIP ViT-L/14 openai + yolov8n ----------
dl $M/clip/ViT-L-14.pt "https://openaipublic.azureedge.net/clip/models/b8cca3fd41ae0c99ba7e8951adf17d267cdb84cd88be6f7c2e0eca1737a03836/ViT-L-14.pt"
dl $M/yolo/yolov8n.pt "$MS/Ultralytics/YOLOv8/repo?FilePath=yolov8n.pt&Revision=master"

# ---------- 5) whisper small.pt via openai-whisper loader ----------
~/cradle/.venv/bin/python - <<'EOF'
import whisper
p = whisper.load_model("small", download_root="/root/cradle/models/whisper")
print("whisper small at", p.dims)
EOF

echo "ALL_MODELS_DONE"
df -h /
