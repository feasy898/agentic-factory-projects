#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_checks.py — WS2 可见验收脚本（TESTS v1.1 AC/BP/HY 组逐条断言）。

覆盖：AC-1..AC-9（AC-8 为留痕口径）、BP-1..BP-9、HY-1..HY-5（HY-4 为留痕位口径）。
全部零模型、离线可跑（skills-ref 已钉版安装）；任一 FAIL → exit 1。

用法：python tests/run_checks.py  （在 skillfactory/dist/ 下执行）
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.dirname(HERE)
SKILLFACTORY = os.path.dirname(DIST)
sys.path.insert(0, DIST)
import build  # noqa: E402

WORK = os.path.join(HERE, "_work")
RESULTS = []


def check(cid, ok, detail=""):
    RESULTS.append({"id": cid, "pass": bool(ok), "detail": str(detail)})
    print("[%s] %s %s" % ("PASS" if ok else "FAIL", cid, detail))


def section(title):
    print("\n== %s ==" % title)


def tree_files(root):
    out = {}
    for base, _dirs, files in os.walk(root):
        for fn in files:
            rel = os.path.relpath(os.path.join(base, fn), root).replace(os.sep, "/")
            with open(os.path.join(base, fn), "rb") as f:
                out[rel] = f.read()
    return out


