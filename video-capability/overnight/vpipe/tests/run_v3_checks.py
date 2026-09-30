#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_v3_checks.py — v3 首批（工程方案v3.1 P0-1/P0-2）验收自检（确定性，零模型调用）
================================================================================
在 overnight/vpipe/ 下运行：  python tests/run_v3_checks.py
退出码：0=全部通过  1=有失败（逐条列出）  2=环境问题（ffmpeg/素材缺失，未执行）

检查清单：
  A. L0 预检接线（qc_orch_v2 在线模式）：注入超差样本被拒（exit 4），合规样本放行
     A1 黑屏片拒收(black_ratio)      A2 时长超差拒收(default, dev=10%>2%)
     A3 avatar 垫尾豁免放行(11s vs expect 10s)   A4 avatar 超垫尾拒收(12.5s vs 11 上限)
     A5 合规片 L0 通过进正常链路(exit 0)
  B. J6 v2 低运动平台豁免（声明制）：dh_stepfun / dh_design / dh_final ghosting 误报归零
     （--profile avatar_talk），且豁免证据落在 temporal_rejected（拒绝是数据，不静默）
  C. known_cuts 白名单：dh_final 的 temporal_swap(cut 13.917s) 豁免
  D. 无声明回归（改动不改行为）：金标 40 / 合成 4 / avatar 15 无 profile 重跑，
     判定级视图（检出/类型/置信度/弃权键）与改动前参考（out/j6v2_*_v3base）逐条一致；
     证据内新增 low_motion_plateau 标注键不视为行为变化（判定未变，证据更富）
  E. eval 回归：qc_orch_v2（契约 1.1）与 qc_orch v1（1.0 仍合法）双双 ACCEPT、
     与 E10 基线零偏差（R=1.0 / FPR=0.25 / F1=0.9143 / B_flag=0.8333）
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent.parent          # vpipe/
DATA = HERE.parent / "数据"
PY = sys.executable
OUT = HERE / "out" / "v3_selftest"
MEDIA = OUT / "media"

FAILS = []


def check(name, ok, detail=""):
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, (" :: " + detail) if detail else ""))
    if not ok:
        FAILS.append((name, detail))


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], capture_output=True,
                          text=True, timeout=kw.pop("timeout", 600), **kw)


def mkclip(path, filt):
    return run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", filt, str(path)])


def judgment_of(qc2json):
    """判定级视图（改动不改行为口径）：检出/类型/置信度 + 弃权键集合。
    证据内新增标注键（如 low_motion_plateau）不算行为变化，不参与比对。"""
    d = json.loads(Path(qc2json).read_text(encoding="utf-8"))
    p = d.get("temporal_protocol") or {}
    return {"clip_id": p.get("clip_id"),
            "detected": p.get("defect_detected"),
            "types": p.get("defect_types"),
            "confidence": p.get("confidence"),
            "rejected_keys": sorted((d.get("temporal_rejected") or {}).keys())}


