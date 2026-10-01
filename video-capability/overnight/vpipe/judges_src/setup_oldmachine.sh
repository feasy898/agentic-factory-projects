#!/usr/bin/env bash
# setup_oldmachine.sh — 在旧 V100 机(203.0.113.40)上搭建 judge 运行环境。
# 背景：anolis-gpu-01 卡1 被生产 xdng 服务(asr/tts/lip/llm+keepalive)占 28.9G/32G，
#       卡0 是生产 vLLM 红线；旧机 GPU 全空(0MiB)但磁盘仅 ~9.6G →
#       权重经 sshfs 从 anolis 只读挂载，venv 本地按精确版本重建(Python 3.12)。
# 由 root 运行。产物：/root/judgenight/{scripts,logs,results,frames,clips,src,smoke_clips}
set -uo pipefail
ROOT=/root/judgenight
ANOLIS=203.0.113.41
ANOLIS_USER=anuser
KEY=$ROOT/.m2m_key
IDX="https://mirrors.cloud.tencent.com/pypi/simple/"
SSHOPT="-i $KEY -o ControlPath=none -o StrictHostKeyChecking=no -o ServerAliveInterval=15 -o ConnectTimeout=20"
LOG=$ROOT/logs/setup.log
mkdir -p $ROOT/{scripts,logs,results,frames,clips,src,smoke_clips} /mnt/nightmodels
exec > >(tee -a $LOG) 2>&1
step(){ echo "[$(date '+%F %T')] $*"; }
fail(){ echo "[$(date '+%F %T')] SETUP_FAILED: $*"; echo "$*" > $ROOT/logs/setup_rc; exit 1; }

step "0/8 precheck"
[ -f $KEY ] || fail "m2m key missing at $KEY (scp it from windev first)"
chmod 600 $KEY
df -h / | tail -1

step "1/8 mount anolis:/data/night/models -> /mnt/nightmodels (ro sshfs)"
if ! mountpoint -q /mnt/nightmodels; then
  umount /mnt/nightmodels 2>/dev/null
  sshfs -o ro,kernel_cache,attr_timeout=600,entry_timeout=600,reconnect,dir_cache=yes \
    -o ssh_command="ssh $SSHOPT" \
    $ANOLIS_USER@$ANOLIS:/data/night/models /mnt/nightmodels \
    || fail "sshfs mount failed"
fi
ls /mnt/nightmodels/Qwen3.5-4B >/dev/null 2>&1 || fail "sshfs mounted but Qwen3.5-4B not visible"
step "sshfs OK: $(ls /mnt/nightmodels | tr '\n' ' ')"

step "2/8 pull repos + golden clips from anolis (tar over ssh; anolis has no rsync)"
ssh $SSHOPT $ANOLIS_USER@$ANOLIS \
  "cd /data/night/src && tar cf - --exclude='__pycache__' --exclude='*.tar.gz' OmniJev-main" \
  | (cd $ROOT/src && tar xf -) || fail "pull OmniJev-main"
ssh $SSHOPT $ANOLIS_USER@$ANOLIS \
  "cd /data/night/src && tar cf - --exclude='__pycache__' Visual-Jev-main" \
  | (cd $ROOT/src && tar xf -) || fail "pull Visual-Jev-main"
ssh $SSHOPT $ANOLIS_USER@$ANOLIS "cd /data/night/golden/clips && tar cf - ." \
  | (cd $ROOT/clips && tar xf -) || fail "pull golden clips"
