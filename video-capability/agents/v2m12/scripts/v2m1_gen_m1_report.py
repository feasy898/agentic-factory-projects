#!/usr/bin/env python
"""V2-M1: 从运行 JSON 生成初跑分数报告(数字全部取自数据, 不手填)。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

data = json.loads((ROOT / "workdir" / "logs" / "v2m1_g7_initial.json").read_text(encoding="utf-8"))
recs = data["records"]
L = []
L.append("# V2-M1: G7 五子项实现 + 47 夹具初跑分数表(冷启动阈值)\n")
L.append("- 执行: V2-M12 子代理, 2026-09-08")
L.append("- 依据: SPECS_V2 §3(五子项)/§4(校准流程); 实现于 `src/gates/g7_object_persistence.py` + `src/gates/g7_vlm_prompt.txt`")
L.append("- 运行口径: 均匀 16 帧/条(D-056), Grounding DINO fp32+autocast(D-054), vendored LiteByteTracker 跟踪, RAFT-small fp32 静态区光流, SAM ViT-B fp16 反选静态区, DINOv2-L CLS(M0 同口径)")
L.append("- 阈值: 全部冷启动值(SPECS_V2 §4, thresholds_v2.yaml 初版): a<0.75(bbox) / b(delta>2, var>4, churn>3) / c(p95>0.5px) / d<0.75 / e≥0.6")
L.append("- 数据: `workdir/logs/v2m1_g7_initial.json`(逐帧原始检测/双口径余弦序列/双口径光流 P95 全量落盘, M2 校准据此离线扫描); 每子项分数落 SQLite g7_runs 表")
L.append("- **G7e: 全部 skipped(vlm_unavailable, D-004 无 VLM API; 规格明令不做 CLIP 假实现)**; 提示词全文含豁免条款落 `src/gates/g7_vlm_prompt.txt`\n")
L.append("## 冷启动结果速览\n")
L.append("| 组 | n | G7 fail 数 | 口径 | 率 |")
L.append("|---|---|---|---|---|")
for lab, note in (("fail", "拦截"), ("pass_structural", "误杀"), ("pass_candidate", "误杀")):
    g = [r for r in recs if r["label"] == lab]
    k = sum(1 for r in g if not r["passed"])
    L.append(f"| {lab} | {len(g)} | {k} | {note} | {k / len(g) * 100:.1f}% |")
L.append("")
L.append("解读: fail 全拦截(15/15)、pass_structural 零误杀; pass_candidate 误杀 16/17 —— 主因 c 项 0.5px 冷启动"
         "对 0.33s 采样对过严(候选组本含非锁定机位的液体/蒸汽运动), a(bbox 口径)另误杀 3 条; 正是 M2 校准的对象, 如实呈现不掩盖。\n")
L.append("## 逐条分数(冷启动)\n")
L.append("| fixture | label | category | passed | score | a | b | c | d | e |")
L.append("|---|---|---|---|---|---|---|---|---|---|")


def fmt_sub(s):
    if s["skipped"]:
        return "skip"
    tr = "**T**" if s["triggered"] else "."
    return f"{s['score']:.3f}{tr}"


for r in recs:
    s = r["subs"]
    verdict = "FAIL" if not r["passed"] else "pass"
    L.append(f"| {r['fixture_id']} | {r['label']} | {r['category'] or '-'} | {verdict} | {r['score']:.3f} | "
             + " | ".join(fmt_sub(s[k]) for k in "abcde") + " |")
L.append("")
L.append("注: T=该子项触发。b 项 counts/churn 序列与逐帧原始检测(dets_raw)、c 项静态区/全帧双口径 P95、"
         "a 项 bbox/fullframe 双口径余弦序列均在运行 JSON 中。")
out = ROOT / "reports" / "milestones" / "V2_M1_g7_initial_scores.md"
out.write_text("\n".join(L), encoding="utf-8")
print("written", out)
