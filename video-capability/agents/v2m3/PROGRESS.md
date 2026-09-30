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

## M5 完成 (2026-09-08, 校准 + 竖横 A/B + Wan 量产 + 9 条成片)

**阶段 0-2 (M5-PROD, 沙箱 /root/cradle_m5, D-038..D-045)**: G5 双锚分锚 (离线重评 59 候选, 美食回退违例 0,
G5 通过率 42.4%→96.6%); 阈值试点验证制 (G3 0.78 / G4 0.95 上调均被试点否决, 维持冷启动值); stable-borderline
短路 + SDXL 本地加载修复; 竖横 A/B 10/10 accepted → **维持竖版 480×832**; Wan 量产 17/17 任务首轮 accepted
(50 候选 48 pass + 2 fail, 0 fallback/blocked), API 消耗 0。详见 `reports/milestones/m5_calibration.md`。

**前手死亡与接棒 (如实记录)**: M5-PROD 在 PROD_DONE (13:25) 之后、启动成片合成之前死亡 (9 条 compose 无日志/
无事件/从未启动; "TTS 20 次合成中途崩"系冒烟产物被清理造成的假象, 见 D-046)。M5-CONT 接棒:
现场固化 commit `322bb42` → 修 pytest (12→17 卡数断言 + venv 流氓 tests 包遮蔽, **226 passed**) →
9 条成片合成一次通过 9/9 (19:38-19:44, 1088×1920 竖版 h264+aac, 时长与模板 ±0s, G6 逐字 9/9;
CER whisper-small 1/9 / whisper-medium 复核 8/9 ≤5%, 差因=ASR 同音字, D-047) → 成片拷回 `~/cradle/output/` →
最终良率报告 `reports/milestones/m5_yield_report.md` (良率 100%, Wan 60/200 口径纠正 D-048, trace_query 5/5 验证,
失败样本 36/36 保全) → 本节 + DECISIONS D-046..D-048 + 收尾 commit。

**关键数字**: 9 成片 = t1_seeding×3 (25s) / t2_ambiance×3 (22s) / t3_offer×3 (17s); 生产良率 17/17 (100%),
一次通过; 显存峰值 23.76GB/32GB; 墙钟 A/B 69min + 量产 305min + 合成 6.5min。


## M6 完成 (2026-09-08, 失败画廊 + FINAL_REPORT + README + git 收尾)

- [gallery] `reports/gallery_failures/`: **24 例** (类型A=校准前 G5 启发式场景偏差×22, 自 34 个 M2 LTX 被拒候选精选; 类型B=生产期 G5 边缘×2 全收), 每例 `video.mp4`(实体) + `gate_json.json`(六门禁原始 JSON) + `grid.jpg`(2×5 抽帧网格) + `case.md`(镜头卡+六门禁分数+main_issue+失败归类+D-041 校准后重评分+入选理由); `INDEX.md` 按失败类型组织, 附"给阈值校准者的要点"与"本管线未出现 G1/G3/G4/G6 类失败"如实附注; 媒体 14.4MB < 50MB 门槛 → mp4/jpg 全量随 git 入库 (D-049); 构建脚本 `tools/m6_build_{gallery,index}.py` 幂等, 数字实时取自 SQLite/m5_reeval_g5.json
- [report] `reports/FINAL_REPORT.md`: §1 一页总览 (良率 100% / 成本 GPU 期≈7.3h+下载≈1.3h / 项目墙钟≈20h / 结论; 标注"全程未经 API VLM 审核 (D-004)"与"主控抽帧目检 3 片通过") / §2 样片索引 9+1 (含 CER 双口径逐条) / §3 良率统计+失败聚类 (类型A/B) / §4 阈值表 (全部维持冷启动, G3/G4 上调被试点否决的依据 + A/B 维持竖版结论) / §5 局限与建议 L1-L11 (CLIP 启发式局限与 VLM 接入路径 / D-019 替代模型 / CER 同音字与 pinyin 建议 / 降级路径未被量产触发 / 单风格资产 / 1080p 软件插值等) / §6 API 用量表 (API 0 次; 本地 VLM 151 + TTS 141 + whisper 记账注记) / §7 交付物对照 / 附录A 自检九项逐项证据 / 附录B D-001..D-050 索引 / 附录C 里程碑索引
- [readme] `README.md` 四指南: ① 新机器复现 (硬件前提 / scripts 01-08 环境序 / 下载源策略 D-021 / 沙箱配方 D-037 三要素 / 一键 `m4_e2e_demo.sh` + CLI 速查); ② 换底模 (models 布局 / gen wrapper generate() 契约 / D-019+D-022 "先冒烟再量产"教训); ③ 换 API (config/api.env 格式 / src/api 适配器位置 / 预算守卫 / 失败重试 1 次切兜底); ④ 换真实实拍资产 (assets 布局 + manifest 格式 + first_frame_asset 指向 + 镜头风险表: **含人脸/手的实拍图必须走 ken_burns 车道**); 附项目结构图与 SQLite 追溯查询速查
- [test] pytest **226 passed** 复核 (M6 无管线代码改动, 仅新增 tools/ 构建脚本)
- [git] commit "M6: failure gallery + FINAL_REPORT + README" + tag **v1.0**; 决策追加 D-049/D-050

## 全项目时间线 (2026-09-08 单日, 服务器时间)

