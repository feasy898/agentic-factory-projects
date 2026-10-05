# -*- coding: utf-8 -*-
# PKG-02 清零核验 + 差异集合对比 + 大小差 max（本 ask 专用一次性核验脚本）
import json, glob, re, os

F = "D:/workspace/澄迈8项目/可玩的小游戏广告/factory"
new = json.load(open(F + "/tmp/diff/d1-packages-evidence.json", encoding="utf-8"))
old = json.load(open(F + "/tmp/diff/pkg02-rebuild/d1-packages-evidence.pre-pkg02fix.json", encoding="utf-8"))
print("verdict:", new["verdict"], "| capturedAt:", new["capturedAt"])
print("inputs:", new["inputs"])

# ---- PKG-02: mintegral 8 格 warnings 逐字核验（直接读两侧 manifest，独立于 d1 判定）
n_ok = 0
cells = sorted(glob.glob(F + "/tmp/diff/oracle-matrix/golden-*/mintegral/*/pack-manifest.json"))
for p in cells:
    rel = os.path.relpath(p, F + "/tmp/diff/oracle-matrix").replace("\\", "/")  # <proj>/mintegral/<loc>/pack-manifest.json
    np_ = os.path.join(F, "artifacts", "matrix", rel)
    ow = json.load(open(p, encoding="utf-8")).get("warnings")
    nw = json.load(open(np_, encoding="utf-8")).get("warnings")
    eq = ow == nw
    n_ok += eq
    print(("OK " if eq else "MISMATCH ") + rel.split("/pack-manifest")[0] + " warnings=" + json.dumps(nw, ensure_ascii=False))
print("PKG-02 warnings 相等的 mintegral 格: %d / 8" % n_ok)

# ---- 差异集合对比（无新增维度差异）
def keyset(e, sev):
    return set((f["cell"], f["item"]) for f in e[sev])

print("regressions: old %d -> new %d" % (len(old["regressions"]), len(new["regressions"])))
print("diffs: old %d -> new %d | 集合相同: %s" % (len(old["diffs"]), len(new["diffs"]), keyset(old, "diffs") == keyset(new, "diffs")))
print("新增(new-only):", keyset(new, "diffs") - keyset(old, "diffs"), "| 消失(old-only):", keyset(old, "diffs") - keyset(new, "diffs"))
print("repro 实现内两建字节一致:", [(r["impl"], r["ok"]) for r in new["repro"]])

# ---- 大小差 max
mx = -1; mxcell = ""; mxd = -1
for c in new["perCell"]:
    for it in c["items"]:
        if it["item"] == "artifact-bytes±5%":
            d = re.search(r"oracle=(\d+) factory=(\d+)", it["detail"])
            if d:
                delta = abs(int(d.group(1)) - int(d.group(2)))
                if delta > mx: mx, mxcell = delta, c["cell"]
        elif "usize±5%" in it["item"]:
            d = re.search(r"oracle=(\d+) factory=(\d+)", it["detail"])
            if d:
                delta = abs(int(d.group(1)) - int(d.group(2)))
                if delta > mxd: mxd = delta
print("artifact 大小差 max: %d B @ %s | zip 条目 usize 差 max: %d B" % (mx, mxcell, mxd))
bad = [it["detail"] for c in new["perCell"] for it in c["items"] if it["item"] == "artifact-bytes±5%" and it["severity"] != "equal"]
print("artifact±5% 超限格数:", len(bad))
