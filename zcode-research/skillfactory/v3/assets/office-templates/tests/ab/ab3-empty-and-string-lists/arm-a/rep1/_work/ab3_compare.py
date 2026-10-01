#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab3_compare.py — ab3 列表字段边界 A/B 对照分析器（arm-a/rep1）。

输入：run_arms.py 产出的 4 个产物目录（A/run1、A/run2、B/run1、B/run2 各 模板/case2）。

输出（JSON + 人读摘要）：
  1) fields.json 深比较（A vs B，剔除 outputs；字节级 + spec §10 一致率）；
  2) docx 全段落（含空段）文本/版式签名对照（jc/firstLineChars/right/line/lineRule/首 run 字体字号）；
  3) ab3 rubric 五条专项判定（占位条目 / 字符串单项化 / 选填小节省略 / spec §9 记账 / 编号与落款）；
  4) 确定性（A run1 vs run2、B run1 vs run2）；
  5) 基线可复现旁证（fresh B vs oracle/out、fresh A vs package/out，剔除 outputs 字节比较）。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORK = Path(__file__).resolve().parent
ASSET = WORK.parents[5]
TEMPLATES = ("周报", "工作总结")
PLACEHOLDER = "____"


def para_sig(p):
    """单段签名：text + 对齐/缩进/行距/段距 + 首 run 字体声明（空段也保留）。"""
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
    return {"text": p.text, "empty": not p.text.strip(), "jc": jc,
            "firstLineChars": flc, "firstLine": fl, "right": ri,
            "line": line, "lineRule": rule, "before": before, "after": after,
            "runs": runs}


def docx_sig(path: Path) -> dict:
    doc = Document(str(path))
    sec = doc.sections[0]
    cm = lambda v: round(v.cm, 3) if v is not None else None
    paras = [para_sig(p) for p in doc.paragraphs]
    return {
        "page": {"w_cm": cm(sec.page_width), "h_cm": cm(sec.page_height),
                 "top_cm": cm(sec.top_margin), "bottom_cm": cm(sec.bottom_margin),
                 "left_cm": cm(sec.left_margin), "right_cm": cm(sec.right_margin)},
        "paras": paras,
        "paras_nonempty": [p for p in paras if not p["empty"]],
        "md5_docx_bytes": hashlib.md5(path.read_bytes()).hexdigest(),
    }


def fields_load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fields_bytes_minus_outputs(path: Path) -> str:
    """剔除 outputs 后以 ensure_ascii=false, indent=2 重序列化的字节串（用于确定性/基线对比）。"""
    d = fields_load(path)
    d.pop("outputs", None)
    return json.dumps(d, ensure_ascii=False, indent=2, sort_keys=False)


def fields_diff(a: dict, b: dict, skip=("outputs",)):
    diffs = []
    if set(a) != set(b):
        diffs.append(f"顶层键集合不同: A多{sorted(set(a)-set(b))} B多{sorted(set(b)-set(a))}")
    for k in sorted(set(a) & set(b) - set(skip)):
        if a[k] != b[k]:
            diffs.append(f"键 {k}: A={json.dumps(a[k], ensure_ascii=False)} "
                         f"B={json.dumps(b[k], ensure_ascii=False)}")
    return diffs


def agreement(tested: dict, oracle: dict):
    """spec §10：以参照 fields 序列为全集，status 相等且 filled 时 value 相等记一致。"""
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
    return {"matched": matched, "total": total, "rate": round(matched / total, 4),
            "mismatch_names": mism}


def focus_rows(fields: dict) -> list:
    """台账焦点行：本 ask 关注的列表/文本边界字段。"""
    focus = {"周期", "部门", "本周工作内容", "问题与需协调事项",
             "总结主体", "主要成绩", "工作回顾", "存在问题", "成文日期", "下周工作计划",
             "下一步工作打算", "填报人", "总结时段", "报送日期"}
    rows = []
    for d in fields["fields"]:
        if d["name"] in focus:
            rows.append({"name": d["name"], "required": d["required"], "kind": d["kind"],
                         "status": d["status"], "value": d["value"],
                         "rendered_as": d.get("rendered_as")})
    return rows


def texts(sig: dict) -> list:
    return [p["text"] for p in sig["paras"]]


