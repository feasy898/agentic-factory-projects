#!/usr/bin/env python3
"""Visual-Jev judge wrapper (Qwen3-VL-4B-Instruct + answer-SFT LoRA).
Sequential-loading contract: ONE model per process, GPU freed at exit.

Usage:
  python visualjev_infer.py --image img.jpg --questions q.json [--out r.json] [--context "..."]
q.json (quickstart request-file format):
  {"questions": {"qid": {"type": "choice", "instructions": "...",
                         "criteria": {"yes": null, "no": null, "other": "description"}}}}
Output: JSON {"model","inputs","answers":{qid:{probabilities,prediction}}}
"""
import argparse
import json
import os
import sys

CODE = "/data/night/src/Visual-Jev-main/code"
BASE = "/data/night/models/Qwen3-VL-4B-Instruct"
ADAPTER = "/data/night/models/visual-jev-4b-answer-sft"
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "1")   # card0 is production vLLM: never touch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--context", default="")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--adapter", default=ADAPTER)
    ap.add_argument("--out")
    ap.add_argument("--device", default=None)
    ap.add_argument("--max-pixels", type=int, default=200704)
    a = ap.parse_args()
    if a.device:
        os.environ["CUDA_VISIBLE_DEVICES"] = a.device

    with open(a.questions, encoding="utf-8") as f:
        request = json.load(f)
    req_q = request["questions"]
    shared_context = request.get("state", "") or a.context

    import torch
    from PIL import Image
    from peft import PeftModel
    sys.path.insert(0, CODE)
    from vdm.models.vdm_model import VDM

    questions, keys = [], []
    for qid, item in req_q.items():
        assert item.get("type") == "choice", "visual-jev wrapper: only choice questions"
        crit = item["criteria"]
        assert 2 <= len(crit) <= 16
        cands = []
        ck = []
        for oid, desc in crit.items():
            ck.append(oid)
            cands.append(oid if desc in (None, "") else f"{oid}: {desc}")
        keys.append(ck)
        questions.append({"qtype": "choice", "instruction": item["instructions"],
                          "candidates": cands})

    model = VDM(a.base, device="cuda", dtype=torch.bfloat16, with_heads=False)
    model.processor.image_processor.max_pixels = a.max_pixels
    model.backbone = PeftModel.from_pretrained(model.backbone, a.adapter).eval()

    with Image.open(a.image) as src:
        image = src.convert("RGB")
    with torch.inference_mode():
        group = model.prepare_group(image, questions, shared_context=shared_context)
        run = model.run_independent if len(questions) == 1 else model.run_prefix_share_batch
        output = run(group)

    answers = {}
    for i, qid in enumerate(req_q):
        logits = output["lm_option_logits"][i, :group.n_options[i]]
        probs = torch.softmax(logits.float(), dim=-1).cpu().tolist()
        answers[qid] = {"probabilities": {k: round(p, 4) for k, p in zip(keys[i], probs)},
                        "prediction": keys[i][max(range(len(probs)), key=probs.__getitem__)]}
    result = {"model": "Visual-Jev-4B(answer-sft)", "base": a.base, "adapter": a.adapter,
              "inputs": {"image": a.image}, "context": shared_context, "answers": answers}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
