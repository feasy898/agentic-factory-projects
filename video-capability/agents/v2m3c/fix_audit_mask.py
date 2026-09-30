#!/usr/bin/env python3
"""V2-M3C: temporal max-projection static mask for overlay audit v2."""
from pathlib import Path

p = Path("/root/cradle/tools/m3_overlay_audit_v2.py")
s = p.read_text(encoding="utf-8")

old = '''        video = ODIR / e["file"]
        mask_png = str(mask_dir / f"{e['file']}.static.png")
        build_static_mask(str(video), mask_png)
        static_mask = Image.open(mask_png).convert("L")
        m_arr = np.asarray(static_mask) > 127
        static_ratio = round(float(m_arr.mean()), 4)
'''
new = '''        video = ODIR / e["file"]
        mask_png = str(mask_dir / f"{e['file']}.static.png")
        # V2-M3C 修正 (D-066): 动态本体常在中后段才出现 (steam_dense 首帧全暗、
        # 白雾中帧渐旺), 首帧亮度 mask 全白失效 (static_ratio=1.0 实测)。
        # 改用时间最大亮度投影: 任一帧亮过的像素都是潜在动态区。
        _frames_mask = read_source_frames(str(video), 9, (480, 832))
        _stack = np.stack([np.asarray(f.convert("L"), dtype="float32") for f in _frames_mask])
        _static = _stack.max(axis=0) < LUMINANCE_STATIC_TAU
        Image.fromarray((_static * 255).astype("uint8"), mode="L").save(mask_png)
        static_mask = Image.open(mask_png).convert("L")
        m_arr = np.asarray(static_mask) > 127
        static_ratio = round(float(m_arr.mean()), 4)
'''
assert old in s, "mask block anchor not found"
s = s.replace(old, new)

# c' 计算处已用 read_source_frames — 确认 import 在 main 里已存在
assert "from src.gen.evidence import read_source_frames" in s, "read_source_frames import missing"
# masked_embed_cos 的 static_mask.resize 调用兼容 (PIL Image) — 不变
p.write_text(s, encoding="utf-8")
print("mask projection fixed v2")
