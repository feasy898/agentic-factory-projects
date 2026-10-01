#!/usr/bin/env bash
# V2-M4 生产沙箱: m3_sandbox.sh 同配方 (D-037/D-038) + 本轮 Wan 硬守卫 120 (D-072)。
# 用法: bash scripts/v2m4_sandbox.sh
set -euo pipefail
SB=/root/cradle_v2m4
mkdir -p "$SB/config" "$SB/workdir/logs" "$SB/output" "$SB/specs"
ln -sfn /root/cradle/models "$SB/models"
ln -sfn /root/cradle/templates "$SB/templates"
# assets 拷贝 (D-037: 资产进沙箱, 不与主仓共写)
rm -rf "$SB/assets"
mkdir -p "$SB/assets"
cp -r /root/cradle/assets/products /root/cradle/assets/scenes "$SB/assets/"
[ -d /root/cradle/assets/overlays ] && cp -r /root/cradle/assets/overlays "$SB/assets/"
[ -d /root/cradle/assets/evidence ] && cp -r /root/cradle/assets/evidence "$SB/assets/"
cp /root/cradle/config/thresholds_v2.yaml "$SB/config/"
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
  wan_candidates_total: 120   # D-072: 本轮硬守卫 (全局 200 - v1/M3 已用 ~78)
debug_model: wan     # 量产口径 (无 LTX 投影)
prod_model: wan_i2v_13b
prod_steps: 20       # D-030
prod_stylize_denoise: 0.3   # 仅 first_frame_i2v 车道受影响 (D-062)
evidence_denoise: 0.30      # evidence_transfer 重绘强度 (SPECS_V2 §5.4 / D-068)
YAML
echo "sandbox ready: $SB"
