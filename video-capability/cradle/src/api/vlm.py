"""VLM 视觉质检能力: API(OpenAI 兼容, 图像输入)优先, 本地 CLIP 启发式兜底。

输出契约与 SPECS §5.4 提示词完全一致:
{defects{7项}, aesthetic{5项1-5}, camera_match 1-5, overall_score 0-1, verdict, main_issue}
本地启发式标注 model=clip_heuristic / unreviewed_by_vlm=True (报告标注"该批未经VLM审核", D-004)。
"""

from __future__ import annotations

from .adapters import Adapter, BudgetGuard, Endpoint, encode_image_data_url, http_post_json

DEFECT_KEYS = (
    "deformed_object",
    "morphing_artifact",
    "flicker",
    "garbled_text",
    "subject_missing",
    "unnatural_motion",
    "overall_defect",
)
AESTHETIC_KEYS = ("composition", "lighting", "color", "appeal", "overall")
DEFECT_KEYS_ZH = {
    "deformed_object": "主体变形",
    "morphing_artifact": "画面形变",
    "flicker": "闪烁",
    "garbled_text": "乱码伪文字",
    "subject_missing": "主体缺失",
    "unnatural_motion": "运动诡异",
    "overall_defect": "综合缺陷",
}


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def parse_vlm_json(text: str) -> dict:
    """从 VLM 返回文本中解析并归一化评分 JSON。不合规抛 ValueError(触发重试)。"""
    if isinstance(text, dict):
        raw = text
    else:
        s = text.strip()
        if "```" in s:  # 剥代码围栏
            parts = s.split("```")
            s = max(parts, key=len)
        i, j = s.find("{"), s.rfind("}")
        if i < 0 or j <= i:
            raise ValueError(f"VLM 返回中未找到 JSON 对象: {text[:120]!r}")
        import json as _json

        raw = _json.loads(s[i : j + 1])

    defects = raw.get("defects")
    aesthetic = raw.get("aesthetic")
    if not isinstance(defects, dict) or any(k not in defects for k in DEFECT_KEYS):
        raise ValueError("VLM JSON 缺少 defects 或分项不全")
    if not isinstance(aesthetic, dict) or any(k not in aesthetic for k in AESTHETIC_KEYS):
        raise ValueError("VLM JSON 缺少 aesthetic 或分项不全")
    for k in DEFECT_KEYS:
        defects[k] = clamp01(defects[k])
    for k in AESTHETIC_KEYS:
        aesthetic[k] = max(1.0, min(5.0, float(aesthetic[k])))
    out = {
        "defects": {k: defects[k] for k in DEFECT_KEYS},
        "aesthetic": {k: aesthetic[k] for k in AESTHETIC_KEYS},
        "camera_match": max(1.0, min(5.0, float(raw["camera_match"]))),
        "overall_score": clamp01(raw["overall_score"]),
        "verdict": raw.get("verdict"),
        "main_issue": str(raw.get("main_issue", "")),
    }
    if out["verdict"] not in ("pass", "borderline", "fail"):
        raise ValueError(f"verdict 非法: {out['verdict']!r}")
    return out


def api_review(endpoint: Endpoint, grid_png_path: str, prompt_text: str, http=http_post_json) -> dict:
    """OpenAI 兼容 chat, 图像输入 + 质检提示词, 解析 JSON 契约。"""
    payload = {
        "model": endpoint.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": encode_image_data_url(grid_png_path)}},
                ],
            }
        ],
        "temperature": 0,
    }
    data = http(f"{endpoint.base}/chat/completions", endpoint.key, payload)
    content = data["choices"][0]["message"]["content"]
    return parse_vlm_json(content)


# ---------------- 本地 CLIP 启发式 ----------------

def _map01(x: float, lo: float = 0.15, hi: float = 0.70) -> float:
    """CLIP 余弦相似度 → 0..1 (经验线性映射, D-009)。"""
    return clamp01((x - lo) / (hi - lo))


def _load_clip_fns(device: str = "cpu"):
    """默认嵌入器: open_clip ViT-L/14。lazy import; 返回 (image_embed, text_embed)。"""
    try:
        import open_clip
        import torch
        from PIL import Image
    except Exception as e:  # pragma: no cover
        from .adapters import LocalUnavailable

        raise LocalUnavailable(f"open_clip 本地依赖不可用: {e}") from e
    model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained="openai")
    model = model.to(device).eval()
    tokenizer = open_clip.get_tokenizer("ViT-L-14")

    def image_embed(img):
        with torch.no_grad():
            f = model.encode_image(preprocess(img.convert("RGB")).unsqueeze(0).to(device))
        return (f / f.norm(dim=-1, keepdim=True)).squeeze(0).cpu().numpy()

    def text_embed(text):
        with torch.no_grad():
            toks = tokenizer([text]).to(device)
            f = model.encode_text(toks)
        return (f / f.norm(dim=-1, keepdim=True)).squeeze(0).cpu().numpy()

    return image_embed, text_embed


