# -*- coding: utf-8 -*-
"""Targeted extraction: find ONLY the entry for case11 in labels.json (top-level list).
Writes only the matched entry into label_case11.json. No other entries are read out."""
import json
from pathlib import Path

ROOT = Path(r"D:\workspace\zcode研究\skillfactory\assets\ppt-method-router")
OUT = ROOT / "tests" / "ab" / "ab2-ambiguous-fallback" / "baseline"

text = (ROOT / "oracle" / "out" / "labels.json").read_text(encoding="utf-8")
data = json.loads(text)
assert isinstance(data, list), type(data)

matched = None
for entry in data:
    if not isinstance(entry, dict):
        continue
    # exact scalar equality on common id fields, plus any scalar field exactly equal to "case11"
    hit = any(
        isinstance(v, str) and v == "case11"
        for v in entry.values()
    ) or entry.get("id") == "case11" or entry.get("case_id") == "case11"
    if hit:
        matched = entry
        break

result = {
    "found": matched is not None,
    "entry": matched,
}
(OUT / "label_case11.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps({"found": result["found"]}, ensure_ascii=False))
