#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""oracle.py — 会议纪要生成参照实现（oracle，确定性关键词规则）

输入：会议转写 txt，每行一条发言，格式 `[hh:mm] 说话人: 内容`。
     不匹配该格式的行（寒暄、口误、空行等噪声）直接跳过。

抽取规则（逐行扫描；一行至多归入一类；优先级 决议 > 待办 > 风险）：
  决议事项   : 决定 / 议定 / 同意 / 结论
  待办事项   : 需要 / 负责 / 跟进 / 截止
  风险与关注 : 风险 / 延期 / 不确定

待办事项附加启发式（均确定性）：
  负责人 = 依次尝试 ①"我(们)负责"→说话人 ②"由/让/交给X负责" ③"负责人是/：X"
          ④"@X"；提取到"我/我们/自己"替换为说话人；都抓不到填"待定"。
  期限   = 依次尝试 日期/月日/星期(含本周/下周X/周五前)/本周末/今天明天/
          "截止到X"等模式；都抓不到填"待定"。

用法：python oracle.py --input <转写.txt> --outdir <输出目录>
产物：<outdir>/纪要.docx（标题 + 一、决议事项；二、待办事项[表格]；三、风险与关注）
     <outdir>/summary.json（各节条数 + 合计）
"""

import argparse
import json
import os
import sys

LINE_RE = r"^\s*\[(\d{1,2}:\d{2})\]\s*([^：:]+?)\s*[：:]\s*(.+?)\s*$"

RULES = [
    ("决议事项", ("决定", "议定", "同意", "结论")),
    ("待办事项", ("需要", "负责", "跟进", "截止")),
    ("风险与关注", ("风险", "延期", "不确定")),
]

SELF_OWNER_RE = r"我(?:们)?\s*负责"
BY_OWNER_RE = r"(?:由|让|交给)\s*([\u4e00-\u9fa5A-Za-z0-9·]{1,6}?)\s*负责"
HEAD_OWNER_RE = (r"负责人\s*[是：:]\s*([\u4e00-\u9fa5A-Za-z0-9·]{1,6}?)"
                 r"(?=[，,。；;！？\s]|$)")
AT_OWNER_RE = r"@([\u4e00-\u9fa5A-Za-z0-9·]{1,10})(?=[，,。；;！？\s]|$)"

DEADLINE_RES = [
    r"(\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*日?)",
    r"(\d{1,2}月\d{1,2}日(?:之?前)?)",
    r"((?:本周|下周|这周)?(?:周|星期)[一二三四五六日天](?:之?前|以前|底)?)",
    r"(本(?:周|月|季度)(?:底|末|内)?)",
    r"(今天|明天|后天|月底前?|下月|本周末)",
    r"截止(?:于|到|至)?\s*([^，。；;\s]{1,8})",
]


def _search(pattern, text):
    import re
    return re.search(pattern, text)


def extract_owner(content, speaker):
    """从待办条目内容中提取负责人；失败返回 待定。"""
    if _search(SELF_OWNER_RE, content):
        return speaker
    for pat in (BY_OWNER_RE, HEAD_OWNER_RE, AT_OWNER_RE):
        m = _search(pat, content)
        if m:
            name = m.group(1).strip()
            if name in ("我", "我们", "自己"):
                return speaker
            return name
    return "待定"


def extract_deadline(content):
    """从待办条目内容中提取期限；失败返回 待定。"""
    for pat in DEADLINE_RES:
        m = _search(pat, content)
        if m:
            return m.group(1).strip()
    return "待定"


def parse_transcript(path):
    """解析转写文件，按关键词规则归类。

    返回 (entries, skipped_lines, total_lines)。
    entries 每项: {"time", "speaker", "content", "category"}
    """
    import re
    line_re = re.compile(LINE_RE)
    with open(path, "r", encoding="utf-8-sig") as f:
        raw_lines = f.read().splitlines()

    entries = []
    skipped = 0
    for line in raw_lines:
        if not line.strip():
            continue
        m = line_re.match(line)
        if not m:
            skipped += 1
            continue
        time_s, speaker, content = m.group(1), m.group(2), m.group(3)
        category = None
        for name, keywords in RULES:
            if any(k in content for k in keywords):
                category = name
                break
        if category is None:
            continue
        entries.append({
            "time": time_s,
            "speaker": speaker,
            "content": content,
            "category": category,
        })
    return entries, skipped, len(raw_lines)


def build_docx(entries, src_name, out_path):
    """生成 纪要.docx：标题 + 三节（决议/待办表格/风险）。"""
    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.font.size = Pt(11)

    def cn(run, size=11, bold=False):
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        run.font.size = Pt(size)
        run.bold = bold
        return run

    by_cat = {name: [e for e in entries if e["category"] == name]
              for name, _ in RULES}

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cn(title.add_run("会议纪要"), size=18, bold=True)

    meta = doc.add_paragraph()
    cn(meta.add_run(
        "来源：%s ｜ 解析发言 %d 条（决议 %d · 待办 %d · 风险 %d）"
        % (src_name, len(entries),
           len(by_cat["决议事项"]), len(by_cat["待办事项"]),
           len(by_cat["风险与关注"]))
    ), size=9)

    # 一、决议事项
    h1 = doc.add_paragraph()
    cn(h1.add_run("一、决议事项"), size=14, bold=True)
    for i, e in enumerate(by_cat["决议事项"], 1):
        p = doc.add_paragraph()
        cn(p.add_run("%d. 【%s · %s】%s" % (i, e["time"], e["speaker"], e["content"])))

    # 二、待办事项（表格：事项 / 负责人 / 期限）
    h2 = doc.add_paragraph()
    cn(h2.add_run("二、待办事项"), size=14, bold=True)
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    for cell, text in zip(table.rows[0].cells, ("事项", "负责人", "期限")):
        cn(cell.paragraphs[0].add_run(text), bold=True)
    for e in by_cat["待办事项"]:
        row = table.add_row().cells
        for cell, text in zip(row, (
                e["content"],
                extract_owner(e["content"], e["speaker"]),
                extract_deadline(e["content"]))):
            cn(cell.paragraphs[0].add_run(text))

    # 三、风险与关注
    h3 = doc.add_paragraph()
    cn(h3.add_run("三、风险与关注"), size=14, bold=True)
    for i, e in enumerate(by_cat["风险与关注"], 1):
        p = doc.add_paragraph()
        cn(p.add_run("%d. 【%s · %s】%s" % (i, e["time"], e["speaker"], e["content"])))

    doc.save(out_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="会议纪要参照实现（关键词规则 oracle）")
    ap.add_argument("--input", required=True, help="会议转写 txt（[hh:mm] 说话人: 内容）")
    ap.add_argument("--outdir", required=True, help="输出目录")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.input):
        print("输入文件不存在: %s" % args.input, file=sys.stderr)
        return 2
    os.makedirs(args.outdir, exist_ok=True)

    entries, skipped, total = parse_transcript(args.input)

    docx_path = os.path.join(args.outdir, "纪要.docx")
    build_docx(entries, os.path.basename(args.input), docx_path)

    counts = {name: sum(1 for e in entries if e["category"] == name)
              for name, _ in RULES}
    summary = dict(counts)
    summary["合计"] = len(entries)
    json_path = os.path.join(args.outdir, "summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("输入: %s（共 %d 行，噪声/空行跳过 %d）" % (args.input, total, skipped))
    print("抽取: 决议 %d 条 · 待办 %d 条 · 风险 %d 条"
          % (counts["决议事项"], counts["待办事项"], counts["风险与关注"]))
    print("产物: %s" % docx_path)
    print("产物: %s" % json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