def clip_heuristic_review(
    grid_png_path: str,
    prompt_text: str | None = None,
    image_embed=None,
    text_embed=None,
    grid_cols: int = 2,
    grid_rows: int = 5,
) -> dict:
    """CLIP ViT-L/14 启发式评分。与 VLM JSON 契约同构, 标注 clip_heuristic。

    image_embed(PIL.Image)->vec, text_embed(str)->vec 均可注入(单测 stub);
    未提供时 lazy 加载 open_clip。
    """
    import numpy as np
    from PIL import Image

    if image_embed is None or text_embed is None:
        image_embed, text_embed = _load_clip_fns()

    img = Image.open(grid_png_path).convert("RGB")
    w, h = img.size
    cells = []
    for r in range(grid_rows):
        for c in range(grid_cols):
            box = (c * w // grid_cols, r * h // grid_rows, (c + 1) * w // grid_cols, (r + 1) * h // grid_rows)
            cells.append(img.crop(box))

    anchors = {
        "pos": "a clear sharp professional photograph, well composed subject",
        "deformed": "a deformed melted distorted malformed blob",
        "garbled": "garbled nonsense pseudo text characters overlay",
        "dark": "a pitch black empty dark frame",
        "bright": "a blown out overexposed plain white frame",
        "blur": "heavy motion blur ghosting double exposure smear",
        "appeal": "beautiful appetizing professional food photography, warm color, shallow depth of field",
    }
    ea = {k: np.asarray(text_embed(v), dtype="float32") for k, v in anchors.items()}
    if prompt_text is not None:
        ea["prompt"] = np.asarray(text_embed(prompt_text[:256]), dtype="float32")

    per_cell = []
    for cell in cells:
        v = np.asarray(image_embed(cell), dtype="float32")

        def sim(name: str) -> float:
            return float(np.dot(v, ea[name]))

        per_cell.append(
            {
                "deformed": sim("deformed"),
                "garbled": sim("garbled"),
                "dark": sim("dark"),
                "bright": sim("bright"),
                "blur": sim("blur"),
                "pos": sim("pos"),
                "appeal": sim("appeal"),
                "prompt": sim("prompt") if "prompt" in ea else None,
            }
        )

    def agg(key: str, how: str = "max") -> float:
        vals = [c[key] for c in per_cell if c[key] is not None]
        return max(vals) if how == "max" else sum(vals) / max(1, len(vals))

    # 缺陷分: 负锚相似度越高缺陷越高; 主体缺失用正锚相似度取反
    defects = {
        "deformed_object": _map01(agg("deformed")),
        "morphing_artifact": _map01(max(agg("deformed"), agg("blur")) * 0.9),
        "flicker": _map01(agg("blur") * 0.8),
        "garbled_text": _map01(agg("garbled")),
        "subject_missing": clamp01(1.0 - _map01(agg("pos", how="mean"), lo=0.10, hi=0.55)),
        "unnatural_motion": _map01(agg("blur") * 0.85),
    }
    defects["overall_defect"] = clamp01(sum(defects.values()) / len(defects) * 1.2)

    appeal01 = _map01(agg("appeal", how="mean"), lo=0.12, hi=0.55)
    aesthetic = {
        "composition": float(max(1, min(5, round(1 + 4 * appeal01)))),
        "lighting": float(max(1, min(5, round(1 + 4 * _map01(agg("pos", how="mean"), lo=0.10, hi=0.55))))),
        "color": float(max(1, min(5, round(1 + 4 * appeal01 * 0.95)))),
        "appeal": float(max(1, min(5, round(1 + 4 * appeal01)))),
    }
    aesthetic["overall"] = float(max(1, min(5, round(sum(aesthetic.values()) / 4))))
    camera_match = (
        float(max(1, min(5, round(1 + 4 * _map01(agg("prompt", how="mean"), lo=0.10, hi=0.50)))))
        if "prompt" in ea
        else 3.0
    )

    overall_score = 0.45 * (1 - defects["overall_defect"]) + 0.35 * (aesthetic["overall"] / 5) + 0.2 * (
        camera_match / 5
    )
    hard_fail = any(v >= 0.5 for k, v in defects.items() if k != "overall_defect")
    if overall_score >= 0.70 and defects["overall_defect"] <= 0.2 and defects["garbled_text"] <= 0.3 and not hard_fail:
        verdict = "pass"
        main_issue = "无明显问题"
    elif hard_fail or overall_score < 0.55:
        verdict = "fail"
        worst = max((k for k in defects if k != "overall_defect"), key=lambda k: defects[k])
        main_issue = f"{DEFECT_KEYS_ZH[worst]}偏高风险"
    else:
        verdict = "borderline"
        main_issue = "整体可过但有瑕疵, 建议复核"

    return {
        "defects": defects,
        "aesthetic": aesthetic,
        "camera_match": camera_match,
        "overall_score": round(overall_score, 4),
        "verdict": verdict,
        "main_issue": main_issue,
        "model": "clip_heuristic",
        "unreviewed_by_vlm": True,
    }


def make_vlm_adapter(endpoint: Endpoint, budget: BudgetGuard, local_fn=None, log=None) -> Adapter:
    return Adapter(
        "vlm",
        endpoint,
        budget,
        api_fn=lambda grid_path, prompt_text, **kw: api_review(endpoint, grid_path, prompt_text, **kw),
        local_fn=local_fn or clip_heuristic_review,
        log=log,
    )
