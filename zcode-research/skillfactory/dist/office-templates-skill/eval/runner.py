#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""eval/runner.py — 中文办公模板技能（office-templates）确定性评测 runner

用法：
  python eval/runner.py <被测产物根> <参照产物根>
  python eval/runner.py package/out oracle/out     # 常规评测
  python eval/runner.py oracle/out oracle/out      # 自校验（应全过、exit 0）
  python eval/runner.py <空目录> oracle/out        # 红检（应报失败、exit 1）
  python eval/runner.py                            # 无参数 = 写死默认 oracle/out oracle/out

产物单元定义：目录恰含 文书.docx 与 fields.json 两个文件；单元相对名 = <模板>/case<N>，
期望恰 8 个（周报/请示函/会议通知/工作总结 × case1/case2），与参照按相对名一一配对。

检查项（checks 数组，元素 {name, pass, detail}；单元级检查名前缀为单元相对名）：
  1. units_found / products_exact / reference_dir_has_units
                             8 个期望单元齐全，每单元恰含两个产物文件
  2. docx_opens_safe         docx 各 XML 条目无 <!DOCTYPE/<!ENTITY（spec §11，防 XXE），
                             且 python-docx 可打开
  3. layout_title_centered / layout_salutation_flush_left / layout_body_indent /
     layout_signature_right  版式要素（spec §4 V2/V3/V4/V5，程序可判）
  4. fields_json_self_consistent   spec §6 S1–S3：键集合、明细结构与计数自洽
  5. fields_match_docx       fields.json 与 docx 实际内容一致（title 相等、filled 值在文中、
                             必填缺失处有 ____）；boundary_reported：缺失记账与占位/留空语义（F1/F2/F4）
  6. field_fill_agreement_ge_90pct  与参照按 spec §10 口径的字段填充一致率 ≥90%

输出：单个 JSON {"ok","tested","reference","checks":[...]}；全部通过 exit 0，任一失败 exit 1。
确定性：本脚本无时间/随机源，同一输入两次运行输出一致；不 import oracle，按 spec 独立实现。
安全：解析候选 docx 前先扫描 zip 内 XML 条目、拒绝 DOCTYPE/ENTITY、不启用外部实体（spec §11）。
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ASSET_ROOT = Path(__file__).resolve().parent.parent          # .../office-templates
DEFAULT_ROOT = ASSET_ROOT / "oracle" / "out"                 # 写死默认（contract §5）

DOCX_NAME = "文书.docx"
FIELDS_NAME = "fields.json"
TEMPLATES = ("周报", "请示函", "会议通知", "工作总结")
CASES = ("case1", "case2")
EXPECTED_UNITS = ["%s/%s" % (t, c) for t in TEMPLATES for c in CASES]
SALUTATION_TEMPLATES = {"请示函", "会议通知"}     # spec V3：仅这两类有称谓段
PLACEHOLDER = "____"

# spec §3.3 字段表：template -> [(name, required, kind), ...]（顺序冻结）
FIELDS_SPEC = {
    "周报": [("部门", True, "text"), ("填报人", True, "text"), ("周期", True, "text"),
             ("本周工作内容", True, "list"), ("下周工作计划", True, "list"),
             ("问题与需协调事项", False, "list"), ("报送日期", False, "text")],
    "请示函": [("请示事由", True, "text"), ("主送机关", True, "text"), ("请示缘由", True, "text"),
               ("请示事项", True, "text"), ("请示单位", True, "text"),
               ("联系人", False, "text"), ("联系电话", False, "text"), ("成文日期", False, "text")],
    "会议通知": [("会议名称", True, "text"), ("召开单位", True, "text"), ("主送对象", True, "text"),
                 ("会议时间", True, "text"), ("会议地点", True, "text"), ("参会人员", True, "text"),
                 ("会议议题", False, "text"), ("会议要求", False, "list"),
                 ("联系人", False, "text"), ("联系电话", False, "text"), ("发文日期", False, "text")],
    "工作总结": [("总结主体", True, "text"), ("总结时段", True, "text"), ("工作回顾", True, "list"),
                 ("主要成绩", True, "list"), ("存在问题", False, "list"),
                 ("下一步工作打算", True, "list"), ("成文日期", False, "text")],
}

