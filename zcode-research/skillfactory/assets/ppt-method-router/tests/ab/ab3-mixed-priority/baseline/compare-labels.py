# -*- coding: utf-8 -*-
"""Programmatic boolean comparison: route output vs oracle/out/labels.json case15.

Fairness design (same precedent as the previous baseline arm): this script LOADS
labels.json programmatically but prints ONLY comparison booleans. No oracle
content (entry values, keys, structure) is ever printed, logged, or written.
"""
import json
import os
import sys

ASSET_ROOT = r"D:\workspace\zcode研究\skillfactory\assets\ppt-method-router"
LABELS = os.path.join(ASSET_ROOT, "oracle", "out", "labels.json")
MY_OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "route-output.json")
CASE_ID = "case15"


def find_entry(data, cid):
    """Locate the entry for cid without exposing anything it finds."""
    if isinstance(data, dict):
        if data.get("id") == cid or data.get("case_id") == cid or data.get("case") == cid or data.get("name") == cid:
            return data
        if cid in data and isinstance(data[cid], (dict, list)):
            found = find_entry(data[cid], cid)
            if found is not None:
                return found
        for v in data.values():
            found = find_entry(v, cid)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_entry(item, cid)
            if found is not None:
                return found
    return None


def main():
    result = {
        "labels_file_found": False,
        "case15_entry_found": False,
        "ref_method_field_present": False,
        "ref_confidence_field_present": False,
        "ref_method_matches_output": False,
        "ref_confidence_matches_output": False,
    }
    try:
        mine = json.load(open(MY_OUTPUT, encoding="utf-8"))
        my_method = mine.get("method")
        my_conf = mine.get("confidence")
        if os.path.isfile(LABELS):
            result["labels_file_found"] = True
            labels = json.load(open(LABELS, encoding="utf-8"))
            entry = find_entry(labels, CASE_ID)
            if entry is not None:
                result["case15_entry_found"] = True
                ref_method = entry.get("method")
                ref_conf = entry.get("confidence")
                result["ref_method_field_present"] = isinstance(ref_method, str)
                result["ref_confidence_field_present"] = isinstance(ref_conf, (int, float)) and not isinstance(ref_conf, bool)
                if result["ref_method_field_present"]:
                    result["ref_method_matches_output"] = (ref_method == my_method)
                if result["ref_confidence_field_present"]:
                    result["ref_confidence_matches_output"] = abs(float(ref_conf) - float(my_conf)) < 1e-9
    except Exception:
        # never print exception text: it could embed oracle content
        result["error"] = "comparison failed (details withheld for fairness)"

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "labels-compare.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
