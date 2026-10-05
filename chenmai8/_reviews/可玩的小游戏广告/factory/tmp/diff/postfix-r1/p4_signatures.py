# -*- coding: utf-8 -*-
"""P4 签名复验（第 1 轮改后）：报告 JSON 字段签名零增删 → 每同模式组 distinct=1。

签名 = 报告顶层键集 + facts 顶层键集 + facts.muteLoadTime 键集 +
facts.viewport_shots.{portrait,landscape} 键集 + checks 逐项键集（含 id 序列）。
对照组：改前 factory 报告（tmp/diff/e3a-n-solo.json、e10b-n-traced.json）与
oracle 报告（tmp/diff/e3b-o-solo.json）——改后键集必须与改前同模式全等。
输出：tmp/diff/postfix-r1/p4-signatures.json
"""
import io, json, os

FACTORY = r"D:/workspace/澄迈8项目/可玩的小游戏广告/factory"


def sig_of(path):
    d = json.load(io.open(path, encoding="utf-8"))
    facts = d.get("facts", {})
    shots = facts.get("viewport_shots", {})
    def keys(x):
        return sorted(x.keys()) if isinstance(x, dict) else None
    return {
        "top": keys(d),
        "facts": keys(facts),
        "muteLoadTime": keys(facts.get("muteLoadTime")),
        "vsp": keys(shots.get("portrait")),
        "vsl": keys(shots.get("landscape")),
        "checks": [sorted(c.keys()) for c in d.get("checks", [])],
        "checkIds": [c.get("id") for c in d.get("checks", [])],
        "reportFactsMuteLoadTimeAbsentAutoplay": "autoplay" not in facts,
    }


def cluster(name, paths, out):
    sigs = {}
    for p in paths:
        s = json.dumps(sig_of(p), ensure_ascii=False, sort_keys=True)
        sigs.setdefault(s, []).append(os.path.relpath(p, FACTORY))
    out[name] = {"n": len(paths), "distinct": len(sigs),
                 "members": [v for v in sigs.values()]}
    return sigs


def main():
    out = {}
    qacore_eval = os.path.join(FACTORY, "tmp", "qacore-eval")
    flag_dir = os.path.join(qacore_eval, "autoplay-flag")
    mut_dir = os.path.join(qacore_eval, "mutations")
    diff_dir = os.path.join(FACTORY, "tmp", "diff")

    autoplay_new = [os.path.join(qacore_eval, "qacore-report.json"),
                    os.path.join(qacore_eval, "negative-sprite.json"),
                    os.path.join(qacore_eval, "negative-text.json")]
    autoplay_new += [os.path.join(mut_dir, f) for f in sorted(os.listdir(mut_dir))
                     if f.endswith(".report.json")]
    autoplay_new = [p for p in autoplay_new if os.path.exists(p)]

    quick_new = []
    for i in range(1, 6):
        p = os.path.join(flag_dir, "b-like-run%d.report.json" % i)
        if os.path.exists(p):
            quick_new.append(p)
    for i in range(1, 4):
        p = os.path.join(flag_dir, "slow-bridge-run%d.report.json" % i)
        if os.path.exists(p):
            quick_new.append(p)

    cluster("autoplay_new", autoplay_new, out)
    cluster("quick_new", quick_new, out)

    # 对照：改前 factory 与 oracle（键集逐一对照，不进聚类）
    ref = {}
    for label, p in [
        ("factory_before_autoplay", os.path.join(diff_dir, "e3a-n-solo.json")),
        ("factory_before_quick", os.path.join(diff_dir, "e10b-n-traced.json")),
        ("oracle_autoplay", os.path.join(diff_dir, "e3b-o-solo.json")),
    ]:
        if os.path.exists(p):
            ref[label] = sig_of(p)
    new_auto_sig = sig_of(autoplay_new[0])
    new_quick_sig = sig_of(quick_new[0])
    cmp = {}
    if "factory_before_autoplay" in ref:
        cmp["new_autoplay_vs_factory_before"] = {
            k: (new_auto_sig[k] == ref["factory_before_autoplay"][k])
            for k in ("top", "facts", "muteLoadTime", "vsp", "vsl", "checks", "checkIds")}
    if "oracle_autoplay" in ref:
        cmp["new_autoplay_vs_oracle"] = {
            k: (new_auto_sig[k] == ref["oracle_autoplay"][k])
            for k in ("top", "facts", "muteLoadTime", "vsp", "vsl", "checks", "checkIds")}
    if "factory_before_quick" in ref:
        cmp["new_quick_vs_factory_before"] = {
            k: (new_quick_sig[k] == ref["factory_before_quick"][k])
            for k in ("top", "facts", "muteLoadTime", "vsp", "vsl", "checks", "checkIds")}
    out["reference_compare"] = cmp

    dst = os.path.join(FACTORY, "tmp", "diff", "postfix-r1", "p4-signatures.json")
    io.open(dst, "w", encoding="utf-8", newline="\n").write(
        json.dumps(out, ensure_ascii=False, indent=2))
    print("written:", dst)
    for g in ("autoplay_new", "quick_new"):
        print(g, "n=%d distinct=%d" % (out[g]["n"], out[g]["distinct"]))
    for k, v in cmp.items():
        print(k, json.dumps(v))


if __name__ == "__main__":
    main()
