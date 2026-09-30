#!/usr/bin/env python3
"""One-clip VideoChat3 debug run: reproduce the smoke path with instrumentation
inside GenerationMixin.generate (decoding_method selection)."""
import json
import os
import sys

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

CLIP = sys.argv[1]
MODEL = sys.argv[2]

import torch
import transformers
import transformers.generation.utils as GU
from transformers import AutoModelForCausalLM, AutoProcessor
from qwen_vl_utils import process_vision_info

print("transformers", transformers.__version__, flush=True)

model = AutoModelForCausalLM.from_pretrained(
    MODEL, torch_dtype="auto", device_map="cuda:0", trust_remote_code=True,
    attn_implementation="sdpa")
model.eval()
processor = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True)

print("type(model) =", type(model), flush=True)
print("type module  =", type(model).__module__, flush=True)
print("gc mode      =", model.generation_config.get_generation_mode(None), flush=True)
for k in ("do_sample", "top_k", "top_p", "penalty_alpha", "num_beams", "constraints"):
    print("  gc", k, "=", getattr(model.generation_config, k, "N/A"), flush=True)
print("_sample attr =", getattr(type(model), "_sample", "MISSING"), flush=True)

orig_repo = GU.GenerationMixin._get_deprecated_gen_repo
def patched(self, generation_mode, trust_remote_code, custom_generate):
    r = orig_repo(self, generation_mode, trust_remote_code, custom_generate)
    print("[dbg] _get_deprecated_gen_repo mode=%s trust=%s custom=%r -> %r" %
          (generation_mode, trust_remote_code, custom_generate, r), flush=True)
    return r
GU.GenerationMixin._get_deprecated_gen_repo = patched

media = {"type": "video", "video": CLIP, "fps": 1.0, "max_pixels": 268144}
messages = [{"role": "user", "content": [media, {"type": "text", "text": "描述这个视频。"}]}]
text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
images, videos, video_kwargs = process_vision_info(
    messages, image_patch_size=14, return_video_kwargs=True, return_video_metadata=True)
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
with torch.inference_mode():
    gen = model.generate(**inputs, max_new_tokens=32, do_sample=False)
out = processor.tokenizer.batch_decode([g[len(i):] for i, g in zip(inputs.input_ids, gen)],
                                       skip_special_tokens=True)[0]
print("ANSWER:", out.strip()[:200], flush=True)
