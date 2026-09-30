#!/usr/bin/env bash
# M5 生产沙箱 (D-037 配方): CRADLE_ROOT=/root/cradle_m5, models/templates 只读软链, settings 生产口径。
# 用法: bash scripts/m5_sandbox.sh
set -euo pipefail
SB=/root/cradle_m5
mkdir -p "$SB/config" "$SB/workdir/logs" "$SB/output"
ln -sfn /root/cradle/models "$SB/models"
ln -sfn /root/cradle/templates "$SB/templates"
cat > "$SB/config/settings.yaml" <<'YAML'
project: cradle
device: cuda
dtype: fp16          # V100: fp16 only
hf_endpoint: https://hf-mirror.com
paths:
  assets: assets
  candidates: workdir/candidates
  gated: workdir/gated
  output: output
  db: workdir/cradle.sqlite3
budgets:
  image_api: 300
  vlm_api: 1500
  tts_api: 200
  asr_api: 200
  wan_candidates_total: 200
debug_model: wan     # M5 生产: 不再投影 LTX 调试卡
prod_model: wan_i2v_13b
prod_steps: 20       # D-030 实测 364.9s/条 <6min
prod_stylize_denoise: 0.3   # SPECS §5.3 首帧风格统一(M5 阶段0.4 生产开启)
YAML
echo "sandbox ready: $SB"