def main():
    if shutil.which("ffmpeg") is None:
        print("ffmpeg 不可用，无法构造注入样本")
        return 2
    for src, tag in ((DATA / "avatar_out" / "dh_stepfun_720p.mp4", "dh素材"),
                     (DATA / "golden" / "clips", "金标 clips")):
        if not Path(src).exists():
            print("素材缺失: %s（%s）" % (src, tag))
            return 2
    OUT.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    THR = HERE / "eval" / "thresholds.yaml"

    # ---------------- A. L0 预检 ----------------
    print("== A. L0 预检接线（注入超差样本） ==")
    good = MEDIA / "good_5s.mp4"
    black = MEDIA / "black_5s.mp4"
    dur11 = MEDIA / "dur_11s.mp4"
    dur125 = MEDIA / "dur_12p5s.mp4"
    for p, f in ((good, "testsrc2=duration=5:size=320x240:rate=25"),
                 (black, "color=c=black:s=320x240:d=5:rate=25"),
                 (dur11, "testsrc2=duration=11:size=320x240:rate=25"),
                 (dur125, "testsrc2=duration=12.5:size=320x240:rate=25")):
        r = mkclip(p, f)
        if r.returncode != 0:
            print("ffmpeg 构造失败 %s: %s" % (p, r.stderr[-200:]))
            return 2

    def l0(cid, clip, expect=None, profile=None):
        cmd = [PY, HERE / "src" / "qc_orch_v2.py", "--online", "--clip-id", cid,
               "--clip", clip, "--thresholds", THR,
               "--out-dir", OUT / "l0_out"]
        if expect is not None:
            cmd += ["--expect-duration", expect]
        if profile:
            cmd += ["--profile", profile]
        return run(cmd)

    r = l0("t_black", black, expect=5)
    l0j = OUT / "l0_out" / "t_black.l0.json"
    check("A1 黑屏片拒收 exit=4", r.returncode == 4, "exit=%s" % r.returncode)
    check("A1 拒收证据 l0.json 落盘", l0j.exists())
    if l0j.exists():
        d = json.loads(l0j.read_text(encoding="utf-8"))
        check("A1 拒因=黑屏占比", any("黑屏" in f for f in d["failures"]),
              json.dumps(d["failures"], ensure_ascii=False))

    r = l0("t_durdev", dur11, expect=10)
    check("A2 时长超差拒收(default dev=10%) exit=4", r.returncode == 4,
          "exit=%s" % r.returncode)

    r = l0("t_av_ok", dur11, expect=10, profile="avatar_talk")
    check("A3 avatar 垫尾豁免放行(11s≤ceil(10)+1) exit=0", r.returncode == 0,
          "exit=%s %s" % (r.returncode, r.stdout[-160:].replace(chr(10), " ")))

    r = l0("t_av_bad", dur125, expect=10, profile="avatar_talk")
    check("A4 avatar 超垫尾拒收(12.5s>11 上限) exit=4", r.returncode == 4,
          "exit=%s" % r.returncode)

    r = l0("t_good", good, expect=5)
    check("A5 合规片 L0 通过 exit=0", r.returncode == 0, "exit=%s" % r.returncode)

    # ---------------- B+C. 检测器豁免（声明制） ----------------
    print("== B/C. J6v2 低运动平台豁免 + known_cuts（--profile avatar_talk） ==")
    cuts = OUT / "cuts_dh_final.json"
    cuts.write_text(json.dumps({"cuts": [{"t": 13.917, "source": "ffmpeg_concat_a/b"}]},
                               ensure_ascii=False), encoding="utf-8")
    (OUT / "dh_exempt").mkdir(parents=True, exist_ok=True)
    dh_ok = True
    for name, clip, extra in (
            ("dh_stepfun_720p", DATA / "avatar_out" / "dh_stepfun_720p.mp4", []),
            ("dh_design_720p", DATA / "avatar_out" / "dh_design_720p.mp4", []),
            ("dh_final_30s", DATA / "digital_human" / "dh_final_30s.mp4",
             ["--known-cuts", cuts])):
        outj = OUT / "dh_exempt" / ("%s.qc2.json" % name)
        r = run([PY, HERE / "src" / "qc_detectors_v2.py", "--clip", clip,
                 "--out", outj, "--params-yaml", THR, "--profile", "avatar_talk"] + extra)
        if r.returncode != 0 or not outj.exists():
            check("B %s 检测器运行" % name, False, "exit=%s" % r.returncode)
            dh_ok = False
            continue
        d = json.loads(outj.read_text(encoding="utf-8"))
        proto = d["temporal_protocol"]
        rej = d.get("temporal_rejected") or {}
        got = set(proto["defect_types"])
        want = {"temporal_swap"} if name == "dh_final_30s" else set()
        # dh_final 允许残留的类型只有非豁免对象；ghosting 必须豁免，swap 必须被 known_cuts 拦
        check("B %s ghosting 误报归零" % name,
              "ghosting" not in got and "ghosting" in (rej or {}) and
              "low_motion_plateau" in json.dumps(rej.get("ghosting") or {}, ensure_ascii=False),
              "types=%s rej_keys=%s" % (sorted(got), sorted(rej)))
        if name == "dh_final_30s":
            check("C %s swap 13.917s 被白名单豁免" % name,
                  "temporal_swap" not in got and
                  "temporal_swap_known_cuts" in rej and
                  abs(rej["temporal_swap_known_cuts"]["exempted_junctions"][0]["cut_t"] - 13.917) <= 0.5,
                  "types=%s" % sorted(got))
        if got - want:
            check("B %s 无其他残留缺陷类型" % name, False,
                  "残留=%s" % sorted(got - want))
            dh_ok = False
    del dh_ok

    # ---------------- D. 无声明回归（行为不变） ----------------
    print("== D. 无声明回归：金标/合成/avatar 判定与改动前逐条一致 ==")
    pairs = (
        ("golden", DATA / "golden" / "clips", HERE / "out" / "j6v2_golden_v3base"),
        ("syn", DATA / "j6_v2" / "synthetic", HERE / "out" / "j6v2_syn_v3base"),
        ("avatar", DATA / "avatar_out", HERE / "out" / "j6v2_dh_v3base"),
    )
    for tag, src, ref in pairs:
        dst = OUT / ("regress_%s" % tag)
        r = run([PY, HERE / "src" / "qc_detectors_v2.py", "--batch", src,
                 "--out-dir", dst, "--params-yaml", THR])
        if r.returncode != 0:
            check("D %s 批量重跑" % tag, False, "exit=%s" % r.returncode)
            continue
        diffs = []
        n = 0
        for f in sorted(Path(ref).glob("*.qc2.json")):
            g = Path(dst) / f.name
            if not g.exists():
                continue
            n += 1
            if judgment_of(f) != judgment_of(g):
                diffs.append(f.name)
        check("D %s 无声明判定一致（%d 条比对）" % (tag, n), not diffs and n >= 4,
              "diffs=%s" % diffs[:5])

    # ---------------- E. eval 回归（契约 1.1 + v1 兼容） ----------------
    print("== E. eval 回归：qc_orch_v2(1.1) 与 qc_orch v1(1.0) ==")
    r = run([PY, HERE / "src" / "qc_orch_v2.py", "--from-tonight",
             "--judges-root", DATA / "judges", "--golden", HERE / "eval" / "golden_manifest.json",
             "--thresholds", THR, "--out-dir", HERE / "out" / "qc_reports_v3post",
             "--manifest", HERE / "out" / "asset_manifest_v3post.json"])
    check("E qc_orch_v2 回放 exit=0", r.returncode == 0, "exit=%s" % r.returncode)
    r = run([PY, HERE / "eval" / "eval_run.py", "--qc-dir", HERE / "out" / "qc_reports_v3post",
             "--out", HERE / "eval" / "eval_results_v3post.json"])
    check("E eval_run(v2/1.1) ACCEPT exit=0", r.returncode == 0,
          (r.stdout[-400:] if r.returncode else "").replace(chr(10), " | "))
    r = run([PY, HERE / "src" / "qc_orch.py", "--from-tonight",
             "--judges-root", DATA / "judges", "--golden", HERE / "eval" / "golden_manifest.json",
             "--thresholds", THR, "--out-dir", HERE / "out" / "qc_reports_v3post_v1",
             "--manifest", HERE / "out" / "asset_manifest_v3post_v1.json"])
    check("E qc_orch v1 回放 exit=0", r.returncode == 0, "exit=%s" % r.returncode)
    r = run([PY, HERE / "eval" / "eval_run.py", "--qc-dir", HERE / "out" / "qc_reports_v3post_v1",
             "--out", HERE / "eval" / "eval_results_v3post_v1.json"])
    check("E eval_run(v1/1.0 兼容) ACCEPT exit=0", r.returncode == 0,
          (r.stdout[-400:] if r.returncode else "").replace(chr(10), " | "))
    # 契约版本抽验
    rep = json.loads((HERE / "out" / "qc_reports_v3post" / "golden_001.json").read_text(encoding="utf-8"))
    check("E v2 报告 schema_version=1.1", rep.get("schema_version") == "1.1",
          rep.get("schema_version"))
    rep1 = json.loads((HERE / "out" / "qc_reports_v3post_v1" / "golden_001.json").read_text(encoding="utf-8"))
    check("E v1 报告 schema_version=1.0 仍合法", rep1.get("schema_version") == "1.0",
          rep1.get("schema_version"))

    print("== 汇总 ==")
    if FAILS:
        print("FAILED %d 项：" % len(FAILS))
        for n, d in FAILS:
            print("  -", n, d)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
