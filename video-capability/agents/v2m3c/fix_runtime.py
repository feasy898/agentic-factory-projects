#!/usr/bin/env python3
"""V2-M3C runtime fixes:
1. open_center_resize accepts PIL.Image (evidence vid2vid first-frame condition)
2. evidence.generate passes source first frame as input_image (Fun-InP has_image_input
   requires y; D-060 recon missed this - fixed per D-065)
3. m3_overlay_audit.py injects real G7 fns (previous audit was a full-skip no-op)
"""
from pathlib import Path

REPO = Path("/root/cradle")

# ---- 1. common.open_center_resize: accept PIL.Image ----
p = REPO / "src" / "gen" / "common.py"
s = p.read_text(encoding="utf-8")
old = '''def open_center_resize(path: str, width: int, height: int):
    """读图 → 中心裁剪到目标宽高比 → resize 到 (width, height)。

    用途: I2V 首帧条件(任意来源图 → 生成分辨率), 资产主图与生成解耦(D-026 按需缩放)。
    返回 PIL.Image; 路径不存在抛 FileNotFoundError。
    """
    from PIL import Image

    img = Image.open(path).convert("RGB")'''
new = '''def open_center_resize(path, width: int, height: int):
    """读图 → 中心裁剪到目标宽高比 → resize 到 (width, height)。

    用途: I2V 首帧条件(任意来源图 → 生成分辨率), 资产主图与生成解耦(D-026 按需缩放)。
    path 亦接受 PIL.Image 实例 (V2-M3 evidence 车道: 源视频首帧已在产线分辨率,
    D-065) —— 实例被拷贝使用, 不修改调用方数据。
    返回 PIL.Image; 路径不存在抛 FileNotFoundError。
    """
    from PIL import Image

    if isinstance(path, Image.Image):
        img = path.convert("RGB")
    else:
        img = Image.open(path).convert("RGB")'''
assert old in s, "open_center_resize anchor not found"
p.write_text(s.replace(old, new), encoding="utf-8")
print("1/3 common.py patched")

# ---- 2. evidence.generate: pass first frame condition ----
p = REPO / "src" / "gen" / "evidence.py"
s = p.read_text(encoding="utf-8")
old = """    reset_vram_counter()
    with timed() as t:
        frames = pipeline(
            prompt=card["prompt_en"],
            negative=negative,
            first_frame=None,"""
new = """    reset_vram_counter()
    with timed() as t:
        frames = pipeline(
            prompt=card["prompt_en"],
            negative=negative,
            # Fun-InP 是 has_image_input 结构模型: DiT 前向无条件 cat([x, y]),
            # y 必须由 input_image 编码 (diffsynth model_fn_wan_video L567 实测崩溃定位)。
            # D-065 修正 D-060 侦察: vid2vid 在 Fun-InP 上须 input_image(源首帧)+
            # input_video(帧序列) 双条件 —— 首帧条件同时强化结构锚定。
            first_frame=frames_src[0],"""
assert old in s, "evidence pipeline call anchor not found"
s = s.replace(old, new)
# 文件头管线注释同步修正
old_doc = """管线 (侦察结论 D-060, 路径①=diffsynth 1.1.9 原生, 零新模型):
  源视频 (用户实拍或合成测试源, assets/evidence/)
  → 均匀采样 num_frames(4k+1, ≤81) 帧, 预缩放到产线分辨率
  → WanVideoPipeline(input_video=帧序列, input_image=首帧,
     denoising_strength=0.2-0.35) 低强度视频重绘
  → 输出 mp4。"""
new_doc = """管线 (侦察结论 D-060, 路径①=diffsynth 1.1.9 原生, 零新模型;
  D-065 运行时修正: Fun-InP has_image_input 要求 input_image 必传, 取源首帧):
  源视频 (用户实拍或合成测试源, assets/evidence/)
  → 均匀采样 num_frames(4k+1, ≤81) 帧, 预缩放到产线分辨率
  → WanVideoPipeline(input_video=帧序列, input_image=源首帧,
     denoising_strength=0.2-0.35) 低强度视频重绘
  → 输出 mp4。"""
assert old_doc in s, "evidence doc anchor not found"
s = s.replace(old_doc, new_doc)
p.write_text(s, encoding="utf-8")
print("2/3 evidence.py patched")

# ---- 3. m3_overlay_audit.py: inject real fns + invalidity guard ----
p = REPO / "tools" / "m3_overlay_audit.py"
s = p.read_text(encoding="utf-8")
old = """    from src.gates.g7_object_persistence import (
        g7_object_persistence,
        load_thresholds,
    )
    from tools.m3_gen_overlays import AUDIT_TERMS

    thresholds = load_thresholds()"""
