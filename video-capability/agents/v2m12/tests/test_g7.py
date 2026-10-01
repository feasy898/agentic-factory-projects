"""G7 物体恒存门禁: 全子项 stub 注入单测(SPECS_V2 §3), 不依赖 GPU/模型。"""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from src.gates.g7_object_persistence import (
    COLD_START_THRESHOLDS,
    G7E_KEYS,
    LiteByteTracker,
    build_gdino_prompt,
    clamp_box,
    count_series_metrics,
    crop_box,
    derive_detect_terms,
    g7_object_persistence,
    g7e_triggered,
    global_ssim,
    iou,
    load_prompt_text,
    load_thresholds,
    make_pair_image,
    match_box,
    parse_g7e_json,
    p95,
    stride_indices,
    tracker_stats,
    union_box,
)


def make_frame(idx: int, red: int, green: int = 0, size: tuple = (16, 16)) -> Image.Image:
    """测试帧: 红通道携带身份(red), 绿通道携带检测数量(green)。"""
    img = Image.new("RGB", size, (red % 256, green, 2))
    return img


class RedEmbed:
    """按图像平均红色通道返回指定向量, 构造可控余弦。"""

    def __init__(self, vec_by_red):
        self.vec_by_red = {int(k): np.asarray(v, dtype="float64") for k, v in vec_by_red.items()}

    def __call__(self, img):
        arr = np.asarray(img.convert("RGB"), dtype="float64")
        key = int(round(arr[..., 0].mean()))
        if key not in self.vec_by_red:
            raise KeyError(f"未配置红色通道 {key}")
        return self.vec_by_red[key]


class GreenDetect:
    """按 (0,0) 绿色通道值返回等量检测框(高分, 分布固定)。"""

    def __call__(self, img, prompt):
        n = img.getpixel((0, 0))[1]
        return [{"box": [2, 2 + i * 3, 9, 5 + i * 3], "score": 0.9, "label": "x"} for i in range(n)]


# ---------- 纯工具 ----------

def test_stride_indices():
    assert stride_indices(16) == [0, 4, 8, 12, 15]
    assert stride_indices(8) == [0, 2, 4, 6, 7]
    assert stride_indices(5) == [0, 1, 2, 3, 4]
    assert stride_indices(3) == [0, 2] or stride_indices(3)[0] == 0 and stride_indices(3)[-1] == 2
    assert stride_indices(1) == [0]
    assert stride_indices(0) == []


def test_clamp_union_iou_match():
    assert clamp_box([-5, -5, 999, 999], 16, 16) == [0, 0, 15, 15]
    assert union_box([[0, 0, 4, 4], [2, 2, 8, 8]]) == [0, 0, 8, 8]
    assert union_box([]) is None
    assert iou([0, 0, 4, 4], [0, 0, 4, 4]) == pytest.approx(1.0)
    assert iou([0, 0, 4, 4], [4, 4, 8, 8]) == 0.0
    assert iou([0, 0, 4, 4], [2, 0, 6, 4]) == pytest.approx(4 / 12)
    img = Image.new("RGB", (16, 16), (0, 0, 0))
    assert crop_box(img, None).size == (16, 16)
    assert crop_box(img, [0, 0, 8, 4]).size == (8, 4)
    best = match_box([0, 0, 4, 4], [{"box": [1, 0, 5, 4]}, {"box": [10, 10, 14, 14]}], min_iou=0.05)
    assert best == [1, 0, 5, 4]


def test_count_series_metrics():
    m = count_series_metrics([3, 3, 4, 9, 15])
    assert m["max_abs_delta"] == 6
    assert m["variance"] > 0
    assert count_series_metrics([5]) == {"max_abs_delta": 0.0, "variance": 0.0}
    assert count_series_metrics([2, 2, 2])["variance"] == 0.0


def test_p95_and_ssim():
    assert p95(list(range(1, 101))) == pytest.approx(95.05, abs=0.2)
    a = np.full((16, 16), 128, dtype="float64")
    assert global_ssim(a, a) == pytest.approx(1.0)
    b = a.copy()
    b[0, 0] = 255
    assert 0.0 < global_ssim(a, b) < 1.0


def test_derive_detect_terms():
    card = {"prompt_en": "extreme close-up of fresh beef tripe dipped into boiling red spicy hotpot broth, "
                         "oil bubbles, rising steam, professional food photography",
            "subject": {"type": "object", "desc_en": ""}}
    terms = derive_detect_terms(card)
    assert terms == ["tripe", "hot pot", "broth"]  # 跨度消费: 无 beef/shrimp 重复; 无 steam
    card2 = {"prompt_en": "hand-made shrimp paste balls dropped into boiling red spicy broth, "
                          "rolling and setting, bubbles, professional food photography"}
    assert "shrimp" in derive_detect_terms(card2)
    assert derive_detect_terms({"prompt_en": "beautiful abstract gradient background, bokeh"}) == []
    assert derive_detect_terms({}) == []
    assert len(derive_detect_terms({"prompt_en": "hotpot broth shrimp tripe beef bowl plate pot glass"})) <= 5


