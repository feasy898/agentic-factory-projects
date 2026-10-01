# PROGRESS
- 墙钟预算: 开工 2026-09-08 00:52 (服务器时间) → 硬停 2026-09-13 00:52 (≤5天,到点即停写终报)

## M0 完成 (2026-09-08 00:52)
- SPECS.md 落盘(142行/12715B,与本地主副本一致), 目录骨架, git init, 2 commits
- 服务器实测: V100S-PCIE-32GB 空闲(0MiB/0%), 盘 83G avail, Python 3.12.3, 62G RAM, 无 tmux server

## M1 (env + code 双线并行)
- [env]  子代理 M1-ENV: **完成 (2026-09-08 03:2x)**，产物清单如下
  - venv `~/cradle/.venv` (Python 3.12.3): torch **2.4.1+cu121** + torchvision 0.19.1+cu121（aliyun pytorch-wheels curl 直连 + 本地轮子安装，见 D-008）；diffsynth **1.1.9**(已打 patchify 补丁, D-009)、diffusers 0.33.1、transformers 4.49.0、accelerate 1.14.0、peft 0.14.0、open_clip 3.3.0、ultralytics 8.4.142、openai-whisper 20250625、edge-tts 7.2.8、opencv-python-headless 4.10.0.84、imageio 2.37.4、modelscope 1.39.1、safetensors/sentencepiece/protobuf/einops/pyyaml/pytest/huggingface_hub
  - 系统包: ffmpeg 6.1.1、fonts-noto-cjk、libgl1/libglib2.0
  - **Volta 自查 PASS** → `reports/milestones/m1_volta_check.txt`: cap==(7,0)、fp16 matmul 前向 OK、SDPA fp16 前向 OK、2048³ fp16 matmul **0.26ms = 66.45 TFLOPS**
  - 模型落盘 (~46G, curl 断点续传, 源策略见 D-008):
    - `models/ltx-video-2b/`: LTX-Video 2B v0.9.x diffusers 布局 fp32 (transformer 7.7G + vae 1.7G，加载转 fp16) + FLUX.1-dev T5-XXL **fp16** 9.5G (替代仓内 19G fp32 T5, D-007) + tokenizer/configs
    - `models/wan-fun-1.3b-inp/`: **PAI/Wan2.1-Fun-1.3B-InP 19.8G** (umt5 T5 11.4G + CLIP 图像编码器 4.8G + DiT 3.1G + Wan2.1 VAE 0.5G)；规格主选 Wan2.1-I2V-1.3B 不存在（HF 401 证实），决策见 **D-006**
    - `models/sdxl-base-1.0-fp16/`: SDXL base fp16 变体 6.9G (diffusers 布局含 model_index/scheduler)
    - `models/clip/ViT-L-14.pt` 0.93G (openai 原版, D-010)、`models/whisper/small.pt` 0.46G、`models/yolo/yolov8n.pt` 6.5M
    - 磁盘巡检全程 D-001 纪律执行，最终 62G used / **33G avail** (≥20G 红线守住)
  - **冒烟 A (LTX) PASS** → `reports/milestones/m1_ltx_smoke.{mp4,png,json}`: 384×512、33帧@24fps=1.375s、steps15、guidance3.0、seed42、纯 fp16（VAE 未触发降级）；生成 **3.1s**、峰值显存 **16.2GB**、gray_mean 60.8/std 30.7
  - **冒烟 B (SDXL→Wan I2V) PASS**: SDXL 首帧 `reports/milestones/m1_wan_first_frame.png`（副本 `assets/products/maodu_01.png`；480×832、30步、4.4s、峰值 8.0GB）→ Wan Fun-InP `reports/milestones/m1_wan_smoke.{mp4,png,json}`: **480×832、81帧@16fps=5.06s、steps20、cfg5.0、seed42**、生成 **364.6s**、峰值显存 **16.9GB**、纯 fp16 一次通过、首帧保真目检≈逐像素一致
  - 小件功能验证 (`workdir/logs/08b_verify_cleanup.log`): CLIP ViT-L/14 前向 norm=1.0；whisper-small GPU 转写；yolov8n 推理 80 类
- [code] 子代理 M2-CODE: 管线代码骨架 + CPU 可跑单测 (后台, 不碰 GPU)
