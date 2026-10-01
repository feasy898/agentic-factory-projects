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


def api_review(endpoint: Endpoint, grid_png_path: str, prompt_text: str, http=http_post_json, **_) -> dict:
    """OpenAI 兼容 chat, 图像输入 + 质检提示词, 解析 JSON 契约。

    额外 kwargs(如 asset_type)对真实 VLM 无意义, 显式接收并忽略(**_),
    以保持与本地启发式相同的调用契约。
    """
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


# M5 G5 分锚 (阶段0校准, 依据 tools/m5_anchor_probe.py 实测 → workdir/logs/m5_clip_anchor_scene.json,
# 全过程见 reports/milestones/m5_calibration.md): 美食锚(D-026)对夜景/雨窗/背影类系统性打低,
# 与合成坏帧完全重叠(food 锚: scene 帧最小 0.1374 < 坏帧最大 0.1564, gap=-0.019)。
# scene 锚选型: 5 候选文案实测, s4_grading 分离度最佳(scene 帧 min 0.1980 vs 坏帧 max 0.1668, gap=+0.0312)。
# 域定标: lo=0.18(坏帧 max 0.1668 之上, scene 帧 min 0.1980 之下), hi=0.25(scene p95≈0.239 附近)。
# **最终设计=双锚取最优(appeal01=max(food,scene))**: 离线重评发现按资产类型硬切换会让
# "空餐桌"类美食观感资产(assets/scenes/table_01)被 scene 锚误杀(0.78→0.64),
# 双锚 max 对美食帧恒等于 food 锚结果(实测 food 帧场景锚 sim≤0.19 < 其 food sim),
# 对场景帧取 scene 锚, 对坏帧两锚皆低且缺陷锚兜底 — 无分类器脆弱性。
ASSET_TYPES = ("food", "scene")
APPEAL_ANCHORS = {
    "food": "beautiful appetizing professional food photography, warm color, shallow depth of field",
    "scene": "stunning cinematic photography with rich color grading and beautiful lighting",
}
APPEAL_DOMAINS = {
    "food": (0.145, 0.28),  # D-026 实测域, 不动
    "scene": (0.18, 0.25),  # M5 实测域, 见 m5_anchor_probe 输出
}


_CLIP_FNS_CACHE: dict = {}  # 进程级缓存(同 g3_consistency, D-027)


def _openai_clip_weights() -> str:
    """openai 权重本地路径优先(pretrained="openai" 会走 HF hub, 离线/慢源不可用, D-027)。"""
    import os

    env_p = os.environ.get("CRADLE_CLIP_WEIGHTS", "")
    if env_p and os.path.exists(env_p):
        return env_p
    try:
        from ..config import project_root

        local = project_root() / "models" / "clip" / "ViT-L-14.pt"
        if local.exists():
            return str(local)
    except Exception:
        pass
    return "openai"


def _load_clip_fns(device: str = "cpu"):
    """默认嵌入器: open_clip ViT-L/14。lazy import; 返回 (image_embed, text_embed)。"""
    if device in _CLIP_FNS_CACHE:
        return _CLIP_FNS_CACHE[device]
    try:
        import open_clip
        import torch
        from PIL import Image
    except Exception as e:  # pragma: no cover
        from .adapters import LocalUnavailable

        raise LocalUnavailable(f"open_clip 本地依赖不可用: {e}") from e
    model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained=_openai_clip_weights())
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

    _CLIP_FNS_CACHE[device] = (image_embed, text_embed)
    return _CLIP_FNS_CACHE[device]


