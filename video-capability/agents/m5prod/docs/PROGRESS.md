# PROGRESS
- 墙钟预算: 开工 2026-09-08 00:52 (服务器时间) → 硬停 2026-09-13 00:52 (≤5天,到点即停写终报)

## M0 完成 (2026-09-08 00:52)
- SPECS.md 落盘(142行/12715B,与本地主副本一致), 目录骨架, git init, 2 commits
- 服务器实测: V100S-PCIE-32GB 空闲(0MiB/0%), 盘 83G avail, Python 3.12.3, 62G RAM, 无 tmux server

## M1 进行中 (env + code 双线并行)
- [env]  子代理 M1-ENV: **完成 (2026-09-08 03:2x)**，产物清单如下
  - venv `~/cradle/.venv` (Python 3.12.3): torch **2.4.1+cu121** + torchvision 0.19.1+cu121（aliyun pytorch-wheels curl 直连 + 本地轮子安装，见 D-008）；diffsynth **1.1.9**(已打 patchify 补丁, D-022)、diffusers 0.33.1、transformers 4.49.0、accelerate 1.14.0、peft 0.14.0、open_clip 3.3.0、ultralytics 8.4.142、openai-whisper 20250625、edge-tts 7.2.8、opencv-python-headless 4.10.0.84、imageio 2.37.4、modelscope 1.39.1、safetensors/sentencepiece/protobuf/einops/pyyaml/pytest/huggingface_hub
  - 系统包: ffmpeg 6.1.1、fonts-noto-cjk、libgl1/libglib2.0
  - **Volta 自查 PASS** → `reports/milestones/m1_volta_check.txt`: cap==(7,0)、fp16 matmul 前向 OK、SDPA fp16 前向 OK、2048³ fp16 matmul **0.26ms = 66.45 TFLOPS**
  - 模型落盘 (~46G, curl 断点续传, 源策略见 D-021):
    - `models/ltx-video-2b/`: LTX-Video 2B v0.9.x diffusers 布局 fp32 (transformer 7.7G + vae 1.7G，加载转 fp16) + FLUX.1-dev T5-XXL **fp16** 9.5G (替代仓内 19G fp32 T5, D-007) + tokenizer/configs
    - `models/wan-fun-1.3b-inp/`: **PAI/Wan2.1-Fun-1.3B-InP 19.8G** (umt5 T5 11.4G + CLIP 图像编码器 4.8G + DiT 3.1G + Wan2.1 VAE 0.5G)；规格主选 Wan2.1-I2V-1.3B 不存在（HF 401 证实），决策见 **D-019**
    - `models/sdxl-base-1.0-fp16/`: SDXL base fp16 变体 6.9G (diffusers 布局含 model_index/scheduler)
    - `models/clip/ViT-L-14.pt` 0.93G (openai 原版, D-010)、`models/whisper/small.pt` 0.46G、`models/yolo/yolov8n.pt` 6.5M
    - 磁盘巡检全程 D-001 纪律执行，最终 62G used / **33G avail** (≥20G 红线守住)
  - **冒烟 A (LTX) PASS** → `reports/milestones/m1_ltx_smoke.{mp4,png,json}`: 384×512、33帧@24fps=1.375s、steps15、guidance3.0、seed42、纯 fp16（VAE 未触发降级）；生成 **3.1s**、峰值显存 **16.2GB**、gray_mean 60.8/std 30.7
  - **冒烟 B (SDXL→Wan I2V) PASS**: SDXL 首帧 `reports/milestones/m1_wan_first_frame.png`（副本 `assets/products/maodu_01.png`；480×832、30步、4.4s、峰值 8.0GB）→ Wan Fun-InP `reports/milestones/m1_wan_smoke.{mp4,png,json}`: **480×832、81帧@16fps=5.06s、steps20、cfg5.0、seed42**、生成 **364.6s**、峰值显存 **16.9GB**、纯 fp16 一次通过、首帧保真目检≈逐像素一致
  - 小件功能验证 (`workdir/logs/08b_verify_cleanup.log`): CLIP ViT-L/14 前向 norm=1.0；whisper-small GPU 转写；yolov8n 推理 80 类
