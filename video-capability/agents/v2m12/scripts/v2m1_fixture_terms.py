#!/usr/bin/env python
"""V2-M1: 夹具 → 源镜头卡 → G7b 检测词表 映射构建 (SPECS_V2 §3-G7b)。

manifest 的 key 形如 SB_S17_60 / SB_ABS03P_4 / MAIN_S10_30:
  前缀定库(SB=沙箱 /root/cradle_m5, MAIN=主仓), 中段为 shot_id;
  由对应库 tasks.card_json.prompt_en 经 derive_detect_terms 派生词表。
key=None(pass_structural 确定性再生成) → terms=[](ken_burns 程序产物无生成主体)。
输出: workdir/fixtures/g7_terms.json
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gates.g7_object_persistence import derive_detect_terms  # noqa: E402

MANIFEST = ROOT / "workdir" / "fixtures" / "fixtures_manifest.json"
OUT = ROOT / "workdir" / "fixtures" / "g7_terms.json"
DBS = {
    "SB": "/root/cradle_m5/workdir/cradle.sqlite3",
    "MAIN": str(ROOT / "workdir" / "cradle.sqlite3"),
}

KEY_RE = re.compile(r"^(SB|MAIN)_(S\d+|ABS\d+[LP])_\d+$")


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cards: dict[tuple[str, str], dict] = {}
    out = {}
    for it in manifest["fixtures"]:
        fid, key = it["fixture_id"], it.get("key")
        # pass_structural = KenBurns/程序运镜产物(构造上不可能形变, D-052), 无生成主体
        # → G7b/c 按无主体跳过(与生产口径一致: ken_burns 车道不派生检测词表)
        if it.get("label") == "pass_structural":
            out[fid] = {"key": key, "shot": None, "prompt_en": None, "terms": [],
                        "note": "pass_structural 程序产物, 无生成主体 → G7b/c 跳过"}
            continue
        m = KEY_RE.match(key or "")
        if not m:
            out[fid] = {"key": key, "shot": None, "prompt_en": None, "terms": [],
                        "note": "无源卡(程序产物/无生成主体) → G7b/c 按无主体跳过"}
            continue
        lib, shot = m.group(1), m.group(2)
        if (lib, shot) not in cards:
            db = sqlite3.connect(DBS[lib])
            row = db.execute("SELECT card_json FROM tasks WHERE shot_id=?", (shot,)).fetchone()
            db.close()
            cards[(lib, shot)] = json.loads(row[0]) if row else {}
        card = cards[(lib, shot)]
        terms = derive_detect_terms(card)
        out[fid] = {"key": key, "shot": shot, "lib": lib,
                    "prompt_en": (card.get("prompt_en") or "")[:200],
                    "terms": terms,
                    "note": "" if terms else "词表派生为空 → G7b/c 跳过"}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n_terms = sum(1 for v in out.values() if v["terms"])
    print(f"OK {OUT} fixtures={len(out)} with_terms={n_terms}")
    for fid, v in out.items():
        print(f"  {fid} {v.get('shot') or '-'}: {v['terms']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
