# PROJECT CRADLE — 营销视频生成管线

「产品图 + 结构化镜头卡 → 无人值守生成营销短视频 → 六道自动门禁验收 → 失败自动重试与降级 → 程序化合成成片」
在 1× Tesla V100 32GB (Volta, sm_70) 上从零建成, 全程本地兜底、无人值守。最终交付: 9 条生产成片 (`output/`)、
良率报告与失败画廊 (`reports/`)、终报 `reports/FINAL_REPORT.md`。

- 快速了解结果 → `reports/FINAL_REPORT.md` (一页总览)
- 看片/校准阈值 → `output/*.mp4` + `reports/gallery_failures/INDEX.md` (24 个失败案例)
- 复现/改造 → 本 README 四指南
- 一切自主决策的依据 → `DECISIONS.md` (D-001..D-050)

> ⚠️ 口径提醒: 门禁 G2/G5 为 CLIP ViT-L/14 本地启发式口径 (未经 API VLM 审核, D-004);
> 生成模型为 PAI/Wan2.1-Fun-1.3B-InP (规格主选 I2V-1.3B 不存在, D-019)。

---

## 0. 项目结构

```
~/cradle/
├── SPECS.md                    # 任务书 (唯一指令来源)
├── PROGRESS.md                 # 过程台账 (M0-M6)
├── DECISIONS.md                # 全部自主决策 D-001..D-050
├── README.md                   # 本文件
├── config/
│   ├── settings.yaml           # 设备/路径/预算守卫/debug_model/prod_model
│   └── api.env                 # 可选 API (空=本地兜底), 见指南三
├── src/
│   ├── api/                    # 能力适配器: adapters.py(路由+预算+重试1次切兜底)
│   │                           #   image.py / vlm.py / tts.py / asr.py (API优先+本地兜底)
│   ├── gen/                    # 生成层: ltx.py(调试) wan.py(生产) kenburns.py common.py
│   ├── gates/                  # 六道门禁 g1_tech..g6_business (+vlm_prompt.txt)
│   ├── route.py                # 路由/重试/fallback/stable-borderline 短路(D-042)
│   ├── compose.py              # 程序合成: 硬切/ASS字幕/TTS对齐/BGM ducking/G6
│   ├── orchestrator.py         # 状态机+不动点推进+断点恢复+预算守卫
│   ├── cli.py                  # initdb/status/ingest/run/compose/compose-video/report
│   └── db.py config.py schema.py
├── templates/
│   ├── narrative/              # 3 叙事模板 ×(v1/v2/v3 变体) 25s/22s/17s
│   └── shotcards/              # 17 张镜头卡 S01-S17 (JSON Schema 校验)
├── assets/{products,scenes}/   # 11 张 SDXL 832×1216 竖版资产 + manifest.json
├── models/                     # 权重 (~46G, 不入 git): ltx/wan-fun-inp/sdxl/clip/whisper/yolo
├── workdir/                    # 运行时: cradle.sqlite3 + candidates/(候选+抽帧缓存)
├── output/                     # 成片 (mp4 不入 git, 目录里有实体文件)
├── reports/
│   ├── FINAL_REPORT.md         # 终报
│   ├── gallery_failures/       # 失败画廊 24 例 (mp4/jpg 已入库, ~14.4MB)
│   └── milestones/             # M1-M5 报告 + 溯源 SQL
├── scripts/                    # 01-08 环境脚本 + m3..m5 演示/量产脚本
├── tools/                      # 锚点探针/重评/画廊构建 (m5_anchor_probe, m6_build_*)
└── tests/                      # pytest 226 passed
```

---

## 指南一: 新机器复现

### 硬件/系统前提

| 项 | 要求 | 备注 |
|---|---|---|
| GPU | NVIDIA, ≥24GB 显存 (本项目 V100 32GB) | Volta 可跑; 若 Ampere+ 可解锁 flash/sage attention 提速 |
| 磁盘 | 预留 ≥80G (权重 46G + 运行时) | 本机 99G 盘, D-001 纪律: 可用 <20G 即停 |
| OS / Python | Linux, Python 3.12 | Ubuntu 22.04 实测 |
| 系统包 | ffmpeg (含 libx264/libass), fonts-noto-cjk, libgl1/libglib2.0 | 字幕烧录与合成依赖 |
| torch | **2.4.1+cu121** (不要 CUDA 13 系, Volta 已被移除支持) | fp16 only, bf16/FP8 无硬件加速 |

