# M4 端到端一键出片演示 (m4_e2e_demo)

- 日期: 2026-09-08 05:28-05:34 (服务器时间)
- 结论: **PASS** — 全新 CRADLE_ROOT 沙箱内, 一条命令完成 initdb → ingest(6 卡) → run --once(生成→六门禁→路由→合成), 6/6 任务 composed, 成片自动产出, 总墙钟 **340s**。

## 1. 沙箱环境 (D-016 隔离)

- 沙箱根: `/root/cradle_m4_sandbox` (真实 workdir/cradle.sqlite3 零接触)
- 构成: `config/` `templates/` `assets/` 完整拷贝; `models -> /root/cradle/models` **只读软链**(46G 权重不复制);
  `m4_cards/` 为 6 张选定镜头卡副本
- 卡片选择 (D-037): S01/S03/S05(证据) + S02(钩子) + S07(氛围) + S12(ken_burns 车道)。
  任务书原拟 S01/S03/S05+S12 缺 hook_product/ambiance_scene 两个 slot, `compose_ready` 的
  needed⊆have 永不满足, 无法演示"自动合成", 故按"美食类全过 G5"口径增选 S02/S07 (M2 实测 accepted)
- 沙箱环境变量 (坑, 见 §5): `CRADLE_ROOT=/root/cradle_m4_sandbox CRADLE_CLIP_WEIGHTS=$SB/models/clip/ViT-L-14.pt HF_HUB_OFFLINE=1`

## 2. 一键命令

```bash
bash /root/cradle/scripts/m4_e2e_demo.sh /root/cradle_m4_sandbox
# 脚本内: CRADLE_ROOT=... python -m src.cli initdb
#      && python -m src.cli run --task-file $SB/m4_cards --template product_seeding_25s --once
#      && python -m src.cli status / report
# run --task-file --once: ingest 后单命令跑完 生成→G1-G6→路由(重试/fallback)→不动点→合成 (D-014)
```

日志: `沙箱/workdir/logs/m4_e2e.log`

## 3. 时间轴与结果

| 时刻 | 事件 |
|---|---|
| t+0s | initdb (schema v1) |
| t+0s | ingest 6 卡: 6 成功 0 拒绝 (S12 ken_burns 不投影, 生产口径 480×832/5s; 其余投影 LTX 调试卡 384×512/1.5625s, D-025) |
| t+0..340s | run --once 不动点推进: LTX 加载 ~50s → 15 候选生成(5 LTX×3 + 1 kenburns) → 逐候选 G1-G6 门禁(CLIP 本地权重) → 全部 accept(无重试/无降级) → compose_ready 自动合成(每幕自适应语速 edge-tts + ASS 烧录 + 程序 BGM ducking) |
| t+340s | status: **composed=6**, 候选 verdict **pass=16**; report: `yield_accepted_rate=1.0`, `yield_with_fallback_rate=1.0`, `unfinished=0 blocked=0` |

```
2026-09-08 05:34:14,356 INFO 成片完成: product_seeding_25s -> /root/cradle_m4_sandbox/output/product_seeding_25s.mp4
2026-09-08 05:34:14,357 INFO run --once: 推进 12 个任务
```

## 4. 产物 (沙箱内)

| 文件 | 属性 |
|---|---|
| `output/product_seeding_25s.mp4` | **h264 1088×1920@16fps + aac, 25.000s, 5.6MB** (ffprobe 实测) |
| `output/product_seeding_25s.mp4.ass` | 烧录字幕(Noto Sans CJK) |
| `output/*.voice{0-5}.mp3, .voice.m4a` | 每幕 TTS + 拼接音轨(中间件) |
| `workdir/m4_yield_report.json` | 良率统计 |

- 合成级 G6(D-011)在管线内执行: ASS Dialogue 与模板渲染文本逐字比对(硬性, 构造性相等);
  ASR 回转 CER 为可选项, 编排器默认跳过并记录(完整两级实跑见 M3 报告 CER=0.0323)
- API 用量: tts api=0 local=10(6 幕 + 4 次自适应语速迭代, D-032); 其余能力 0(全本地, D-004)

## 5. 踩坑记录 (已修复, 复现指南必读)

1. **沙箱缺 models 软链 → gater 回落 `pretrained="openai"` 走 HF hub**, 墙内连接超时
   (huggingface.co HEAD 重试 5 次/进程, 分钟级卡死; 首跑实例: 05:24 启动 05:28 仍在 CLIP 加载)。
   修复: 沙箱 `ln -s /root/cradle/models <SB>/models` + 显式 `CRADLE_CLIP_WEIGHTS` + `HF_HUB_OFFLINE=1`
   (D-027 权重本地化机制在沙箱根下需要这三个条件齐备)。
2. 首跑被杀后重置沙箱 DB/candidates/output, 重跑即上方 340s 的干净结果。
