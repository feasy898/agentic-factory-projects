#!/usr/bin/env bash
# T3 env round 3: numpy 1.26.4 (mmcv/xtcocotools ABI) + torch 2.5.1+cu118 (VoxCPM enable_gqa)
set -uo pipefail
source /data/xdng/smoke/env.sh
LOG=/data/xdng/smoke/logs/upgrade_env.log
exec >>"$LOG" 2>&1
echo "=== upgrade_env start $(date -Is) ==="
P="$VENV/bin/pip"

$P install -q "numpy==1.26.4" 2>&1 | grep -E 'Successfully installed|ERROR' | tail -1
timeout 1500 $P install torch==2.5.1+cu118 torchaudio==2.5.1+cu118 torchvision==0.20.1+cu118 --index-url https://download.pytorch.org/whl/cu118 2>&1 | grep -E 'Successfully installed|ERROR' | tail -2

echo "--- verification ---"
$VENV/bin/python -c "import numpy, torch, torchvision, torchaudio; print('numpy', numpy.__version__, '| torch', torch.__version__, torch.cuda.is_available(), '| tv', torchvision.__version__)" 2>&1 | tail -1
$VENV/bin/python -c "import torch; print('arch list:', torch.cuda.get_arch_list()[:6]); x=torch.randn(2,4,8,device='cuda',dtype=torch.half); import torch.nn.functional as F; y=F.scaled_dot_product_attention(x,x,x,enable_gqa=True); print('enable_gqa sdpa ok', y.shape)" 2>&1 | tail -2
for m in mmcv mmpose cv2 librosa; do
  timeout 30 $VENV/bin/python -c "import $m" 2>/dev/null && echo "ok $m" || echo "FAIL $m"
done
timeout 60 $VENV/bin/python -c "import sys; sys.path.insert(0,'/data/xdng/smoke/repos/index-tts'); from indextts.infer_v2_5 import IndexTTS2; print('indextts import ok')" 2>&1 | tail -1
timeout 60 $VENV/bin/python -c "from voxcpm import VoxCPM; print('voxcpm import ok')" 2>&1 | tail -1
echo "=== upgrade_env done $(date -Is) ==="
