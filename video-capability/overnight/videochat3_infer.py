#!/usr/bin/env python3
"""VideoChat3-4B judge wrapper (MCG-NJU, transformers remote-code).
Sequential-loading contract: ONE model per process, GPU freed at exit.

Usage:
  python videochat3_infer.py --video clip.mp4 --question "视频里发生了什么？" [--out r.json]
  python videochat3_infer.py --image img.jpg --question "..."
  python videochat3_infer.py --frames-dir frames/ --question "..."   # frames fed as a frame list
Output: JSON {"model","inputs","question","answer","gen_seconds"}
"""
import argparse
import json
import os
import time

MODEL = "/data/night/models/VideoChat3-4B"
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "1")   # card0 is production vLLM: never touch
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--video")
    g.add_argument("--image")
    g.add_argument("--frames-dir")
    ap.add_argument("--question", required=True)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--out")
    ap.add_argument("--max-new-tokens", type=int, default=256)
    ap.add_argument("--device", default=None)
    ap.add_argument("--fps", type=float, default=2.0, help="frame sampling fps for video input")
    ap.add_argument("--max-pixels", type=int, default=768 * 768,
                    help="per-frame pixel budget for video input (V100: keep low, no flash-attn)")
    a = ap.parse_args()
    if a.device:
        os.environ["CUDA_VISIBLE_DEVICES"] = a.device

    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor
    from qwen_vl_utils import process_vision_info

    model = AutoModelForCausalLM.from_pretrained(
        a.model, torch_dtype="auto", device_map="cuda:0", trust_remote_code=True,
        attn_implementation="sdpa")   # V100 has no flash-attn (sm70); sdpa branch exists in remote code
    model.eval()
    processor = AutoProcessor.from_pretrained(a.model, trust_remote_code=True)

    if a.video:
        media = {"type": "video", "video": a.video, "fps": a.fps, "max_pixels": a.max_pixels}
        inputs_desc = {"video": a.video, "fps": a.fps, "max_pixels": a.max_pixels}
    elif a.image:
        media = {"type": "image", "image": a.image}
        inputs_desc = {"image": a.image}
    else:
        exts = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
        frames = sorted(os.path.join(a.frames_dir, f) for f in os.listdir(a.frames_dir)
                        if f.lower().endswith(exts))
        if not frames:
            print(json.dumps({"error": "no frames in %s" % a.frames_dir}))
            sys_exit(2)
        media = {"type": "video", "video": frames, "fps": a.fps, "max_pixels": a.max_pixels}
        inputs_desc = {"frames_dir": a.frames_dir, "n_frames": len(frames), "fps": a.fps}

    messages = [{"role": "user", "content": [media, {"type": "text", "text": a.question}]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    images, videos, video_kwargs = process_vision_info(
        messages, image_patch_size=14, return_video_kwargs=True, return_video_metadata=True)
    video_metadatas = None
    if videos is not None:
        videos, video_metadatas = zip(*videos)
        videos, video_metadatas = list(videos), list(video_metadatas)
    inputs = processor(text=text, images=images, videos=videos, video_metadata=video_metadatas,
                       do_resize=False, return_tensors="pt", **(video_kwargs or {}))
    inputs = inputs.to(model.device)
    if hasattr(model, "dtype"):
        inputs = inputs.to(model.dtype)
    t0 = time.time()
    with torch.inference_mode():
        gen = model.generate(**inputs, max_new_tokens=a.max_new_tokens, do_sample=False)
    gen_s = time.time() - t0
    out_ids = [o[len(i):] for i, o in zip(inputs.input_ids, gen)]
    answer = processor.tokenizer.batch_decode(out_ids, skip_special_tokens=True,
                                              clean_up_tokenization_spaces=False)[0]
    result = {"model": "VideoChat3-4B", "path": a.model, "inputs": inputs_desc,
              "question": a.question, "answer": answer.strip(), "gen_seconds": round(gen_s, 2)}
    js = json.dumps(result, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(js)
    print(js)


def sys_exit(code):
    import sys
    sys.exit(code)


if __name__ == "__main__":
    main()
