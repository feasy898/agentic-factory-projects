# lip 服务（:9003）依赖与部署实录 —— 真名对照（内部文档，不入公开仓）

> 本文件属 `docs/`（公开扫描豁免），登记 lip-fast 口型服务的真实上游名、
> 权重来源、依赖版本与部署实测。公开仓文本一律用中性名（lip-fast 等），
> 本文件是两者之间的对照表。建立：T16（2026-09-29）。

## 1. 真名对照

| 中性名（公开仓） | 真名（内部） | 版本/commit | 来源 |
|---|---|---|---|
| lip-fast | MuseTalk 1.5（main 分支） | `0a89dec`（`feat: update download_weights.bat (#372)`） | github.com/TMElyralab/MuseTalk，D1 冒烟检出 `/data/xdng/smoke/repos/MuseTalk`，MIT |
| lip-fast 生成网络 v15 | musetalkV15/unet.pth + musetalk.json | — | 官方权重（MIT），`/data/xdng/models/lip-fast-repo/musetalkV15/` |
| lip-fast 顶包资产 | musetalk/ + musetalkV15/（引擎包与配置） | — | `/data/xdng/models/lip-fast-repo/` |
| lip-fast VAE | sd-vae（stable-diffusion VAE） | — | `/data/xdng/models/lip-fast/sd-vae/` |
| lip-fast 特征抽取器 | whisper-tiny（特征器+encoder，AutoFeatureExtractor/WhisperModel 装载） | — | `/data/xdng/models/lip-fast/whisper/` |
| lip-fast 姿态 | dwpose（rtmpose-l wholebody 384x288，dw-ll_ucoco_384.pth） | — | `/data/xdng/models/lip-fast/dwpose/`，config 在引擎仓 `musetalk/utils/dwpose/` |
| lip-fast 脸部解析 | face-parse-bisent（BiSeNet + resnet18） | — | `/data/xdng/models/lip-fast/face-parse-bisent/` |
| 人脸检测 | face-detection pip 包（S³FD） | 0.2.2（包内 `detection/sfd/s3fd.pth`） | PyPI `face-detection`，权重已内置 |
| lip-pro（未部署） | LatentSync 1.6 | TBD-D1 | 权重未部署；服务对 mode=pro 恒回 503，客户端按 models.yaml fallback 降级 |

## 2. GPU 机依赖版本（主 venv /data/xdng/venv，2026-09-29 实测）

torch 2.5.1+cu118（sm_70 在 arch_list）/ transformers 4.52.1 / diffusers 0.30.2 /
mmpose 1.3.2 / mmcv 2.2.0（openmmlab cu118-torch2.4 索引，与 torch 2.5.1 实测兼容——
D1 冒烟同栈）/ mmengine 0.10.7 / face_detection 0.2.2 / librosa 0.11.0 /
omegaconf 2.3.1 / moviepy 2.1.2 / fastapi 0.141.1 / uvicorn 0.53.0 / soundfile 0.14.0 /
opencv 5.0.0 / python-multipart（T12 已装）。

安装史：`/data/xdng/smoke/prep_musetalk2.sh`（D1，constraints torch==2.4.1
+transformers==5.13.0——约束只约束了新装包，torch/transformers 未被降级，
实测保持 2.5.1+cu118 / 4.52.1）。

## 3. 编解码器坑（T16 实测）

系统包管理器 ffmpeg（/usr/bin/ffmpeg，8.0.1）**不带 libx264**（`ffmpeg -encoders |
grep libx264` 零命中，仅 h264_v4l2m2m）→ 服务端管道编码 `Popen(stdin).write` 立即
BrokenPipeError。解法：D1 冒烟同源的静态构建 `/data/xdng/bin/ffmpeg`（7.0.2-static，
johnvansickle，带 libx264+aac）经 `LIP_FFMPEG` 注入服务（run_gpu.sh 缺省注入；
setup_lip_service.sh 第 4.5 节核验编码器在位）。