def test_build_gdino_prompt():
    assert build_gdino_prompt(["shrimp", "bowl", "hot pot"]) == "shrimp. bowl. hot pot."
    assert build_gdino_prompt([]) == ""


def test_tracker_steady_and_flicker():
    tr = LiteByteTracker(min_hits=2, max_age=2)
    dets = [{"box": [2, 2, 9, 5], "score": 0.9}, {"box": [2, 8, 9, 11], "score": 0.8}]
    for i in range(8):
        if i == 3:  # 单帧丢失, max_age=2 应复活而非换 ID
            dets_i = []
        else:
            dets_i = dets
        tr.update(dets_i, i)
    stats = tracker_stats(tr, 8)
    assert stats["n_tracks"] == 2
    assert stats["counts"] == [2] * 8  # confirmed 区间含首帧
    assert stats["churn"] == 0


def test_tracker_birth_death_churn():
    tr = LiteByteTracker(min_hits=2, max_age=1)
    for i in range(8):
        if i <= 2:
            d = [{"box": [2, 2, 9, 5], "score": 0.9}]
        elif i >= 5:
            d = [{"box": [2, 8, 9, 11], "score": 0.9}]  # 旧目标消失, 新目标出现
        else:
            d = []
        tr.update(d, i)
    stats = tracker_stats(tr, 8)
    assert stats["births"] == 1 and stats["deaths"] == 1 and stats["churn"] == 2


def test_tracker_single_frame_noise_ignored():
    tr = LiteByteTracker(min_hits=2, max_age=1)
    for i in range(6):
        d = [{"box": [2, 2, 9, 5], "score": 0.9}] + ([{"box": [14, 14, 15, 15], "score": 0.99}] if i == 3 else [])
        tr.update(d, i)
    stats = tracker_stats(tr, 6)
    assert stats["counts"] == [1] * 6  # 单帧误检不入计数
    assert stats["churn"] == 0  # 未 confirm 的噪声不产生 churn


# ---------- G7e ----------

def test_parse_g7e_json():
    ok = '{"object_shape_kept":1,"object_count_kept":0.8,"no_liquid_flow":0.5,"no_split_merge":0.9,' \
         '"verdict":"fail","main_issue":"虾仁液化"}'
    parsed = parse_g7e_json(f"```json\n{ok}\n```")
    assert [parsed[k] for k in G7E_KEYS] == [1.0, 0.8, 0.5, 0.9]
    assert parsed["verdict"] == "fail" and parsed["main_issue"] == "虾仁液化"
    assert g7e_triggered(parsed, 0.6) is True
    good = parse_g7e_json({"object_shape_kept": 1, "object_count_kept": 1, "no_liquid_flow": 1,
                           "no_split_merge": 1, "verdict": "pass", "main_issue": ""})
    assert g7e_triggered(good, 0.6) is False
    with pytest.raises(ValueError):
        parse_g7e_json("没有 JSON")
    with pytest.raises(ValueError):
        parse_g7e_json('{"object_shape_kept":1}')


def test_prompt_file_and_exemption():
    text = load_prompt_text()
    for kw in ("object_shape_kept", "object_count_kept", "no_liquid_flow", "no_split_merge",
               "verdict", "main_issue", "0.6", "豁免条款", "蒸汽", "烟雾", "火焰", "光斑", "涟漪",
               "左帧", "右帧"):
        assert kw in text, f"提示词缺少: {kw}"


def test_make_pair_image(tmp_path):
    a, b = Image.new("RGB", (16, 16), (255, 0, 0)), Image.new("RGB", (16, 8), (0, 255, 0))
    p = make_pair_image(a, b, str(tmp_path / "pair.png"))
    img = Image.open(p)
    # 右帧按左帧高度等比放大: 16x8 → 32x16; 画布 = 16 + 32 + 8 宽, 16 高
    assert img.size == (16 + 32 + 8, 16)


# ---------- 阈值加载 ----------

def test_load_thresholds_defaults_and_yaml(tmp_path):
    assert load_thresholds(path="/nonexistent/xx.yaml")["g7a_min_cos"] == 0.75
    y = tmp_path / "th.yaml"
    y.write_text("g7:\n  g7a_min_cos: 0.61\n  g7c_flow_p95_max_px: 1.2\n", encoding="utf-8")
    th = load_thresholds(path=str(y))
    assert th["g7a_min_cos"] == 0.61 and th["g7c_flow_p95_max_px"] == 1.2
    assert th["g7d_min_cos"] == COLD_START_THRESHOLDS["g7d_min_cos"]  # 未覆盖项保持冷启动


