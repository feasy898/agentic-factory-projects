#!/usr/bin/env python3
"""M2-EXEC patch 3: CLIP 启发式重校准 (D-026, 依据 workdir/logs/m2_clip_anchor_probe.json 实测)。"""
from pathlib import Path

REPO = Path("~/cradle").expanduser()


def patch(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    n = text.count(old)
    assert n == 1, f"[{label}] 期望命中 1 次, 实际 {n} 次: {path}"
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"patched {label}")


P = REPO / "src/api/vlm.py"

patch(
    P,
    '''    # 缺陷分: 负锚相似度越高缺陷越高; 主体缺失用正锚相似度取反
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
    )''',
    '''    # 缺陷分 (D-026 实测重校准: 11 张资产 + LTX 真实帧 + 合成坏帧, 见 workdir/logs/m2_clip_anchor_*.json):
    # - pos 锚对平坦垃圾帧反向(黑/灰 pos 0.175-0.198 > 美食帧 0.154-0.163), 不可用作 subject 信号;
    # - garbled 锚可分(正样本 0.042-0.115 vs 文字/噪声 0.183-0.197) → 域收紧 (0.12, 0.30);
    # - subject_missing 无可靠 CLIP 文本锚, 退化为"内容丧失"复合信号(garbled/dark/bright),
    #   语义局限(真实主体缺席不触发)如实写入报告;
    # - appeal 锚是内容/食欲 present 的有效信号(正 0.145-0.232 vs 坏帧 ≤0.156) → 美学域 (0.145, 0.28);
    #   夜景/背影类资产 appeal 偏低(0.145-0.159), G5 对夜景偏严是已知局限, 校准建议入报告。
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

    appeal01 = _map01(agg("appeal", how="mean"), lo=0.145, hi=0.28)
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
        camera_basis = "neutral_qc_prompt"''',
    "vlm-heuristic-recalibration",
)

patch(
    P,
    '''        "model": "clip_heuristic",
        "unreviewed_by_vlm": True,
    }''',
    '''        "model": "clip_heuristic",
        "unreviewed_by_vlm": True,
        "camera_match_basis": camera_basis,
        "calibration": "D-026",
    }''',
    "vlm-heuristic-meta",
)

print("ALL PATCHES OK")