## 4. 服务部署要点（gpu-services/lip/）

- **CWD 敏感**：引擎预处理模块 import 时即按 CWD 相对路径初始化姿态/检测权重
  （`./models/dwpose/...` 与 `./musetalk/utils/dwpose/...`）→ run_gpu.sh 先建
  models/ 符号链接（幂等）再 `cd $REPO` 拉起；service.py 启动即 `os.chdir(REPO_ROOT)`。
- **物理卡**：models.yaml `lip-fast.device=cuda:1` → run_gpu.sh
  `CUDA_VISIBLE_DEVICES=$LIP_GPU_ID`（缺省 1）独占式注入，进程内用逻辑 cuda:0；
  /health 同时上报 physical_device/logical_device。
- **显存互斥**：:9002 备选合成引擎（懒加载）与口型同落物理 cuda:1 → run_gpu.sh
  启动前探测 :9002 /health 已装载备选 B 即拒启（`LIP_ALLOW_SHARED=1` 显式解除）。
  T16 实测物理 #1 现状：mt 服务（:9004）16.3GB + lip-fast 7.6GB ≈ 24GB/32GB，
  余 8.1GB——256px fp16 推理余量充足；lip-pro（18GB 独占）上线前须清卡。
- **引擎装载**：fp16（`use_float16` 口径：pe/vae/unet 全 half），实测 28.1s 常驻。
- **逐帧对齐**：服务把上传音频硬裁/补到恰 `帧数/fps` 秒（引擎特征器按
  `floor(音频秒×fps)` 出帧，音频-视频等长是"输出帧数=输入帧数"的充要条件）。

## 5. T16 部署与自验收实录（2026-09-29）

- ssh 命令：`ssh dev-env-with-gpu`（公网宿主，203.0.113.41）；
  部署：`scp gpu-services/lip/{service.py,run_gpu.sh} dev-env-with-gpu:/data/xdng/services/lip/`
  + `scp gpu/setup_lip_service.sh dev-env-with-gpu:/data/xdng/`；
  核验：`bash /data/xdng/setup_lip_service.sh`（全 OK）；启动：
  `bash /data/xdng/services/lip/run_gpu.sh start`（引擎装载 28.1s）。
- 隧道：`TUNNEL_LOCAL_PORT=9003 TUNNEL_REMOTE_PORT=9003 bash ops/tunnel_gpu.sh start`
  （+ keepalive 同端口）。
- 自验收（tests/test_m10_lipsync.py::test_real_run_2s_window）：4s 正脸近景样本
  （公版人像 cover 裁切+缓慢变焦 540x960@25fps=100 帧；配音轨前 2s 人声带通信号
  后 2s 静音），C6 窗 [0,2)——服务真跑 50 帧（单句按台词最长前 10% 计划升
  lip-pro → 服务 503 → models.yaml fallback 降级 lip-fast 真跑，attempts 留痕），
  回贴合成自验：非口型帧（50 帧）raw yuv sha256 逐帧字节级不变、口型窗 50 帧
  全异、嘴区 MAD 达标（阈值 3.0 灰阶）。实测数字见当日报告与 09_lip/lip_report.en.json。
- RTF 口径：服务端 total/时长 如实回传（含预处理）；RTF ≤1.0 的 M10 GPU 冻结线
  归 D5 批次 10 镜 eval（scripts/eval_m10_gpu.sh，未在本批范围）。

## 6. 已知边界

- 引擎逐帧预处理（dwpose batch=1）为当前耗时大头；同镜多句共用坐标
  （use_saved_coord 思路）列优化项，未在本批。
- 服务单进程推理锁串行化；多窗并发请求排队执行。
- 全部帧无脸 → 422 如实拒绝（不伪造口型）；偶发丢检帧以最近有效框续用
  （n_placeholder_fixed 计数入响应与报告）。