# ---------- 主入口(全 stub) ----------

def _frames_dir(tmp_path, reds, greens=None):
    import os

    d = tmp_path / "frames"
    d.mkdir(exist_ok=True)
    paths = []
    for i, r in enumerate(reds):
        g = (greens or [0] * len(reds))[i]
        p = d / f"frame_{i:03d}.png"
        make_frame(i, r, g).save(p)
        paths.append(str(p))
    return paths


def test_g7_all_healthy_pass(tmp_path):
    paths = _frames_dir(tmp_path, [10] * 8, [3] * 8)
    g = g7_object_persistence(
        "fake.mp4", ["shrimp", "bowl"],
        thresholds={"g7a_min_cos": 0.75, "g7d_min_cos": 0.75, "g7b_count_delta_tol": 2,
                    "g7b_count_var_max": 4, "g7b_churn_max": 3, "g7c_flow_p95_max_px": 0.5,
                    "g7e_min_ok": 0.6},
        embed_fn=RedEmbed({10: [1.0, 0.0]}),
        detect_fn=GreenDetect(), seg_fn=lambda img, boxes: np.zeros((16, 16), dtype=bool),
        flow_fn=lambda a, b, m: {"p95_px": 0.1, "photo_diff": 0.01, "ssim": 0.99, "raft": True},
        frame_paths=paths,
    )
    assert g["passed"] is True
    assert g["detail"]["a"]["score"] == pytest.approx(1.0)
    assert g["detail"]["d"]["score"] == pytest.approx(1.0)
    assert g["detail"]["b"]["counts"] == [3] * 8
    assert g["detail"]["b"]["triggered"] is False
    assert g["detail"]["c"]["skipped"] is False and g["detail"]["c"]["p95_px"] == pytest.approx(0.1)
    assert g["detail"]["e"]["skipped"] is True and g["detail"]["e"]["reason"] == "vlm_unavailable"
    # e skipped → 加权仅在 a/b/c/d 上
    exp = (0.30 * 1.0 + 0.25 * 1.0 + 0.25 * 1.0 + 0.20 * 1.0) / 1.0
    assert g["score"] == pytest.approx(round(exp, 4))


def test_g7_drift_triggers_a_and_d(tmp_path):
    paths = _frames_dir(tmp_path, [10] * 7 + [200], [3] * 8)
    g = g7_object_persistence(
        "fake.mp4", ["shrimp"], {},
        embed_fn=RedEmbed({10: [1.0, 0.0], 200: [0.0, 1.0]}),
        detect_fn=GreenDetect(),
        frame_paths=paths, n_samples=8,
    )
    assert g["passed"] is False
    assert g["detail"]["a"]["triggered"] is True  # 末段跨步 min 掉到 0
    assert g["detail"]["d"]["triggered"] is True  # 首尾全帧 0
    assert g["detail"]["c"]["skipped"] is True and g["detail"]["c"]["reason"] == "no_flow_fn"


def test_g7_count_drift_triggers_b(tmp_path):
    paths = _frames_dir(tmp_path, [10] * 8, [2] * 4 + [9] * 4)
    g = g7_object_persistence(
        "fake.mp4", ["shrimp"], {},
        embed_fn=RedEmbed({10: [1.0, 0.0]}),
        detect_fn=GreenDetect(),
        frame_paths=paths,
    )
    assert g["detail"]["b"]["triggered"] is True
    assert g["detail"]["b"]["max_abs_delta"] == 7
    assert g["passed"] is False


def test_g7_static_flow_triggers_c(tmp_path):
    calls = {}

    def flow_fn(a, b, mask):
        calls["mask_mean"] = float(np.asarray(mask, dtype=bool).mean())
        return {"p95_px": 8.0, "photo_diff": 0.2, "ssim": 0.4, "raft": True}

    paths = _frames_dir(tmp_path, [10] * 8, [2] * 8)
    g = g7_object_persistence(
        "fake.mp4", ["shrimp"], {"g7c_flow_p95_max_px": 0.5},
        embed_fn=RedEmbed({10: [1.0, 0.0]}),
        detect_fn=GreenDetect(),
        seg_fn=lambda img, boxes: np.zeros((16, 16), dtype=bool),  # 动态区=0 → 静态=全帧
        flow_fn=flow_fn,
        frame_paths=paths,
    )
    assert g["detail"]["c"]["triggered"] is True and g["detail"]["c"]["p95_px"] == pytest.approx(8.0)
    assert calls["mask_mean"] == pytest.approx(1.0)  # 反选生效: 动态并集为空 → 静态=全帧
    assert g["passed"] is False


