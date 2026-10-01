# 任务书:营销视频生成管线 PROJECT CRADLE v1.0
## 0. 总则
你可以通过内网，链接到一台配备 NVIDIA V100 32GB 的 Linux 服务器。具体连接方法，可以查看D盘下的相关指引。拥有 shell、文件读写、pip 安装、网络下载权限。本任务书是你唯一的指令来源,自包含,不依赖你看不到的任何对话历史。
**你的第一个动作**:把本任务书完整保存到 `~/cradle/SPECS.md`,此后一切工作以该文件为准,并建立 git 仓库。
**总目标**:从零建成一条管线——「产品图 + 结构化镜头卡 → 无人值守生成营销短视频 → 六道自动门禁验收 → 失败自动重试与降级 → 程序化合成成片」——并用真实运行产出:8-10条成片、良率统计报告、失败案例库。用户只在最终看报告和成片,中途不会回答任何问题。
**自主性三原则**:
1. 禁止向用户提问。规格未覆盖的决策点,选最保守可靠的方案,记入 `DECISIONS.md`(编号+理由),继续推进。
2. 诚实性:任何"已完成"声明必须由自动化测试或产物文件佐证。做不到的如实标注"未达成+原因"。
3. 守卫:墙钟总预算 ≤5天;到期无论进度,停止生成,写最终报告交付已有成果。
## 1. 硬件事实(不可协商)
| 项 | 值 |
|---|---|
| GPU | 1× Tesla V100 32GB,Volta架构,compute capability 7.0 |
| 限制1 | 不支持 FlashAttention-2 / SageAttention(需 Ampere+)。一切 attention 走 PyTorch SDPA 或 Volta 可用的 xformers 版本 |
| 限制2 | 无 BF16 硬件加速。**所有模型强制 FP16 推理**;bf16 会导致回退或不可用 |
| 限制3 | 不支持 FP8(DiffSynth 的 fp8 量化模式不可用) |
| torch | ≥2.1,选 cu118 或 cu121/cu124 轮子。**不要装 CUDA 13 系(已移除 Volta 支持)** |
| 磁盘 | 预留 ≥150GB,开工前 `df -h` 检查 |
| 下载 | HuggingFace 一律设 `HF_ENDPOINT=https://hf-mirror.com`,用支持断点续传的方式下载 |
**FP16 数值风险预案**:视频扩散模型纯 fp16 偶发 NaN(黑屏/花屏)。若出现:① VAE 改 fp32;② 局部关 autocast;③ 记入 DECISIONS.md。
## 2. 外部 API 与本地兜底(双路径,缺 API 不许停摆)
用户可能在 `config/api.env` 提供以下 API(也可能为空):
```
IMAGE_API_BASE= IMAGE_API_KEY= IMAGE_MODEL=
VLM_API_BASE=  VLM_API_KEY=  VLM_MODEL=
TTS_API_BASE=  TTS_API_KEY=  TTS_MODEL=
ASR_API_BASE=  ASR_API_KEY=  ASR_MODEL=
```
每个能力实现"API优先、本地兜底",统一在 `src/api/` 做适配器(OpenAI 兼容格式优先;调用失败重试1次后切兜底并计数):
| 能力 | API(若提供) | 本地兜底(必须实现) |
|---|---|---|
| 生图/改图 | OpenAI兼容图像接口 | diffusers + SDXL(fp16,32G可跑) |
| VLM 视觉质检 | OpenAI兼容,图像输入 | CLIP ViT-L/14 启发式评分,报告中标注"该批未经VLM审核" |
| TTS | OpenAI兼容 | edge-tts(免费) |
| ASR | OpenAI兼容 | openai-whisper small;均不可用则跳过对应门禁并记录 |
**预算守卫(硬性)**:生图≤300次、VLM≤1500次、TTS≤200次、ASR≤200次。耗尽即切本地兜底,报告实际用量。
## 3. 技术选型(已定死;仅主选不可救药时走备选并记录)
| 组件 | 主选 | 备选链 |
|---|---|---|
| 生成框架 | DiffSynth-Studio(纯Python,程序可控) | Wan2.1官方repo → ComfyUI API模式 |
| 调试模型(迭代期唯一允许) | LTX-Video 2B,≤2秒,384×512,steps≤15 | — |
| 产出模型 | Wan2.1-I2V-1.3B,fp16,480p,81帧@16fps(约5秒) | Wan2.1-T2V-1.3B |
| 主体检测 | YOLOv8n | VLM 替代 |
| 一致性/语义 | open_clip ViT-L/14 | CLIP ViT-B/32 |
| 稳定性 | 相邻帧 CLIP 相似度(必做)+ RAFT-small 光流残差 P95(尽力,Volta 兼容性自查) | 仅 CLIP |
| 合成 | FFmpeg 命令行 | moviepy 仅辅助 |
| 编排 | 纯 Python 主循环 + SQLite 任务表 | — |
**开工自查**:装完 torch 验证 fp16 张量前向、SDPA 前向、`get_device_capability()==(7,0)`。任何依赖隐式要求 flash-attn 时,找其禁用开关降级,不要死磕编译。
## 4. 架构与仓库
七层:`L0触发(本期用手动任务表代替,留接口) → L1叙事模板 → L2镜头卡 → L3资产 → L4生成 → L5六道门禁 → L6程序合成`。
```
~/cradle/
  config/{settings.yaml, api.env}
  SPECS.md  PROGRESS.md  DECISIONS.md  README.md
  src/{api/, gen/{ltx.py,wan.py}, gates/{g1..g6}, route.py, compose.py, orchestrator.py, cli.py}
  templates/{narrative/, shotcards/}
  assets/{products/, scenes/}
  tests/
  workdir/{candidates/, gated/}
  output/
  reports/{milestones/, gallery_failures/, FINAL_REPORT.md}
```
**断点续跑(强制)**:任务状态机 pending→generating→gating→accepted/retrying→fallback→composed 持久化于 SQLite;长任务一律 nohup 后台+日志文件;进程崩溃后重启 orchestrator 从断点继续,不依赖你的会话存活。
## 5. 核心规格
### 5.1 测试资产(贯穿案例:火锅店)
用生图API或SDXL产出10张竖版测试资产:毛肚特写、沸腾红汤锅底、虾滑、肥牛卷、甜品、饮品、店内暖光蒸汽环境、门头夜景、雨窗氛围、空餐桌。1024px级,风格统一(暖色/食欲感/浅景深)。每张图同时充当:I2V首帧、Ken Burns降级源、门禁参考图。
设计要点:管线不区分锚点是生图还是实拍——将来换成真实照片零改动。资产层与生成层解耦。
### 5.2 镜头卡 Schema(JSON 校验,字段定死)
```json
{
  "shot_id": "S03",
  "narrative_slot": "evidence_product",
  "lane": "first_frame_i2v",
  "orientation": "portrait",
  "duration_sec": 5, "resolution": [480, 832], "fps": 16,
  "camera": {"scale":"closeup","angle":"high_45","motion":"slow_push_in","depth":"shallow"},
  "subject": {"type":"object","desc_zh":"毛肚浸入沸腾红汤,油花翻涌,蒸汽升腾"},
  "prompt_en": "...",
  "first_frame_asset": "assets/products/maodu_01.png",
  "negative": ["human face","hands","fingers","text","watermark","logo","deformed","extra limbs"],
  "n_best": 3, "retry_max": 2,
  "acceptance": {
    "clip_ref_min": 0.65, "clip_text_min": 0.22, "temporal_clip_min": 0.85,
    "vlm_overall_min": 0.70, "vlm_defect_max": 0.2, "duration_tol": 0.5
  },
  "fallback": {"type":"ken_burns","asset":"assets/products/maodu_01.png","motion":"zoom_in_1.06","duration_sec":5}
}
```
`lane` 枚举:`first_frame_i2v | t2v | ken_burns | future_3d_guided`(3D引导车道本期不实现,仅留枚举位)。
**镜头风险表(镜头卡设计依据)**:低风险=产品特写微动作/环境空镜(生成主力);中风险=单主体中动作、无人背影(n_best放大+重试);**高风险=人脸/手部/多主体/文字数字入画——禁止生成,直接fallback**。negative 必含人脸/手/文字。
**画幅**:主目标竖版480×832(投放场景为竖屏平台)。先各测5镜头对比竖/横质量,竖版明显劣则全量横版,结论记入 DECISIONS。
### 5.3 生成层
- 迭代期一律 LTX 短样本校准门禁,门禁全链路跑通之前**禁止碰 Wan**;
- 产出期 Wan2.1-I2V-1.3B:480p、5秒、steps 20-30 起步按实测耗时调整;每镜头 n_best=3(不同seed);首帧先经 img2img 低强度重绘(denoise 0.2-0.35)统一风格;
- 每次生成记录 seed/steps/耗时/显存峰值入 SQLite;
- 产出期总量守卫:Wan 候选总数 ≤200 次(超出即停,保交付)。
### 5.4 六道门禁(阈值=冷启动值,校准过程写进报告)
| # | 门禁 | 实现 | 判据 |
|---|---|---|---|
| G1 技术 | ffprobe | 时长±0.5s、分辨率/fps正确、无全黑全白帧 | 硬性 |
| G2 完整性 | VLM | deformed/morphing/garbled_text/subject_missing 各<0.3 | 无VLM时YOLO+启发式 |
| G3 一致性 | CLIP | 每帧与首帧参考相似度最小值≥0.65 | |
| G4 稳定性 | CLIP 相邻帧≥0.85(+可选RAFT残差P95) | |
| G5 美学 | VLM 结构化评分 | overall_score≥0.70 且 overall_defect≤0.2 | |
| G6 业务 | 程序比对 | 字幕文本逐字等于模板数据;TTS→ASR回转 CER≤5%(可选) | 硬性 |
**VLM 评分提示词全文**(存 `src/gates/vlm_prompt.txt`;视频均匀抽10帧,2×5网格拼图或逐帧,按API能力适配;非法JSON重试1次,再失败按 borderline+低分并标记解析失败):
> 你是严格的视频质检员。检查这段视频的抽帧,只输出一个JSON对象,不要任何其他文字。字段:{"defects":{"deformed_object":0.0-1.0主体变形融化扭曲程度,"morphing_artifact":0.0-1.0画面异常形变,"flicker":0.0-1.0闪烁抖动,"garbled_text":0.0-1.0乱码伪文字,"subject_missing":0.0-1.0主体缺失,"unnatural_motion":0.0-1.0运动诡异,"overall_defect":0.0-1.0综合缺陷},"aesthetic":{"composition":1-5,"lighting":1-5,"color":1-5,"appeal":1-5吸引力/食欲感,"overall":1-5},"camera_match":1-5是否符合指定运镜,"overall_score":0.0-1.0(=0.45*(1-overall_defect)+0.35*(aesthetic.overall/5)+0.2*(camera_match/5)),"verdict":"pass|borderline|fail","main_issue":"一句话中文"}。判定:overall_score≥0.70 且 overall_defect≤0.2 且 garbled_text≤0.3 → pass;0.55-0.70 → borderline;<0.55 或任一分项≥0.5 → fail。
### 5.5 路由与降级
```
每镜头:n_best 全过门禁 → 有pass → 取 overall_score 最高者
→ 全fail → 换seed重试(≤2轮,允许加强negative/降guidance 0.5)
→ 仍fail → fallback(Ken Burns:ffmpeg zoompan,注意用先超采样再zoompan的稳定公式避免抖动,可靠性100%)
→ 源图缺失 → 标记blocked入报告
```
### 5.6 合成层(零生成,纯程序)
硬切剪辑;钩子段(0-3s)允许1秒短镜头高密度;口播=TTS(稿由模板数据渲染,语速-10%);字幕ASS烧录与TTS时间轴对齐;**价格/优惠数字一律程序渲染(字幕/贴片),禁止进入生成画面**;BGM可选(程序合成或CC0循环,口播段ducking -12dB,没有则交付口播版);输出H.264竖版1088×1920(或备选横版)。
### 5.7 叙事模板(3个,JSON)
1. **产品种草** 25-30s:钩子产品高光3s → 证据镜头3×5s → 氛围4s → CTA贴片3s;
2. **到店氛围** 20-25s:门头钩子 → 环境空镜×2 → 产品点缀 → CTA;
3. **即时优惠** 15-20s:优惠字卡+产品短镜头×2 → 产品镜头×2 → CTA。
每幕绑 narrative_slot,同 slot 可换镜头卡——这是变体能力的来源。
## 6. 执行顺序(连续执行,无人值守)
| M | 内容 | 墙钟 | 产物佐证 |
|---|---|---|---|
| M1 | 环境与基线 | ≤0.5天 | Volta自查通过;LTX、Wan各成功1条测试视频+截图 |
| M2 | 单镜头闭环 | ≤1天 | LTX 上≥10镜头跑通"卡→生成→六门禁→路由";良率报告v1 |
| M3 | 合成层 | ≤0.5天 | LTX镜头拼1条完整成片(含TTS/字幕/CTA) |
| M4 | 端到端 | ≤0.5天 | cli一键出片;故意kill进程并恢复续跑,演示通过 |
| M5 | 产出与良率 | ≤2天 | Wan 产出8-10条成片,最终良率统计 |
| M6 | 收尾 | ≤0.5天 | 失败画廊、FINAL_REPORT、README、git整理 |
每完成一个M:更新PROGRESS.md、commit、在 reports/milestones/ 留产物索引。(可选P2,时间富余才做:同镜头卡多风格变体演示。)
## 7. 最终交付物(用户只看这些)
1. **`reports/FINAL_REPORT.md`**:一页总览(良率/成本/耗时/结论,可用标准=含降级交付率≥95%);样片索引表;良率统计+失败聚类;阈值表(冷启动值→校准后值+依据);局限与建议;API用量;DECISIONS 附录。
2. **`output/`**:8-10条成片。
3. **`reports/gallery_failures/`**:≥20个典型失败候选,按失败类型组织,每个附视频/各门禁得分/main_issue/所属镜头卡。**这是用户校准阈值的主要材料,认真挑选有代表性的。**
4. **`README.md`**:新机器复现指南、换底模指南、换API指南、换真实实拍资产指南。
## 8. 工作纪律
PROGRESS.md 每任务块更新;DECISIONS.md 记录全部自主决策;每M一个git commit;长任务后台化+日志;不提问,一切疑问转 DECISIONS 条目+保守选择。
## 9. 预判的坑(预案已内置)
① flash-attn 被隐式要求→找禁用开关降级;② fp16 NaN→VAE fp32;③ 下载慢→hf-mirror+断点续传;④ DiffSynth 在 Volta 不可救药→备选链,架构不变,记录切换原因;⑤ Wan 竖版质量差→横版全量+报告说明;⑥ OOM→文本编码器 CPU offload、候选串行、及时清缓存;⑦ VLM 不支持多帧→抽帧网格图;⑧ zoompan 抖动→超采样公式;⑨ 自身上下文漂移→一切状态落盘,不依赖记忆;⑩ API 欠费/未填→兜底链自动接管,报告标注。
## 10. 最终自检清单(全部满足才允许写"任务完成")
□ M1-M6 均有产物佐证 □ ≥8条 Wan 成片在 output/ □ 每条成片门禁明细可追溯(附SQLite查询脚本) □ 失败画廊≥20例 □ FINAL_REPORT 四节齐全 □ 崩溃恢复演示通过 □ README 完整 □ DECISIONS 全记录 □ git 历史干净
