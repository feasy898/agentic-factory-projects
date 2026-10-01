#!/usr/bin/env python3
"""J3 OmniJev-4B batch judge: per clip a 16-frame 4x4 timestamped mosaic (mso.video),
9 noul questions (8 defects + overall), calibrated P(yes). Protocol JSON per clip.
Sequential contract: ONE model resident in this process; loop clips in-process.

Usage:
  python omnijev_batch.py --clips-dir DIR --out-dir DIR --src-dir OMNIJEV_REPO \
      [--ckpt DIR] [--base DIR] [--raw-dir DIR] [--meta FILE] [--chunk 9]
"""
import argparse
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judge_common as JC


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--src-dir", required=True, help="path to OmniJev-main repo")
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--chunk", type=int, default=9, help="questions per system_one call")
    a = ap.parse_args()

    sys.path.insert(0, a.src_dir)
    import torch
    from mso.infer import MSO1
    from mso.video import video_state

    clips = JC.list_clips(a.clips_dir)
    questions = JC.omnijev_questions()
    qids = list(questions.keys())
    os.makedirs(a.out_dir, exist_ok=True)
    os.makedirs(a.raw_dir, exist_ok=True)

    t_load0 = time.time()
    m = MSO1(a.ckpt, a.base)
    load_s = round(time.time() - t_load0, 1)
    print("[omnijev] model loaded in %ss (chunk=%d)" % (load_s, a.chunk), flush=True)

    meta = {"judge": "omnijev", "model": "OmniJev-4B(v1.1)", "ckpt": a.ckpt, "base": a.base,
            "questions": questions, "threshold": JC.THRESHOLD, "chunk": a.chunk,
            "load_seconds": load_s, "clips": []}
    n_ok = n_fail = 0
    for idx, clip in enumerate(clips, 1):
        cid = os.path.splitext(os.path.basename(clip))[0]
        t0 = time.time()
        entry = {"clip_id": cid, "ok": False}
        try:
            torch.cuda.reset_peak_memory_stats()
            state = video_state(clip)
            answers = {}
            for i in range(0, len(qids), a.chunk):
                part = {q: questions[q] for q in qids[i:i + a.chunk]}
                answers.update(m.system_one(state, part))
            probs = {q[len("q_"):]: float(answers[q]["noul"]) for q in qids if q in answers}
            p_types = {k: v for k, v in probs.items() if k in JC.DEFECTS}
            notes = ("noul概率 " + " ".join("%s=%.3f" % (k, probs.get(k, float("nan")))
                                           for k in JC.DEFECTS) +
                     "; overall=%.3f" % probs.get("overall", float("nan")) +
                     "; 阈值0.5; 16帧4x4时间戳拼图整体判定")
            proto = JC.protocol_from_probs(cid, probs,
                                           spans="full_clip:16帧均匀采样4x4拼图",
                                           notes=notes)
            raw = {"model": "OmniJev-4B(v1.1)", "clip_id": cid, "clip": clip,
                   "mosaic": state.get("images", [None])[0],
                   "questions": questions, "answers": answers, "probs": probs}
            JC.write_json(os.path.join(a.raw_dir, cid + ".json"), raw)
            JC.write_json(os.path.join(a.out_dir, cid + ".json"), proto)
            entry.update(ok=True, probs=probs,
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
        print("[omnijev] %d/%d %s ok=%s lat=%.1fs %s" %
              (idx, len(clips), cid, entry["ok"], entry["latency_s"],
               entry.get("error", "")), flush=True)
        with open(a.meta + ".jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    meta.update(n_clips=len(clips), n_ok=n_ok, n_fail=n_fail,
                torch=torch.__version__, finished_at=time.strftime("%F %T"))
    JC.write_json(a.meta, meta)
    print("[omnijev] DONE ok=%d fail=%d" % (n_ok, n_fail), flush=True)


if __name__ == "__main__":
    main()