def test_g7c_skips_without_subject(tmp_path):
    ran = {"flow": 0}
    paths = _frames_dir(tmp_path, [10] * 8, [0] * 8)  # 无检测词/无框
    g = g7_object_persistence(
        "fake.mp4", None, {},
        embed_fn=RedEmbed({10: [1.0, 0.0]}),
        flow_fn=lambda a, b, m: ran.update(n=ran["flow"] + 1) or {"p95_px": 0.1, "raft": True},
        frame_paths=paths,
    )
    assert g["detail"]["b"]["skipped"] is True and g["detail"]["b"]["reason"] == "no_terms_or_detect_fn"
    assert g["detail"]["c"]["skipped"] is True
    assert g["passed"] is True  # a/d 全帧口径仍工作


def test_g7_expected_static_mask(tmp_path):
    mask = tmp_path / "static.png"
    arr = np.zeros((16, 16), dtype=np.uint8)
    arr[:, :8] = 255  # 左半静态
    Image.fromarray(arr).save(mask)
    seen = {}

    def flow_fn(a, b, m):
        seen["m"] = np.asarray(m, dtype=bool).copy()
        return {"p95_px": 0.2, "raft": True}

    def boom_seg(img, boxes):
        raise AssertionError("expected_static_mask 存在时不应调用 SAM")

    paths = _frames_dir(tmp_path, [10] * 8, [2] * 8)
    g = g7_object_persistence(
        "fake.mp4", ["shrimp"], {},
        embed_fn=RedEmbed({10: [1.0, 0.0]}), detect_fn=GreenDetect(),
        seg_fn=boom_seg,
        flow_fn=flow_fn, frame_paths=paths, expected_static_mask=str(mask),
    )
    assert g["detail"]["c"]["mask_source"] == "expected_static_mask"
    assert seen["m"].mean() == pytest.approx(0.5)


def test_g7e_vlm_triggers_and_parse_fail(tmp_path):
    paths = _frames_dir(tmp_path, [10] * 8, [3] * 8)
    bad = '{"object_shape_kept":1,"object_count_kept":1,"no_liquid_flow":0.2,"no_split_merge":1,' \
          '"verdict":"fail","main_issue":"汤体液化"}'
    g = g7_object_persistence(
        "fake.mp4", ["shrimp"], {},
        embed_fn=RedEmbed({10: [1.0, 0.0]}), detect_fn=GreenDetect(),
        frame_paths=paths, vlm_fn=lambda png, prompt: bad,
    )
    assert g["detail"]["e"]["skipped"] is False and g["detail"]["e"]["triggered"] is True
    assert g["passed"] is False

    g2 = g7_object_persistence(
        "fake.mp4", ["shrimp"], {},
        embed_fn=RedEmbed({10: [1.0, 0.0]}), detect_fn=GreenDetect(),
        frame_paths=paths, vlm_fn=lambda png, prompt: "模型抽风返回非 JSON",
    )
    assert g2["detail"]["e"]["skipped"] is True and "vlm_failed" in g2["detail"]["e"]["reason"]
    assert g2["passed"] is True  # e 解析失败不误杀, 如实记录


def test_g7_insufficient_frames():
    g = g7_object_persistence("x.mp4", ["shrimp"], {}, frame_paths=["only.png"])
    assert g["passed"] is True
    assert all(g["detail"][s]["skipped"] for s in "abcde")


def test_g7_gate_structure_json_serializable(tmp_path):
    paths = _frames_dir(tmp_path, [10] * 8, [3] * 8)
    g = g7_object_persistence(
        "fake.mp4", ["shrimp", "bowl"], {},
        embed_fn=RedEmbed({10: [1.0, 0.0]}), detect_fn=GreenDetect(),
        frame_paths=paths,
    )
    assert g["gate"] == "G7"
    s = json.dumps(g, ensure_ascii=False)  # 入 gate_json 必须可序列化
    assert "G7" in s
    assert g["detail"]["meta"]["gdino_prompt"] == "shrimp. bowl."


def test_resolve_thresholds_precedence(tmp_path):
    from src.gates.g7_object_persistence import resolve_thresholds
    # 显式 dict → 合并冷启动
    th = resolve_thresholds({"g7a_min_cos": 0.61})
    assert th["g7a_min_cos"] == 0.61 and th["g7d_min_cos"] == COLD_START_THRESHOLDS["g7d_min_cos"]
    # 显式 yaml 优先于 dict
    y = tmp_path / "th.yaml"
    y.write_text("g7:\n  g7d_min_cos: 0.91\n", encoding="utf-8")
    assert resolve_thresholds({"g7d_min_cos": 0.5}, str(y))["g7d_min_cos"] == 0.91
    # 缺省 → config/thresholds_v2.yaml(M2 校准后 g7a_mode=full); 无文件则冷启动
    default = resolve_thresholds()
    assert default["g7a_mode"] in ("bbox", "full")