def last_nonempty(sig: dict):
    for p in reversed(sig["paras"]):
        if not p["empty"]:
            return p
    return None


def ph_count(sig: dict) -> int:
    return sum(p["text"].count(PLACEHOLDER) for p in sig["paras"])


def section_headers(sig: dict) -> list:
    """识别节头段（黑体、含全角顿号编号或以、分隔的短行）。"""
    heads = []
    for p in sig["paras_nonempty"]:
        if p["runs"] and p["runs"][0]["eastAsia"] == "黑体" and "、" in p["text"]:
            heads.append(p["text"])
    return heads


def fmt_line(i: int, p: dict) -> str:
    run = p["runs"][0] if p["runs"] else {}
    return ("%02d|jc=%-6s|flc=%-4s|line=%s/%s|ri=%s|%s|east=%s,size=%s" % (
        i, p["jc"], p["firstLineChars"], p["line"], p["lineRule"], p["right"],
        p["text"] if p["text"] else "<空段>",
        run.get("eastAsia", "?"), run.get("size_pt", "?")))


def main() -> int:
    report = {}
    for t in TEMPLATES:
        rep = {"template": t}
        pa = docx_sig(WORK / "A" / "run1" / t / "case2" / "文书.docx")
        pb = docx_sig(WORK / "B" / "run1" / t / "case2" / "文书.docx")
        pa2 = docx_sig(WORK / "A" / "run2" / t / "case2" / "文书.docx")
        pb2 = docx_sig(WORK / "B" / "run2" / t / "case2" / "文书.docx")
        fa = fields_load(WORK / "A" / "run1" / t / "case2" / "fields.json")
        fb = fields_load(WORK / "B" / "run1" / t / "case2" / "fields.json")

        # ---- 1) fields.json A vs B ----
        rep["fields_top_keys_equal"] = set(fa) == set(fb)
        rep["fields_diffs_minus_outputs"] = fields_diff(fa, fb)
        rep["fields_bytes_equal_minus_outputs"] = (
            fields_bytes_minus_outputs(WORK / "A" / "run1" / t / "case2" / "fields.json")
            == fields_bytes_minus_outputs(WORK / "B" / "run1" / t / "case2" / "fields.json"))
        rep["agreement_spec10"] = agreement(fa, fb)
        rep["title"] = {"A": fa["title"], "B": fb["title"]}
        rep["summary"] = {"A": fa["summary"], "B": fb["summary"]}
        rep["focus_rows_A"] = focus_rows(fa)
        rep["focus_rows_B"] = focus_rows(fb)

        # ---- 2) docx A vs B ----
        rep["page_equal"] = pa["page"] == pb["page"]
        rep["page"] = {"A": pa["page"], "B": pb["page"]}
        rep["para_count"] = {"A": len(pa["paras"]), "B": len(pb["paras"])}
        rep["docx_sig_identical"] = pa == pb
        rep["A_lines"] = [fmt_line(i, p) for i, p in enumerate(pa["paras"])]
        rep["B_lines"] = [fmt_line(i, p) for i, p in enumerate(pb["paras"])]
        rep["A_paras_sig"] = pa["paras"]
        rep["B_paras_sig"] = pb["paras"]
        rep["sections_A"] = section_headers(pa)
        rep["sections_B"] = section_headers(pb)

        # ---- 3) rubric 判定 ----
        ta, tb = texts(pa), texts(pb)
        if t == "周报":
            r1 = {
                "A_节头存在": "一、本周工作内容" in ta,
                "A_占位条目存在": "1．____" in ta,
                "B_节头存在": "一、本周工作内容" in tb,
                "B_占位条目存在": "1．____" in tb,
                "A_rendered_as": next((d.get("rendered_as") for d in fa["fields"]
                                       if d["name"] == "本周工作内容"), None),
                "B_rendered_as": next((d.get("rendered_as") for d in fb["fields"]
                                       if d["name"] == "本周工作内容"), None),
            }
            r3 = {
                "A_问题节头未出现": all("问题与需协调事项" not in x for x in ta),
                "B_问题节头未出现": all("问题与需协调事项" not in x for x in tb),
                "A_记账missing": next((d for d in fa["fields"]
                                       if d["name"] == "问题与需协调事项"), {}),
                "B_记账missing": next((d for d in fb["fields"]
                                       if d["name"] == "问题与需协调事项"), {}),
            }
            r4 = {
                "A_missing_required_names": fa["summary"]["missing_required_names"],
                "B_missing_required_names": fb["summary"]["missing_required_names"],
                "expect": ["部门", "周期", "本周工作内容"],
                "A_title": fa["title"], "B_title": fb["title"], "expect_title": "____工作周报",
                "A_filled_total": [fa["summary"]["filled"], fa["summary"]["total"]],
                "B_filled_total": [fb["summary"]["filled"], fb["summary"]["total"]],
            }
            r5 = {
                "A_sections": section_headers(pa), "B_sections": section_headers(pb),
                "expect_sections": ["一、本周工作内容", "二、下周工作计划"],
                "A_last_nonempty": last_nonempty(pa)["text"],
                "B_last_nonempty": last_nonempty(pb)["text"],
                "A_last_nonempty_jc": last_nonempty(pa)["jc"],
                "B_last_nonempty_jc": last_nonempty(pb)["jc"],
                "A_last_nonempty_right": last_nonempty(pa)["right"],
                "B_last_nonempty_right": last_nonempty(pb)["right"],
                "A_item_lines": [x for x in ta if x.startswith("1．") or x.startswith("2．")],
                "B_item_lines": [x for x in tb if x.startswith("1．") or x.startswith("2．")],
            }
        else:
            r1 = {
                "A_节头存在": "二、主要成绩" in ta,
                "A_占位条目存在": "1．____" in ta,
                "B_节头存在": "二、主要成绩" in tb,
                "B_占位条目存在": "1．____" in tb,
                "A_rendered_as": next((d.get("rendered_as") for d in fa["fields"]
                                       if d["name"] == "主要成绩"), None),
                "B_rendered_as": next((d.get("rendered_as") for d in fb["fields"]
                                       if d["name"] == "主要成绩"), None),
            }
            r2 = {
                "A_回顾节头": "一、工作回顾" in ta,
                "A_单项条目": "1．完成评测平台月度巡检" in ta,
                "B_回顾节头": "一、工作回顾" in tb,
                "B_单项条目": "1．完成评测平台月度巡检" in tb,
                "A_value": next((d.get("value") for d in fa["fields"]
                                 if d["name"] == "工作回顾"), None),
                "B_value": next((d.get("value") for d in fb["fields"]
                                 if d["name"] == "工作回顾"), None),
                "A_status": next((d.get("status") for d in fa["fields"]
                                  if d["name"] == "工作回顾"), None),
                "B_status": next((d.get("status") for d in fb["fields"]
                                  if d["name"] == "工作回顾"), None),
            }
            r3 = {
                "A_存在问题节未出现": all("存在问题" not in x for x in ta),
                "B_存在问题节未出现": all("存在问题" not in x for x in tb),
                "A_记账missing": next((d for d in fa["fields"]
                                       if d["name"] == "存在问题"), {}),
                "B_记账missing": next((d for d in fb["fields"]
                                       if d["name"] == "存在问题"), {}),
                "A_成文日期_末段为空段": bool(pa["paras"]) and pa["paras"][-1]["empty"],
                "B_成文日期_末段为空段": bool(pb["paras"]) and pb["paras"][-1]["empty"],
                "A_记账成文日期": next((d for d in fa["fields"]
                                       if d["name"] == "成文日期"), {}),
                "B_记账成文日期": next((d for d in fb["fields"]
                                       if d["name"] == "成文日期"), {}),
            }
            r4 = {
                "A_missing_required_names": fa["summary"]["missing_required_names"],
                "B_missing_required_names": fb["summary"]["missing_required_names"],
                "expect": ["总结主体", "主要成绩"],
                "A_title": fa["title"], "B_title": fb["title"],
                "expect_title": "____2026年9月工作总结",
                "A_filled_total": [fa["summary"]["filled"], fa["summary"]["total"]],
                "B_filled_total": [fb["summary"]["filled"], fb["summary"]["total"]],
            }
            r5 = {
                "A_sections": section_headers(pa), "B_sections": section_headers(pb),
                "expect_sections": ["一、工作回顾", "二、主要成绩", "三、下一步工作打算"],
                "A_last_nonempty": last_nonempty(pa)["text"],
                "B_last_nonempty": last_nonempty(pb)["text"],
                "A_last_nonempty_jc": last_nonempty(pa)["jc"],
                "B_last_nonempty_jc": last_nonempty(pb)["jc"],
                "A_last_nonempty_right": last_nonempty(pa)["right"],
                "B_last_nonempty_right": last_nonempty(pb)["right"],
                "A_item_lines": [x for x in ta if x.startswith(("1．", "2．", "3．"))],
                "B_item_lines": [x for x in tb if x.startswith(("1．", "2．", "3．"))],
            }
        rep["rubric_r1_placeholder_entry"] = r1
        if t == "工作总结":
            rep["rubric_r2_string_singularization"] = r2
        rep["rubric_r3_optional_omission"] = r3
        rep["rubric_r4_spec9_accounting"] = r4
        rep["rubric_r5_numbering_signature"] = r5
        rep["placeholder_count"] = {"A": ph_count(pa), "B": ph_count(pb)}

        # ---- 4) 确定性 ----
        rep["determinism"] = {
            "A_fields_bytes_equal_run1_run2": (
                fields_bytes_minus_outputs(WORK / "A" / "run1" / t / "case2" / "fields.json")
                == fields_bytes_minus_outputs(WORK / "A" / "run2" / t / "case2" / "fields.json")),
            "B_fields_bytes_equal_run1_run2": (
                fields_bytes_minus_outputs(WORK / "B" / "run1" / t / "case2" / "fields.json")
                == fields_bytes_minus_outputs(WORK / "B" / "run2" / t / "case2" / "fields.json")),
            "A_docx_sig_equal_run1_run2": pa == pa2,
            "B_docx_sig_equal_run1_run2": pb == pb2,
            "md5_docx": {"A_run1": pa["md5_docx_bytes"], "A_run2": pa2["md5_docx_bytes"],
                         "B_run1": pb["md5_docx_bytes"], "B_run2": pb2["md5_docx_bytes"]},
        }

        # ---- 5) 基线可复现旁证（fresh vs 预置产物）----
        stored_oracle = ASSET / "oracle" / "out" / t / "case2" / "fields.json"
        stored_package = ASSET / "package" / "out" / t / "case2" / "fields.json"
        rep["baseline"] = {
            "freshB_vs_stored_oracle_fields_equal": (
                fields_bytes_minus_outputs(WORK / "B" / "run1" / t / "case2" / "fields.json")
                == fields_bytes_minus_outputs(stored_oracle)),
            "freshA_vs_stored_package_fields_equal": (
                fields_bytes_minus_outputs(WORK / "A" / "run1" / t / "case2" / "fields.json")
                == fields_bytes_minus_outputs(stored_package)),
        }

        report[t] = rep

    out_path = WORK / "ab3_compare_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 人读摘要 ----
    for t in TEMPLATES:
        r = report[t]
        print(f"\n===== {t} =====")
        print("fields 顶层键相等:", r["fields_top_keys_equal"],
              "| 剔除outputs字节相等:", r["fields_bytes_equal_minus_outputs"],
              "| 深比较diffs:", r["fields_diffs_minus_outputs"] or "无")
        print("spec §10 一致率:", r["agreement_spec10"])
        print("docx 段落数 A/B:", r["para_count"], "| 页面相等:", r["page_equal"],
              "| 全签名相等:", r["docx_sig_identical"])
        print("A 正文：")
        for ln in r["A_lines"]:
            print("  ", ln)
        print("B 正文：")
        for ln in r["B_lines"]:
            print("  ", ln)
        for key in ("rubric_r1_placeholder_entry", "rubric_r2_string_singularization",
                    "rubric_r3_optional_omission", "rubric_r4_spec9_accounting",
                    "rubric_r5_numbering_signature"):
            if key in r:
                print(f"{key}:", json.dumps(r[key], ensure_ascii=False))
        print("placeholder_count:", r["placeholder_count"])
        print("determinism:", json.dumps(r["determinism"], ensure_ascii=False))
        print("baseline:", r["baseline"])
    print("\nreport ->", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
