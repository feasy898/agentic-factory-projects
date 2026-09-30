#!/usr/bin/env python3
"""V2-M3C: inject real G7 model fns into orchestrator gate chain.

_run_g7 has called g7_object_persistence without fn injection since V2-M1
(fc53ed9) - all sub-gates skipped (no_embed_fn/no_flow_fn), score恒1.0.
The calibration chain (run_fixtures) injects fns, so M1/M2 calibration data
was real; the production gate chain was silently hollow. Fix: inject the same
default fns (process-cached inside the g7 module).
"""
from pathlib import Path

p = Path("/root/cradle/src/orchestrator.py")
s = p.read_text(encoding="utf-8")

old = """    def _run_g7(self, candidate_path: str, card: dict) -> dict:
        try:
            from .gates.g7_object_persistence import (
                derive_detect_terms,
                g7_object_persistence,
                load_thresholds,
            )

            return g7_object_persistence(
                candidate_path,
                derive_detect_terms(card),
                load_thresholds(),
                frames_dir=f"{candidate_path}.g7frames",
            )"""
new = """    def _run_g7(self, candidate_path: str, card: dict) -> dict:
        try:
            from .gates.g7_object_persistence import (
                default_detect_fn,
                default_embed_fn,
                default_flow_fn,
                default_seg_fn,
                default_vlm_fn,
                derive_detect_terms,
                g7_object_persistence,
                load_thresholds,
            )

            # V2-M3C 修复: G7 不内置模型加载, 必须显式注入 fn (与校准链 run_fixtures
            # 同款, default_* 进程级缓存)。此前 orchestrator 门禁链自 V2-M1 起漏配,
            # 全子项 skipped (no_embed_fn/no_flow_fn) → score 恒 1.0 假绿, 三车道实测
            # (workdir/logs/v2m3_lane_shots.json 首版) 暴露。vlm_fn 无 API → None →
            # e 项 skipped (D-004/D-057, 不做假实现)。
            return g7_object_persistence(
                candidate_path,
                derive_detect_terms(card),
                load_thresholds(),
                frames_dir=f"{candidate_path}.g7frames",
                embed_fn=default_embed_fn(),
                detect_fn=default_detect_fn(),
                seg_fn=default_seg_fn(),
                flow_fn=default_flow_fn(),
                vlm_fn=default_vlm_fn(),
            )"""
assert old in s, "_run_g7 anchor not found"
p.write_text(s.replace(old, new), encoding="utf-8")
print("_run_g7 fns injected")