TOP_KEYS = {"template", "title", "filled_fields", "missing_fields", "fields", "summary", "outputs"}
SUMMARY_KEYS = {"total", "filled", "missing", "missing_required",
                "missing_required_names", "unknown_keys"}
DETAIL_KEYS_MIN = {"name", "required", "kind", "status", "value"}

AGREE_MIN = 0.90            # spec §10 字段填充一致率下限
INDENT_PT_TOL = 2.0         # 落款右缩进 32pt 的容差
SPACING_TOL_EMU = 635       # 行距 28pt 的容差（0.05pt）
TITLE_SIZE_PT, BODY_SIZE_PT, LINE_SPACING_PT = 22.0, 16.0, 28.0
TITLE_FONT, BODY_FONT, ASCII_FONT = "黑体", "仿宋", "Times New Roman"


# ---------------------------------------------------------------- 工具

def first_line_chars(p) -> str:
    """读 w:ind/@w:firstLineChars；无 w:ind 或无属性返回 ""。"""
    ppr = p._p.pPr
    if ppr is None:
        return ""
    ind = ppr.find(qn("w:ind"))
    if ind is None:
        return ""
    return ind.get(qn("w:firstLineChars")) or ""


def run_fonts(p):
    """返回首 run 的 (eastAsia, ascii, size_pt)。无 run 返回 ("", "", None)。"""
    if not p.runs:
        return "", "", None
    r = p.runs[0]
    east = ascii_ = ""
    rpr = r._element.rPr
    if rpr is not None and rpr.rFonts is not None:
        east = rpr.rFonts.get(qn("w:eastAsia")) or ""
        ascii_ = rpr.rFonts.get(qn("w:ascii")) or ""
    size = float(r.font.size.pt) if r.font.size is not None else None
    return east, ascii_, size


def spacing_emu(p):
    """固定行距（EMU）；若为倍数行距（float）返回 None。"""
    ls = p.paragraph_format.line_spacing
    if isinstance(ls, int):          # docx Length 是 int 子类；倍数行距为 float
        return int(ls)
    return None


def xml_entries_safe(docx_path: Path):
    """spec §11：扫描 docx 内全部 .xml/.rels 条目，拒绝 DOCTYPE/ENTITY（不启用外部实体）。
    返回 (ok, 说明)。"""
    try:
        with zipfile.ZipFile(docx_path) as zf:
            for name in zf.namelist():
                if not (name.endswith(".xml") or name.endswith(".rels")):
                    continue
                data = zf.read(name)
                upper = data.upper()
                if b"<!DOCTYPE" in upper:
                    return False, "%s 含 <!DOCTYPE 声明（拒绝解析）" % name
                if b"<!ENTITY" in upper:
                    return False, "%s 含 <!ENTITY 实体声明（拒绝解析）" % name
    except zipfile.BadZipFile as e:
        return False, "不是合法 zip/docx: %s" % e
    except Exception as e:  # noqa: BLE001 — 任何读取异常都按不安全处理
        return False, "扫描失败: %s" % e
    return True, "全部 XML 条目无 DOCTYPE/ENTITY"


def load_docx(docx_path: Path):
    """安全打开 docx：先 DOCTYPE/ENTITY 扫描，再 python-docx 解析。失败抛异常。"""
    ok, why = xml_entries_safe(docx_path)
    if not ok:
        raise ValueError(why)
    return Document(str(docx_path))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def find_units(root: Path):
    """返回 ({相对名: 目录}, [多余产物单元相对名])。单元 = 恰含两个产物文件的目录。"""
    units, extras = {}, []

    def is_unit(d: Path) -> bool:
        return d.is_dir() and (d / DOCX_NAME).is_file() and (d / FIELDS_NAME).is_file()

    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            for sub in sorted(child.iterdir()):
                if is_unit(sub):
                    rel = "%s/%s" % (child.name, sub.name)
                    if rel in EXPECTED_UNITS:
                        units[rel] = sub
                    else:
                        extras.append(rel)
    return units, extras