| 时刻 | 事件 |
|---|---|
| 00:52 | M0 开工 (SPECS 落盘/git init) |
| 03:2x | M1 环境就绪 (权重 46G 落盘, LTX/Wan 冒烟 PASS) |
| 04:03-04:21 | M2 十镜头闭环 (9 accepted/3 fallback, 34 被拒候选保全) + Wan 装配验证 |
| 05:19 | M3 合成层完整成片 (m3_seeding_debug.mp4, CER 0.0323) |
| 05:34 / 05:53 | M4 e2e 一键出片 340s / kill -9 崩溃恢复演示 PASS |
| 06:03-08:13 | M5 校准 (G5 双锚 D-041) + 竖横 A/B 10/10 (维持竖版) |
| 08:20-13:25 | M5 Wan 量产 17/17 首轮 accepted (50 候选 48 pass/2 fail) |
| 19:38-19:44 | M5-CONT 接棒: 9 条成片合成 9/9 (G6 逐字 9/9) |
| 20:0x-收尾 | M6: 画廊 24 例 + FINAL_REPORT + README + 自检九项 + tag **v1.0** |

## V2-M0 完成 (2026-09-08, v2 状态恢复 + 回归夹具库 + G7 模型准备)
- [audit] v1 状态审计(SPECS_V2 §0):git 13 commits + tag v1.0;主仓库 12 任务/62 候选(34 LTX fail + 25 pass + 3 fallback);沙箱库 27 任务/60 候选(58 pass + 2 fail)+ m5_videos 9 成片台账;output 10 片;画廊 24 例;api_usage 230 次全部 route=local(API 预算零消耗)。全文: reports/V2_M0_AUDIT.md
- [disk] 治理 3.3G(used 67→64G, avail 28→31G):m4 演示沙箱 208M + /tmp 残留 80M + .frames 缓存 609M + open_clip 冗余副本 890M + whisper medium 评测残留 1.5G;8G 目标不可达,范围裁定记 D-051
- [verify] v1 最小任务全链 51s 全绿:m0v 沙箱(D-037 配方)S12 ken_burns 走 initdb→ingest→run,六门禁 G1 1.0/G2 0.926/G3 0.970/G4 0.995/G5 0.770/G6 deferred;**pytest 226 passed**;记 D-055
- [fixtures] **回归夹具库 47 条入库**(指标全达标):fail 15(fluid_melt 8/split_merge 3/count_drift 2/object_flow 2,四类全覆盖;8 条曾 verdict=pass、6 条曾 selected)+ pass_structural 15(v1 真产物 4 + kenburns 确定性再生成 11)+ pass_candidate 17(G7e 预审,**待人工确认**)。方法: DINOv2 粗筛 122/122(median 0.972)→ 26 条嫌疑三联帧逐条目检;可分性 fail≤0.845 vs pass_structural≥0.962 零重叠。入库: 主仓库 fixtures 表 + workdir/fixtures/(媒体 32.1MB 随 git 入库,D-053)+ reports/fixtures/INDEX.md + dino_scan_hist.png。口径记 D-052
- [models] G7 模型 5/6 就绪且 Volta 自查通过(D-054):DINOv2 ViT-L/14 1.22G(ModelScope, fp16 OK)/ grounding-dino-tiny 689M(**fp32+autocast-fp16 口径**, 纯 .half() 有 dtype bug)/ SAM ViT-B 375M(fp16 OK)/ RAFT-small 4M(fp32 OK, FX-F001 光流 P95=128px)/ Depth-Anything-V1-Small 99M(fp16 OK);pip matplotlib+lap 就绪;MobileSAM 备份第三次断点续传成功(40.7M,torch.load 439 keys 校验通过)
- git: "V2-M0: audit + fixture library + G7 model prep"

## V2-M1 完成 (2026-09-08, V2-M12: G7 五子项实现 + 初跑)
- 实现 `src/gates/g7_object_persistence.py`(a 跨步主体一致性/b 开放词表检测+LiteByteTracker 计数 churn/c 静态区 RAFT 光流(SAM 反选+expected_static_mask)/d 首尾漂移/e VLM 成对审讯) + `src/gates/g7_vlm_prompt.txt`(豁免条款逐字保留); 全链 stub 注入可单测
- schema v3: expected_static_mask 可选字段 + fixtures 表收编迁移 + g7_runs 分数表; gates 链挂 G7(G6 之后, gate_json 增 G7 键, GATE_IDS 六门禁不动保 v1 兼容, D-057); cli `g7-fixtures` 夹具复跑入口
- 47 夹具冷启动初跑: fail 拦截 15/15, struct 误杀 0/15, pass_candidate 误杀 16/17(冷启动 c=0.5px 过严, 交 M2 校准) → `reports/milestones/V2_M1_g7_initial_scores.md` + `workdir/logs/v2m1_g7_initial.json`(逐帧原始检测/双口径序列全落盘)
- pytest 256 passed; 决策 D-056..D-058; commit "V2-M1: G7 five sub-gates implemented + initial fixture scores"

## V2-M2 完成 (2026-09-08, V2-M12: G7 校准 + 工作点落盘)
- 校准: 初跑原始指标离线重放 1288 组合×阈值栅格(零 GPU 重跑) → 定版 OP1: g7a_mode=full<0.82 / d<0.84 / c>30px / b 宽容(4/100/12), 写 `config/thresholds_v2.yaml`(calibrated: true)
- **终版重跑(47/47 真实 GPU): fail 拦截 15/15=100%(≥90%), pass_structural 误杀 0/15=0%(≤15%), pass_candidate 误杀 4/17=23.5%(≤25% 带内); 迭代 1/3 轮达标**
- 产物: `reports/G7_CALIBRATION.md`(头条数字/分布图索引/子项 ROC/迭代表/人工复核清单) + `reports/fixtures/g7_{dist,roc}_*.png` + `workdir/logs/v2m1_{calibration,g7_final}.json`; pytest 257 passed; 决策 D-059; commit "V2-M2: G7 calibration + thresholds_v2.yaml"
