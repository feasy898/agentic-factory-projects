#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""det_compare.py — ab5 确定性对照：两份产物单元的 fields.json 逐字节比对 +
docx 语义签名（spec D1：段落文本/对齐/缩进/字体/行距/页边距；zip 时间戳允许不同）。

用法：python det_compare.py <unitA> <unitB> <输出.json>
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

ALIGN_NAMES = {
    WD_ALIGN_PARAGRAPH.CENTER: "CENTER",
    WD_ALIGN_PARAGRAPH.RIGHT: "RIGHT",
    WD_ALIGN_PARAGRAPH.LEFT: "LEFT",
    WD_ALIGN_PARAGRAPH.JUSTIFY: "JUSTIFY",
    None: "None",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fields_hashes(unit: Path) -> dict:
    raw = (unit / "fields.json").read_bytes()
    meta = json.loads(raw.decode("utf-8"))
    no_out = {k: v for k, v in meta.items() if k != "outputs"}
    canon = json.dumps(no_out, ensure_ascii=False, indent=2).encode("utf-8")
    return {
        "raw_sha256": sha(raw),
        "no_outputs_sha256": sha(canon),
        "outputs": meta.get("outputs"),
        "size": len(raw),
    }


def cm(emu) -> float:
    return round(emu / 360000.0, 3)


def docx_signature(unit: Path) -> dict:
    doc = Document(str(unit / "文书.docx"))
    sec = doc.sections[0]
    geo = {
        "page_w_cm": cm(sec.page_width), "page_h_cm": cm(sec.page_height),
        "top_cm": cm(sec.top_margin), "bottom_cm": cm(sec.bottom_margin),
        "left_cm": cm(sec.left_margin), "right_cm": cm(sec.right_margin),
    }
    paras = []
    for p in doc.paragraphs:
        ppr = p._p.pPr
        flc = ""
        ri_emu = None
        if ppr is not None:
            ind = ppr.find(qn("w:ind"))
            if ind is not None:
                flc = ind.get(qn("w:firstLineChars")) or ""
                rv = ind.get(qn("w:right"))
                ri_emu = int(rv) if rv else None
        ls = p.paragraph_format.line_spacing
        ls_val = None
        ls_rule = None
        if ppr is not None:
            sp = ppr.find(qn("w:spacing"))
            if sp is not None:
                ls_val = sp.get(qn("w:line"))
                ls_rule = sp.get(qn("w:lineRule"))
        runs = []
        for r in p.runs[:1]:
            rpr = r._element.rPr
            east = ascii_ = hansi = ""
            if rpr is not None and rpr.rFonts is not None:
                east = rpr.rFonts.get(qn("w:eastAsia")) or ""
                ascii_ = rpr.rFonts.get(qn("w:ascii")) or ""
                hansi = rpr.rFonts.get(qn("w:hAnsi")) or ""
            runs.append({
                "text": r.text,
                "eastAsia": east, "ascii": ascii_, "hAnsi": hansi,
                "size_pt": float(r.font.size.pt) if r.font.size is not None else None,
                "bold": r.font.bold,
            })
        paras.append({
            "text": p.text,
            "align": ALIGN_NAMES.get(p.alignment, str(p.alignment)),
            "firstLineChars": flc,
            "right_char_twips": ri_emu,
            "line": ls_val, "lineRule": ls_rule,
            "runs": runs,
        })
    return {"geometry": geo, "n_paras": len(paras), "paragraphs": paras}


def zip_table(unit: Path) -> dict:
    with zipfile.ZipFile(unit / "文书.docx") as zf:
        infos = zf.infolist()
        return {
            "names": [i.filename for i in infos],
            "name_sha256": sha(json.dumps([i.filename for i in infos]).encode()),
            "date_time": ["%04d-%02d-%02dT%02d:%02d:%02d" % i.date_time for i in infos],
        }


def compare(a: Path, b: Path) -> dict:
    fa, fb = fields_hashes(a), fields_hashes(b)
    sa, sb = docx_signature(a), docx_signature(b)
    za, zb = zip_table(a), zip_table(b)
    sig_a = json.dumps(sa, ensure_ascii=False, sort_keys=True)
    sig_b = json.dumps(sb, ensure_ascii=False, sort_keys=True)
    result = {
        "unit_a": str(a), "unit_b": str(b),
        "fields_raw_identical": fa["raw_sha256"] == fb["raw_sha256"],
        "fields_raw_sha256": [fa["raw_sha256"], fb["raw_sha256"]],
        "fields_no_outputs_identical": fa["no_outputs_sha256"] == fb["no_outputs_sha256"],
        "fields_outputs": [fa["outputs"], fb["outputs"]],
        "docx_semantic_signature_identical": sig_a == sig_b,
        "docx_signature_sha256": [sha(sig_a.encode()), sha(sig_b.encode())],
        "zip_entry_names_identical": za["names"] == zb["names"],
        "zip_entry_timestamps_identical": za["date_time"] == zb["date_time"],
        "docx_raw_identical": sha((a / "文书.docx").read_bytes()) == sha((b / "文书.docx").read_bytes()),
        "signature_a": sa, "signature_b": sb,
    }
    if not result["docx_semantic_signature_identical"]:
        diffs = []
        if sa["geometry"] != sb["geometry"]:
            diffs.append("geometry: %s vs %s" % (sa["geometry"], sb["geometry"]))
        if sa["n_paras"] != sb["n_paras"]:
            diffs.append("n_paras: %d vs %d" % (sa["n_paras"], sb["n_paras"]))
        for i, (pa, pb) in enumerate(zip(sa["paragraphs"], sb["paragraphs"])):
            if json.dumps(pa, sort_keys=True, ensure_ascii=False) != json.dumps(pb, sort_keys=True, ensure_ascii=False):
                diffs.append("para[%d]: A=%s | B=%s" % (i, json.dumps(pa, ensure_ascii=False), json.dumps(pb, ensure_ascii=False)))
        result["semantic_diffs"] = diffs
    return result


def main(argv) -> int:
    a, b, out = Path(argv[1]), Path(argv[2]), Path(argv[3])
    r = compare(a, b)
    out.write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in r.items()
                      if k in ("fields_raw_identical", "fields_no_outputs_identical",
                               "docx_semantic_signature_identical", "zip_entry_names_identical",
                               "zip_entry_timestamps_identical", "docx_raw_identical",
                               "docx_signature_sha256")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
