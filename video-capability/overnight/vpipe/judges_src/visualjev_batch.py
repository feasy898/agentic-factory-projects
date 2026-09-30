#!/usr/bin/env python3
"""J4 Visual-Jev-4B batch judge: per clip extract first/middle/last frames (ffmpeg),
9 choice(yes/no) questions per frame, average P(yes) over the 3 frames, threshold 0.5.
Sequential contract: ONE model resident; loop clips in-process.

Usage:
  python visualjev_batch.py --clips-dir DIR --out-dir DIR --code-dir VISUALJEV/code \
      --frames-dir DIR --base DIR --adapter DIR [--raw-dir DIR] [--meta FILE] [--max-pixels N]
"""
import argparse
import json
import os
import subprocess
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judge_common as JC


def ffprobe_dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def grab(path, ss, out_jpg):
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % max(0.0, ss), "-i", path,
           "-frames:v", "1", "-q:v", "2", out_jpg]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0 or not os.path.exists(out_jpg):
        raise RuntimeError("ffmpeg -ss %s failed: %s" % (ss, r.stderr.decode(errors="replace")[-200:]))


def extract_three(clip, fdir):
    os.makedirs(fdir, exist_ok=True)
    dur = ffprobe_dur(clip)
    if dur is None or dur < 0.2:
        raise RuntimeError("bad duration %s" % dur)
    first = os.path.join(fdir, "first.jpg")
    mid = os.path.join(fdir, "mid.jpg")
    last = os.path.join(fdir, "last.jpg")
    grab(clip, 0.0, first)
    grab(clip, dur / 2.0, mid)
    if not os.path.exists(last):
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-sseof", "-0.2", "-i", clip,
                            "-frames:v", "1", "-q:v", "2", last], capture_output=True, timeout=120)
        if r.returncode != 0 or not os.path.exists(last):
            grab(clip, dur - 0.1, last)
    return [first, mid, last]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--code-dir", required=True, help="path to Visual-Jev-main/code")
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--max-pixels", type=int, default=200704)
    ap.add_argument("--chunk", type=int, default=5, help="questions per prepare_group call")
    a = ap.parse_args()

    sys.path.insert(0, a.code_dir)
    import torch
    from PIL import Image
    from peft import PeftModel
    from vdm.models.vdm_model import VDM

    clips = JC.list_clips(a.clips_dir)
    request = JC.visualjev_questions()
    req_q = request["questions"]
    qids = list(req_q.keys())

    # flatten to wrapper format once (same construction as visualjev_infer.py)
    questions, keys = [], []
    for qid in qids:
        item = req_q[qid]
        ck, cands = [], []
        for oid, desc in item["criteria"].items():
            ck.append(oid)
            cands.append(oid if desc in (None, "") else "%s: %s" % (oid, desc))
        keys.append(ck)
        questions.append({"qtype": "choice", "instruction": item["instructions"],
                          "candidates": cands})

    os.makedirs(a.out_dir, exist_ok=True)
    os.makedirs(a.raw_dir, exist_ok=True)

    t_load0 = time.time()
    model = VDM(a.base, device="cuda", dtype=torch.bfloat16, with_heads=False)
    model.processor.image_processor.max_pixels = a.max_pixels
    model.backbone = PeftModel.from_pretrained(model.backbone, a.adapter).eval()
    load_s = round(time.time() - t_load0, 1)
    print("[visualjev] model+adapter loaded in %ss" % load_s, flush=True)

    meta = {"judge": "visualjev", "model": "Visual-Jev-4B(answer-sft)", "base": a.base,
            "adapter": a.adapter, "questions": req_q, "threshold": JC.THRESHOLD,
            "frames": "first/middle(dur/2)/last", "chunk": a.chunk,
            "max_pixels": a.max_pixels, "load_seconds": load_s, "clips": []}
    n_ok = n_fail = 0
    for idx, clip in enumerate(clips, 1):
        cid = os.path.splitext(os.path.basename(clip))[0]
        t0 = time.time()
        entry = {"clip_id": cid, "ok": False}
        try:
            frames = extract_three(clip, os.path.join(a.frames_dir, cid))
            torch.cuda.reset_peak_memory_stats()
            per_frame = []   # [{qid: p_yes}]
            for fp in frames:
                with Image.open(fp) as src:
                    image = src.convert("RGB")
                frame_probs = {}
                for i in range(0, len(questions), a.chunk):
                    qs = questions[i:i + a.chunk]
                    with torch.inference_mode():
                        group = model.prepare_group(image, qs, shared_context="")
                        output = model.run_prefix_share_batch(group)
                    for j in range(len(qs)):
                        logits = output["lm_option_logits"][j, :group.n_options[j]]
                        pr = torch.softmax(logits.float(), dim=-1).cpu().tolist()
                        d = {k: float(p) for k, p in zip(keys[i + j], pr)}
                        frame_probs[qids[i + j]] = d.get("yes", 0.0)
                per_frame.append(frame_probs)
            probs = {}
            for q in qids:
                key = q[len("q_"):]
                vals = [f[q] for f in per_frame]
                probs[key] = sum(vals) / len(vals)
            notes = ("3帧平均yes概率 " + " ".join("%s=%.3f" % (k, probs.get(k, float("nan")))
                                                for k in JC.DEFECTS) +
                     "; overall=%.3f" % probs.get("overall", float("nan")) +
                     "; 阈值0.5; 单帧choice判定(first/mid/last)")
            proto = JC.protocol_from_probs(cid, probs,
                                           spans="first,mid,last帧P(yes)平均",
                                           notes=notes)
            raw = {"model": "Visual-Jev-4B(answer-sft)", "clip_id": cid, "clip": clip,
                   "frames": frames, "per_frame_yes_probs": per_frame, "probs_avg": probs,
                   "questions": req_q}
            JC.write_json(os.path.join(a.raw_dir, cid + ".json"), raw)
            JC.write_json(os.path.join(a.out_dir, cid + ".json"), proto)
            entry.update(ok=True, probs=probs, frames=frames,
                         peak_vram_mb=round(torch.cuda.max_memory_allocated() / 2**20, 1))
            n_ok += 1
        except Exception as e:
            entry["error"] = "%s: %s" % (type(e).__name__, e)
            entry["trace"] = traceback.format_exc(limit=3)
            n_fail += 1
            JC.write_json(os.path.join(a.out_dir, cid + ".json"),
                          {"clip_id": cid, "defect_detected": False, "defect_types": [],
                           "confidence": 0.0, "spans": "", "notes": "judge FAILED: %s" % entry["error"]})
        entry["latency_s"] = round(time.time() - t0, 2)
        meta["clips"].append(entry)
        print("[visualjev] %d/%d %s ok=%s lat=%.1fs %s" %
              (idx, len(clips), cid, entry["ok"], entry["latency_s"],
               entry.get("error", "")), flush=True)
        with open(a.meta + ".jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    meta.update(n_clips=len(clips), n_ok=n_ok, n_fail=n_fail,
                torch=torch.__version__, finished_at=time.strftime("%F %T"))
    JC.write_json(a.meta, meta)
    print("[visualjev] DONE ok=%d fail=%d" % (n_ok, n_fail), flush=True)


if __name__ == "__main__":
    main()