def load_unit(unit_dir: Path):
    """返回 (meta, meta_err, doc, doc_err)；加载失败时对应项为 (None, 错误说明)。"""
    meta = meta_err = doc = doc_err = None
    try:
        meta = read_json(unit_dir / FIELDS_NAME)
        if not isinstance(meta, dict):
            meta, meta_err = None, "fields.json 顶层不是 JSON 对象"
    except Exception as e:  # noqa: BLE001
        meta, meta_err = None, str(e)
    try:
        doc = load_docx(unit_dir / DOCX_NAME)
    except Exception as e:  # noqa: BLE001
        doc, doc_err = None, str(e)
    return meta, meta_err, doc, doc_err


# ---------------------------------------------------------------- 单元评测

def check_unit(rel: str, meta, doc, checks) -> None:
    """单元级检查 3–5（docx_opens_safe 由 main 恒记录）。meta/doc 失败时相关检查记失败。"""
    def add(name, ok, detail):
        checks.append({"name": "%s/%s" % (rel, name), "pass": bool(ok), "detail": detail})

    template = (meta or {}).get("template")

    if doc is None:
        for n in ("layout_title_centered", "layout_salutation_flush_left",
                  "layout_body_indent", "layout_signature_right",
                  "fields_match_docx", "boundary_reported"):
            add(n, False, "docx 无法安全打开/解析，无法核对版式与内容")
    else:
        paras = doc.paragraphs
        nonempty = [p for p in paras if p.text.strip()]

        # 3a) 标题居中（V2）：首个非空段居中、黑体 22pt、文本 == fields.json.title
        if not nonempty:
            add("layout_title_centered", False, "文书无任何非空段落")
        else:
            t = nonempty[0]
            east, _ascii, size = run_fonts(t)
            ok = (t.alignment == WD_ALIGN_PARAGRAPH.CENTER
                  and east == TITLE_FONT
                  and size is not None and abs(size - TITLE_SIZE_PT) < 0.01
                  and meta is not None and t.text == meta.get("title"))
            add("layout_title_centered", ok,
                "标题=%r 居中=%s eastAsia=%s 字号=%spt（要求居中/黑体/22pt/与 title 一致）"
                % (t.text, t.alignment == WD_ALIGN_PARAGRAPH.CENTER, east or "无", size))

        # 3b) 称谓顶格（V3）：仅请示函/会议通知；第二个非空段无首行缩进、以全角冒号收尾
        if template not in SALUTATION_TEMPLATES:
            add("layout_salutation_flush_left", True, "该模板无称谓段（spec V3），跳过")
        elif len(nonempty) < 2:
            add("layout_salutation_flush_left", False, "段落不足，缺称谓段")
        else:
            s = nonempty[1]
            flc = first_line_chars(s)
            ok = flc in ("", "0") and s.text.rstrip().endswith("：")
            add("layout_salutation_flush_left", ok,
                "称谓=%r firstLineChars=%s（要求顶格且以「：」收尾）" % (s.text, flc or "无"))

        # 3c) 正文首行缩进两字符（V4）：存在 firstLineChars=200 的段，且其中有仿宋/TNR/16pt/28 磅段
        indented = [p for p in nonempty[1:] if first_line_chars(p) == "200"]
        body_ok = False
        for p in indented:
            east, ascii_, size = run_fonts(p)
            ls = spacing_emu(p)
            if (east == BODY_FONT and ascii_ == ASCII_FONT
                    and size is not None and abs(size - BODY_SIZE_PT) < 0.01
                    and ls is not None
                    and abs(ls - int(Pt(LINE_SPACING_PT))) <= SPACING_TOL_EMU):
                body_ok = True
                break
        add("layout_body_indent", bool(indented) and body_ok,
            "firstLineChars=200 段落数=%d，其中仿宋/Times New Roman/16pt/28磅固定行距段=%s"
            % (len(indented), "有" if body_ok else "无"))

        # 3d) 落款右对齐（V5）：末个非空段右对齐 + 右缩进约两字（32pt）
        if not nonempty:
            add("layout_signature_right", False, "文书无任何非空段落，无落款")
        else:
            last = nonempty[-1]
            ri = last.paragraph_format.right_indent
            ri_pt = float(ri.pt) if ri is not None else None
            ok = (last.alignment == WD_ALIGN_PARAGRAPH.RIGHT
                  and ri_pt is not None and abs(ri_pt - 32.0) <= INDENT_PT_TOL)
            add("layout_signature_right", ok,
                "落款=%r 右对齐=%s 右缩进=%spt（要求右对齐、右空两字≈32pt）"
                % (last.text, last.alignment == WD_ALIGN_PARAGRAPH.RIGHT, ri_pt))

    if meta is None:
        for n in ("fields_json_self_consistent", "fields_match_docx", "boundary_reported"):
            if not any(c["name"] == "%s/%s" % (rel, n) for c in checks):
                add(n, False, "fields.json 缺失或不可解析，无法核对")
        return

    # 4) fields.json 自洽（S1–S3）
    problems = []
    if set(meta.keys()) != TOP_KEYS:
        problems.append("顶层键集合不符: 多 %s 缺 %s"
                        % (sorted(set(meta.keys()) - TOP_KEYS),
                           sorted(TOP_KEYS - set(meta.keys()))))
    if template not in FIELDS_SPEC:
        problems.append("template 非法: %r" % (template,))
    else:
        spec = FIELDS_SPEC[template]
        details = meta.get("fields")
        if not isinstance(details, list) or len(details) != len(spec):
            problems.append("fields 长度 %s != 期望 %d"
                            % (len(details) if isinstance(details, list)
                               else type(details).__name__, len(spec)))
            details = details if isinstance(details, list) else []
        for idx, item in enumerate(details):
            want = spec[idx] if idx < len(spec) else None
            if not isinstance(item, dict) or not DETAIL_KEYS_MIN <= set(item.keys()):
                problems.append("第 %d 项明细结构不全（需含 %s）"
                                % (idx, sorted(DETAIL_KEYS_MIN)))
                continue
            if want is not None:
                name, req, kind = want
                if item.get("name") != name or bool(item.get("required")) != req \
                        or item.get("kind") != kind:
                    problems.append("第 %d 项 %r 与字段表不符（期望 %s/required=%s/%s）"
                                    % (idx, item.get("name"), name, req, kind))
            name = item.get("name")
            if item.get("status") not in ("filled", "missing"):
                problems.append("字段 %r status 非法: %r" % (name, item.get("status")))
            elif item["status"] == "filled" and item.get("value") is None:
                problems.append("字段 %r status=filled 但 value 为 null" % name)
            elif item["status"] == "missing":
                if item.get("value") is not None:
                    problems.append("字段 %r status=missing 但 value 非 null" % name)
                if not str(item.get("rendered_as") or "").strip():
                    problems.append("字段 %r 缺 rendered_as" % name)
        names = [i.get("name") for i in details if isinstance(i, dict)]
        if len(names) != len(set(names)):
            problems.append("fields 存在重复字段名")
        filled = [i["name"] for i in details
                  if isinstance(i, dict) and i.get("status") == "filled"]
        missing = [i["name"] for i in details
                   if isinstance(i, dict) and i.get("status") == "missing"]
        if sorted(filled) != sorted(meta.get("filled_fields") or []) or \
                sorted(missing) != sorted(meta.get("missing_fields") or []):
            problems.append("filled/missing 清单与明细不一致")
        s = meta.get("summary")
        if not isinstance(s, dict) or set(s.keys()) != SUMMARY_KEYS:
            problems.append("summary 键集合不符: %s"
                            % (sorted(s.keys()) if isinstance(s, dict) else type(s).__name__))
        else:
            if s.get("total") != len(details) or s.get("filled") != len(filled) \
                    or s.get("missing") != len(missing) \
                    or s.get("filled", 0) + s.get("missing", 0) != s.get("total"):
                problems.append("summary 计数不自洽: %r" % s)
            mr = [i["name"] for i in details
                  if isinstance(i, dict) and i.get("status") == "missing" and i.get("required")]
            if sorted(s.get("missing_required_names") or []) != sorted(mr) \
                    or s.get("missing_required") != len(mr):
                problems.append("missing_required_names/计数与明细不一致")
            uk = s.get("unknown_keys")
            if not isinstance(uk, list) or not all(isinstance(k, str) for k in uk):
                problems.append("unknown_keys 必须为字符串数组")
    add("fields_json_self_consistent", not problems,
        ("S1–S3 全部自洽（%d 个字段与字段表一致）" % len(meta.get("fields") or []))
        if not problems else "；".join(problems[:6]))

    if doc is None:
        return

    # 5a) fields.json 与 docx 实际内容一致
    full_text = "\n".join(p.text for p in doc.paragraphs)
    lines = full_text.splitlines()
    problems = []
    if not lines or meta.get("title") != lines[0]:
        problems.append("title %r 与文书首段 %r 不相等"
                        % (meta.get("title"), lines[0] if lines else "<空>"))
    n_mr = len(meta.get("summary", {}).get("missing_required_names") or [])
    for item in meta.get("fields") or []:
        if item.get("status") != "filled":
            continue
        value = item.get("value")
        for v in (value if isinstance(value, list) else [value]):
            if not isinstance(v, str) or v not in full_text:
                problems.append("filled 字段 %r 的值 %r 未出现在文书文本" % (item.get("name"), v))
    if n_mr > 0 and full_text.count(PLACEHOLDER) < n_mr:
        problems.append("必填缺失 %d 个，但文中 %r 仅出现 %d 次（应≥%d）"
                        % (n_mr, PLACEHOLDER, full_text.count(PLACEHOLDER), n_mr))
    add("fields_match_docx", not problems,
        ("title 与全部 filled 值在文中；占位符 %d 处 ≥ 必填缺失 %d"
         % (full_text.count(PLACEHOLDER), n_mr)) if not problems
        else "；".join(problems[:6]))

    # 5b) 缺失记账与渲染语义（F1/F2/F4）
    problems = []
    mr_names = meta.get("summary", {}).get("missing_required_names") or []
    for item in meta.get("fields") or []:
        if item.get("status") != "missing":
            continue
        if not str(item.get("rendered_as") or "").strip():
            problems.append("missing 字段 %r 缺 rendered_as" % item.get("name"))
        if item.get("required") and item.get("name") not in mr_names:
            problems.append("必填缺失字段 %r 未记入 missing_required_names" % item.get("name"))
        if not item.get("required") and item.get("name") in mr_names:
            problems.append("选填缺失字段 %r 被误记入 missing_required_names" % item.get("name"))
    add("boundary_reported", not problems,
        ("缺失记账正确：必填缺失 %s 以____占位；选填缺失 %s 留空/省略"
         % (mr_names or "无",
            [i.get("name") for i in meta.get("fields") or []
             if i.get("status") == "missing" and not i.get("required")] or "无"))
        if not problems else "；".join(problems[:6]))


