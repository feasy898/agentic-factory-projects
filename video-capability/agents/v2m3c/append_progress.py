#!/usr/bin/env python3
"""Append V2-M3 section to PROGRESS.md."""
from pathlib import Path

SECTION = """

## V2-M3 完成 (2026-09-09, V2-M3C 接棒: 三车道重构运行时验证)
- [handover] 前手 V2-M3 写完三车道代码后、运行时验证前死亡(无提交); 固化 WIP commit `1d3c3cb`(42 files +3788 行)先于一切改动; 决策 D-060/062/063/064 按其代码引用补记(D-061 空号保留), 接棒新决策 D-065..D-069
- [tests] 3 失败修复 → **pytest 309 passed**: evidence 测试笔误(out 未定义)/lane_dispatch 夹具缺 evidence_asset(route 红线系设计行为)/**预算守卫真 bug**(守卫在 lane 分支后被 puregen/evidence 提前 return 绕过, 前置修复); 记 D-067
- [runtime] 运行时修复 4 处: ①evidence vid2vid 崩溃——Fun-InP has_image_input 要求 input_image 必传, 改源首帧+帧序列双条件(路径①维持, D-065); ②compositing 底片用源图尺寸(横图 1216x832 与 overlay 形状不匹配), 修为中心裁剪到卡面分辨率; ③orchestrator 门禁链 G7 自 V2-M1 起未注入模型 fn(全子项 skipped 假绿, 校准链有注入故未发现), 补注入后重跑; ④m3_lane_shots.sh 两处脚本错误(cd 沙箱/heredoc SQL 引号)
- [overlays] **6 条氛围循环素材入库** assets/overlays/(蒸汽x2/雾x2/光斑x2, 4s@16fps, 程序暗底首帧, Wan x6+重生成 x2); 审计口径 v2(D-066): 豁免条款贯彻(masked 静态区 DINO 首尾 cos)+时间最大亮度 mask+低纹理 RAFT 伪光流光度差/SSIM 复核, 终版 **3/6 PASS, 三类各≥1 可用**(steam_thin/mist_cool/light_warm); 首帧亮度 mask 全白失效与近黑 RAFT p95=150px 伪光流均实测暴露; 重生成裁定记 D-069
- [evidence] **合成源结构保持度验证通过**(D-068): zoompan+确定性粒子合成源 → d=0.30 重绘 → flow_cos 0.9177/0.9616 vs 正控(重编码)0.969/负控(异运动)0.0464, 深度相关性≥0.999; denoise=0.30 维持生产缺省
- [lane shots] **三车道实测 G1-G7 全链 accepted**(沙箱 cradle_m3): S01 compositing overall 0.9604(G7 0.9836, overlay=steam_thin)/S09 puregen 0.9451+0.9425(G7 0.9979, c 项 p95=0.503px 首尾锚定有效)/S18 evidence 0.9613(G7 0.9914); G7e 无 API skipped(D-004); 目检拼图+候选 mp4 留档 reports/milestones/v2m3_media/
- [report] `reports/milestones/V2_M3_lane_report.md`(三车道设计/路径取舍/审计/结构保持度/门禁分数/19 卡映射表)
- Wan 本轮约 18 次调用(累计 ≈78 ≤200); pytest 309 passed; commit "V2-M3: three-lane refactor validated (overlays + lane shots + synthetic-source)"
"""

p = Path("/root/cradle/PROGRESS.md")
s = p.read_text(encoding="utf-8")
p.write_text(s + SECTION, encoding="utf-8")
print("PROGRESS appended")
