#!/usr/bin/env python3
"""M5 阶段0.1 校准步骤②: 离线重评 M2 存量 62 候选的 G5 (不重新生成)。

方法: 对每个候选已有的抽帧网格 PNG (*.grid.png) 重跑本地 CLIP 启发式 —
  old = clip_heuristic_review(grid, asset_type="food")   # D-026 行为(美食锚全域), 应逐字节复现 M2 分数
  new = clip_heuristic_review(grid, asset_type=按首帧资产路径推导)  # 分锚后
验证: ① 美食卡(new=food)分数与 M2 DB 中 G5 分数零回退(应完全一致);
      ② 场景卡(new=scene)分数落到与目检结论相符的区间(目检=画质良好, 应 ≥0.70 进入 pass 带)。
只读 M2 DB, 不写库、不生成任何视频。结果写 workdir/logs/m5_reeval_g5.json。

用法: ~/cradle/.venv/bin/python tools/m5_reeval_g5.py [--db workdir/cradle.sqlite3]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

OUT = REPO / "workdir" / "logs" / "m5_reeval_g5.json"


def asset_type_of(card: dict) -> str:
    asset = str(card.get("first_frame_asset") or "").replace("\\", "/").lower()
    return "scene" if "/scenes/" in f"/{asset}" else "food"


def main() -> int:
    from src.api.vlm import clip_heuristic_review
    from src.db import DB
    from src.gates.g2g5_vlm import load_vlm_prompt
    from src.orchestrator import asset_type_of as orch_asset_type

    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(REPO / "workdir" / "cradle.sqlite3"))
    args = ap.parse_args()

    prompt_text = load_vlm_prompt()
    db = DB(args.db)
    rows = db._query("SELECT shot_id, card_json FROM tasks ORDER BY shot_id")
    cards = {r["shot_id"]: json.loads(r["card_json"]) for r in rows}

    out_rows = []
    n_missing = 0
    for shot_id in sorted(cards):
        card = cards[shot_id]
        atype_rule = orch_asset_type(card)  # 与生产 gater 同一推导函数(仅作标签记录)
        for cand in db.get_candidates(shot_id):
            grid = f"{cand['path']}.grid.png"
            if cand["verdict"] == "fallback" or not Path(grid).exists():
                n_missing += 1
                continue
            # M5 最终校准(双锚取最优)即生产缺省行为; M2 旧分取自 DB(单 food 锚, D-026)
            new = clip_heuristic_review(grid, prompt_text, asset_type=atype_rule)
            m2_g5 = (cand["gate_json"] or {}).get("G5", {}).get("score")
            out_rows.append({
                "shot_id": shot_id, "candidate_id": cand["id"], "path": cand["path"],
                "m2_verdict": cand["verdict"], "m2_g5_score": m2_g5,
                "new_g5": new["overall_score"],
                "aesthetic": new["aesthetic"],
                "appeal_basis": new.get("appeal_basis"),
                "appeal01_food": new.get("appeal01_food"),
                "appeal01_scene": new.get("appeal01_scene"),
                "asset_type": atype_rule,
                "new_verdict": new["verdict"],
                "food_no_regression": (atype_rule != "food"
                                       or abs(new["overall_score"] - float(m2_g5 or -1)) < 1e-6),
            })

    db.close()
    OUT.write_text(json.dumps({"n": len(out_rows), "rows": out_rows}, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    # 摘要
    by_shot: dict[str, list[dict]] = {}
    for r in out_rows:
        by_shot.setdefault(r["shot_id"], []).append(r)
    print(f"{'shot':5s} {'type':6s} {'n':>3s} {'m2_g5(p50)':>10s} {'new(p50)':>9s} "
          f"{'new_min':>8s} {'new_max':>8s} {'new_pass':>8s} basis food_no_regress")
    for shot_id in sorted(by_shot):
        rs = by_shot[shot_id]
        noreg = all(r["food_no_regression"] for r in rs if r["asset_type"] == "food")
        new_scores = [r["new_g5"] for r in rs]
        m2_scores = [float(r["m2_g5_score"]) for r in rs if r["m2_g5_score"] is not None]
        bases = {r.get("appeal_basis") for r in rs}
        print(f"{shot_id:5s} {rs[0]['asset_type']:6s} {len(rs):3d} "
              f"{statistics.median(m2_scores):10.4f} {statistics.median(new_scores):9.4f} "
              f"{min(new_scores):8.4f} {max(new_scores):8.4f} "
              f"{sum(1 for s in new_scores if s >= 0.70)}/{len(new_scores):<7d} "
              f"{','.join(sorted(bases))} {'OK' if noreg else 'REGRESS'}")
    regress = [r for r in out_rows if not r["food_no_regression"]]
    print(f"\n总数 {len(out_rows)} (无网格/降级跳过 {n_missing}); 美食类回退违例: {len(regress)}")
    print(f"明细 → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
