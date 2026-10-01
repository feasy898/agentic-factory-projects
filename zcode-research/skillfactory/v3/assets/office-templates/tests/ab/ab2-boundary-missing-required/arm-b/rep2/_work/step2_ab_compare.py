# -*- coding: utf-8 -*-
"""step2: A/B 对照 — fields.json 缺失记账深度 diff + docx 占位渲染画像 + 与运行前快照的确定性核验。"""
import json, os, sys, zipfile, hashlib
from docx import Document
from lxml import etree

ROOT = r"D:\workspace\zcode研究\skillfactory\v3\assets\office-templates"
WORK = os.path.join(ROOT, r"tests\ab\ab2-boundary-missing-required\arm-b\rep2\_work")
BK = os.path.join(WORK, "backup")

TPLS = ["请示函", "会议通知"]
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

# ---------- helpers ----------

def load_json(p):
    with open(p, "rb") as f:
        return json.loads(f.read().decode("utf-8"))

def deep_diff(a, b, path="$", out=None):
    if out is None: out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a: out.append((f"{path}.{k}", "ONLY-IN-B", b[k]))
            elif k not in b: out.append((f"{path}.{k}", "ONLY-IN-A", a[k]))
            else: deep_diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, "LEN", f"A={len(a)} B={len(b)}"))
        for i, (x, y) in enumerate(zip(a, b)):
            deep_diff(x, y, f"{path}[{i}]", out)
    else:
        if a != b:
            out.append((path, "DIFF", f"A={a!r} B={b!r}"))
    return out

def para_profile(doc):
    """逐段：文本、对齐、首行缩进(firstLineChars/firstLine twips)、run字体字号。"""
    prof = []
    body = doc.element.body
    for p in body.findall(".//w:p", NS):
        texts = [t.text or "" for t in p.findall(".//w:t", NS)]
        text = "".join(texts)
        pPr = p.find("w:pPr", NS)
        jc = pPr.find("w:jc", NS).get("{%s}val" % NS["w"]) if (pPr is not None and pPr.find("w:jc", NS) is not None) else None
        ind = pPr.find("w:ind", NS) if pPr is not None else None
        flc = ind.get("{%s}firstLineChars" % NS["w"]) if ind is not None else None
        fl = ind.get("{%s}firstLine" % NS["w"]) if ind is not None else None
        runs = []
        for r in p.findall("w:r", NS):
            rPr = r.find("w:rPr", NS)
            rfonts = rPr.find("w:rFonts", NS) if rPr is not None else None
            ea = rfonts.get("{%s}eastAsia" % NS["w"]) if rfonts is not None else None
            sz = rPr.find("w:sz", NS) if rPr is not None else None
            runs.append((ea, sz.get("{%s}val" % NS["w"]) if sz is not None else None))
        prof.append({"text": text, "align": jc, "flc": flc, "fl": fl, "runs": runs[:1]})
    return prof

def docx_zip_entries(p):
    with zipfile.ZipFile(p) as z:
        return {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()}

out = []
def say(s=""):
    out.append(s); print(s)

# ---------- 1. fields.json 深度对照 ----------
for tpl in TPLS:
    say(f"\n########## {tpl} case2 fields.json 对照 ##########")
    a = load_json(os.path.join(ROOT, "package", "out", tpl, "case2", "fields.json"))  # 被测 PKG
    b = load_json(os.path.join(ROOT, "oracle", "out", tpl, "case2", "fields.json"))   # 参照 ORC
    diffs = deep_diff(a, b)
    real = [d for d in diffs if not d[0].startswith("$.outputs")]
    say(f"深度 diff 差异数（全量）={len(diffs)}；剔除 $.outputs.* 后={len(real)}")
    for d in diffs:
        say(f"  {d[0]}: {d[1]} {d[2]!r}")
    say(f"-- PKG 台账逐字段 --")
    say(f"  顶层键: {sorted(a.keys())}")
    s = a["summary"]
    say(f"  summary 键: {sorted(s.keys())}")
    say(f"  summary: total={s['total']} filled={s['filled']} missing={s['missing']} "
        f"missing_required={s['missing_required']} names={s['missing_required_names']} unknown={s['unknown_keys']}")
    say(f"  title={a['title']!r}")
    say(f"  filled_fields={a['filled_fields']}")
    say(f"  missing_fields={a['missing_fields']}")
    for it in a["fields"]:
        say(f"    - {it['name']}: required={it['required']} kind={it['kind']} status={it['status']} "
            f"value={it['value']!r}" + (f" rendered_as={it['rendered_as']!r}" if "rendered_as" in it else ""))
    say(f"  计数自洽: filled+missing==total → {s['filled']+s['missing']==s['total']}; "
        f"missing_required_names==缺失且必填序列 → {s['missing_required_names']==[i['name'] for i in a['fields'] if i['status']=='missing' and i['required']]}")
    say(f"-- ORC 台账逐字段 --")
    s2 = b["summary"]
    say(f"  summary: total={s2['total']} filled={s2['filled']} missing={s2['missing']} "
        f"missing_required={s2['missing_required']} names={s2['missing_required_names']} unknown={s2['unknown_keys']}")
    for it in b["fields"]:
        say(f"    - {it['name']}: required={it['required']} kind={it['kind']} status={it['status']} "
            f"value={it['value']!r}" + (f" rendered_as={it['rendered_as']!r}" if "rendered_as" in it else ""))

