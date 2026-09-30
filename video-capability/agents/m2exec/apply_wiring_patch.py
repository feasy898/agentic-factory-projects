#!/usr/bin/env python3
"""M2-EXEC wiring patch: orchestrator LTX 车道接线 / cli ingest 卡片投影 / CLIP 模型缓存 / 测试同步。

每个替换都断言恰好命中一次, 防止重复应用或漂移。
"""
import sys
from pathlib import Path

REPO = Path("~/cradle").expanduser()


def patch(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    n = text.count(old)
    assert n == 1, f"[{label}] 期望命中 1 次, 实际 {n} 次: {path}"
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"patched {label} -> {path.name}")


# ---------------- 1. orchestrator._default_generator: LTX 调试车道接线 ----------------
patch(
    REPO / "src/orchestrator.py",
    """            # 产出期守卫: Wan 候选总数 ≤200 (SPECS §5.3)
            if settings.get("debug_model") != "force_ltx":
                used = db._query(
                    "SELECT COUNT(*) AS c FROM candidates WHERE verdict != 'fallback' AND shot_id IN"
                    " (SELECT shot_id FROM tasks WHERE lane IN ('first_frame_i2v','t2v'))"
                )[0]["c"]
                limit = settings.get("budgets", {}).get("wan_candidates_total", 200)
                if used >= limit:
                    raise RuntimeError(f"Wan 候选总数已达守卫上限 {limit}, 停止生成保交付")
            from .gen.wan import generate as wan_generate
""",
    """            # 调试车道: settings.debug_model=ltx → LTX 短样本 (SPECS §5.3; 装配见 D-024, 投影见 D-025)
            if settings.get("debug_model") == "ltx":
                from .gen.ltx import generate as ltx_generate

                return ltx_generate(
                    card, seed, out_path,
                    steps=int(hint.get("steps", 12)),
                    negative_extra=hint.get("negative_extra"),
                    guidance_delta=float(hint.get("guidance_delta", 0.0)),
                )
            # 产出期守卫: Wan 候选总数 ≤200 (SPECS §5.3)
            used = db._query(
                "SELECT COUNT(*) AS c FROM candidates WHERE verdict != 'fallback' AND shot_id IN"
                " (SELECT shot_id FROM tasks WHERE lane IN ('first_frame_i2v','t2v'))"
            )[0]["c"]
            limit = settings.get("budgets", {}).get("wan_candidates_total", 200)
            if used >= limit:
                raise RuntimeError(f"Wan 候选总数已达守卫上限 {limit}, 停止生成保交付")
            from .gen.wan import generate as wan_generate
""",
    "orchestrator-ltx-lane",
)

# ---------------- 2. cli.cmd_ingest: debug_model=ltx 时卡面投影落库 (D-025) ----------------
patch(
    REPO / "src/cli.py",
    """        try:
            card = load_shotcard(f)
            tid = db.ingest_task(card["shot_id"], card["narrative_slot"], card["lane"],
                                 card_json=card, template=args.template)
            ok += 1
            print(f"ingest {card['shot_id']} (task#{tid}, lane={card['lane']}, template={args.template})")
""",
    """        try:
            card = load_shotcard(f)
            card_eff = card
            if load_settings().get("debug_model") == "ltx" and card["lane"] != "ken_burns":
                # 调试期: 卡面投影为 LTX 调试卡落库, 生成与门禁共用同一口径 (D-025)
                from .gen.ltx import project_card_for_debug

                card_eff = project_card_for_debug(card)
            tid = db.ingest_task(card_eff["shot_id"], card_eff["narrative_slot"], card_eff["lane"],
                                 card_json=card_eff, template=args.template)
            ok += 1
            print(f"ingest {card_eff['shot_id']} (task#{tid}, lane={card_eff['lane']}, "
                  f"res={card_eff['resolution'][0]}x{card_eff['resolution'][1]}, "
                  f"dur={card_eff['duration_sec']}s, template={args.template})")
""",
    "cli-ingest-projection",
)

# ---------------- 3. g3_consistency.default_embed_fns: 进程级模型缓存 ----------------
patch(
    REPO / "src/gates/g3_consistency.py",
    '''def default_embed_fns(device: str = "cpu"):
    """返回 (image_embed, text_embed); lazy import open_clip, 不可用抛 RuntimeError。"""
    try:''',
    '''_EMBED_CACHE: dict = {}  # 进程级缓存(候选间复用, 避免逐候选重载 ViT-L/14)


def default_embed_fns(device: str = "cpu"):
    """返回 (image_embed, text_embed); lazy import open_clip, 不可用抛 RuntimeError。"""
    if device in _EMBED_CACHE:
        return _EMBED_CACHE[device]
    try:''',
    "g3-cache-head",
)
patch(
    REPO / "src/gates/g3_consistency.py",
    '''    def text_embed(text):
        with torch.no_grad():
            f = model.encode_text(tokenizer([text]).to(device))
        return (f / f.norm(dim=-1, keepdim=True)).squeeze(0).cpu().numpy()

    return image_embed, text_embed''',
    '''    def text_embed(text):
        with torch.no_grad():
            f = model.encode_text(tokenizer([text]).to(device))
        return (f / f.norm(dim=-1, keepdim=True)).squeeze(0).cpu().numpy()

    _EMBED_CACHE[device] = (image_embed, text_embed)
    return _EMBED_CACHE[device]''',
    "g3-cache-tail",
)

