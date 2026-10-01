#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab_compare.py — A/B 逐单元对照脚本（rep1 实测用）。

对 (tested_dir, oracle_dir) 逐对比较：
  1) fields.json：顶层键集合、除 outputs 外的深比较（逐键报告差异）、spec §10 字段一致率；
  2) 文书.docx：版式语义签名 = 页面几何 + 每非空段(text/对齐/firstLineChars/firstLine/右缩进/
     行距line+lineRule/段前段后) + 每段首 run(eastAsia/ascii/hAnsi/字号/加粗)，逐段 diff。

用法：python ab_compare.py <pair_name> <tested_dir> <oracle_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEMPLATES = ("周报", "请示函", "会议通知", "工作总结")


def para_sig(p):
    """单段签名：text + pPr 关键属性 + 首 run 字体声明。"""
    ppr = p._p.pPr
    flc = fl = ri = line = rule = before = after = jc = None
    if ppr is not None:
        ind = ppr.find(qn("w:ind"))
        if ind is not None:
            flc = ind.get(qn("w:firstLineChars"))
            fl = ind.get(qn("w:firstLine"))
            ri = ind.get(qn("w:right"))
        sp = ppr.find(qn("w:spacing"))
        if sp is not None:
            line = sp.get(qn("w:line"))
            rule = sp.get(qn("w:lineRule"))
            before = sp.get(qn("w:before"))
            after = sp.get(qn("w:after"))
        jcel = ppr.find(qn("w:jc"))
        if jcel is not None:
            jc = jcel.get(qn("w:val"))
    runs = []
    for r in p.runs:
        rpr = r._element.rPr
        east = ascii_ = hansi = ""
        size = bold = None
        if rpr is not None and rpr.rFonts is not None:
            east = rpr.rFonts.get(qn("w:eastAsia")) or ""
            ascii_ = rpr.rFonts.get(qn("w:ascii")) or ""
            hansi = rpr.rFonts.get(qn("w:hAnsi")) or ""
        if r.font.size is not None:
            size = float(r.font.size.pt)
        bold = r.font.bold
        runs.append({"eastAsia": east, "ascii": ascii_, "hAnsi": hansi,
                     "size_pt": size, "bold": bold})
    return {"text": p.text, "jc": jc, "firstLineChars": flc, "firstLine": fl,
            "right": ri, "line": line, "lineRule": rule,
            "before": before, "after": after, "runs": runs}


def docx_sig(path: Path) -> dict:
    doc = Document(str(path))
    sec = doc.sections[0]

    def cm(v):
        return round(v.cm, 3) if v is not None else None

    return {
        "page": {"w_cm": cm(sec.page_width), "h_cm": cm(sec.page_height),
                 "top_cm": cm(sec.top_margin), "bottom_cm": cm(sec.bottom_margin),
                 "left_cm": cm(sec.left_margin), "right_cm": cm(sec.right_margin)},
        "paras": [para_sig(p) for p in doc.paragraphs if p.text.strip()],
    }


def fields_deep_diff(a: dict, b: dict, skip=("outputs",)):
    """返回除 skip 键外的差异列表（a=tested, b=oracle）。"""
    diffs = []
    ka, kb = set(a) - set(skip), set(b) - set(skip)
    if set(a) != set(b):
        diffs.append(f"顶层键集合不同: tested多{sorted(set(a)-set(b))} oracle多{sorted(set(b)-set(a))}")
    for k in sorted(ka & kb):
        if a[k] != b[k]:
            diffs.append(f"键 {k}: tested={json.dumps(a[k], ensure_ascii=False)} "
                         f"oracle={json.dumps(b[k], ensure_ascii=False)}")
    return diffs


def agreement(tested: dict, oracle: dict):
    """spec §10：以参照 fields 序列为字段全集，status 相等且 filled 时 value 相等记一致。"""
    total = matched = 0
    mism = []
    for rf in oracle["fields"]:
        total += 1
        tf = next((x for x in tested.get("fields", []) if x.get("name") == rf.get("name")), None)
        if (tf is not None and rf.get("status") == tf.get("status")
                and (rf.get("status") != "filled" or rf.get("value") == tf.get("value"))):
            matched += 1
        else:
            mism.append(rf.get("name"))
    return matched, total, mism


def render_text_lines(sig: dict):
    return ["%02d|jc=%-6s|flc=%-4s|line=%s/%s|ri=%s|%s|east=%s,size=%s" % (
        i, p["jc"], p["firstLineChars"], p["line"], p["lineRule"], p["right"],
        p["text"], p["runs"][0]["eastAsia"] if p["runs"] else "?",
        p["runs"][0]["size_pt"] if p["runs"] else "?")
        for i, p in enumerate(sig["paras"])]


def main(argv):
    results = []
    for t in TEMPLATES:
        tdir = Path(argv[1]) / t / "case1"
        odir = Path(argv[2]) / t / "case1"
        rep = {"template": t}

        t_fields = json.loads((tdir / "fields.json").read_text(encoding="utf-8"))
        o_fields = json.loads((odir / "fields.json").read_text(encoding="utf-8"))
        rep["fields_top_keys_equal"] = set(t_fields) == set(o_fields)
        rep["fields_diffs_minus_outputs"] = fields_deep_diff(t_fields, o_fields)
        rep["fields_outputs_tested"] = t_fields.get("outputs")
        rep["fields_outputs_oracle"] = o_fields.get("outputs")
        m, tot, mism = agreement(t_fields, o_fields)
        rep["agreement"] = {"matched": m, "total": tot, "rate": round(m / tot, 4),
                            "mismatch_names": mism}
        rep["title"] = {"tested": t_fields.get("title"), "oracle": o_fields.get("title")}

        tsig, osig = docx_sig(tdir / "文书.docx"), docx_sig(odir / "文书.docx")
        rep["page_equal"] = tsig["page"] == osig["page"]
        rep["page"] = {"tested": tsig["page"], "oracle": osig["page"]}
        rep["para_count"] = {"tested": len(tsig["paras"]), "oracle": len(osig["paras"])}
        rep["docx_identical_sig"] = tsig == osig
        rep["tested_lines"] = render_text_lines(tsig)
        rep["oracle_lines"] = render_text_lines(osig)
        results.append(rep)

    out = json.dumps(results, ensure_ascii=False, indent=1)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
