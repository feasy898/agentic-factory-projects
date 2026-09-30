#!/usr/bin/env python3
"""OmniJev-4B judge wrapper (sequential-loading contract: ONE model per process, GPU freed at exit).

Usage:
  python omnijev_infer.py --image img.jpg --questions q.json [--out r.json]
  python omnijev_infer.py --frames-dir frames/ --questions q.json      # frames tiled as numbered panels
  python omnijev_infer.py --video clip.mp4 --questions q.json          # 16-frame 4x4 mosaic (needs ffmpeg)
  python omnijev_infer.py --image img.jpg --noul "图中人的手指总数是否为五"

q.json format (mso.infer native): {"qid": {"type": "noul|choice|score", "instructions": "...",
  "criteria": {"opt": null, ...}?, "levels": [...]}?}
Output: one JSON object on stdout: {"model", "inputs", "answers": {qid: mso answer}}
"""
import argparse
import json
import os
import sys

REPO = "/data/night/src/OmniJev-main"
CKPT = "/data/night/models/OmniJev-4B-v1.1"
BASE = "/data/night/models/Qwen3.5-4B"
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "1")   # card0 is production vLLM: never touch
sys.path.insert(0, REPO)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--image")
    g.add_argument("--frames-dir")
    g.add_argument("--video")
    g.add_argument("--noul", help="single noul question shortcut")
    ap.add_argument("--questions", help="JSON map id->question (mso format)")
    ap.add_argument("--ckpt", default=CKPT)
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--out", help="also write JSON here")
    ap.add_argument("--device", default=None, help="override CUDA_VISIBLE_DEVICES (e.g. 1)")
    a = ap.parse_args()
    if a.device:
        os.environ["CUDA_VISIBLE_DEVICES"] = a.device
    if a.noul:
        questions = {"q1": {"type": "noul", "instructions": a.noul}}
    elif a.questions:
        with open(a.questions, encoding="utf-8") as f:
            questions = json.load(f)
    else:
        questions = None  # supplied later for --video/--frames-dir via stdin? no: required
    if questions is None:
        ap.error("--questions or --noul is required")

    import torch
    from mso.infer import MSO1

    if a.video:
        from mso.video import video_state
        state = video_state(a.video)
        inputs_desc = {"video": a.video, "mosaic": state["images"][0]}
    elif a.frames_dir:
        exts = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
        frames = sorted(os.path.join(a.frames_dir, f) for f in os.listdir(a.frames_dir)
                        if f.lower().endswith(exts))
        if not frames:
            print(json.dumps({"error": "no frames found in %s" % a.frames_dir}))
            sys.exit(2)
        state = {"images": frames}
        inputs_desc = {"frames_dir": a.frames_dir, "n_frames": len(frames)}
    else:
        state = {"images": [a.image]}
        inputs_desc = {"image": a.image}

    m = MSO1(a.ckpt, a.base)
    answers = m.system_one(state, questions)
    result = {"model": "OmniJev-4B(v1.1)", "ckpt": a.ckpt, "base": a.base,
              "inputs": inputs_desc, "questions": questions, "answers": answers}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