### 环境安装 (顺序执行, 均有日志)

```bash
cd ~/cradle
bash bootstrap.sh                          # M0: 目录骨架 + config 模板 + git init
# 以下按 scripts/ 编号 (对应 M1-ENV 实际执行序):
bash scripts/01_bootstrap.sh               # venv + 基础工具
bash scripts/02_torch_local.sh             # torch 轮子 curl 直连下载 (aliyun)
bash scripts/03b_torch_install.sh          # 本地轮子安装 torch 2.4.1+cu121
bash scripts/04b_pip_rest.sh               # 其余依赖 (aliyun pypi): diffsynth==1.1.9
bash scripts/04c_fix_stack.sh              # diffusers==0.33.1 / transformers==4.49.0 等
bash scripts/04_models.sh                  # 全部权重下载 (curl 断点续传, ~46G, 见下)
bash scripts/06_ltx_fp32.sh                # LTX fp32 布局补件
bash scripts/07_patch_diffsynth.sh         # diffsynth patchify 补丁 (D-022, 必须!)
bash scripts/08_verify_cleanup.sh          # Volta 自查 + CLIP/whisper/yolo 小件验证
```

**下载源策略 (D-021, 国内 CVM 实测)**: hf-mirror 文件 CDN 仅 24-196KB/s 不可用; 一律 **curl 直连** —
模型走 ModelScope `api/v1/models/<repo>/repo?FilePath=` (11-12MB/s), torch 轮子走 aliyun pytorch-wheels,
CLIP/whisper 走 openaipublic.azureedge.net; HF 仅用于公开小 json。断点续传 `-C -` + 每次大下载后 `df -h` 巡检。

**权重清单** (`models/`): `ltx-video-2b/` (7.7G+VAE 1.7G+FLUX T5-XXL fp16 9.5G)、`wan-fun-1.3b-inp/` 19.8G、
`sdxl-base-1.0-fp16/` 6.9G、`clip/ViT-L-14.pt` 0.93G、`whisper/small.pt` 0.46G、`yolo/yolov8n.pt` 6.5M。

### 一键验证 (端到端最小闭环)

```bash
# 沙箱全链: initdb → ingest 6 卡 → 生成→六门禁→路由→自动合成, 历史实测 340s
bash scripts/m4_e2e_demo.sh /root/cradle_m4_sandbox
# 产物: <沙箱>/output/product_seeding_25s.mp4 (1088×1920, 25s)
```

**沙箱配方 (D-037/D-038, 三要素缺一不可)**:

```bash
SB=/root/cradle_m4_sandbox
mkdir -p $SB && cp -r config templates assets $SB/
ln -s /root/cradle/models $SB/models                    # ① models 只读软链 (46G 不复制)
export CRADLE_ROOT=$SB
export CRADLE_CLIP_WEIGHTS=$SB/models/clip/ViT-L-14.pt  # ② 显式 CLIP 权重路径
export HF_HUB_OFFLINE=1                                 # ③ 离线开关 (否则回落 HF hub 被墙卡死)
```

日常操作 (CLI):

```bash
python -m src.cli initdb
python -m src.cli ingest templates/shotcards/S01_evidence_product.json --template product_seeding_25s
python -m src.cli run --once        # 不动点推进: 生成→门禁→路由→(重试/fallback)→合成
python -m src.cli status && python -m src.cli report
python -m src.cli compose-video --spec specs/my_video.json   # 显式合成 (D-043)
# 生产口径两开关: settings.yaml 加 prod_steps: 20 / prod_stylize_denoise: 0.3 (D-039/D-044)
# 调试口径: settings.yaml debug_model: ltx (生产卡自动投影为 384×512 短卡, D-025)
```

