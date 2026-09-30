# DECISIONS — 全部自主决策记录(编号+理由,只增不改)

- **D-001** (2026-09-08): 本机盘总量 99G,可用 83G,达不到规格"预留≥150GB"。决策:继续执行(这是任务书指定的唯一 V100)。配套纪律:只下载 fp16 权重、跳过 fp8/重复格式副本、pip 缓存装完即 purge、模型统一放 ~/.cache/huggingface、每个大下载后 df -h 巡检,可用 <20G 即停并清理。依据:预估总需求 ~55G < 83G。
- **D-002** (2026-09-08): 规格内部张力——§6 M1 佐证要求"LTX、Wan 各成功1条测试视频",而 §5.3 说门禁全链路跑通前禁止碰 Wan。解释:M1 的单条 Wan 冒烟视频属"模型可用性验证"(证明 V100+DiffSynth+Wan 栈能出片),不是迭代期生成;门禁校准(M2)仍只用 LTX;产出期批量用 Wan 严格在门禁跑通之后。
- **D-003** (2026-09-08): git 仓库不纳入大媒体文件(workdir/candidates、workdir/gated、output 的 mp4/png 等),.gitignore 排除。证据链走 SQLite + reports/ 索引 + 服务器文件本体。理由:99G 盘装不下 git 对象膨胀,且成片最终在 output/ 目睹即证。
- **D-004** (2026-09-08): 用户未提供 config/api.env(本地工作目录与服务器均无该文件)。全链路走本地兜底:SDXL 生图、CLIP ViT-L/14 启发式替代 VLM(报告将标注"该批未经VLM审核")、edge-tts TTS、whisper-small ASR。适配器仍按 API 优先实现,留接口。
- **D-005** (2026-09-08): 服务器现为独占(nvidia-smi 0MiB,无 tmux server,旧租户已清场)。仍守共享纪律:自建 tmux 会话一律加前缀 cradle_,不动 /root/workspace 旧目录(留档),GPU 任务前先 nvidia-smi。
- **D-006** (2026-09-08, M2-CODE): BGM ducking -12dB 的实现口径: ffmpeg 无精确"按 dB ducking"参数,采用 BGM 预衰减 volume=10^(-12/20)≈0.2512 + sidechaincompress(threshold=0.03:ratio=12) 组合近似;口播段压缩由 sidechain 链路承担。依据: 保守可复现,报告标注近似值。
- **D-007** (2026-09-08, M2-CODE): tasks 表在规格列之外新增追加列 card_json / template / hint_json / error(遵循迁移只新增原则,schema_migrations 管版本)。用途: 镜头卡全文落盘(断点续跑不必回读模板)、模板组归属(compose 触发)、路由重试钩子持久化(崩溃后带着加强 negative/guidance 继续)、blocked 原因记录。另在 .gitignore 追加 workdir/*.sqlite3,防数据库误入库。
- **D-008** (2026-09-08, M2-CODE): 预算守卫计数口径: api_usage 中 route='api' 的每次尝试(含失败)都计入预算。理由: 失败请求通常也已消耗 provider 配额,按尝试计数是保守方向;本地兜底调用(route='local')不占 API 预算。
- **D-009** (2026-09-08, M2-CODE): 本地 VLM 兜底(CLIP ViT-L/14 启发式)评分公式: 对每格抽帧与 7 个正/负文本锚点算余弦相似度,经线性映射 map01(x; lo,hi)(经验值 lo≈0.10-0.15, hi≈0.45-0.70)转成 0-1 缺陷分;overall_score 严格按 vlm_prompt 中的公式 0.45*(1-overall_defect)+0.35*(aesthetic/5)+0.2*(camera/5) 合成,判定阈值与提示词一致。输出强制标注 model=clip_heuristic 与 unreviewed_by_vlm=True(对应 D-004 报告标注义务)。纯启发式,仅用于门禁链路不中断,精度校准依赖后续真实数据。
- **D-010** (2026-09-08, M2-CODE): CPU 测试环境用系统 python3(pip --break-system-packages 安装 pytest/pyyaml/numpy/pillow),不触碰 ~/cradle/.venv(M1-ENV 领地)。所有重依赖(diffusers/open_clip/edge-tts/whisper/DiffSynth/torch)一律 lazy import,单测通过函数注入 stub;ffmpeg 相关集成测试用 pytest.mark.skipif(检测 ffmpeg/ffprobe) 守护,当前服务器 ffmpeg 已就绪故全部实跑。
- **D-011** (2026-09-08, M2-CODE): G6(业务)门禁分两级: 镜头级候选无字幕可校验,G6 在六门禁评估中为占位通过(detail.deferred=合成阶段逐字校验),不参与淘汰;合成级 compose 后执行硬校验——ASS 字幕文本与模板渲染文本逐字比对(必做)+ 可选 TTS→ASR 回转 CER≤5%(自实现编辑距离,不引 jiwer;ASR 不可用则跳过并记录)。理由: 保持"六门禁"结构完整的同时避免镜头级假失败。
- **D-012** (2026-09-08, M2-CODE): blocked 语义与恢复路径: 源图/降级源缺失在 pending 阶段检测,走合法迁移 pending→blocked;门禁期无法降级、生成反复失败(次数>retry_max+3)等异常路径用 DB.force_status 绕过状态机并强制留事件痕(reason 写入 tasks.error)。recover(): 孤儿 generating→pending 重生成;gating 且无候选→pending。
- **D-013** (2026-09-08, M2-CODE): ken_burns 车道任务的 n_best 视为 1——zoompan 是确定性渲染,多 seed 无意义;其产物仍作为候选过 G1 等门禁并记账,便于失败画廊统一收集。
- **D-014** (2026-09-08, M2-CODE): run_once 为不动点推进(最多 10 遍,每遍每任务推进一步),保证一次调用内完成 生成→门禁→路由→重试/fallback→合成 的级联,便于无人值守与测试;run_forever 连续 3 轮无进展自动退出并告警,防止任务卡死时空转占用进程。
- **D-015** (2026-09-08, M2-CODE): CTA 贴片/优惠字卡=程序渲染纯色段: 叙事模板场景可声明 background:{type:"solid",color},compose 用 lavfi color 源生成该幕(无需生成模型/镜头卡),文字由 ASS 烧录承担。价格/优惠等数字只存于模板 numbers 字段→render_narration→字幕/贴片,代码路径上不接触镜头卡 prompt(计划对象 video_paths 中断言不含数字),落实 SPECS §5.6"数字禁止进入生成画面"。
- **D-016** (2026-09-08, M2-CODE): 路径根可注入: 环境变量 CRADLE_ROOT 覆盖项目根(缺省为仓库根),cli 另提供 --root/--db。用途: CPU 单测与多实例完全隔离,不污染真实 workdir/output。
- **D-017** (2026-09-08, M2-CODE): ingest 幂等策略: shot_id 冲突时仅当原任务仍为 pending 才覆盖卡面字段;非 pending(生成中/已验收)保留原状,避免运行中任务被换卡导致候选与卡面错位。重复 ingest 返回同一任务 id。
- **D-018** (2026-09-08, M2-CODE): 候选级 overall_score 定义为六门禁 score 的算术平均(每门禁 score∈[0,1],缺门禁按 fail=0 计),路由"取 overall_score 最高"用该统一口径;VLM 的 overall_score 原值单列于 G5.score,不被平均稀释,报告可分别追溯。

- **D-019** (2026-09-08, M1-ENV; 原编号 D-006，因与 M2-CODE 并行撞号重编): 规格主选产出模型 **Wan2.1-I2V-1.3B 不存在**——HF `Wan-AI/Wan2.1-I2V-1.3B-480P(-Diffusers)` 返回 401（仓库不存在），官方 Wan2.1 只发布过 T2V-1.3B / I2V-14B-480P / I2V-14B-720P（社区 issue Wan-Video/Wan2.1#7 证实）。备选权衡：I2V-14B（fp16 权重 28G+，磁盘/显存/速度均不可行）；Wan2.2-TI2V-5B（MS 仓 34.2G 且 fp32 存储、原生 720p@24fps 偏离产线 480p@16fps81帧）；T2V-1.3B（SPECS 备选，但丧失 I2V 车道=产品图锚定+G3 参考图一致性）。**决策：采用 PAI/Wan2.1-Fun-1.3B-InP**（阿里 PAI 官方、Wan2.1 血统 1.3B、首个/末帧条件 I2V、原生 480p@16fps 81 帧恰好等于产线参数、ModelScope 19.8G、DiffSynth 官方模型表按 hash 登记可直接加载）。M5 量产若需更高质量，可在此份额内重评 TI2V-5B。
- **D-020** (2026-09-08, M1-ENV; 原编号 D-007，因与 M2-CODE 并行撞号重编): 生成框架版本矩阵（Volta sm_70 + torch 2.4.1+cu121 约束下的兼容性实测）：① PyPI `diffsynth` 2.1.6 的 wan_video 管线 import `torch.nn.attention.flex_attention`（torch≥2.5 才有）直接崩，且其模型表已无 LTX-Video-2B（只剩 LTX-2）→ 弃用；② 定版 **diffsynth==1.1.9**（torch 2.4 兼容、Fun-InP DiT hash 已登记、ModelManager API）；③ LTX-Video 2B 走 **diffusers==0.33.1 LTXPipeline**（DiffSynth 任何 PyPI 版本都不含 LTX-2B；SPECS 备选链精神内：框架服务于模型）；④ transformers 定版 **4.49.0**（5.16.1 要求 torch≥2.5 且自带 NameError bug，会将 PyTorch 整体禁用）；⑤ peft==0.14.0、opencv-python-headless==4.10.0.84（5.0.0.93 装完 import cv2 失败）。LTX 文本编码器用 **FLUX.1-dev 的 T5-XXL fp16**（9.5G）替代 LTX 仓 19G fp32 T5（同架构 google/t5-v1_1-xxl、caption_channels 4096 匹配，省 9.5G 磁盘）；LTX 主权重用 MS 仓 diffusers 布局 fp32 shard 加载时转 fp16（单文件 v0.9.1 路线被 diffusers 0.33 的 from_single_file 内置旧 64-ch VAE 默认 config 打断，改用与 config.json 自洽的 fp32 布局，净增 +3.7G）。
- **D-021** (2026-09-08, M1-ENV; 原编号 D-008，因与 M2-CODE 并行撞号重编): 下载源实测与策略（腾讯云 CVM 内网）：hf-mirror 文件 CDN 仅 24-196KB/s（不可用于大文件）；download.pytorch.org 对 pip 通道仅 ~20KB/s（curl 同 URL 却 6.3MB/s，pip 栈异常）；pip 走阿里 pypi 稳定 400-500KB/s，curl 走阿里 9-12MB/s。**策略：大文件一律 curl 直连**——模型走 ModelScope `api/v1/models/<repo>/repo?FilePath=`（实测 11-12MB/s），torch/nvidia 轮子走 aliyun pytorch-wheels + aliyun pypi（curl 后本地 pip 安装；pip 26 的 --find-links 对该目录不生效，改为显式轮子路径安装），openai 原版权重（CLIP ViT-L-14.pt / whisper small.pt）走 openaipublic.azureedge.net（6.2MB/s 可达）。HF 仅用于公开小 json（SDXL model_index/scheduler config 成功；Lightricks/ltx-video-2b-v0.9 已 gated 返回 401 不可用）。

- **D-022** (2026-09-08, M1-ENV; 原编号 D-009，因与 M2-CODE 并行撞号重编): 阿里源 `diffsynth==1.1.9` wheel 是 2025-11 重打包的错配快照：`WanModel.patchify` 丢失了 flatten+返回 grid 两行（只 `return x`），而 `models/wan_video_dit.py:374` 与 `pipelines/wan_video.py:571` 都按 `x, (f, h, w) = patchify(x)` 解包 → Wan 去噪第一步即 `ValueError: not enough values to unpack`。按上游语义补丁：patchify 末尾加 `grid_size = x.shape[2:]; x = x.flatten(2).transpose(1, 2); return x, grid_size`（原文件备份 .bak；补丁脚本 `scripts/07_patch_diffsynth.sh`，验证见 `workdir/logs/07` 与 Wan 冒烟通过）。教训：镜像站重打包的 sdist/wheel 可能与上游 repo 不一致，关键路径必须先冒烟再量产。
- **D-023** (2026-09-08, M1-ENV; 原编号 D-010，因与 M2-CODE 并行撞号重编): openai CLIP ViT-L/14.pt 完整性确认：azureedge 下载 932,768,134 字节即完整尺寸（openai 发布格式为 fp16 TorchScript 归档），torch.load + open_clip 加载前向 norm=1.0 验证通过；非中断截断。


- **D-024** (2026-09-08, M2-EXEC): src/gen/ltx.py 装配定版: diffusers 0.33.1 **LTXPipeline(T2V) +
  LTXImageToVideoPipeline(I2V 首帧条件)**——0.33.1 自带 I2V 管线, 无需 latents 拼接/升级(任务书预案未触发);
  组件加载照抄 M1 冒烟路径(flux_t5 T5-XXL fp16 + transformer/vae fp32 布局转 fp16 + FlowMatchEuler
  dynamic shifting); `frame_rate` 不传(保持 M1 实测默认路径); 首帧任意来源图统一 center-crop→resize
  384×512(src/gen/common.open_center_resize); 管线进程级缓存(首候选 ~50s 含加载, 后续 ~2.2s/条);
  fp16 黑帧守卫(SPECS §9-②, 命中则 VAE→fp32 重试一次, 本批实测未触发)。generate() 对外契约
  (pipeline 可注入 callable)与 CPU 单测保持兼容。
- **D-025** (2026-09-08, M2-EXEC): 卡面投影——`settings.debug_model=ltx` 时 `cli ingest` 把生产卡
  (480×832/5s)投影为 **LTX 调试卡落库**(384×512, 帧数吸附 8k+1 布局@16fps → 1.5625s ≤2s,
  fallback.duration_sec 同步投影), 生成与六门禁共用同一卡面, G1 不会对调试候选按生产分辨率误杀;
  ken_burns 车道卡(S12)不投影, 在生产口径 480×832/5s 直接验证降级渲染。生产卡文件不被修改。
- **D-026** (2026-09-08, M2-EXEC): CLIP 启发式重校准(D-009 经验值 → 实测数据定标)。
  实测: 11 张资产 + LTX 真实帧 + 合成坏帧 × 7 文本锚(`workdir/logs/m2_clip_anchor_probe.json`/
  `m2_clip_anchor_assets.json`)。发现: ① pos 锚对平坦帧**反向**(黑/灰 pos 0.175-0.198 > 美食帧
  0.154-0.163), 原公式 `subject_missing=1-map01(pos;0.10,0.55)` 对任何真实帧 ≥0.67 → G2 探针 0% 通过,
  属映射 bug, 按"先修 bug"授权修复; ② garbled 锚可分(正 0.042-0.115 vs 文字/噪声 0.183-0.197);
  ③ appeal 锚是内容/食欲有效信号(正 0.145-0.232 vs 坏帧 ≤0.156) 但对夜景/背影偏低。定标:
  garbled 域 (0.12,0.30); subject_missing=内容丧失复合信号 max(garbled(0.12,0.30), dark(0.20,0.32),
  bright(0.16,0.28))——语义局限(无法检出"主体错型")如实入报告; 美学域 appeal01 (0.145,0.28), lighting
  改用 appeal 锚; 传 QC 提示词时 camera_match 取中性 3.0(QC 文本与各锚自相似 0.48-0.72, 无运镜信息)。
  **镜头卡阈值一律未动**, G5 对夜景类偏严留给良率报告校准建议。
- **D-027** (2026-09-08, M2-EXEC): open_clip 权重本地化: `pretrained="openai"` 会走 HF hub
  (HF_HUB_OFFLINE 下直接失败, hf-mirror 又慢), 改为优先加载 `models/clip/ViT-L-14.pt`(M1 已验证
  open_clip 可载 OpenAI JIT 归档), 环境变量 CRADLE_CLIP_WEIGHTS 可覆盖, 找不到再回落 "openai";
  同时给 `g3_consistency.default_embed_fns` 与 `api.vlm._load_clip_fns` 加进程级缓存(此前每候选重载
  0.93G 模型)。
- **D-028** (2026-09-08, M2-EXEC): src/gen/wan.py 装配定版: PAI/Wan2.1-Fun-1.3B-InP(D-019) 经
  DiffSynth 1.1.9 ModelManager 四件套加载(umt5-xxl bf16→fp16 / CLIP 图编 / DiT / VAE), 照抄 M1 冒烟
  (`tests/m1_wan_smoke.py`); 候选记账标签 `wan_i2v_13b`→`wan_fun_1.3b_inp`(如实反映模型, 测试同步);
  cfg_scale 基准 5.0(M1 实测)+路由 guidance_delta 钩子; **DiffSynth 契约: negative_prompt 必须是逗号串**,
  传 list 会 batch 维错配崩(`torch.cat clip_embdding/context` 1≠8, 首次验证实测踩坑后修复);
  首帧 img2img 风格统一钩子保留、默认关闭(first_frame_pipe=None, 本阶段不跑); input_image 复用
  open_center_resize → 480×832; 管线进程级缓存; fp16 黑帧守卫同 LTX。
- **D-029** (2026-09-08, M2-EXEC): 资产策略: **832×1216(SDXL 标准 portrait 桶, "1024px 级"口径)主图**
  直接落在卡面引用路径(assets/products|scenes/*.png), LTX/Wan 生成时按需 center-crop+resize,
  **不建派生子尺寸目录**(省盘且单一事实源; 派生目录方案备查)。共 11 张=§5.1 十类 + S11 背景图;
  back_view 首版无人影, 以 3 seeds(2001-2003)重生成择优 2001(目检正背影/无正脸); storefront 有
  SDXL 伪书法残留(灯笼字帖), 可接受并记录。prompt/negative/seed/耗时全量入
  `assets/products/manifest.json`。
- **D-030** (2026-09-08, M2-EXEC): Wan 装配一次性验证(十镜头闭环全绿后执行, 兑现任务 6): S01 生产卡
  81帧@16fps=5.0625s, steps 20, 生成 364.864s, 峰值显存 16931.4MB, vae_mode=fp16, 总墙钟(含加载/门禁) 388.7s。六门禁: G1=PASS(1.0); G2=PASS(0.8882); G3=PASS(0.9018); G4=PASS(0.9677); G5=PASS(0.7453); G6=PASS(1.0); all_passed=True。产物
  `reports/milestones/m2_wan_verify.json` + `workdir/candidates/wan_verify_S01.mp4`。M5 量产装配风险消除。
- **D-031** (2026-09-08, M2-EXEC): 记账粒度: candidates 表不含 seed/steps/gen_seconds(每任务末次值在
  tasks 表); 候选级 seed 可由文件名恢复: `{shot}_a{attempt}_{i}.mp4` →
  seed=stable_seed(shot)+attempt*1000+i(crc32(shot_id)&0x7FFFFFFF)。M5 量产如需逐候选记账,
  按"迁移只新增"原则加列。

- **D-032** (2026-09-08, M3-COMPOSE): 口播自适应语速。实测(edge-tts zh-CN-XiaoxiaoNeural, rate=-10%): hook 幕文案 21 字需 5.376s、CTA 幕 20 字需 5.832s, 而模板幕长均 3s——硬时间轴下 atrim 必截断口播并必挂 G6/CER。决策: compose_group 内建 fit_tts_to_scene——以基准 -10%(§5.6) 起测, 用语速-时长线性模型(dur∝1/(1+rate/100))按实测解方程 ceil 预测下一档(+1% 裕量), 保证 ≤ 幕时长-0.10s; 触顶 +100% 仍超长则 truncated=true 如实上报不粉饰。实测落点 hook +70%(2.88s)/CTA +84%(2.88s), 其余四幕 -10% 即可。配套: g1_tech.probe_duration 只认视频流, 新增 compose.probe_media_duration(仅 format.duration, 音视频通用)供 TTS/fit 探测, api/tts.py 探测失败时回退之。校准建议: 模板 v2 应缩短 hook/CTA 文案或将其幕长提到 5s(总 29s 仍在 [25,30]), M5 前与 owner 确认。
- **D-033** (2026-09-08, M3-COMPOSE): 调试素材(384×512/1.5625s, D-025)与生产幕长(3-5s)差 ~3×: 采用 tpad=stop_mode=clone hold-last-frame 补齐(任务书建议的保守方案)。build_compose_argv 新增 video_durations 入参保持纯函数可单测, compose_group 逐幕 ffprobe 自动喂入; 长素材仍由 trim 硬切, 色卡幕不探测。备选"setpts 慢放 3.2×"否决: 会放大 LTX 帧间伪影且扭曲运镜节奏。幕内单镜头停帧最长 ~3.44s, 幻灯片感为可接受调试产物属性(M5 量产素材 5s 天然对齐)。
- **D-034** (2026-09-08, M3-COMPOSE): G6 ASR 回转 CER 归一化口径: 参照与假设双侧经 normalize_for_cer——阿拉伯数字→中文读法(与 TTS 朗读一致, 39.9→三十九点九; 整数 0..9999 精确读法), 剥标点/空白/符号, casefold。不归一化则 whisper 的标点习惯与数字书写(39.91位 vs 39.9一位)会淹没真实错误。
- **D-035** (2026-09-08, M3-COMPOSE): BGM 程序合成(D-006 ducking 链路的真实验证载体): G 大三和弦正弦(196/246.94/293.66Hz)+amix+tremolo 0.4Hz+低通 1.5kHz → m4a, 终混经 volume≈0.2512(-12dB 预衰减)+sidechaincompress(threshold=0.03:ratio=12) 混入。零版权风险; 音质为占位级, M5 可换 CC0 循环或交付口播版(build_bgm_argv 与 bgm_path 参数均已有)。
- **D-036** (2026-09-08, M3-COMPOSE): G6 ASR 回转配置与热词披露: whisper-small(GPU) language=zh temperature=0 + 领域热词 initial_prompt="火锅店美食口播，词汇：老灶火锅、毛肚、锁鲜、到港、虾滑、肥牛、半价。"。依据: 无热词基线 CER=0.0645(93 字中 6 错)全部为同音字混淆(灶/造, 锁/所, 鲜/先, 港/岗, 份/分, 价/假), 无截断/漏句; 热词是 ASR 标准上下文偏置(等价领域词典), 不提供讲稿全文, 模型仍需真实识别音频——热词后 CER=0.0323(残差: 锁鲜→所先, 脆→翠), ≤5% 达标。报告同时披露两个数字。

- **D-037** (2026-09-08, M4-EXEC): M4 沙箱口径与选卡偏差。① 任务面原拟 e2e 选卡 S01/S03/S05+S12, 但该组合缺 hook_product/ambiance_scene 两个 slot, `compose_ready` 的 needed⊆have 判定永不满足→无法演示"自动合成"; 增选 S02/S07(M2 实测 accepted, 纯美食/店内类无 G5 偏差)共 6 卡, 未选 S08/S09/S11。② 沙箱(D-016)的完整隔离配方: config/templates/assets 拷贝 + **models 只读软链**(46G 不复制) + `CRADLE_CLIP_WEIGHTS=<SB>/models/clip/ViT-L-14.pt` + `HF_HUB_OFFLINE=1`——三者缺一则 gater 回落 `pretrained="openai"` 走 HF hub, 墙内 HEAD 超时重试 5 次/进程(实测卡死 4 分钟+), 属首跑实测踩坑。配方齐备后 e2e 全链 340s 无卡点。③ 演示工具: scripts/m4_start_orch.sh(exec 保证 $!=python PID)、scripts/m4_kill_when_mixed.sh(1s 轮询 DB 命中 gating≥1∧generating≥1 窗口即 kill -9+快照), kill -9 恢复演示(SPECS §6-M4 验收点)实测通过: 05:47:38 杀, 05:48:02 重启 recover 重置 1 孤儿, 05:53:20 六任务 composed+自动成片; gating 候选以 id+mtime 佐证未重生成, generating 孤儿按 D-012 重生成。
