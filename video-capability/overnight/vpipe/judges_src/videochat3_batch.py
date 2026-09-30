#!/usr/bin/env python3
"""J5 VideoChat3-4B batch judge: per clip one video-level QA ("which of the 8 defect
types are present"), parse the text answer into protocol JSON.
Primary mode: decord video path (as smoke-validated). Fallback (no decord on py3.12):
extract fps frames with ffmpeg and feed the frame list.

Usage:
  python videochat3_batch.py --clips-dir DIR --out-dir DIR --raw-dir DIR --model DIR \
      [--frames-dir DIR] [--meta FILE] [--fps 1.0] [--max-pixels 268144]
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

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


def extract_frames(clip, fdir, fps):
    os.makedirs(fdir, exist_ok=True)
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", clip, "-vf", "fps=%.3f" % fps,
                        "-q:v", "3", os.path.join(fdir, "f%03d.jpg")], capture_output=True, timeout=180)
    frames = sorted(os.path.join(fdir, f) for f in os.listdir(fdir) if f.endswith(".jpg"))
    if r.returncode != 0 or not frames:
        raise RuntimeError("ffmpeg fps extract failed: %s" % r.stderr.decode(errors="replace")[-200:])
    return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--frames-dir", required=True, help="fallback frames dir")
    ap.add_argument("--model", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--max-pixels", type=int, default=268144)
    ap.add_argument("--max-new-tokens", type=int, default=256)
    ap.add_argument("--force-frames", action="store_true")
    a = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor
    from qwen_vl_utils import process_vision_info

    try:
        import decord  # noqa: F401
        use_frames = bool(a.force_frames)
        input_mode = "video(decord)" if not use_frames else "frames(forced)"
    except Exception:
        use_frames = True
        input_mode = "frames(decord unavailable)"

    clips = JC.list_clips(a.clips_dir)
    os.makedirs(a.out_dir, exist_ok=True)
    os.makedirs(a.raw_dir, exist_ok=True)
    os.makedirs(a.frames_dir, exist_ok=True)

    t_load0 = time.time()
    model = AutoModelForCausalLM.from_pretrained(
        a.model, torch_dtype="auto", device_map="cuda:0", trust_remote_code=True,
        attn_implementation="sdpa")
    model.eval()
    processor = AutoProcessor.from_pretrained(a.model, trust_remote_code=True)
    load_s = round(time.time() - t_load0, 1)
    print("[vc3] model loaded in %ss; input_mode=%s" % (load_s, input_mode), flush=True)

    meta = {"judge": "videochat3", "model": "VideoChat3-4B", "path": a.model,
            "question": JC.VC3_QA_PROMPT, "fps": a.fps, "max_pixels": a.max_pixels,
            "input_mode": input_mode, "load_seconds": load_s, "clips": []}
    n_ok = n_fail = 0
    for idx, clip in enumerate(clips, 1):
        cid = os.path.splitext(os.path.basename(clip))[0]
        t0 = time.time()
        entry = {"clip_id": cid, "ok": False}
        try:
            if use_frames:
                fdir = os.path.join(a.frames_dir, cid)
                frames = extract_frames(clip, fdir, a.fps)
                media = {"type": "video", "video": frames, "fps": a.fps,
                         "max_pixels": a.max_pixels}
                inputs_desc = {"mode": "frames", "n_frames": len(frames), "fps": a.fps}
            else:
                media = {"type": "video", "video": clip, "fps": a.fps,
                         "max_pixels": a.max_pixels}
                inputs_desc = {"mode": "video", "fps": a.fps, "max_pixels": a.max_pixels}
            messages = [{"role": "user", "content": [media,
                                                     {"type": "text", "text": JC.VC3_QA_PROMPT}]}]
            text = processor.apply_chat_template(messages, tokenize=False,
                                                 add_generation_prompt=True)
            images, videos, video_kwargs = process_vision_info(
                messages, image_patch_size=14, return_video_kwargs=True,
                return_video_metadata=True)
            video_metadatas = None
            if videos is not None:
                videos, video_metadatas = zip(*videos)
                videos, video_metadatas = list(videos), list(video_metadatas)
            inputs = processor(text=text, images=images, videos=videos,
                               video_metadata=video_metadatas, do_resize=False,
                               return_tensors="pt", **(video_kwargs or {}))
            inputs = inputs.to(model.device)
            if hasattr(model, "dtype"):
                inputs = inputs.to(model.dtype)
            tg = time.time()
            with torch.inference_mode():
                gen = model.generate(**inputs, max_new_tokens=a.max_new_tokens, do_sample=False)
            gen_s = round(time.time() - tg, 2)
            out_ids = [o[len(i):] for i, o in zip(inputs.input_ids, gen)]
            answer = processor.tokenizer.batch_decode(
                out_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0].strip()

            types, other, method, reason = JC.parse_vc3_answer(answer)
            conf = {"json": 0.8, "keyword": 0.5, "none": 0.3}[method]
            spans = "full_clip:%s" % ("fps=%.1f抽帧" % a.fps if use_frames else "fps=%.1f解码" % a.fps)
            notes = "解析=%s; 回答=%s" % (method, answer[:150].replace("\n", " "))
            proto = JC.protocol_from_types(cid, types, conf, spans, notes)
            raw = {"model": "VideoChat3-4B", "clip_id": cid, "clip": clip,
                   "inputs": inputs_desc, "question": JC.VC3_QA_PROMPT, "answer": answer,
                   "parsed": {"types": types, "other": other, "method": method,
                              "reason": reason}, "gen_seconds": gen_s}
            JC.write_json(os.path.join(a.raw_dir, cid + ".json"), raw)
            JC.write_json(os.path.join(a.out_dir, cid + ".json"), proto)
            entry.update(ok=True, parse=method, types=types, gen_seconds=gen_s)
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
        print("[vc3] %d/%d %s ok=%s lat=%.1fs %s" %
              (idx, len(clips), cid, entry["ok"], entry["latency_s"],
               entry.get("error", "")), flush=True)
        with open(a.meta + ".jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    meta.update(n_clips=len(clips), n_ok=n_ok, n_fail=n_fail,
                torch=torch.__version__, finished_at=time.strftime("%F %T"))
    JC.write_json(a.meta, meta)
    print("[vc3] DONE ok=%d fail=%d" % (n_ok, n_fail), flush=True)


if __name__ == "__main__":
    main()
