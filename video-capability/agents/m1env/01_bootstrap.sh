#!/usr/bin/env bash
# M1-ENV step 01: system packages + venv
set -x
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3.12-venv ffmpeg fonts-noto-cjk libgl1 libglib2.0-0 tmux
echo "=== versions ==="
ffmpeg -version | head -1
fc-list :lang=zh | head -3
mkdir -p ~/cradle/workdir/logs ~/cradle/reports/milestones ~/cradle/scripts
python3 -m venv ~/cradle/.venv
~/cradle/.venv/bin/pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/
~/cradle/.venv/bin/python --version
echo "STEP01_DONE rc=$?"