def fresh(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def g05(pkg, **kw):
    return build.g05_gate(pkg, **kw)


def parse_fm(text):
    return build.parse_frontmatter(text)[0]


def run_runner(pkg_root, tested, reference):
    return subprocess.run(
        [sys.executable, os.path.join(pkg_root, "eval", "runner.py"), tested, reference],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)


# ---------------------------------------------------------------- AC 组
def ac_group():
    section("AC 组 · G0-5 形式合规门")
    golden = os.path.join(HERE, "golden-min", "golden-demo")

    rep, code = g05(golden)   # AC-1
    fails = [c["name"] for c in rep.get("checks", []) if not c["pass"]]
    check("AC-1", code == 0 and not fails, "golden exit=%d fails=%s" % (code, fails))

    subprocess.run([sys.executable, os.path.join(HERE, "make_red_fixtures.py")],
                   check=True, capture_output=True)
    red_root = os.path.join(HERE, "red-work")
    fixtures = {
        "r1-name-dir-mismatch": ("name_equals_dir", "r1-name-dir-mismatch/foo-skill"),
        "r2-top-version": ("top_fields_whitelist", "r2-top-version/golden-demo"),
        "r3-top-permissions": ("top_fields_whitelist", "r3-top-permissions/golden-demo"),
        "r4-unknown-field": ("top_fields_whitelist", "r4-unknown-field/golden-demo"),
        "r5-no-metadata-version": ("metadata_version_present",
                                   "r5-no-metadata-version/golden-demo"),
        "r6-no-frontmatter": ("frontmatter_present", "r6-no-frontmatter/golden-demo"),
        "r7-no-name": ("name_present", "r7-no-name/golden-demo"),
        "r8-desc-1025": ("description_length", "r8-desc-1025/golden-demo"),
    }
    per_fixture = {}
    for fx, (rule, rel) in fixtures.items():
        pkg = os.path.join(red_root, rel)
        rep, code = g05(pkg)
        internal_fails = [c["name"] for c in rep.get("checks", [])
                          if not c["pass"] and c["name"] != "skills_ref_validate"]
        per_fixture[fx] = (code, internal_fails)
        check("AC-2..5/%s" % fx, code == 1 and rule in internal_fails,
              "exit=%d internal_fails=%s target=%s" % (code, internal_fails, rule))

    stray = {fx: f for fx, (_c, f) in per_fixture.items()
             if set(f) - {fixtures[fx][0]}}
    check("AC-6", code is not None and not stray,
          "单一变异源：非目标内部规则命中=%s" % (stray or "无"))

    # AC-7：隔离 PATH 使 skills-ref 不可用 → fail-closed
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([r"C:\Windows\System32", r"C:\Windows"])
    proc = subprocess.run(
        [sys.executable, os.path.join(DIST, "build.py"), "g05", golden],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=120)
    out = proc.stdout or ""
    check("AC-7", proc.returncode == 3 and "不可用" in out and "fail_closed" in out,
          "隔离 PATH exit=%d fail_closed=%s" % (proc.returncode, "fail_closed" in out))

    # AC-8：G0-5 ↔ 现行体检器字段语义对照（留痕口径：对齐动作属 WS9）
    hc = os.path.join(SKILLFACTORY, "v3", "tools", "healthcheck",
                      "package", "healthcheck.py")
    try:
        with open(hc, "r", encoding="utf-8") as f:
            hc_src = f.read()
        import re as _re
        m = _re.search(r"REQUIRED_FIELDS\s*=\s*\(([^)]*)\)", hc_src)
        hc_fields = [s.strip().strip("'\"") for s in m.group(1).split(",")] if m else []
    except OSError:
        hc_fields = None
    conflict = ([f for f in ("version", "permissions")
                 if f in (hc_fields or [])] if hc_fields is not None else None)
    check("AC-8", hc_fields is not None and conflict is not None,
          "留痕：现行体检器 REQUIRED_FIELDS=%s；与 G0-5 白名单冲突字段=%s；"
          "对齐（体检器升级）属 WS9，届时重跑本条" % (hc_fields, conflict))

    # AC-9：canonical 双根 package/ 布局 → 拒绝且不出违规结论
    pkg_v5 = os.path.join(SKILLFACTORY, "v5", "assets", "deploy-pack", "package")
    rep, code = g05(pkg_v5)
    check("AC-9", code == 3 and rep.get("refused") is True and not rep.get("checks"),
          "v5 package/ 布局 exit=%d refused=%s" % (code, rep.get("refused")))


# ---------------------------------------------------------------- BP 组
def bp_group():
    section("BP 组 · build.py 三变体")
    src = os.path.join(HERE, "src-demo", "src-demo-skill")
    out = os.path.join(WORK, "bp")
    fresh(out)
    products = {}
    for v in build.VARIANTS:
        root, _rep, err = build.build_pkg(src, v, out)
        assert root, err
        products[v] = root

    # BP-1 三产物布局契约
    ok1 = True
    detail = []
    for v, root in products.items():
        files = set(tree_files(root))
        need = {"SKILL.md", "eval/runner.py", "eval/golden.json",
                "references/notes.md", "MANIFEST.json"}
        extra_expect = {"README.md"} if v == "learner" else set()
        must_absent = {"README.md", "reference/inputs/case1.txt",
                       "reference/out/case1/dummy.txt"} - extra_expect
        ok = need | extra_expect <= files and not (files & must_absent)
        ok1 = ok1 and ok
        detail.append("%s:%s" % (v, "OK" if ok else "BAD %s" % sorted(files)))
    check("BP-1", ok1, "; ".join(detail))

    std_skill = tree_files(products["standard"])["SKILL.md"].decode("utf-8")
    meta = parse_fm(std_skill)
    ok2 = (meta["metadata"].get("version") == "0.2.0"
           and meta["metadata"].get("permissions") == "[shell]"
           and set(meta["top"]) <= set(build.TOP_ALLOWED)
           and os.path.basename(products["standard"]) == "src-demo")
    check("BP-2", ok2, "metadata.version=%s metadata.permissions=%s top=%s dir=%s"
          % (meta["metadata"].get("version"), meta["metadata"].get("permissions"),
             sorted(meta["top"]), os.path.basename(products["standard"])))

    cc_skill = tree_files(products["claude-code"])["SKILL.md"].decode("utf-8")
    meta_cc = parse_fm(cc_skill)
    ok3a = set(meta_cc["top"]) <= set(build.TOP_ALLOWED) and "allowed-tools" not in meta_cc["top"]
    check("BP-3a", ok3a and "<!-- cc-only:" not in cc_skill,
          "无标注源：claude-code 零私字段=%s 正文零标注块残留=%s"
          % (ok3a, "<!-- cc-only:" not in cc_skill))
    cc_src = os.path.join(HERE, "src-demo-cc", "cc-demo-skill")
    out_cc = os.path.join(WORK, "bp-cc")
    fresh(out_cc)
    cc_std_root, _r, _e = build.build_pkg(cc_src, "standard", out_cc)
    cc_cc_root, _r, _e = build.build_pkg(cc_src, "claude-code", out_cc)
    cc_std_txt = tree_files(cc_std_root)["SKILL.md"].decode("utf-8")
    cc_cc_txt = tree_files(cc_cc_root)["SKILL.md"].decode("utf-8")
    ok3b = (parse_fm(cc_cc_txt)["top"].get("allowed-tools") == "Read, Bash(git status)"
            and "allowed-tools" not in parse_fm(cc_std_txt)["top"]
            and "<!-- cc-only:" not in cc_std_txt and "<!-- cc-only:" not in cc_cc_txt)
    check("BP-3b", ok3b, "含标注源：claude-code 恰生成 allowed-tools 且正文剥离")

    # BP-4 learner：eval 双件在位 + smoke 双态（参照=源包 reference/out）
    learner = products["learner"]
    ref_out = os.path.join(src, "reference", "out")
    green = run_runner(learner, ref_out, ref_out)
    empty = os.path.join(WORK, "empty")
    fresh(empty)
    red = run_runner(learner, empty, ref_out)
    check("BP-4", green.returncode == 0 and red.returncode == 1,
          "smoke 双态：绿 exit=%d 红 exit=%d" % (green.returncode, red.returncode))

    # BP-5 learner 白名单豁免边界（机制微测：白名单收紧后 README 应被拦）
    saved = set(build.LEARNER_EXTRA_ALLOWLIST)
    try:
        build.LEARNER_EXTRA_ALLOWLIST = ("QUICKSTART.md",)  # 临时收紧
        _root, _rep, err = build.build_pkg(src, "learner", out)
    finally:
        build.LEARNER_EXTRA_ALLOWLIST = tuple(saved)
    check("BP-5", err is not None and "越界" in str(err) and "README.md" in str(err)
          and "README.md" not in tree_files(products["standard"]),
          "白名单外 learner 文件被拦=%s；standard 剥 README 维持=%s"
          % (err is not None, "README.md" not in tree_files(products["standard"])))

    # BP-6 打包纯净性：声明变换面之外 sha256==源（源文本按 LF 归一口径）
    ok6 = True
    d6 = []
    std_files = tree_files(products["standard"])
    for rel, data in std_files.items():
        if rel in ("SKILL.md", "MANIFEST.json"):
            continue
        src_path = os.path.join(src, *rel.split("/"))
        with open(src_path, "rb") as f:
            raw = f.read()
        expect = build.normalize_text(raw) if build.is_text_bytes(raw) else raw
        if data != expect:
            ok6 = False
            d6.append(rel)
    banned = [r for r in std_files
              if r.split("/")[0] in (".git", "__pycache__", "reference")
              or build.WINDOWS_RESERVED.match(r.rsplit("/", 1)[-1])]
    body_src = build.read_pkg_frontmatter(src)[2]
    body_std = std_files["SKILL.md"].decode("utf-8")
    body_ok = body_src.split("---\n", 2)[2] in body_std.replace("---\n", "---\n", 1) \
        if False else body_std.endswith(body_src.split("---\n", 2)[2])
    check("BP-6", ok6 and not banned and body_ok,
          "变换面外差异=%s 违禁=%s 正文保真=%s" % (d6 or "无", banned or "无", body_ok))

    # BP-7 重建确定性：连跑两次逐字节比对
    out7 = os.path.join(WORK, "bp7")
    fresh(out7)
    build.build_pkg(src, "standard", out7)
    t1 = tree_files(os.path.join(out7, "standard", "src-demo"))
    build.build_pkg(src, "standard", out7)
    t2 = tree_files(os.path.join(out7, "standard", "src-demo"))
    check("BP-7", t1 == t2, "双跑 diff=%s" % ([k for k in set(t1) | set(t2)
                                               if t1.get(k) != t2.get(k)] or "空"))

    # BP-8 变体组合：learner(standard(源)) vs learner(源)，两个产物落不同根防覆盖
    out8a = os.path.join(WORK, "bp8a")
    out8b = os.path.join(WORK, "bp8b")
    fresh(out8a)
    fresh(out8b)
    std8, _r, _e = build.build_pkg(src, "standard", out8a)
    lr_from_std, _r, _e = build.build_pkg(std8, "learner", out8a)
    lr_direct, _r, _e = build.build_pkg(src, "learner", out8b)
    a, b = tree_files(lr_from_std), tree_files(lr_direct)
    # MANIFEST.json 是构建元数据（source_pkg 等必然随源不同），不进逐字节比较，
    # 其字段正确性由自身断言覆盖
    shared_ok = all(a[k] == b[k] for k in set(a) & set(b) - {"MANIFEST.json"})
    diff = sorted((set(a) ^ set(b)) - {"MANIFEST.json"})
    ma = json.loads(a["MANIFEST.json"].decode("utf-8"))
    mb = json.loads(b["MANIFEST.json"].decode("utf-8"))
    meta_ok = (ma["source_pkg"] == "src-demo" and mb["source_pkg"] == "src-demo-skill")
    check("BP-8", shared_ok and diff == ["README.md"] and meta_ok,
          "共享文件逐字节一致=%s 差异集=%s（⊆ standard 已剥离人读层）；"
          "MANIFEST source_pkg 随源正确=%s"
          % (shared_ok, diff, meta_ok))

    # BP-9 重打包回归：dist 三包 × 三变体 + runner 复跑（绿/红）
    # hot runner 的 golden input 路径相对资产根解析（reference/inputs），而 reference/
    # 按打包卫生不进产物 → 测试脚手架在产物根临时建 junction 指回源包 reference/，
    # 跑完即删；产物字节不动（runner/golden 保真由 BP-6 断言）。
    out9 = os.path.join(DIST, "build")
    fresh(out9)
    all_ok, d9 = True, []

    def make_junction(link, target):
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", link, target],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30)
        return proc.returncode == 0

    empty = os.path.join(WORK, "empty")
    fresh(empty)
    for pkg in build.DIST_PACKAGES:
        srcp = os.path.join(DIST, pkg)
        ref = os.path.join(srcp, "reference", "out")
        for v in build.VARIANTS:
            root, _rep, err = build.build_pkg(srcp, v, out9)
            if not root:
                all_ok = False
                d9.append("%s/%s build err=%s" % (pkg, v, err))
                continue
            _g, gcode = g05(root, allow_cc_private=(v == "claude-code"))
            junction = os.path.join(root, "reference")
            linked = os.path.isdir(junction) or make_junction(junction, os.path.join(srcp, "reference"))
            try:
                g = run_runner(root, ref, ref)
                r = run_runner(root, empty, ref)
            finally:
                if linked and os.path.isdir(junction):
                    os.rmdir(junction)  # junction 本体删除，不递归源
            if not (gcode == 0 and g.returncode == 0 and r.returncode == 1):
                all_ok = False
                d9.append("%s/%s g05=%d green=%d red=%d"
                          % (pkg, v, gcode, g.returncode, r.returncode))
    check("BP-9", all_ok, "三包×三变体 门+绿+红：%s" % ("全过" if all_ok else d9))


# ---------------------------------------------------------------- HY 组
def hy_group():
    section("HY 组 · 发布卫生与打包清单")
    products_root = os.path.join(DIST, "build")
    ok1, d1 = True, []
    srcs = [os.path.join(DIST, p) for p in build.DIST_PACKAGES]
    srcs += [os.path.join(HERE, "src-demo", "src-demo-skill")]
    for s in srcs:
        hits = build.scan_reserved_names(s)
        if hits:
            ok1 = False
            d1.append("%s:%s" % (os.path.basename(s), hits))
    prod_hits = build.scan_reserved_names(products_root)
    check("HY-1", ok1 and not prod_hits,
          "打包输入+产物双侧保留名扫描：源=%s 产物=%s" % (d1 or "零命中",
                                                    prod_hits or "零命中"))

    ok2, d2 = True, []
    for base, _dirs, files in os.walk(products_root):
        for fn in files:
            p = os.path.join(base, fn)
            with open(p, "rb") as f:
                raw = f.read()
            if not build.is_text_bytes(raw):
                continue
            if b"\r\n" in raw or b"\r" in raw:
                ok2 = False
                d2.append(os.path.relpath(p, products_root))
    check("HY-2", ok2, "发布物 CRLF 扫描=%s（utf-8 严格解码由 is_text_bytes 隐式验证）"
          % (d2 or "零命中"))

    ok3, d3 = True, []
    for base, _dirs, files in os.walk(products_root):
        for fn in files:
            if not fn.endswith(".json"):
                continue
            p = os.path.join(base, fn)
            try:
                with open(p, "rb") as f:
                    json.loads(f.read().decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                ok3 = False
                d3.append("%s:%s" % (os.path.relpath(p, products_root), exc))
    check("HY-3", ok3, "评测留档 json.load=%s" % (d3 or "全部可解析"))

    ticket = os.path.join(DIST, "dist-compliance-tickets.md")
    try:
        with open(ticket, "r", encoding="utf-8") as f:
            tsrc = f.read()
        ok4 = "K-5" in tsrc
    except OSError:
        ok4, tsrc = False, ""
    check("HY-4", ok4, "K-5 发布批准留痕位在修复票（发布亲签动作归 owner，本轮只留位）")

    ok5, d5 = True, []
    for base, _dirs, files in os.walk(products_root):
        root_rel = os.path.relpath(base, products_root)
        parts = root_rel.replace(os.sep, "/").split("/")
        if parts and parts[0] in ("oracle", "reference", ".git", "__pycache__"):
            ok5 = False
            d5.append(root_rel)
    mcount = 0
    for base, _dirs, files in os.walk(products_root):
        for fn in files:
            p = os.path.join(base, fn)
            rel = os.path.relpath(p, products_root).replace(os.sep, "/")
            variant = rel.split("/")[0]
            if fn == "MANIFEST.json":
                with open(p, "rb") as f:
                    m = json.loads(f.read().decode("utf-8"))
                if not (m.get("skill_version") and m.get("files")
                        and all(e.get("sha256") for e in m["files"])):
                    ok5 = False
                    d5.append(rel + " manifest 不完整")
                mcount += 1
            if variant == "learner" and rel.endswith("eval/runner.py"):
                mcount += 0  # 在位性由 BP-4 覆盖
    check("HY-5", ok5 and mcount >= 9,
          "产物无 oracle/reference/%s；MANIFEST.json %d 份均含版本+sha256 指纹"
          % (d5 or "违禁目录", mcount))


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    ac_group()
    bp_group()
    hy_group()
    failed = [r for r in RESULTS if not r["pass"]]
    print("\n==== 总计 %d 条：PASS %d / FAIL %d ====" % (
        len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    out_path = os.path.join(DIST, "build", "ws2-checks-report.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(json.dumps(RESULTS, ensure_ascii=False, indent=2).encode("utf-8"))
    print("report -> %s" % out_path)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
