# tests/fixtures 说明

- `portrait_pd.jpg` —— 马克·吐温坐像（摄影 A.F. Bradley，约 1907），**公有领域**
  （Wikimedia Commons `Mark_Twain_by_AF_Bradley_(high_quality).jpg`，605×806 原件
  缩放至 480px 宽）。用作 M5 facemesh 组件 eval 的真人人像 fixture（合成图案
  无法被人脸检测器检出，必须真实人脸）。
- `fbank_ref.npy` —— kaldi 口径 fbank 数值回归参照（float32 [398, 80]）：
  由 GPU 机 venv-asr 的 torchaudio 2.5.1 参照实现
  （`torchaudio.compliance.kaldi.fbank(wav.unsqueeze(0), num_mel_bins=80)`）
  对 `np.random.default_rng(7).standard_normal(4*16000)` 波形计算所得；
  本仓 `_voxdia_net.kaldi_fbank` 与之对拍 max_abs < 0.02（T7 实测 2.1e-4）。
  参照实现环境：anolis-gpu-01（`/data/xdng/venv-asr`）。