- [code] 子代理 M2-CODE: 管线代码骨架 + CPU 可跑单测 (后台, 不碰 GPU)
## M2-CODE 完成 (2026-09-08, 管线代码骨架 + CPU 单测)
- [code] 全管线代码落位 src/: schema(镜头卡/叙事模板校验+风险表强制)、db(SQLite WAL+状态机非法迁移拒绝+只新增迁移)、api/(统一适配器: API优先+重试1次切本地+预算守卫 300/1500/200/200; 本地实现 SDXL img2img/CLIP启发式/edge-tts/whisper 均 lazy import)、gates/(G1 ffprobe+signalstats 全黑全白帧; G2/G5 按 vlm_prompt.txt 契约, 非法JSON重试1次→borderline 0.5 parse_failed; G3/G4 CLIP 可注入, RAFT 留桩; G6 字幕逐字+CER 自实现)、gen/(ltx 384×512/≤2s/steps≤15 硬校验; wan 480p/81帧/steps20-30+首帧img2img denoise0.2-0.35; kenburns 超采样4×+zoompan 线性z/居中x/y, 4种motion)、route(全分支: accept/retry钩子加强negative+guidance-0.5/fallback校验asset/blocked)、compose(硬切trim+concat、ASS(Noto Sans CJK)烧录、TTS时间轴对齐、BGM sidechaincompress ≈-12dB ducking、CTA/字卡=程序渲染纯色段、数字只进字幕的代码级强制、H.264 1088×1920/横版备选)、orchestrator(状态机推进+不动点run_once+recover断点续跑+Wan≤200守卫+nohup日志)、cli(initdb/status/ingest/run/compose/report)
- [tpl] templates/: 3 叙事模板(25s/22s/17s, 总时长均落在区间, 数字独立 numbers 字段)+12 张火锅镜头卡(tools/gen_shotcards.py 生成, 十类资产+2变体: S11无人背影中风险 n_best=4/retry_max=3; S12手部入画高风险 lane=ken_burns 演示风险表)
- [test] tests/ 187 passed 0 skipped (系统 python3 + pytest 9.1.1, ffmpeg 已装全部实跑: 真渲染 KenBurns/mp4 落盘/2幕合成成片端到端); 覆盖: schema合法/非法卡、状态机全迁移矩阵、路由全分支、预算守卫/重试切兜底、G1解析+真视频、VLM契约/重试/parse_failed、CLIP启发式stub、G6逐字+CER、zoompan/ASS/concat/终混 argv 纯函数、叙事模板时长区间、镜头卡风险表、编排器全链路(stub 生成/门禁/合成)+崩溃恢复+run_forever 退出、CLI initdb/ingest/status/report
- [fix] 实测修复: ass_time 厘秒进位 bug; 终混 apad 无 whole_dur 导致音频无限填充(测试中暴露为撑爆磁盘)→ apad=whole_dur; gating→fallback 须经 retrying 两步合法迁移
- 决策追加 D-006..D-018; git: M2 两个 commit; 未做(超出本子代理范围): 真实 GPU 生成/真实 CLIP/edge-tts/whisper 运行验证(M1 权重与依赖就绪后由 M3+ 联调)


## M2-EXEC 完成 (2026-09-08, 闭环联调 + 良率报告 v1)
- [gen] `src/gen/ltx.py` 补齐: diffusers 0.33.1 LTXPipeline/LTXImageToVideoPipeline 装配(D-024),
  首帧 center-crop→384×512, fp16 黑帧守卫, 进程级管线缓存(2.2s/候选); `src/gen/wan.py` 补齐:
  DiffSynth Fun-InP(D-019/D-028, negative_prompt 必须逗号串——list 会 batch 错配崩), cfg 5.0+delta 钩子,
  stylize 钩子默认关; `common.open_center_resize` 公共首帧预处理
- [wire] orchestrator LTX 车道接线(debug_model=ltx→ltx.generate, 原 force_ltx 判断是死代码);
  cli ingest 卡面投影落库(D-025: 384×512/1.5625s 调试卡, 生成与门禁同口径); open_clip 权重本地化+
  embed 进程级缓存(D-027); CLIP 启发式按实测重校准(D-026: 修 G2 0% 映射 bug, 锚点数据入
  workdir/logs/m2_clip_anchor_*.json); 镜头卡阈值未动
- [assets] SDXL 11 张 832×1216 竖版资产(§5.1 十类+S11 背景; back_view 重生成择优 seed2001),
  manifest.json 全记录(D-029)
- [loop] **十镜头闭环 PASS**: cli ingest 12 卡 → tmux cradle_m2 orchestrator run → 17m11s 走完:
  **9 accepted / 3 fallback / 0 blocked**(62 候选=59 LTX 生成+3 KenBurns), 一次通过率 9/12,
  含降级交付率 100%; S12 ken_burns 车道在生产口径 480×832/5s 真实渲染验证; 被拒候选 34 个 mp4+门禁
  JSON 保全在 workdir/candidates/(M6 失败画廊素材)
- [report] 良率报告 v1: `reports/milestones/m2_yield_report_v1.md` + 溯源脚本 m2_gate_query.{py,sql}
  + 聚合快照 m2_gate_stats.json。核心: G1-G4/G6 100%, **G5 42.4% 唯一卡点**(夜景/背影类 appeal 锚
  系统性偏低, 分数恒定 0.62-0.64 vs 美食类 0.75-0.78 → 建议真实 VLM 复审或按资产类型归一化);
  G3/G4 冷启动阈值偏松(建议 0.80/0.95, 依据实测 min 0.8151/0.9602); 重试对确定性 borderline 无效
  (建议稳定-borderline 短路)。该批未经 VLM 审核(D-004 标注义务)
