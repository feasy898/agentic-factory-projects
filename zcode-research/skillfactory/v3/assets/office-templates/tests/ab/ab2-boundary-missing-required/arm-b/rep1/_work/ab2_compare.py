#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab2_compare.py — AB2 必填缺失边界对照工具。

对指定模板/case 的 A（被测 gen_doc.py）与 B（参照 oracle.py）产物做：
  1) fields.json 深度 diff（忽略 outputs 自引用路径）+ S1/S2/S3 规范自检；
  2) docx 段落级语义 dump（序号/文本/对齐/首行缩进chars/右缩进/字体/字号）；
  3) `____` 占位出现位置清点；
  4) 「编造检测」：docx 全文中出现的每个非空文本行，必须属于
     (a) 输入数据中的某个 strip 后值 / 列表项，或 (b) 模板固定公式串（白名单），
     否则列为 FABRICATED-SUSPECT。
用法：python ab2_compare.py <A_dir> <B_dir> <data_json> <模板>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PLACEHOLDER = "____"


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


# ---------- fields.json ----------

def strip_outputs(meta: dict) -> dict:
    m = json.loads(json.dumps(meta, ensure_ascii=False))
    m.pop("outputs", None)
    return m


def deep_diff(a, b, path="$"):
    diffs = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                diffs.append(f"{path}.{k}: 仅在B={b[k]!r}")
            elif k not in b:
                diffs.append(f"{path}.{k}: 仅在A={a[k]!r}")
            else:
                diffs += deep_diff(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path}: len A={len(a)} B={len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diffs += deep_diff(x, y, f"{path}[{i}]")
    else:
        if a != b:
            diffs.append(f"{path}: A={a!r} != B={b!r}")
    return diffs


def check_schema(meta: dict, side: str) -> list:
    errs = []
    top = {"template", "title", "filled_fields", "missing_fields", "fields", "summary", "outputs"}
    if set(meta) != top:
        errs.append(f"{side} 顶层键≠S1: {sorted(set(meta) ^ top)}")
    s = meta["summary"]
    if set(s) != {"total", "filled", "missing", "missing_required", "missing_required_names", "unknown_keys"}:
        errs.append(f"{side} summary 键≠S3: {sorted(set(s))}")
    for d in meta["fields"]:
        base = {"name", "required", "kind", "status", "value"}
        if d["status"] == "filled":
            if set(d) != base or d["value"] is None:
                errs.append(f"{side} filled 项不规范: {d}")
        else:
            if set(d) != base | {"rendered_as"} or d["value"] is not None:
                errs.append(f"{side} missing 项不规范: {d}")
    names = [d["name"] for d in meta["fields"]]
    if len(names) != len(set(names)):
        errs.append(f"{side} fields 重名")
    filled = [d["name"] for d in meta["fields"] if d["status"] == "filled"]
    missing = [d["name"] for d in meta["fields"] if d["status"] == "missing"]
    if filled != meta["filled_fields"] or missing != meta["missing_fields"]:
        errs.append(f"{side} 清单与明细不一致")
    if s["total"] != len(names) or s["filled"] != len(filled) or s["missing"] != len(missing):
        errs.append(f"{side} summary 计数不自洽")
    mreq = [d["name"] for d in meta["fields"] if d["status"] == "missing" and d["required"]]
    if s["missing_required"] != len(mreq) or s["missing_required_names"] != mreq:
        errs.append(f"{side} missing_required 不自洽: {s} vs {mreq}")
    return errs


# ---------- docx ----------

def para_sig(p):
    ppr = p._p.pPr
    flc = 0
    right = None
    if ppr is not None:
        ind = ppr.find(qn("w:ind"))
        if ind is not None:
            v = ind.get(qn("w:firstLineChars"))
            flc = int(v) if v else 0
            rv = ind.get(qn("w:right"))
            right = rv
    align = p.alignment.name if p.alignment is not None else "None"
    runs = []
    for r in p.runs:
        rf = r._element.find(qn("w:rPr"))
        east = None
        if rf is not None:
            rfonts = rf.find(qn("w:rFonts"))
            if rfonts is not None:
                east = rfonts.get(qn("w:eastAsia"))
        sz = r.font.size.pt if r.font.size else None
        runs.append((r.text, east, sz, bool(r.font.bold)))
    ls = p.paragraph_format.line_spacing
    ls = ls.pt if ls is not None else None
    return {"text": p.text, "align": align, "firstLineChars": flc, "right_ind": right,
            "line_spacing_pt": ls, "runs": runs}


def dump_docx(path: Path) -> list:
    doc = Document(str(path))
    return [para_sig(p) for p in doc.paragraphs]


def main():
    a_dir, b_dir, data_path, tpl = (Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
    data = load_json(data_path)
    input_values = set()
    for v in data.values():
        if isinstance(v, list):
            input_values |= {str(x).strip() for x in v if str(x).strip()}
        else:
            s = str(v).strip()
            if s:
                input_values.add(s)

    print("=" * 90)
    print(f"# 模板 {tpl}")
    for side, d in (("A", a_dir), ("B", b_dir)):
        meta = load_json(d / "fields.json")
        errs = check_schema(meta, side)
        print(f"\n[{side}] fields.json: template={meta['template']} title={meta['title']!r}")
        print(f"    filled_fields={meta['filled_fields']}")
        print(f"    missing_fields={meta['missing_fields']}")
        print(f"    summary={json.dumps(meta['summary'], ensure_ascii=False)}")
        for x in meta["fields"]:
            print(f"    - {x['name']}(req={x['required']},{x['kind']},{x['status']})"
                  f" value={json.dumps(x['value'], ensure_ascii=False)}"
                  + (f" rendered_as={x['rendered_as']}" if "rendered_as" in x else ""))
        print(f"    S1/S2/S3 自检: {'PASS' if not errs else errs}")

    ma, mb = load_json(a_dir / "fields.json"), load_json(b_dir / "fields.json")
    diffs = deep_diff(strip_outputs(ma), strip_outputs(mb))
    print(f"\n[DIFF fields.json A vs B（忽略 outputs）] {'共 ' + str(len(diffs)) + ' 处' if diffs else '完全一致（0 差异）'}")
    for d in diffs:
        print("   ", d)

    for side, d in (("A", a_dir), ("B", b_dir)):
        sigs = dump_docx(d / "文书.docx")
        nonempty = [s for s in sigs if s["text"].strip()]
        print(f"\n[{side}] 文书.docx 段落（共 {len(sigs)} 段，非空 {len(nonempty)}）:")
        for i, s in enumerate(sigs, 1):
            mark = "  " if s["text"].strip() else "空"
            print(f"  {i:02d}{mark}| align={s['align']:<6} flc={s['firstLineChars']:<3} "
                  f"ls={s['line_spacing_pt']} ri={s['right_ind']} | {s['text']!r}")
        ph = [(i, s["text"]) for i, s in enumerate(sigs, 1) if PLACEHOLDER in s["text"]]
        n = sum(t.count(PLACEHOLDER) for _, t in ph)
        print(f"  [{side}] ____ 占位: {n} 处，位于段落 {[i for i, _ in ph]}")
        # 编造检测：每个非空段文本须可由 输入值∪固定公式 解释
        fixed = {  # 两实现共用的模板固定文案（含各自版本）
            "现就有关事项请示如下：", "妥否，请批示。", "特此通知。",
        }
        susp = []
        for i, s in enumerate(sigs, 1):
            t = s["text"]
            if not t.strip():
                continue
            parts = [t] + [pp for pp in t.replace("：", "\n").replace("．", "\n").split("\n") if pp.strip()]
            for seg in (t,):
                core = seg
                for token in ([PLACEHOLDER] + sorted(input_values, key=len, reverse=True) + list(fixed)):
                    core = core.replace(token, "§")
                # 剩余内容只允许标签词/编号/标点/数字
                residue = core.replace("§", "")
                labels = ["联系人", "联系电话", "会议时间", "会议地点", "参会人员", "会议议题",
                          "会议要求", "关于", "召开", "的通知", "的请示", "一", "二", "三", "四",
                          "五", "六", "七", "八", "九", "十", "工作周报", "工作总结", "填报人",
                          "周期", "部门", "报送日期", "经研究", "决定", "现将有关事项通知如下",
                          "年", "月", "日", "周五"]
                for lab in labels:
                    residue = residue.replace(lab, "")
                allowed = set("：、．　 ，。；：0123456789()（）:-")
                residue = "".join(ch for ch in residue if ch not in allowed)
                if residue:
                    susp.append((i, t, residue))
        if susp:
            print(f"  [{side}] 编造检测（剩余无法解释残差）:")
            for i, t, r in susp:
                print(f"     段{i} {t!r} 残差={r!r}")
        else:
            print(f"  [{side}] 编造检测: PASS（全文文本均可由输入值+模板固定公式解释，无凭空内容）")

    print("=" * 90)


if __name__ == "__main__":
    main()
