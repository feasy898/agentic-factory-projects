#!/usr/bin/env python3
"""Move read_source_frames import before first use in audit v2 main()."""
from pathlib import Path

p = Path("/root/cradle/tools/m3_overlay_audit_v2.py")
s = p.read_text(encoding="utf-8")

old = """    n_pass = 0
    for e in entries:
"""
new = """    from src.gen.evidence import read_source_frames

    n_pass = 0
    for e in entries:
"""
assert old in s, "main loop anchor not found"
s = s.replace(old, new, 1)

old2 = """        # --- G7c': 静态区稳定性 (RAFT p95; 超阈用光度差+SSIM 复核低纹理伪光流) ---
        from src.gen.evidence import read_source_frames
        frames = read_source_frames(str(video), 9, (480, 832))"""
new2 = """        # --- G7c': 静态区稳定性 (RAFT p95; 超阈用光度差+SSIM 复核低纹理伪光流) ---
        frames = read_source_frames(str(video), 9, (480, 832))"""
assert old2 in s, "late import anchor not found"
s = s.replace(old2, new2, 1)
p.write_text(s, encoding="utf-8")
print("import moved")
