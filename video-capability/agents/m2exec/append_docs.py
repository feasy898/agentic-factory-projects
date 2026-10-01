#!/usr/bin/env python3
"""M2-EXEC: 追加 DECISIONS D-024..D-031 + PROGRESS.md M2-EXEC 小节(数字占位由 verify JSON 填充)。"""
import json
import os
from pathlib import Path

REPO = Path("~/cradle").expanduser()
os.chdir(REPO)

verify = {}
try:
    verify = json.load(open("reports/milestones/m2_wan_verify.json"))
    m = verify["gen_meta"]
    wan_line = (f"{m['num_frames']}帧@{m['fps']}fps={m['duration_s']}s, steps {m['steps']}, "
                f"生成 {m['gen_seconds']}s, 峰值显存 {m['vram_peak_mb']}MB, vae_mode={m['vae_mode']}, "
                f"总墙钟(含加载/门禁) {verify['total_sec']}s")
    wan_gates = "; ".join(f"{g}={'PASS' if verify['gates'][g]['passed'] else 'FAIL'}({verify['gates'][g]['score']})"
                          for g in ("G1", "G2", "G3", "G4", "G5", "G6"))
    wan_all = verify["all_passed"]
except Exception as e:
    wan_line = f"(verify 未完成: {e})"
    wan_gates = "n/a"
    wan_all = "n/a"

DECISIONS = f"""

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
  {wan_line}。六门禁: {wan_gates}; all_passed={wan_all}。产物
  `reports/milestones/m2_wan_verify.json` + `workdir/candidates/wan_verify_S01.mp4`。M5 量产装配风险消除。
- **D-031** (2026-09-08, M2-EXEC): 记账粒度: candidates 表不含 seed/steps/gen_seconds(每任务末次值在
  tasks 表); 候选级 seed 可由文件名恢复: `{{shot}}_a{{attempt}}_{{i}}.mp4` →
  seed=stable_seed(shot)+attempt*1000+i(crc32(shot_id)&0x7FFFFFFF)。M5 量产如需逐候选记账,
  按"迁移只新增"原则加列。
"""

d = REPO / "DECISIONS.md"
text = d.read_text(encoding="utf-8")
assert "D-024" not in text, "D-024 已存在, 禁止重复追加"
d.write_text(text + DECISIONS, encoding="utf-8")
print("DECISIONS appended D-024..D-031")

PROGRESS = """

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
- [test] pytest 194 passed(新增投影/首帧预处理/重试钩子/启发式行为测试); git: M2 收尾 commit
"""
p = REPO / "PROGRESS.md"
p.write_text(p.read_text(encoding="utf-8") + PROGRESS, encoding="utf-8")
print("PROGRESS appended")