长任务一律后台 + 日志 (`setsid nohup ... > workdir/logs/xxx.log 2>&1 &`, 勿用 tmux 承载唯一进程, D-038 教训);
进程崩溃后直接重启 `run`, `recover()` 自动复位孤儿任务并保留已生成候选 (M4 kill -9 演示通过)。

---

## 指南二: 换底模 (生成模型)

### 现有布局

| 车道 | 模型 | 接入文件 | 装配要点 (均已踩坑定版) |
|---|---|---|---|
| 调试 (迭代期) | LTX-Video 2B v0.9.x (diffusers 布局) | `src/gen/ltx.py` | T5 用 FLUX.1-dev fp16 (D-020); fp32 shard 加载转 fp16; steps≤12/384×512 |
| 生产 (产出期) | **PAI/Wan2.1-Fun-1.3B-InP** (DiffSynth 1.1.9) | `src/gen/wan.py` | ModelManager 四件套 (umt5/clip/DiT/VAE); **negative_prompt 必须逗号串**, list 会 batch 错配崩 (D-028); cfg 5.0 |
| 降级 | ffmpeg zoompan (Ken Burns) | `src/gen/kenburns.py` | 超采样 4× 抗抖动; n_best=1 (D-013) |

### 换模步骤

1. 权重落盘到 `models/<new-model>/` (建议 diffusers 布局或 DiffSynth ModelManager 可识别布局, fp16 优先省盘)。
2. 在 `src/gen/` 新增或改造 wrapper, 对齐现有契约: `generate(card, seed, out_path, hint) -> meta`
   (meta 需含 path/model/steps/num_frames/duration_s/fps/vram_peak_mb/gen_seconds/vae_mode)。
3. 注册到 `orchestrator.generator()` 的选择逻辑 (现按 `settings.debug_model` / `prod_model` 分发)。
4. 分辨率/帧数硬校验同步: `gen/wan.py` 内 480p/81帧/steps 范围校验按新模型产线参数修改。
5. **先冒烟再量产 (D-019/D-022 血训)**: 单镜头单候选跑通六门禁 (对齐 `m2_wan_verify.json` 流程), 全绿后才允许批量 —
   本项目两次大坑 (官方 I2V-1.3B 不存在、镜像站 diffsynth wheel 被重打包损坏) 都是被冒烟拦住的。
6. 换模后门禁分数分布会变 (Wan 81 帧长片比 LTX 短片 G3/G4 系统性更低一档, 见 FINAL_REPORT §4), 阈值勿直接沿用结论。

---

## 指南三: 换 API (接入真实 VLM / 云端能力)

### 格式 (`config/api.env`, OpenAI 兼容)

```ini
IMAGE_API_BASE=   IMAGE_API_KEY=   IMAGE_MODEL=
VLM_API_BASE=     VLM_API_KEY=     VLM_MODEL=
TTS_API_BASE=     TTS_API_KEY=     TTS_API_MODEL=
ASR_API_BASE=     ASR_API_KEY=     ASR_API_MODEL=
```

填上即自动走 API; 留空走本地兜底 (SDXL img2img / CLIP 启发式 / edge-tts / whisper-small)。

### 适配器位置与行为

- 路由与预算: `src/api/adapters.py` — 每次调用按 `route=api|local` 记入 SQLite `api_usage` 表;
  **失败重试 1 次后自动切本地兜底并计数** (管线不停摆, SPECS §2); 预算守卫见 `config/settings.yaml`
  `budgets:` (生图 300 / VLM 1500 / TTS 200 / ASR 200), 耗尽即切兜底。
- 能力实现: `src/api/{image,vlm,tts,asr}.py`; VLM 判分契约 (含评分公式与非法 JSON 处理) 见
  `src/gates/vlm_prompt.txt` + `src/gates/g5_aesthetic.py`, API 返回必须是对应 JSON 结构。

### 接入真实 VLM 后建议做的事 (本项目的最大口径升级)

