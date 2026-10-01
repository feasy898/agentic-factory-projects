# -*- coding: utf-8 -*-
"""step3: 补充核验 — ORC fresh vs 快照 fields.json 差异定位（是否仅 $.outputs.* 路径）。"""
import json, os

ROOT = r"D:\workspace\zcode研究\skillfactory\v3\assets\office-templates"
WORK = os.path.join(ROOT, r"tests\ab\ab2-boundary-missing-required\arm-b\rep2\_work")

def load(p):
    with open(p, "rb") as f:
        return json.loads(f.read().decode("utf-8"))

for tpl in ["请示函", "会议通知"]:
    a = load(os.path.join(ROOT, "oracle", "out", tpl, "case2", "fields.json"))
    b = load(os.path.join(WORK, "backup", "oracle_out", f"{tpl}_case2", "fields.json"))
    print(f"=== ORC {tpl}: fresh vs 快照")
    for k in sorted(set(a) | set(b)):
        if k == "outputs":
            for k2 in sorted(set(a[k]) | set(b[k])):
                same = a[k].get(k2) == b[k].get(k2)
                print(f"  $.outputs.{k2}: same={same}  fresh={a[k].get(k2)!r} snapshot={b[k].get(k2)!r}")
        else:
            print(f"  ${k}: same={a.get(k)==b.get(k)}")
