#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify.py —— 校验 oracle 产物的版式不变量与 fields.json 一致性。

对 out/<template>/caseN/ 下每份产物检查：
  1) 文书.docx 与 fields.json 存在且可解析；
  2) 标题段居中；
  3) 含称谓的模板（请示函/会议通知）称谓段顶格（无首行缩进）；
  4) 正文存在 w:firstLineChars=200（首行缩进两字符）的段落；
  5) 末个非空段落（落款）右对齐；
  6) fields.json 汇总自洽，且必填缺失数 >0 时文书文本含占位符 "____"。

用法：python verify.py [out 目录，默认脚本旁的 out/]
全部通过退出码 0，任一失败退出码 1 并打印 FAIL 行。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

PLACEHOLDER = "____"
SALUTATION_TEMPLATES = {"请示函", "会议通知"}


def first_line_chars(p) -> int:
    ppr = p._p.pPr
    if ppr is None or ppr.find(qn("w:ind")) is None:
        return 0
    ind = ppr.find(qn("w:ind"))
    raw = ind.get(qn("w:firstLineChars"))
    return int(raw) if raw else 0


def check_one(case_dir: Path) -> list:
    errors = []
    docx_path = case_dir / "文书.docx"
    json_path = case_dir / "fields.json"
    if not docx_path.is_file():
        return [f"{case_dir}: 缺少 文书.docx"]
    if not json_path.is_file():
        return [f"{case_dir}: 缺少 fields.json"]
    try:
        meta = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return [f"{case_dir}: fields.json 解析失败: {e}"]

    template = meta["template"]
    doc = Document(str(docx_path))
    paras = doc.paragraphs
    nonempty = [p for p in paras if p.text.strip()]

    # 1) 标题居中
    if not nonempty or nonempty[0].alignment != WD_ALIGN_PARAGRAPH.CENTER:
        errors.append(f"{case_dir}: 标题段未居中")
    if meta.get("title") not in (nonempty[0].text if nonempty else ""):
        errors.append(f"{case_dir}: 标题文本与 fields.json.title 不符: "
                      f"docx={nonempty[0].text!r} meta={meta.get('title')!r}")

    # 2) 称谓顶格（紧随标题的第一段）
    if template in SALUTATION_TEMPLATES:
        if len(nonempty) < 2:
            errors.append(f"{case_dir}: 段落不足，缺称谓")
        elif first_line_chars(nonempty[1]) != 0:
            errors.append(f"{case_dir}: 称谓段应有顶格（实际 firstLineChars="
                          f"{first_line_chars(nonempty[1])}）: {nonempty[1].text!r}")

    # 3) 正文首行缩进两字符
    if not any(first_line_chars(p) == 200 for p in nonempty[1:]):
        errors.append(f"{case_dir}: 未找到 firstLineChars=200 的正文段")

    # 4) 落款右对齐（末个非空段）
    if not nonempty or nonempty[-1].alignment != WD_ALIGN_PARAGRAPH.RIGHT:
        errors.append(f"{case_dir}: 末段（落款）未右对齐")

    # 5) fields.json 汇总自洽
    names = [f["name"] for f in meta["fields"]]
    if len(names) != len(set(names)):
        errors.append(f"{case_dir}: fields 存在重复字段名")
    filled = [f["name"] for f in meta["fields"] if f["status"] == "filled"]
    missing = [f["name"] for f in meta["fields"] if f["status"] == "missing"]
    s = meta["summary"]
    if sorted(filled) != sorted(meta["filled_fields"]) or sorted(missing) != sorted(meta["missing_fields"]):
        errors.append(f"{case_dir}: filled/missing 明细与清单不一致")
    if s["total"] != len(meta["fields"]) or s["filled"] != len(filled) or s["missing"] != len(missing):
        errors.append(f"{case_dir}: summary 计数不自洽: {s}")
    if sorted(s["missing_required_names"]) != sorted(
            f["name"] for f in meta["fields"] if f["status"] == "missing" and f["required"]):
        errors.append(f"{case_dir}: missing_required_names 与明细不一致")

    # 6) 必填缺失应出现占位符
    if s["missing_required"] > 0 and PLACEHOLDER not in "\n".join(p.text for p in paras):
        errors.append(f"{case_dir}: 有必填缺失但文书无占位符 {PLACEHOLDER!r}")

    return errors


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "out"
    case_dirs = sorted(d for d in root.glob("*/*") if d.is_dir())
    if not case_dirs:
        print(f"FAIL 未找到任何产物目录: {root}")
        return 1
    all_errors = []
    passed = 0
    for d in case_dirs:
        errors = check_one(d)
        if errors:
            all_errors.extend(errors)
        else:
            passed += 1
            print(f"PASS {d.relative_to(root.parent)}")
    for e in all_errors:
        print(f"FAIL {e}")
    print(f"\n共 {len(case_dirs)} 份产物: PASS={passed} FAIL={len(case_dirs) - passed}")
    return 0 if not all_errors else 1


if __name__ == "__main__":
    sys.exit(main())