new = """    from src.gates.g7_object_persistence import (
        g7_object_persistence,
        load_thresholds,
        default_embed_fn,
        default_detect_fn,
        default_flow_fn,
        default_seg_fn,
        default_vlm_fn,
    )
    from tools.m3_gen_overlays import AUDIT_TERMS

    thresholds = load_thresholds()
    # V2-M3C 修正: g7_object_persistence 不内置模型加载, fn 必须显式注入 ——
    # 前手 WIP 未注入导致全部子项 skipped 空转 (score 恒 1.0), 审计无度量。
    # 缺省注入与 run_fixtures 同款本地模型; vlm_fn 无 API → None → e 项 skipped (D-004)。
    embed_fn = default_embed_fn()
    detect_fn = default_detect_fn()
    seg_fn = default_seg_fn()
    flow_fn = default_flow_fn()
    vlm_fn = default_vlm_fn()"""
assert old in s, "audit imports anchor not found"
s = s.replace(old, new)

old = """        result = g7_object_persistence(
            str(video), terms, thresholds,
            expected_static_mask=mask_png,
            frames_dir=str(video) + ".g7frames",
        )
        subs = result.get("detail", {})"""
new = """        result = g7_object_persistence(
            str(video), terms, thresholds,
            expected_static_mask=mask_png,
            frames_dir=str(video) + ".g7frames",
            embed_fn=embed_fn, detect_fn=detect_fn, seg_fn=seg_fn,
            flow_fn=flow_fn, vlm_fn=vlm_fn,
        )
        subs = result.get("detail", {})
        # 审计有效性守卫: 硬判据 c(静态区光流)/d(首尾漂移) 任一真实运行才有效;
        # 双双 skipped(如模型缺失) → 判审计无效 (fail-closed), 不给 PASS。
        c_run = not subs.get("c", {}).get("skipped", True)
        d_run = not subs.get("d", {}).get("skipped", True)"""
assert old in s, "audit call anchor not found"
s = s.replace(old, new)

old = """        # D-064 判据: c/d 硬性 (背景稳定 + 无整体漂移); a/b 记录不判死 (豁免条款)
        c_ok = bool(subs.get("c", {}).get("skipped", True)) or not subs.get("c", {}).get("triggered", False)
        d_ok = bool(subs.get("d", {}).get("skipped", True)) or not subs.get("d", {}).get("triggered", False)
        audit_pass = c_ok and d_ok"""
new = """        # D-064 判据: c/d 硬性 (背景稳定 + 无整体漂移, 且必须真实运行); a/b 记录不判死 (豁免条款)
        c_ok = c_run and not subs.get("c", {}).get("triggered", False)
        d_ok = d_run and not subs.get("d", {}).get("triggered", False)
        audit_pass = c_ok and d_ok"""
assert old in s, "audit criteria anchor not found"
s = s.replace(old, new)

old = """            "c": {"passed": c_ok, "score": subs.get("c", {}).get("score"),
                  "p95_px": subs.get("c", {}).get("p95_px"),
                  "mask_source": subs.get("c", {}).get("mask_source")},
            "d": {"passed": d_ok, "score": subs.get("d", {}).get("score"),
                  "cos": subs.get("d", {}).get("score")},"""
new = """            "c": {"passed": c_ok, "ran": c_run,
                  "skipped_reason": subs.get("c", {}).get("reason"),
                  "score": subs.get("c", {}).get("score"),
                  "p95_px": subs.get("c", {}).get("p95_px"),
                  "p95_px_per_pair": subs.get("c", {}).get("p95_px_per_pair"),
                  "raft": subs.get("c", {}).get("raft"),
                  "threshold_px": subs.get("c", {}).get("threshold"),
                  "mask_source": subs.get("c", {}).get("mask_source")},
            "d": {"passed": d_ok, "ran": d_run,
                  "skipped_reason": subs.get("d", {}).get("reason"),
                  "score": subs.get("d", {}).get("score"),
                  "cos": subs.get("d", {}).get("score"),
                  "threshold": subs.get("d", {}).get("threshold")},"""
assert old in s, "audit manifest fields anchor not found"
s = s.replace(old, new)

old = """        print(f"{e['file']}: audit={'PASS' if audit_pass else 'FAIL'} "
              f"c(p95={e['g7_audit']['c']['p95_px']}) d(cos={e['g7_audit']['d']['cos']}) "
              f"a={e['g7_audit']['a']['score']} b(churn={e['g7_audit']['b']['churn']})")"""
new = """        print(f"{e['file']}: audit={'PASS' if audit_pass else 'FAIL'} "
              f"c(ran={c_run},p95={e['g7_audit']['c']['p95_px']}) "
              f"d(ran={d_run},cos={e['g7_audit']['d']['cos']}) "
              f"a={e['g7_audit']['a']['score']} b(churn={e['g7_audit']['b']['churn']})")"""
assert old in s, "audit print anchor not found"
s = s.replace(old, new)
p.write_text(s, encoding="utf-8")
print("3/3 m3_overlay_audit.py patched")
