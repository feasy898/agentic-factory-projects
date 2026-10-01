#!/usr/bin/env python3
"""V2-M3C: regenerate 2 failed overlays with brighter/limited prompts (+2 Wan)."""
from pathlib import Path

p = Path("/root/cradle/tools/m3_gen_overlays.py")
s = p.read_text(encoding="utf-8")

old = """    {
        "file": "ov_mist_cool.mp4",
        "kind": "fog",
        "prompt": (
            "cool blue-white mist swirling gently in slow motion, ethereal vapor, "
            "pure black background, fixed camera, locked tripod, only mist moves, "
            "no objects, no food, no hands"
        ),
    },"""
new = """    {
        "file": "ov_mist_cool.mp4",
        "kind": "fog",
        # V2-M3C 重生成 (D-069): 首版雾团中帧爆发致全帧 cos 0.7272<0.84 —
        # 限域+淡雾重生成, 控制"氛围粒子不盖画面"
        "prompt": (
            "subtle localized wisps of pale mist drifting gently near bottom edge, "
            "faint thin vapor, pure black background, dim, fixed camera, locked tripod, "
            "only mist moves, no objects, no food, no hands"
        ),
    },"""
assert old in s, "mist spec anchor not found"
s = s.replace(old, new)

old = """    {
        "file": "ov_bokeh_dust.mp4",
        "kind": "light",
        "prompt": (
            "tiny golden dust motes and bokeh sparkles floating slowly, glittering particles, "
            "pure black background, fixed camera, locked tripod, only particles move, "
            "no objects, no food, no hands"
        ),
    },"""
new = """    {
        "file": "ov_bokeh_dust.mp4",
        "kind": "light",
        # V2-M3C 重生成 (D-069): 首版暗金粒子亮度低于静态阈值(60)致动态本体不可分
        # (masked_cos 0.5499) — 亮化粒子重生成, 使动态区可分且 screen 混合可见
        "prompt": (
            "bright glowing golden dust motes and bokeh sparkles floating slowly, "
            "luminous sparkling particles, pure black background, fixed camera, "
            "locked tripod, only particles move, no objects, no food, no hands"
        ),
    },"""
assert old in s, "bokeh spec anchor not found"
s = s.replace(old, new)
p.write_text(s, encoding="utf-8")
print("prompts updated")