- [wan] 装配验证 1 条过全门禁(D-030): S01 生产卡 480×832/81帧/steps20, 产物
  reports/milestones/m2_wan_verify.json + workdir/candidates/wan_verify_S01.mp4
- [test] pytest 192 passed(新增投影/首帧预处理/重试钩子/启发式行为测试); git: M2 收尾 commit

## M3 完成 (2026-09-08, 合成层完整成片)
- [compose] src/compose.py 升级(全部真跑验证): ① build_compose_argv 支持 video_durations →
  短素材 tpad=stop_mode=clone hold-last-frame 补齐幕长(D-033); ② fit_tts_to_scene 自适应语速,
  保证口播不超幕时长不被 atrim 截断(D-032: hook +70%/CTA +84%, 其余 -10%); ③ probe_media_duration
  音频兼容探测(g1_tech.probe_duration 只认视频流的坑), api/tts.py 回退接线; ④ compose_g6 合成级
  G6: 烧录 ASS 回读(parse_ass_dialogues)与模板渲染文本逐字比对(硬) + whisper TTS→ASR 回转 CER
  (normalize_for_cer 归一化 D-034, 领域热词 D-036); ⑤ build_bgm_argv 程序合成 BGM(D-035),
  终混 sidechain ducking ≈-12dB(D-006)首次真跑; orchestrator 默认 composer 接 rate 感知 tts_fn
  并在 G6 未过时落 warn 事件
- [video] **output/m3_seeding_debug.mp4**: 25.0s(模板 25.0s ±0) 1088×1920@16fps h264+aac 3.4MB;
  幕-镜头cast: hook=S02 evidence=S01/S03/S04 ambiance=S07 CTA=程序纯色贴片; 首帧/CTA 帧目检
  字幕(Noto Sans CJK)烧录正确; reports/milestones/m3_compose_report.{md,json} +
  m3_seeding_debug.ass + m3_first_frame.png(磁盘证据, 媒体不入 git)
- [g6] 合成级两级: ① ASS 逐字比对 PASS(6 幕全等); ② whisper-small GPU CER=0.0323 ≤0.05 PASS
  (无热词基线 0.0645 全为同音字混淆, 如实披露, 见 D-036); 数字隔离(D-015)复查:
  numbers 只出现于字幕, 不在任何视频路径
- [test] pytest 209 passed(新增 tests/test_compose_m3.py 17 测: tpad/ASS回读/中文数字归一化/
  自适应语速含触顶/BGM argv/compose_group 端到端 G6 过/挂/跳过); 修复测试中暴露问题:
  语速预测整数化收敛过慢(改 ceil+1)、tts 无 rate 形参时死循环、纯音频探测异常
- [report] 首跑 CER=6.45% 超标 → 逐字分析全部为同音字混淆(非截断) → 标准领域热词偏置后 3.23%,
  两数字均入报告(D-036); hook/CTA 3s 幕 vs 21 字文案的模板张力记 D-032 校准建议
- 决策追加 D-032..D-036; commit "M3: compose layer full video"

## M4 完成 (2026-09-08, 端到端 + 崩溃恢复)
- [e2e] 全新沙箱 /root/cradle_m4_sandbox (CRADLE_ROOT 隔离, models 只读软链, D-037 配方) 一键出片
  PASS: `bash scripts/m4_e2e_demo.sh` = initdb → ingest 6 卡(S01/S03/S05/S02/S07 + S12 ken_burns,
  D-037) → run --task-file --once 不动点全链 → 自动 compose。总墙钟 **340s**;
  终态 composed=6/6, 候选 pass=16, yield_accepted=1.0 / with_fallback=1.0, unfinished=0 blocked=0;
  成片 output/product_seeding_25s.mp4 (h264 1088×1920+aac, 25.000s, 5.6MB);
  报告 reports/milestones/m4_e2e_demo.md (含踩坑: 沙箱缺 models 软链时 gater 回落 HF hub 被墙卡死)
- [recover] **kill -9 崩溃恢复演示 PASS** (M4 核心验收点): 沙箱 /root/cradle_m4_sandbox2,
  05:47:38 于 gating=1∧generating=1 混合孤儿窗口 kill -9 (watcher 1s 轮询自动命中);
  05:48:02 重启 → `recover(): 重置 1 个孤儿任务` (generating S02→pending;
  gating S01 有 3 候选**保留不重生成**, id/mtime 佐证: 重启后 verdict pending→pass 而
  文件 mtime 仍为 kill 前 05:47:34-38) → 05:53:20 6/6 composed + 自动合成成片(25.000s) +
  主循环干净退出, 全库 16 候选无重复无冗余生成;
  报告 reports/milestones/m4_recovery_demo.md (prekill 快照/时间轴/候选对照表)
- [tool] scripts/m4_start_orch.sh + m4_kill_when_mixed.sh (演示可复现, 入 git)
- [test] pytest 209 passed 复核(M4 无管线代码改动, 复用 M3 合成层升级)
- 决策追加 D-037; commit "M4: e2e CLI + crash recovery demo"