N_CLIPS=$(ls $ROOT/clips/*.mp4 2>/dev/null | wc -l)
[ "$N_CLIPS" -eq 40 ] || fail "expected 40 golden clips, got $N_CLIPS"
du -sh $ROOT/src/* $ROOT/clips
step "repos+clips OK (40 clips)"

step "3/8 python env check"
python3 --version
python3 -m venv --help >/dev/null 2>&1 || { apt-get install -y -qq python3-venv python3-pip >>$LOG 2>&1 || fail "no venv module and apt install failed"; }

build_venv(){  # $1=venvpath
  local V=$1
  [ -x $V/bin/python ] && $V/bin/python -c "import torch" 2>/dev/null && { step "venv exists: $V"; return 0; }
  rm -rf $V
  python3 -m venv $V || fail "venv create $V"
  $V/bin/pip install -q --no-cache-dir -i $IDX --timeout 120 --retries 8 \
    torch==2.7.0 torchvision==0.22.0 || fail "torch install $V"
  $V/bin/python -c "import torch; assert torch.cuda.is_available(), 'cuda unavailable'" || fail "cuda check $V"
}

step "4/8 build venv-judge (torch 2.7.0 base)"
df / | tail -1
build_venv $ROOT/venvs/venv-judge

step "5/8 install judge deps (transformers 5.17 / peft 0.21 ...)"
$ROOT/venvs/venv-judge/bin/pip install -q --no-cache-dir -i $IDX --timeout 120 --retries 8 \
  transformers==5.17.0 peft==0.21.0 "safetensors>=0.8.0" tokenizers==0.23.2 \
  "huggingface_hub[cli]" qwen-vl-utils opencv-python-headless einops matplotlib \
  accelerate "numpy==2.2.6" av || fail "judge deps"
$ROOT/venvs/venv-judge/bin/python - <<'PYEOF' || fail "judge import check"
import torch, transformers, peft, PIL, numpy
print("torch", torch.__version__, "cuda", torch.cuda.is_available(),
      "| transformers", transformers.__version__, "| peft", peft.__version__)
x = torch.randn(64, 64, device="cuda"); y = (x @ x).sum().item()
print("gpu matmul OK:", round(y, 2))
PYEOF
find $ROOT/venvs/venv-judge -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
df / | tail -1

step "6/8 OmniJev single-clip smoke (validates torch+sshfs-weight-load+repo+adapter)"
cp $ROOT/clips/golden_001.mp4 $ROOT/smoke_clips/ 2>/dev/null || fail "copy smoke clip"
CUDA_VISIBLE_DEVICES=0 $ROOT/venvs/venv-judge/bin/python $ROOT/scripts/omnijev_batch.py \
  --clips-dir $ROOT/smoke_clips \
  --out-dir $ROOT/results/judges/omnijev_smoke \
  --raw-dir $ROOT/results/judges/omnijev_smoke/raw \
  --src-dir $ROOT/src/OmniJev-main \
  --ckpt /mnt/nightmodels/OmniJev-4B-v1.1 \
  --base /mnt/nightmodels/Qwen3.5-4B \
  --meta $ROOT/results/judges/omnijev_smoke/run_metadata.json \
  || fail "omnijev smoke"
[ -f $ROOT/results/judges/omnijev_smoke/golden_001.json ] || fail "smoke output missing"
step "smoke output: $(cat $ROOT/results/judges/omnijev_smoke/golden_001.json | head -c 400)"

step "7/8 Visual-Jev single-clip smoke"
CUDA_VISIBLE_DEVICES=0 $ROOT/venvs/venv-judge/bin/python $ROOT/scripts/visualjev_batch.py \
  --clips-dir $ROOT/smoke_clips \
  --out-dir $ROOT/results/judges/visualjev_smoke \
  --raw-dir $ROOT/results/judges/visualjev_smoke/raw \
  --code-dir $ROOT/src/Visual-Jev-main/code \
  --frames-dir $ROOT/frames/visualjev_smoke \
  --base /mnt/nightmodels/Qwen3-VL-4B-Instruct \
  --adapter /mnt/nightmodels/visual-jev-4b-answer-sft \
  --meta $ROOT/results/judges/visualjev_smoke/run_metadata.json \
  || fail "visualjev smoke"
[ -f $ROOT/results/judges/visualjev_smoke/golden_001.json ] || fail "vj smoke output missing"
step "smoke output: $(cat $ROOT/results/judges/visualjev_smoke/golden_001.json | head -c 400)"

step "8/8 setup done — full runs via run_judges_full.sh (vc3 venv built there)"
echo "SETUP_OK" > $ROOT/logs/setup_rc