1. 用真实 VLM 复审 `reports/gallery_failures/` 24 例 + M2 存量候选, 重定 G5 阈值 (当前 0.70 是启发式口径的产物);
2. G2 的 subject_missing 真语义化 (现仅"内容丧失"代理, 检不出主体错型, D-026);
3. ASR 若换云端, G6 CER 同音字问题大概率消失 (差集全是 ASR 同音混淆, D-047), 或改 pinyin 归一口径。
注: G6 的 ASR 回转为门禁内直连 (`asr_fn` 注入), 不经 api_usage 记账 — 统计口径见 FINAL_REPORT §6。

---

## 指南四: 换真实实拍资产

### 现有布局

```
assets/products/  maodu_01.png soup_01.png shrimp_01.png beef_01.png dessert_01.png drink_01.png + manifest.json
assets/scenes/    interior_01.png table_01.png storefront_01.png rain_window_01.png back_view_01.png
```

- 规格: 832×1216 竖版 (SDXL portrait 桶), **单一事实源** —— 生成时按需 center-crop/resize, 无派生目录 (D-029)。
- `manifest.json`: 每张的 asset 路径 / shot_id / seed / steps / guidance / prompt / negative / 尺寸, 换资产请同格式登记。

### 换成实拍图的步骤 (管线零改动)

管线**不区分锚点是生图还是实拍** (资产层与生成层解耦, SPECS §5.1): 把实拍图按同名/新名放入
`assets/{products,scenes}/`, 然后改镜头卡 `templates/shotcards/S*.json` 的两个字段:

```json
"first_frame_asset": "assets/products/my_real_dish.jpg",   // I2V 首帧 + G3 参考图 + KenBurns 源
"fallback": {"type": "ken_burns", "asset": "assets/products/my_real_dish.jpg", ...}
```

实拍图建议 ≥832×1216、主体居中 (center-crop 安全区)、曝光统一; 每换一批建议跑一次
`tools/m5_anchor_probe.py` 式锚点探针, 确认 G5 锚对新材料不是系统性偏低 (本项目最大的失败教训就是锚与新资产类型不匹配, 见画廊类型A)。

### ⚠️ 镜头风险表 (选资产前必读, SPECS §5.2)

| 风险 | 内容 | 处置 |
|---|---|---|
| 低风险 | 产品特写微动作 / 环境空镜 | 生成主力 (I2V 车道) |
| 中风险 | 单主体中动作 / 无人背影 | n_best 放大 + 重试 (参考 S11: n_best=4/retry_max=3) |
| **高风险** | **人脸 / 手部 / 多主体 / 文字数字入画** | **禁止生成, 直接 fallback (ken_burns 车道)** — 含人脸/手的实拍图必须走 ken_burns (先例 S12), 文字/价格一律程序渲染进字幕 (D-015) |

镜头卡 schema 会强制校验 negative 必含 "human face/hands/text" 等字段; 违反风险表的卡在 ingest 即被拒。

---

## 附: SQLite 追溯查询快速上手

库文件: `workdir/cradle.sqlite3` (服务器无 sqlite3 CLI 时用 `python3 -c "import sqlite3..."` 或 DB Browser)。

```sql
-- 任务状态全景
SELECT shot_id, status, attempts, seed, steps, vram_peak_mb FROM tasks ORDER BY shot_id;

-- 每条成片 → 镜头 → 候选 → 六门禁分数反查 (M5 核心追溯, m5_videos 台账)
-- 现成脚本: reports/milestones/m5_trace_query.sql (5 条, 实测 5/5 可用)
SELECT v.video_id, v.slots_json, c.shot_id, c.verdict, c.overall_score
FROM m5_videos v, candidates c WHERE c.selected=1;

-- 任一候选的六门禁原始 JSON (含每门禁 score/passed/detail)
SELECT path, verdict, overall_score, gate_json FROM candidates WHERE verdict='fail';

-- API/本地调用记账 (D-008 口径: route=api 计预算, local 不计)
SELECT capability, route, COUNT(*) FROM api_usage GROUP BY capability, route;
```

更多现成查询: `reports/milestones/m2_gate_query.sql` (M2 库), `m5_trace_query.sql` (M5 成片台账);
画廊案例的逐门禁解读见 `reports/gallery_failures/*/case.md`。
