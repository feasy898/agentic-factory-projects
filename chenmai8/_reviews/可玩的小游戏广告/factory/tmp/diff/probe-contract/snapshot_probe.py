# -*- coding: utf-8 -*-
"""PROBE_JS 契约锚点工具（只读 oracle；写仅限 factory/tmp/diff/probe-contract/）。

用法：
  python snapshot_probe.py before   # 快照当前 factory PROBE_JS 为 probe-js-before.ts.txt
  python snapshot_probe.py after    # 快照改后 factory PROBE_JS 为 probe-js-after.ts.txt
  python snapshot_probe.py diff     # 与 oracle 逐字节比对并输出长度
"""
import io, os, re, sys

WS = r"D:/workspace/澄迈8项目/可玩的小游戏广告"
ORACLE_AUTOPLAY = os.path.join(WS, "repo", "python", "qacore", "autoplay.py")
FACTORY_PROBE = os.path.join(WS, "factory", "qacore", "src", "probe.ts")
OUT_DIR = os.path.join(WS, "factory", "tmp", "diff", "probe-contract")


def oracle_body():
    o = io.open(ORACLE_AUTOPLAY, encoding="utf-8", newline="").read()
    m = re.search(r'PROBE_JS = """\\\r?\n(.*?)"""', o, re.S)
    assert m, "oracle PROBE_JS 未找到"
    return m.group(1)


def factory_body():
    f = io.open(FACTORY_PROBE, encoding="utf-8", newline="").read()
    m = re.search(r"PROBE_JS = String\.raw`(.*?)`;\s*$", f, re.S | re.M)
    assert m, "factory PROBE_JS 未找到"
    return m.group(1)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "diff"
    os.makedirs(OUT_DIR, exist_ok=True)
    if cmd in ("before", "after"):
        body = factory_body()
        p = os.path.join(OUT_DIR, "probe-js-%s.ts.txt" % cmd)
        io.open(p, "w", encoding="utf-8", newline="").write(body)
        print("written:", p, "chars:", len(body))
        return
    ob, fb = oracle_body(), factory_body()
    print("oracle PROBE_JS chars:", len(ob))
    print("factory PROBE_JS chars:", len(fb))
    print("byte-identical:", ob == fb)


if __name__ == "__main__":
    main()
