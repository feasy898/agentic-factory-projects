# -*- coding: utf-8 -*-
"""ab5 arm-a rep1 — D1 确定性比对器。

对两组「同输入连跑两遍、同一 outdir 覆盖复写」的产物做逐字节与语义比对：
  组A（被测）：_work/run1  vs _work/run2     （package/scripts/gen_doc.py 两遍快照）
  组B（参照）：_work/oracle-run2/fields_run1.json+docx_run1.docx vs _work/oracle-run1（第二遍在盘）
比对口径 = spec.md §8 D1：
  fields.json（除 outputs 键外）逐字节一致；
  文书.docx 解析后的段落文本、对齐、缩进、字体、行距、页边距全部一致
  （zip 条目时间戳允许不同，不做逐字节要求）。
并做跨实现 layout 对照（被测第二遍产物 vs oracle/out 参照基线，同输入）与
§10 字段填充一致率抽查（本单元）。
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[6]          # .../office-templates
W = Path(__file__).resolve().parent
sys_enc = "utf-8"

GROUPS = {
    "tested_run1_vs_run2": {
        "fields_a": W / "run1/fields.json", "fields_b": W / "run2/fields.json",
        "docx_a": W / "run1/文书.docx", "docx_b": W / "run2/文书.docx",
    },
    "oracle_run1_vs_run2": {
        "fields_a": W / "oracle-run2/fields_run1.json", "fields_b": W / "oracle-run1/fields.json",
        "docx_a": W / "oracle-run2/docx_run1.docx", "docx_b": W / "oracle-run1/文书.docx",
    },
}


def docx_signature(path: Path) -> dict:
    """解析后的语义签名：页面几何 + 逐段（文本/对齐/缩进/行距/右缩进/首 run 字体）。"""
    doc = Document(str(path))
    sec = doc.sections[0]

    def tw(el, attr):
        v = el.get(qn(attr))
        return int(v) if v is not None and v.lstrip("-").isdigit() else v

    pgsz, pgmar = sec._sectPr.find(qn("w:pgSz")), sec._sectPr.find(qn("w:pgMar"))
    paras = []
    for p in doc.paragraphs:
        ppr = p._p.pPr
        ind = ppr.find(qn("w:ind")) if ppr is not None else None
        spc = ppr.find(qn("w:spacing")) if ppr is not None else None
        jc = ppr.find(qn("w:jc")) if ppr is not None else None
        run_info = []
        for r in p.runs[:1]:
            rpr = r._element.rPr
            fonts = rpr.rFonts if rpr is not None else None
            run_info.append({
                "eastAsia": fonts.get(qn("w:eastAsia")) if fonts is not None else None,
                "ascii": fonts.get(qn("w:ascii")) if fonts is not None else None,
                "hAnsi": fonts.get(qn("w:hAnsi")) if fonts is not None else None,
                "sz_halfpt": rpr.find(qn("w:sz")).get(qn("w:val"))
                             if rpr is not None and rpr.find(qn("w:sz")) is not None else None,
                "text": r.text,
            })
        paras.append({
            "text": p.text,
            "jc": jc.get(qn("w:val")) if jc is not None else None,
            "firstLineChars": ind.get(qn("w:firstLineChars")) if ind is not None else None,
            "firstLine_tw": tw(ind, "w:firstLine") if ind is not None else None,
            "rightChars": ind.get(qn("w:rightChars")) if ind is not None else None,
            "right_tw": tw(ind, "w:right") if ind is not None else None,
            "line": spc.get(qn("w:line")) if spc is not None else None,
            "lineRule": spc.get(qn("w:lineRule")) if spc is not None else None,
            "before": spc.get(qn("w:before")) if spc is not None else None,
            "after": spc.get(qn("w:after")) if spc is not None else None,
            "first_run": run_info[0] if run_info else None,
            "n_runs": len(p.runs),
        })
    return {
        "pgSz": {"w": pgsz.get(qn("w:w")), "h": pgsz.get(qn("w:h"))},
        "pgMar": {k: pgmar.get(qn(f"w:{k}")) for k in ("top", "bottom", "left", "right")},
        "n_paragraphs": len(paras),
        "paragraphs": paras,
    }


def zip_facts(path: Path) -> dict:
    """zip 条目表：每条目的 CRC / 解压内容 md5 / DOS 时间戳，用于区分「内容差」与「时间戳差」。"""
    facts = {}
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            facts[info.filename] = {
                "crc": "%08x" % info.CRC,
                "size": info.file_size,
                "content_md5": hashlib.md5(zf.read(info.filename)).hexdigest(),
                "zip_date_time": list(info.date_time),
            }
    return facts


def fields_bytes_minus_outputs(path: Path) -> bytes:
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta.pop("outputs", None)
    return (json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def compare_group(tag: str, fields_a: Path, fields_b: Path, docx_a: Path, docx_b: Path) -> dict:
    out: dict = {"group": tag}
    # --- fields.json ---
    raw_a, raw_b = fields_a.read_bytes(), fields_b.read_bytes()
    out["fields"] = {
        "raw_bytes_equal": raw_a == raw_b,
        "md5_a": hashlib.md5(raw_a).hexdigest(), "md5_b": hashlib.md5(raw_b).hexdigest(),
        "minus_outputs_equal": fields_bytes_minus_outputs(fields_a) == fields_bytes_minus_outputs(fields_b),
    }
    # --- docx 语义签名（D1 口径） ---
    sig_a, sig_b = docx_signature(docx_a), docx_signature(docx_b)
    out["docx"] = {
        "raw_bytes_equal": docx_a.read_bytes() == docx_b.read_bytes(),
        "md5_a": hashlib.md5(docx_a.read_bytes()).hexdigest(),
        "md5_b": hashlib.md5(docx_b.read_bytes()).hexdigest(),
        "size_a": docx_a.stat().st_size, "size_b": docx_b.stat().st_size,
        "semantic_signature_equal": sig_a == sig_b,
        "pgSz_equal": sig_a["pgSz"] == sig_b["pgSz"],
        "pgMar_equal": sig_a["pgMar"] == sig_b["pgMar"],
        "n_paragraphs": sig_a["n_paragraphs"],
    }
    if sig_a != sig_b:
        diffs = []
        for i, (pa, pb) in enumerate(zip(sig_a["paragraphs"], sig_b["paragraphs"])):
            if pa != pb:
                diffs.append({"idx": i, "a": pa, "b": pb})
        out["docx"]["signature_diffs"] = diffs[:10]
    # --- zip 条目表：内容 vs 时间戳 ---
    za, zb = zip_facts(docx_a), zip_facts(docx_b)
    names_a, names_b = list(za), list(zb)
    out["zip"] = {
        "namelist_equal": names_a == names_b,
        "n_entries": len(names_a),
        "content_identical_all_entries": all(za[n]["content_md5"] == zb[n]["content_md5"]
                                             for n in names_a if n in zb),
        "entries_content_diff": [n for n in names_a
                                 if n in zb and za[n]["content_md5"] != zb[n]["content_md5"]],
        "entries_timestamp_diff": [n for n in names_a
                                   if n in zb and za[n]["zip_date_time"] != zb[n]["zip_date_time"]],
        "sample_timestamps": {n: {"a": za[n]["zip_date_time"], "b": zb[n]["zip_date_time"]}
                              for n in names_a[:2]},
    }
    return out


def cross_impl_layout() -> dict:
    """被测最终产物（package/out 第二遍覆盖后）vs 参照基线 oracle/out 同单元：layout 对照。"""
    t_docx = ROOT / "package/out/会议通知/case1/文书.docx"
    r_docx = ROOT / "oracle/out/会议通知/case1/文书.docx"
    sig_t, sig_r = docx_signature(t_docx), docx_signature(r_docx)
    per_para = []
    for i, (pt, pr) in enumerate(zip(sig_t["paragraphs"], sig_r["paragraphs"])):
        per_para.append({
            "idx": i, "tested_text": pt["text"], "ref_text": pr["text"],
            "tested": {k: pt[k] for k in ("jc", "firstLineChars", "line", "lineRule",
                                          "right_tw", "before", "after")},
            "ref": {k: pr[k] for k in ("jc", "firstLineChars", "line", "lineRule",
                                       "right_tw", "before", "after")},
        })
    return {
        "pgSz": {"tested": sig_t["pgSz"], "ref": sig_r["pgSz"],
                 "equal": sig_t["pgSz"] == sig_r["pgSz"]},
        "pgMar": {"tested": sig_t["pgMar"], "ref": sig_r["pgMar"],
                  "equal": sig_t["pgMar"] == sig_r["pgMar"]},
        "n_paragraphs": {"tested": sig_t["n_paragraphs"], "ref": sig_r["n_paragraphs"]},
        "paragraphs": per_para,
    }


def field_agreement() -> dict:
    """spec §10 口径（status 相等且 filled 时 value 相等）——本单元被测 vs 参照。"""
    t = json.loads((ROOT / "package/out/会议通知/case1/fields.json").read_text(encoding="utf-8"))
    r = json.loads((ROOT / "oracle/out/会议通知/case1/fields.json").read_text(encoding="utf-8"))
    t_by = {d["name"]: d for d in t["fields"]}
    matched, mismatch = 0, []
    for rf in r["fields"]:
        tf = t_by.get(rf["name"])
        if tf is not None and rf["status"] == tf["status"] and \
                (rf["status"] != "filled" or rf["value"] == tf["value"]):
            matched += 1
        else:
            mismatch.append(rf["name"])
    return {"matched": matched, "total": len(r["fields"]),
            "rate": matched / len(r["fields"]) if r["fields"] else 0.0,
            "mismatch": mismatch,
            "title_equal": t["title"] == r["title"],
            "title": t["title"]}


def main() -> int:
    import sys
    sys.stdout.reconfigure(encoding=sys_enc, errors="replace")
    report = {"groups": [compare_group(tag, **kw) for tag, kw in GROUPS.items()],
              "cross_impl_layout_vs_oracle_out": cross_impl_layout(),
              "field_agreement_vs_oracle_out": field_agreement()}
    out = W / "step4_determinism_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    # 摘要
    for g in report["groups"]:
        print(json.dumps({
            "group": g["group"],
            "fields_raw_equal": g["fields"]["raw_bytes_equal"],
            "fields_minus_outputs_equal": g["fields"]["minus_outputs_equal"],
            "docx_raw_equal": g["docx"]["raw_bytes_equal"],
            "docx_signature_equal": g["docx"]["semantic_signature_equal"],
            "docx_pgSz_pgMar_equal": g["docx"]["pgSz_equal"] and g["docx"]["pgMar_equal"],
            "zip_namelist_equal": g["zip"]["namelist_equal"],
            "zip_content_identical": g["zip"]["content_identical_all_entries"],
            "zip_content_diff_entries": g["zip"]["entries_content_diff"],
            "zip_timestamp_diff_count": len(g["zip"]["entries_timestamp_diff"]),
        }, ensure_ascii=False))
    c = report["cross_impl_layout_vs_oracle_out"]
    print("cross_impl: pgSz equal=%s pgMar equal=%s paras tested=%d ref=%d" % (
        c["pgSz"]["equal"], c["pgMar"]["equal"],
        c["n_paragraphs"]["tested"], c["n_paragraphs"]["ref"]))
    print("field_agreement: %d/%d rate=%.1f%% title_equal=%s title=%s" % (
        report["field_agreement_vs_oracle_out"]["matched"],
        report["field_agreement_vs_oracle_out"]["total"],
        report["field_agreement_vs_oracle_out"]["rate"] * 100,
        report["field_agreement_vs_oracle_out"]["title_equal"],
        report["field_agreement_vs_oracle_out"]["title"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