# ---------------- 4. api/vlm._load_clip_fns: 进程级模型缓存 ----------------
patch(
    REPO / "src/api/vlm.py",
    '''def _load_clip_fns(device: str = "cpu"):
    """默认嵌入器: open_clip ViT-L/14。lazy import; 返回 (image_embed, text_embed)。"""
    try:''',
    '''_CLIP_FNS_CACHE: dict = {}  # 进程级缓存(同 g3_consistency, D-027)


def _load_clip_fns(device: str = "cpu"):
    """默认嵌入器: open_clip ViT-L/14。lazy import; 返回 (image_embed, text_embed)。"""
    if device in _CLIP_FNS_CACHE:
        return _CLIP_FNS_CACHE[device]
    try:''',
    "vlm-cache-head",
)
patch(
    REPO / "src/api/vlm.py",
    '''    def text_embed(text):
        with torch.no_grad():
            toks = tokenizer([text]).to(device)
            f = model.encode_text(toks)
        return (f / f.norm(dim=-1, keepdim=True)).squeeze(0).cpu().numpy()

    return image_embed, text_embed''',
    '''    def text_embed(text):
        with torch.no_grad():
            toks = tokenizer([text]).to(device)
            f = model.encode_text(toks)
        return (f / f.norm(dim=-1, keepdim=True)).squeeze(0).cpu().numpy()

    _CLIP_FNS_CACHE[device] = (image_embed, text_embed)
    return _CLIP_FNS_CACHE[device]''',
    "vlm-cache-tail",
)

# ---------------- 5. tests/test_gen.py: 模型标签同步 + 新增测试 ----------------
patch(
    REPO / "tests/test_gen.py",
    """from src.gen.common import build_frames_to_mp4_argv, even, write_frames_mp4
from src.gen.ltx import (
    LTX_MAX_DURATION_S,
    LTX_MAX_STEPS,
    LTX_RESOLUTION,
    generate as ltx_generate,
    validate_ltx_params,
)""",
    """from src.gen.common import build_frames_to_mp4_argv, even, open_center_resize, write_frames_mp4
from src.gen.ltx import (
    LTX_MAX_DURATION_S,
    LTX_MAX_STEPS,
    LTX_RESOLUTION,
    generate as ltx_generate,
    project_card_for_debug,
    validate_ltx_params,
)""",
    "test-gen-imports",
)
patch(
    REPO / "tests/test_gen.py",
    '''assert meta["seed"] == 7 and meta["steps"] == 25 and meta["model"] == "wan_i2v_13b"''',
    '''assert meta["seed"] == 7 and meta["steps"] == 25 and meta["model"] == "wan_fun_1.3b_inp"''',
    "test-gen-wan-tag",
)
patch(
    REPO / "tests/test_gen.py",
    '''def test_wan_generate_rejects_bad_steps(tmp_path):
    with pytest.raises(ValueError):
        wan_generate(_wan_card(), seed=1, out_path="x.mp4", steps=15, num_frames=9,
                     pipeline=lambda **k: [])''',
    '''def test_wan_generate_rejects_bad_steps(tmp_path):
    with pytest.raises(ValueError):
        wan_generate(_wan_card(), seed=1, out_path="x.mp4", steps=15, num_frames=9,
                     pipeline=lambda **k: [])


# ---------------- M2-EXEC wiring: 首帧预处理 / 卡片投影 / LTX 重试钩子 ----------------

def test_open_center_resize_crops_to_target_ar(tmp_path):
    from PIL import Image

    wide = Image.new("RGB", (800, 400), (200, 30, 30))
    pw = tmp_path / "wide.png"
    wide.save(pw)
    img = open_center_resize(str(pw), 384, 512)
    assert img.size == (384, 512)

    tall = Image.new("RGB", (400, 800), (30, 200, 30))
    pt = tmp_path / "tall.png"
    tall.save(pt)
    img2 = open_center_resize(str(pt), 480, 832)
    assert img2.size == (480, 832)

    same = Image.new("RGB", (384, 512), (10, 10, 250))
    ps = tmp_path / "same.png"
    same.save(ps)
    img3 = open_center_resize(str(ps), 384, 512)
    assert img3.size == (384, 512)


def test_project_card_for_debug(valid_card):
    proj = project_card_for_debug(valid_card)
    assert proj["resolution"] == [384, 512]
    assert proj["fps"] == 16
    assert proj["duration_sec"] <= LTX_MAX_DURATION_S
    n = round(proj["duration_sec"] * 16)
    assert (n - 1) % 8 == 0  # 8k+1 帧布局
    assert proj["fallback"]["duration_sec"] == proj["duration_sec"]
    assert proj["prompt_en"] == valid_card["prompt_en"]
    assert proj["negative"] == valid_card["negative"]
    assert proj["n_best"] == valid_card["n_best"] and proj["retry_max"] == valid_card["retry_max"]
    assert proj["acceptance"] == valid_card["acceptance"]
    from src.schema import validate_shotcard

    validate_shotcard(proj)  # 投影卡必须仍过 schema


def test_ltx_generate_retry_hooks(tmp_path):
    calls = {}

    def fake_pipeline(**kw):
        calls.update(kw)
        return [np.full((16, 24, 3), 128, dtype="uint8") for _ in range(kw["num_frames"])]

    out = tmp_path / "ltx_hooks.mp4"
    meta = ltx_generate(_ltx_card(), seed=5, out_path=str(out), steps=12, pipeline=fake_pipeline,
                        negative_extra=["blurry"], guidance_delta=-0.5)
    assert calls["guidance"] == 2.5  # 3.0 - 0.5
    assert "blurry" in calls["negative"]
    assert meta["hint"]["guidance_delta"] == -0.5 and meta["vae_mode"] == "fp16"''',
    "test-gen-new-tests",
)

print("ALL PATCHES OK")