def clip_heuristic_review(
    grid_png_path: str,
    prompt_text: str | None = None,
    image_embed=None,
    text_embed=None,
    grid_cols: int = 2,
    grid_rows: int = 5,
    asset_type: str = "food",
) -> dict:
    """CLIP ViT-L/14 启发式评分。与 VLM JSON 契约同构, 标注 clip_heuristic。

    image_embed(PIL.Image)->vec, text_embed(str)->vec 均可注入(单测 stub);
    未提供时 lazy 加载 open_clip。
    asset_type: 按首帧资产路径推导的资产类型标签(food/scene), 记录进输出供报告分组;
    M5 最终校准为**双锚取最优**: appeal 同时对 food/scene 两锚计算, appeal01 取两域映射的
    max — 美食帧结果与 D-026 完全一致(food 锚恒占优), 场景/夜景帧由 scene 锚正确评分。
    """
    import numpy as np
    from PIL import Image

    if asset_type not in APPEAL_ANCHORS:
        asset_type = "food"
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
        # appeal 双锚(M5 校准): food=D-026 原锚, scene=实测选型锚; appeal01 取两域映射 max
        "appeal_food": APPEAL_ANCHORS["food"],
        "appeal_scene": APPEAL_ANCHORS["scene"],
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
                "appeal_food": sim("appeal_food"),
                "appeal_scene": sim("appeal_scene"),
                "prompt": sim("prompt") if "prompt" in ea else None,
            }
        )

    def agg(key: str, how: str = "max") -> float:
        vals = [c[key] for c in per_cell if c[key] is not None]
        return max(vals) if how == "max" else sum(vals) / max(1, len(vals))

    # 缺陷分 (D-026 实测重校准: 11 张资产 + LTX 真实帧 + 合成坏帧, 见 workdir/logs/m2_clip_anchor_*.json):
    # - pos 锚对平坦垃圾帧反向(黑/灰 pos 0.175-0.198 > 美食帧 0.154-0.163), 不可用作 subject 信号;
    # - garbled 锚可分(正样本 0.042-0.115 vs 文字/噪声 0.183-0.197) → 域收紧 (0.12, 0.30);
    # - subject_missing 无可靠 CLIP 文本锚, 退化为"内容丧失"复合信号(garbled/dark/bright),
    #   语义局限(真实主体缺席不触发)如实写入报告;
    # - appeal 锚是内容/食欲 present 的有效信号(正 0.145-0.232 vs 坏帧 ≤0.156) → 美学域 (0.145, 0.28);
    #   夜景/背影类系统性偏低问题已由 M5 分锚解决(asset_type="scene" 走实测选型锚与新域)。
    defects = {
        "deformed_object": _map01(agg("deformed")),
        "morphing_artifact": _map01(max(agg("deformed"), agg("blur")) * 0.9),
        "flicker": _map01(agg("blur") * 0.8),
        "garbled_text": _map01(agg("garbled"), lo=0.12, hi=0.30),
        "subject_missing": max(
            _map01(agg("garbled"), lo=0.12, hi=0.30),
            _map01(agg("dark"), lo=0.20, hi=0.32),
            _map01(agg("bright"), lo=0.16, hi=0.28),
        ),
        "unnatural_motion": _map01(agg("blur") * 0.85),
    }
    defects["overall_defect"] = clamp01(sum(defects.values()) / len(defects) * 1.2)

    food01 = _map01(agg("appeal_food", how="mean"), lo=APPEAL_DOMAINS["food"][0], hi=APPEAL_DOMAINS["food"][1])
    scene01 = _map01(agg("appeal_scene", how="mean"), lo=APPEAL_DOMAINS["scene"][0], hi=APPEAL_DOMAINS["scene"][1])
    appeal01 = max(food01, scene01)  # 双锚取最优(M5): 美食帧 food 锚占优, 场景帧 scene 锚占优
    appeal_basis = "food" if food01 >= scene01 else "scene"
    aesthetic = {
        "composition": float(max(1, min(5, round(1 + 4 * appeal01)))),
        "lighting": float(max(1, min(5, round(1 + 4 * appeal01)))),
        "color": float(max(1, min(5, round(1 + 4 * appeal01 * 0.95)))),
        "appeal": float(max(1, min(5, round(1 + 4 * appeal01)))),
    }
    aesthetic["overall"] = float(max(1, min(5, round(sum(aesthetic.values()) / 4))))
    # D-026: 门禁传入的是 QC 提示词(无运镜信息, 实测与各锚自相似 0.48-0.72) → camera_match 取中性 3.0;
    # 只有显式传入镜头级 prompt 才启用锚点映射。
    if "prompt" in ea and prompt_text is not None and "质检员" not in str(prompt_text):
        camera_match = float(max(1, min(5, round(1 + 4 * _map01(agg("prompt", how="mean"), lo=0.10, hi=0.50)))))
        camera_basis = "shot_prompt_anchor"
    else:
        camera_match = 3.0
        camera_basis = "neutral_qc_prompt"

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
        "camera_match_basis": camera_basis,
        "asset_type": asset_type,
        "appeal_basis": appeal_basis,
        "appeal01_food": round(food01, 4),
        "appeal01_scene": round(scene01, 4),
        "calibration": "D-026+M5-dual-anchor",
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
