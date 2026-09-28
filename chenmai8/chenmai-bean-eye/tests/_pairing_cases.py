"""M6 配对 fixture 构造器：合成上下框对三类用例（确定性，无随机）。

三类用例（任务 W6 spec）：
- ``pairable``             可配对：同一粒豆的上下观测，门限内；
- ``occlusion_single_side`` 遮挡单面：豆只在一面被观测到（盘中部）；
- ``edge_miss``            边缘漏检：豆位于盘边缘，另一面检测器漏检。

用法（仓库根）::

    python -c "import sys; sys.path[:0]=['.','tests']; import _pairing_cases as pc; pc.write_json('tests/fixtures/pairing/cases_v1.json')"

生成 ``tests/fixtures/pairing/cases_v1.json``；test_pairing.py 会校验
JSON 与本构造器同步（沿袭 tests/_fixture_builders.py 的做法）。

几何约定：每粒豆 = 半径 3.0mm 正六边形轮廓（面积 pi*r^2，等效直径 6mm），
severity_rank 取自 configs/taxonomy.yaml 默认序，expect 块为逐用例期望。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from beaneye.taxonomy import load_taxonomy

SCAN_ID = "scan_synth_0001"
HEX_R_MM = 3.0
TRAY_MM = 300.0
EDGE_BAND_MM = 8.0  # 距边 ≤8mm 视为边缘豆
MID_MIN_MM = 50.0  # 距每条边 ≥50mm 视为盘中部


def _obs_dict(obs_id: str, side: str, cx: float, cy: float, *, defect: str, conf: float) -> dict[str, Any]:
    tax = load_taxonomy()
    polygon = [
        [round(cx + HEX_R_MM * math.cos(math.radians(60 * k)), 3),
         round(cy + HEX_R_MM * math.sin(math.radians(60 * k)), 3)]
        for k in range(6)
    ]
    return {
        "obs_id": obs_id,
        "side": side,
        "defect": defect,
        "defect_conf": conf,
        "severity_rank": tax.severity_rank(defect),
        "crop_path": f"out/crops/{SCAN_ID}/{obs_id}.png",
        "mask": {
            "mask_id": obs_id,
            "side": side,
            "polygon": polygon,
            "bbox_mm": [round(cx - HEX_R_MM, 3), round(cy - HEX_R_MM, 3),
                        round(cx + HEX_R_MM, 3), round(cy + HEX_R_MM, 3)],
            "area_mm2": round(math.pi * HEX_R_MM**2, 3),
            "centroid_mm": [round(cx, 3), round(cy, 3)],
            "source": "oracle",
            "conf": 1.0,
        },
        "color_lab": [52.0, -10.0, 20.0],
        "eq_diameter_mm": 2.0 * HEX_R_MM,
    }


def build_cases() -> dict[str, Any]:
    """六用例：可配对×2 / 遮挡单面×2 / 边缘漏检×2。确定性输出。"""
    cases: list[dict[str, Any]] = [
        {
            "case_id": "pairable_mid_tray",
            "kind": "pairable",
            "top": _obs_dict("top_001", "top", 100.0, 100.0, defect="black", conf=0.92),
            "bottom": _obs_dict("bottom_001", "bottom", 100.6, 100.8, defect="normal", conf=0.99),
            "expect": {"paired": True, "worst_side": "top", "final_defect": "black"},
        },
        {
            "case_id": "pairable_near_gate",
            "kind": "pairable",
            "top": _obs_dict("top_002", "top", 40.0, 200.0, defect="broken", conf=0.70),
            "bottom": _obs_dict("bottom_002", "bottom", 40.0, 188.5, defect="broken", conf=0.90),
            "expect": {"paired": True, "worst_side": "both", "final_defect": "broken"},
        },
        {
            "case_id": "occlusion_top_only_mid",
            "kind": "occlusion_single_side",
            "top": _obs_dict("top_003", "top", 150.0, 100.0, defect="mold", conf=0.85),
            "bottom": None,
            "expect": {"paired": False, "kept_side": "top", "worst_side": "top", "final_defect": "mold"},
        },
        {
            "case_id": "occlusion_bottom_only_mid",
            "kind": "occlusion_single_side",
            "top": None,
            "bottom": _obs_dict("bottom_004", "bottom", 150.0, 200.0, defect="insect", conf=0.88),
            "expect": {"paired": False, "kept_side": "bottom", "worst_side": "bottom", "final_defect": "insect"},
        },
        {
            "case_id": "edge_miss_top_only_right",
            "kind": "edge_miss",
            "top": _obs_dict("top_005", "top", 296.0, 150.0, defect="sour", conf=0.81),
            "bottom": None,
            "expect": {"paired": False, "kept_side": "top", "worst_side": "top", "final_defect": "sour"},
        },
        {
            "case_id": "edge_miss_bottom_only_left",
            "kind": "edge_miss",
            "top": None,
            "bottom": _obs_dict("bottom_006", "bottom", 4.0, 250.0, defect="dried", conf=0.86),
            "expect": {"paired": False, "kept_side": "bottom", "worst_side": "bottom", "final_defect": "dried"},
        },
    ]
    return {
        "_comment": (
            "M6 配对合成上下框对 fixture（确定性生成，见 tests/_pairing_cases.py）；"
            "pairable=门限内可配对, occlusion_single_side=遮挡单面, edge_miss=边缘漏检。"
        ),
        "scan_id": SCAN_ID,
        "gate_mm": 12.0,
        "tray_mm": TRAY_MM,
        "edge_band_mm": EDGE_BAND_MM,
        "mid_min_mm": MID_MIN_MM,
        "cases": cases,
    }


def write_json(path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(build_cases(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


if __name__ == "__main__":  # pragma: no cover
    print(f"wrote {write_json('tests/fixtures/pairing/cases_v1.json')}")