# ---------- 2. docx 渲染对照 ----------
for tpl in TPLS:
    say(f"\n########## {tpl} case2 文书.docx 渲染对照 ##########")
    da = Document(os.path.join(ROOT, "package", "out", tpl, "case2", "文书.docx"))
    db = Document(os.path.join(ROOT, "oracle", "out", tpl, "case2", "文书.docx"))
    pa, pb = para_profile(da), para_profile(db)
    say(f"段落数 A(PKG)={len(pa)} B(ORC)={len(pb)}")
    n = max(len(pa), len(pb))
    for i in range(n):
        x = pa[i] if i < len(pa) else None
        y = pb[i] if i < len(pb) else None
        mark = "SAME" if (x and y and x["text"] == y["text"]) else "DIFF"
        def fmt(p):
            if p is None: return "<缺失>"
            r0 = p["runs"][0] if p["runs"] else (None, None)
            return f"{p['text']!r} align={p['align']} flc={p['flc']} fl={p['fl']} font={r0[0]}/{r0[1]}"
        say(f"  P{i:02d} [{mark}]")
        say(f"     A: {fmt(x)}")
        if mark == "DIFF":
            say(f"     B: {fmt(y)}")
    ta = "\n".join(p["text"] for p in pa)
    tb = "\n".join(p["text"] for p in pb)
    say(f"-- 针脚检索（全文）--")
    probes = {
        "请示函": ["____：", "____", "联系人：李工", "联系电话：", "评测技术部"],
        "会议通知": ["关于召开____的通知", "会议地点：____", "各部门：", "一、会议要求", "会议议题：",
                 "联系人：", "联系电话：", "评测技术部", "2026年9月30日", "此键不在模板字段内", "特此通知"],
    }[tpl]
    for pr in probes:
        say(f"  {pr!r}: in-A={pr in ta} in-B={pr in tb}")
    if tpl == "请示函":
        import re
        dig_a = re.findall(r"[0-9０-９]", ta); dig_b = re.findall(r"[0-9０-９]", tb)
        say(f"  数字探针（输入无任何数字→文书出现任何数字即编造）: A={dig_a} B={dig_b}")
    # 末个非空段对齐（落款检查）
    for tag, prof, txts in (("A", pa, None), ("B", pb, None)):
        nonempty = [p for p in prof if p["text"].strip()]
        say(f"  {tag} 末个非空段: {nonempty[-1]['text']!r} align={nonempty[-1]['align']} "
            f"(倒数第二非空段={nonempty[-2]['text']!r} align={nonempty[-2]['align']})")

# ---------- 3. 确定性：本次重跑 vs 运行前快照 ----------
say(f"\n########## 确定性核验（fresh vs 运行前快照）##########")
for side, sub in (("PKG", "package_out"), ("ORC", "oracle_out")):
    for tpl in TPLS:
        cur = os.path.join(ROOT, "package" if side == "PKG" else "oracle", "out", tpl, "case2")
        old = os.path.join(BK, sub, f"{tpl}_case2")
        fj_same = open(os.path.join(cur, "fields.json"), "rb").read() == open(os.path.join(old, "fields.json"), "rb").read()
        ze, zd = docx_zip_entries(os.path.join(cur, "文书.docx")), docx_zip_entries(os.path.join(old, "文书.docx"))
        diff_entries = [k for k in sorted(set(ze) | set(zd)) if ze.get(k) != zd.get(k)]
        say(f"  {side} {tpl}: fields.json 逐字节相同={fj_same}; docx zip 内容不同的 entry={diff_entries or '无'}")

with open(os.path.join(WORK, "step2_ab_report.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("\n[DONE] → step2_ab_report.txt")