# ---------------------------------------------------------------- 主流程

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="office-templates 确定性评测 runner")
    ap.add_argument("tested", nargs="?", default=None,
                    help="被测产物根（默认写死: %s）" % DEFAULT_ROOT)
    ap.add_argument("reference", nargs="?", default=None,
                    help="参照产物根（默认写死: %s）" % DEFAULT_ROOT)
    args = ap.parse_args(argv)

    tested_root = Path(args.tested) if args.tested else DEFAULT_ROOT
    ref_root = Path(args.reference) if args.reference else DEFAULT_ROOT
    checks: list[dict] = []

    tested_units, tested_extra = find_units(tested_root)
    ref_units, _ref_extra = find_units(ref_root)

    # 1) 单元发现与产物文件集
    missing = [u for u in EXPECTED_UNITS if u not in tested_units]
    if missing or tested_extra:
        checks.append({
            "name": "units_found", "pass": False,
            "detail": "被测根 %s：缺单元 %s；多余产物单元 %s（期望恰 8 个）"
                      % (tested_root, missing or "无", tested_extra or "无")})
    else:
        checks.append({"name": "units_found", "pass": True,
                       "detail": "8 个期望单元齐全: %s" % ", ".join(EXPECTED_UNITS)})

    bad_files = []
    for rel in EXPECTED_UNITS:
        d = tested_root / rel
        if d.is_dir():
            names = set(p.name for p in d.iterdir())
            lack = sorted({DOCX_NAME, FIELDS_NAME} - names)
            extra = sorted(names - {DOCX_NAME, FIELDS_NAME})
            if lack or extra:
                bad_files.append("%s（缺 %s，多 %s）" % (rel, lack or "无", extra or "无"))
    checks.append({"name": "products_exact", "pass": not bad_files,
                   "detail": "每个单元目录恰含 文书.docx + fields.json" if not bad_files
                   else "单元产物文件集不合契约: %s" % "; ".join(bad_files)})

    checks.append({"name": "reference_dir_has_units", "pass": len(ref_units) == len(EXPECTED_UNITS),
                   "detail": "参照根 %s 含 %d/%d 个产物单元"
                             % (ref_root, len(ref_units), len(EXPECTED_UNITS))})

    # 2–5) 单元级检查
    for rel in EXPECTED_UNITS:
        d = tested_units.get(rel)
        if d is None:
            continue  # 缺单元已由 units_found 记失败
        meta, meta_err, doc, doc_err = load_unit(d)
        checks.append({"name": "%s/docx_opens_safe" % rel, "pass": doc is not None,
                       "detail": ("DOCTYPE/ENTITY 扫描通过且 python-docx 打开成功")
                       if doc is not None else "docx 无法安全打开: %s" % doc_err})
        if meta is None:
            checks.append({"name": "%s/fields_json_self_consistent" % rel, "pass": False,
                           "detail": "fields.json 不可解析: %s" % meta_err})
        check_unit(rel, meta, doc, checks)

    # 6) 与参照的字段填充一致率 ≥90%（spec §10）
    matched = total = 0
    mismatches = []
    for rel in EXPECTED_UNITS:
        if rel not in ref_units:
            continue
        try:
            ref_meta = read_json(ref_units[rel] / FIELDS_NAME)
        except Exception:  # noqa: BLE001
            continue
        ref_fields = ref_meta.get("fields") if isinstance(ref_meta, dict) else None
        if not isinstance(ref_fields, list):
            continue
        total += len(ref_fields)
        t_by_name = {}
        if rel in tested_units:
            try:
                t_meta = read_json(tested_units[rel] / FIELDS_NAME)
                if isinstance(t_meta, dict) and isinstance(t_meta.get("fields"), list):
                    t_by_name = {i["name"]: i for i in t_meta["fields"]
                                 if isinstance(i, dict) and "name" in i}
            except Exception:  # noqa: BLE001
                t_by_name = {}
        for rf in ref_fields:
            name = rf.get("name") if isinstance(rf, dict) else None
            tf = t_by_name.get(name)
            if (isinstance(tf, dict)
                    and rf.get("status") == tf.get("status")
                    and (rf.get("status") != "filled" or rf.get("value") == tf.get("value"))):
                matched += 1
            else:
                mismatches.append("%s/%s" % (rel, name))
    rate = (matched / total) if total else 0.0
    checks.append({"name": "field_fill_agreement_ge_90pct", "pass": total > 0 and rate >= AGREE_MIN,
                   "detail": "字段填充一致率 %.1f%%（%d/%d，阈值 %.0f%%）%s"
                             % (rate * 100, matched, total, AGREE_MIN * 100,
                                ("；不一致: " + "; ".join(mismatches[:10])
                                 + ("…" if len(mismatches) > 10 else "")) if mismatches else "")})

    ok = all(c["pass"] for c in checks)
    print(json.dumps({"ok": ok, "tested": str(tested_root), "reference": str(ref_root),
                      "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
