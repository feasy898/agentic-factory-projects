#!/usr/bin/env python3
"""Fix compositing25.generate: render base at card resolution (center-crop, no stretch)."""
from pathlib import Path

p = Path("/root/cradle/src/gen/compositing25.py")
s = p.read_text(encoding="utf-8")

old = """    asset = card["first_frame_asset"]
    d_fn = depth_fn or default_depth_fn
    depth = d_fn(asset)
"""
new = """    asset = card["first_frame_asset"]
    d_fn = depth_fn or default_depth_fn
    depth = d_fn(asset)
    # 底片必须渲染到卡面分辨率: 源资产可能是任意比例 (实测 maodu_01 横图 1216x832
    # 导致底片 (1216,832) 与 overlay (832,480) 形状不一致 + 产线竖版分辨率错误)。
    # 中心裁剪到卡面宽高比再 resize (不拉伸, 与 I2V 首帧口径同款), V2-M3C 修复。
    from .common import open_center_resize

    asset_img = open_center_resize(asset, res[0], res[1])
"""
assert old in s, "asset anchor not found"
s = s.replace(old, new)

old = """        frames = render_parallax_frames(
            Image.open(asset).convert("RGB"), depth, n, motion=motion_eff,
        )"""
new = """        frames = render_parallax_frames(asset_img, depth, n, motion=motion_eff)"""
assert old in s, "render call anchor not found"
s = s.replace(old, new)
p.write_text(s, encoding="utf-8")
print("compositing25 fixed")
