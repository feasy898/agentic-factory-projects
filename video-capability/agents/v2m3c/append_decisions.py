#!/usr/bin/env python3
"""Append V2-M3 decisions (D-060..D-067) to ~/cradle/DECISIONS.md."""

APPEND = """

---

## V2-M3 三车道（接棒补记与新决策）

> 说明: 前手 V2-M3 代理写完三车道代码后、运行时验证前死亡（无提交、未写决策），
> 但其代码注释已引用 D-060/D-062/D-063/D-064 编号。V2-M3C 依其代码与注释如实补记
> 这四条（标注"补记"），D-061 为前手空号（代码无引用，保留跳过），接棒新决策从
> D-065 起。补记内容以 git 1d3c3cb（WIP 固化）代码文本为依据。

- **D-060** (2026-09-08, V2-M3 前手/补记): v2 三车道生成路径侦察。①evidence_transfer
  vid2vid = diffsynth 1.1.9 原生 WanVideoPipeline(input_video=帧序列,
  denoising_strength=0.2-0.35) 低强度视频重绘（路径①, 零新模型; 帧预缩放到产线分辨率
  由调用方负责——preprocess_images 不缩放）; 备选路径未启用。②pure_gen_short 几何锁定
  = 路径 a: Fun-InP 原生 end_image 首尾帧锚定（末帧=首帧资产, 固定机位下最强几何约束）,
  复用缓存管线; 路径 b 分段法(segmented_generate)留备份不用于生产。③compositing_2d5 =
  Depth-Anything 深度分层(前≥65分位) + 羽化 + 双层视差运镜 + overlay screen 混合
  (默认上方 1/3), 全纯代码确定性渲染, 食物不参与生成（形变物理性消灭）。
- **D-062** (2026-09-08, V2-M3 前手/补记): 三车道编排接入口径。①schema v4: LANES 扩为
  6 枚举(删 t2v), 食物 subject 禁入 pure_gen_short + 该车道时长限 1-2s,
  evidence_asset 仅 evidence 车道可用且必填; ②DETERMINISTIC_LANES={ken_burns,
  compositing_2d5} 生成 n_best 视为 1（确定性渲染多 seed 无意义, D-013 扩展）;
  ③WAN_CONSUMING_LANES={first_frame_i2v, pure_gen_short, evidence_transfer} 为预算守卫
  计数口径（SQL 兼容并集 t2v 历史行）; ④车道分发优先于 debug_model=ltx 投影, cli ingest
  的 LTX 投影收紧到仅 first_frame_i2v; ⑤prod_stylize_denoise 首帧风格统一仅
  first_frame_i2v 适用（compositing 不得改产品图底, evidence 必须贴源）; ⑥沙箱 settings
  生产口径 + evidence_denoise=0.30。
- **D-063** (2026-09-08, V2-M3 前手/补记): 19 张 v2 镜头卡映射（tools/m3_gen_shotcards_v2.py
  确定性重写 v1 卡）。食物/产品(S01-S06,S13,S14,S15,S17)→compositing_2d5,
  n_best=1/retry=0; 环境(S07-S11,S16)→pure_gen_short 1-2s 固定机位; S12(手部高风险)
  →ken_burns 原样; +S18/S19 evidence_transfer 演示卡（evidence_asset 指向合成测试源,
  报告标注演示源非实拍）。**S15 裁定**: 任务面原清单把 S15 列入环境组, 但其主体=红汤
  锅底（食物）, 按 §5.2 红线（食物禁入 pure_gen_short）归 compositing_2d5——红线优先。
  另有 narrative_v2 两份模板（product_seeding_30s/store_ambiance_28s）。
- **D-064** (2026-09-08, V2-M3 前手/补记): overlay 素材 G7 审计豁免口径（设计稿）。
  overlay 的"动态本体"就是蒸汽/雾/光斑, 按 G7e 豁免条款其自身运动不算缺陷; 审计对象
  =静态暗底背景必须稳定; a/b（主体一致性/计数）按豁免仅记录不判死。**运行时修正见
  D-066**: 前手实现把 G7d 保留为全帧口径且未注入模型 fn, 与豁免条款自相矛盾且审计空转。
- **D-065** (2026-09-09, V2-M3C): evidence vid2vid 运行时修正——Fun-InP 是
  has_image_input 结构模型, DiT 前向无条件 cat([x,y])（diffsynth wan_video.py L567）,
  y 必须由 input_image 经 encode_image 编码; 前手 D-060 路径①代码传 first_frame=None
  → TypeError: expected Tensor as element 1 实测崩溃。修正: pipeline 调用同时传
  input_video（帧序列, 噪声底=源视频低强度重绘）+ input_image=源首帧（y 条件, msk 仅
  首帧作用域）——双条件不改变"重绘贴源"语义, 且首帧条件强化结构锚定;
  open_center_resize 扩展接受 PIL.Image（源首帧已在产线分辨率, 免落盘）。重跑验证:
  d=0.30 重绘成功, 结构保持度见 D-068。**路径①维持**, 备选路径（坑③）无需启用。
- **D-066** (2026-09-09, V2-M3C): overlay 审计口径 v2（豁免条款贯彻 + 低纹理复核）。
  前手审计工具两处运行时缺陷: ①g7_object_persistence 不内置模型加载, 未注入
  embed/detect/flow fn → 全子项 skipped 空转（score 恒 1.0, 6/6 PASS 无度量, 属假通过）;
  ②G7d 全帧首尾余弦与豁免条款自相矛盾——steam_dense/mist_cool/light_warm/bokeh_dust
  的动态本体占画面主体, 本体演化直接打穿 0.84（实测全帧 cos 0.27-0.90）。v2 口径:
  **c'** = 静态暗底区(首帧亮度<60)稳定——RAFT P95≤30px, 但近黑低纹理区 RAFT 无纹理可追
  产生伪光流（ov_fog_low 目检静止却 p95=46.3px, 实测教训）, 超阈时以 G7c 退化判据同源
  阈值复核（静态区光度差≤0.08 且 SSIM≥0.60 → 判低纹理噪声不触发）; **d'** = 静态区
  masked 首尾 DINO 余弦≥0.84（两帧动态区置底色后 embed, 度量背景语义稳定而非本体演化）;
  a/b 记录不判死（D-064 沿用）; c/d 必须真实运行否则审计无效（fail-closed, 防再次空转）。
  另: 6 条素材首中尾帧拼图目检留存（agents/v2m3c/overlay_grid.jpg）。
- **D-067** (2026-09-09, V2-M3C): 前手 WIP 的 3 个失败测试定性与预算守卫前置修复。
  ①test_evidence NameError: 前手测试笔误（out 未定义）, 补定义; ②lane_dispatch[evidence]:
  夹具缺 evidence_asset——route.check_assets 红线（必填且须存在）是设计行为, 补夹具;
  ③budget_guard: **真代码 bug**——守卫放在三车道 lane 分支之后, pure_gen_short/
  evidence_transfer 提前 return 绕过守卫, 守卫形同虚设; 修复=守卫前置到 lane 分发之前
  （if lane in WAN_CONSUMING_LANES_SQL）; ④该测试 attempts==1 断言与 run_once 不动点
  语义不符（守卫拒绝→pending 回环, 烧满 retry_max+3 后 blocked, 与 v1
  test_wan_total_guard_blocks_generation 同口径）, 按实际语义修断言。修复后 309 passed。
  另: m3_lane_shots.sh 两处前手脚本错误修正（cd $SB→主仓跑代码+CRADLE_ROOT 指沙箱;
  heredoc SQL 引号丢失）。
- **D-068** (2026-09-09, V2-M3C): 合成源结构保持度验证结论（SPECS_V2 §5.4 必做项）。
  d=0.30 双条件重绘（D-065 路径）: 源01(虾滑) flow_cos=0.9177/pearson=0.9455/
  epe=0.115px/depth 0.9997-0.9996; 源02(毛肚) flow_cos=0.9616/pearson=0.9754/
  epe=0.086px/depth 0.9998-0.9992。**基线参照**: 正控(源重编码副本) flow_cos=0.969,
  负控(不同运动 kenburns) flow_cos=0.0464——重绘输出 0.92-0.96 落在正控带内(≥99%),
  显著高于负控 20×, 光流场方向/幅度与源逐对一致, 深度骨架相关性≈1.0。判定:
  **结构保持度过关, denoise=0.30 维持生产缺省**, 换备选路径预案不触发。数据:
  workdir/logs/v2m3_evidence_validation.json。
- **D-069** (2026-09-09, V2-M3C): overlay 限域/亮化重生成 ×2（mist_cool/bokeh_dust,
  +2 Wan 调用, 本轮合计约 18 次, v1 60 + 本轮 ≈78 ≤ 红线 200）。依据: 首版
  mist_cool 雾团中帧爆发（masked_cos 0.7272<0.84）、bokeh_dust 暗金粒子低于亮度
  阈值使动态区不可分（0.5499）。prompt 改"限域淡雾"/"亮化粒子"后: mist_cool 转
  **PASS**（0.9427）; bokeh_dust 0.7100 仍 FAIL（粒子本性动, 不再重生成——雾光渗透
  类与粒子类的剩余 FAIL 属素材类型与产线要求的固有张力, 不放宽口径, 不对称原则）。
  终版库: **3/6 PASS, 蒸汽(steam_thin)/雾(mist_cool)/光斑(light_warm) 三类各 ≥1 可用**。
  另: 三车道实测暴露 orchestrator 门禁链 G7 自 V2-M1 起未注入模型 fn（全子项
  skipped 假绿, 校准链 run_fixtures 有注入故未发现）——已修（_run_g7 注入
  default_* fns, 与校准链同款）, 三车道 G7 分数为修复后重跑的真实值。
"""


def main():
    import os
    p = os.path.expanduser("~/cradle/DECISIONS.md")
    with open(p, "a", encoding="utf-8") as f:
        f.write(APPEND)
    print("DECISIONS appended: D-060..D-068")


if __name__ == "__main__":
    main()
