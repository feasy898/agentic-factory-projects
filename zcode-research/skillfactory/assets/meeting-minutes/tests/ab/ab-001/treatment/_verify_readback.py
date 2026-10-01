#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_verify_readback.py — ab-001 treatment 产物写后回读核验（docx-and-summary.md §3 + rubric 各维度）。

只读核验，不改任何产物；全部中间文件按任务要求留在本产物目录内。
"""
import io
import json
import os
import re
import sys

from docx import Document
from docx.shared import Pt

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
DOCX = os.path.join(HERE, "纪要.docx")
SUMMARY = os.path.join(HERE, "summary.json")
TRANSCRIPT = os.path.abspath(os.path.join(
    HERE, "..", "..", "..", "..", "oracle", "inputs", "case1.txt"))

SECTIONS = ("一、决议事项", "二、待办事项", "三、风险与关注")
LINE_RE = re.compile(r"^\s*\[(\d{1,2}:\d{2})\]\s*([^：:]+?)\s*[：:]\s*(.+?)\s*$")
ENTRY_RE = re.compile(r"^\s*\d+\.\s*【\s*([^·】]+?)\s*·\s*([^·】]+?)\s*】\s*(.*)$", re.S)

results = []


def check(name, ok, detail):
    results.append((name, bool(ok), detail))
    print("[%s] %s — %s" % ("PASS" if ok else "FAIL", name, detail))


# ---------- 1) docx 可被 python-docx 打开 ----------
doc = Document(DOCX)
check("docx_opens", True, "python-docx 打开成功: %s" % DOCX)

paras = doc.paragraphs
texts = [p.text for p in paras]

# ---------- 2) 三个节标题：文本精确 + 顺序正确 ----------
idx = [next(i for i, t in enumerate(texts) if t.strip() == h) for h in SECTIONS]
check("three_sections_exact_order", idx == sorted(idx) and len(idx) == 3,
      "节标题按序出现于段落 %s: %s" % (idx, " / ".join(SECTIONS)))

# ---------- 3) 标题与节标题版式（SKILL/docx-and-summary §1） ----------
title = paras[0]
title_run = title.runs[0]
check("title_format", title.text.strip() == "会议纪要"
      and title_run.bold and title_run.font.size == Pt(18)
      and str(title.alignment) .startswith("CENTER"),
      "标题=《%s》bold=%s size=%s align=%s"
      % (title.text.strip(), title_run.bold, title_run.font.size, title.alignment))
head_ok, head_detail = True, []
for i in idx:
    p = paras[i]
    r = p.runs[0]
    ok = r.bold and r.font.size == Pt(14)
    head_ok = head_ok and ok
    head_detail.append("%s:bold=%s,pt=%s" % (p.text.strip(), r.bold,
                                             r.font.size.pt if r.font.size else None))
check("section_heading_format", head_ok, "; ".join(head_detail))

# ---------- 4) 条目按节切分 ----------
def section_entries():
    secs = {h: [] for h in SECTIONS}
    cur = None
    for t in texts:
        s = t.strip()
        if s in secs:
            cur = s
            continue
        if cur and s:
            secs[cur].append(s)
    return secs

secs = section_entries()
entries = {}
for h in (SECTIONS[0], SECTIONS[2]):
    parsed = []
    for t in secs[h]:
        m = ENTRY_RE.match(t)
        parsed.append(m.groups() if m else None)
    entries[h] = parsed
check("entries_have_time_speaker_prefix",
      all(g is not None for g in entries[SECTIONS[0]] + entries[SECTIONS[2]]),
      "决议 %d 条、风险 %d 条均带【时间 · 说话人】前缀"
      % (len(entries[SECTIONS[0]]), len(entries[SECTIONS[2]])))

# ---------- 5) 条数精确：决议2/待办2/风险3 ----------
todo_table = next((t for t in doc.tables
                   if t.rows and [c.text.strip() for c in t.rows[0].cells][:3]
                   and set(("事项", "负责人", "期限"))
                   <= set(c.text.strip() for c in t.rows[0].cells)), None)
todo_rows = len(todo_table.rows) - 1 if todo_table else 0
check("counts_exact",
      len(entries[SECTIONS[0]]) == 2 and len(entries[SECTIONS[2]]) == 3
      and todo_rows == 2,
      "决议=%d(需2) 待办=%d(需2) 风险=%d(需3)"
      % (len(entries[SECTIONS[0]]), todo_rows, len(entries[SECTIONS[2]])))

# ---------- 6) 待办表格：3 列、表头精确、数据行 2 行 ----------
header = [c.text.strip() for c in todo_table.rows[0].cells] if todo_table else []
check("todo_table_header", todo_table is not None
      and len(todo_table.columns) == 3
      and header[0] == "事项" and header[1] == "负责人" and header[2] == "期限",
      "表头=%s 列数=%s 数据行=%d" % (header,
                                   len(todo_table.columns) if todo_table else 0,
                                   todo_rows))

# ---------- 7) summary.json 四键、与 docx 一致、合计=7 ----------
with open(SUMMARY, "r", encoding="utf-8") as f:
    raw = f.read()
summary = json.loads(raw)
keys_ok = list(summary.keys()) == ["决议事项", "待办事项", "风险与关注", "合计"]
actual = {"决议事项": len(entries[SECTIONS[0]]), "待办事项": todo_rows,
          "风险与关注": len(entries[SECTIONS[2]])}
match = all(summary[k] == actual[k] for k in actual)
sum_ok = summary["合计"] == sum(summary[k] for k in actual)
check("summary_json", keys_ok and match and sum_ok and summary["合计"] == 7,
      "keys=%s json=%s docx实际=%s 合计=%d(需7) 文件内容=%s"
      % (keys_ok, json.dumps(summary, ensure_ascii=False),
         json.dumps(actual, ensure_ascii=False), summary["合计"],
         raw.replace("\n", " ")))

# ---------- 8) 元信息行与 summary 数字一致 ----------
meta = texts[1]
n_total = len(entries[SECTIONS[0]]) + todo_rows + len(entries[SECTIONS[2]])
check("meta_line", meta == "来源：case1.txt ｜ 解析发言 %d 条（决议 %d · 待办 %d · 风险 %d）"
      % (n_total, summary["决议事项"], summary["待办事项"], summary["风险与关注"]),
      "元信息行=《%s》" % meta)

# ---------- 9) 溯源：每条目在 case1.txt 逐字找到出处（时间+说话人+内容） ----------
with open(TRANSCRIPT, "r", encoding="utf-8-sig") as f:
    lines = f.read().splitlines()
bad = []
for h in (SECTIONS[0], SECTIONS[2]):
    for (time_s, speaker, content), src in zip(entries[h], secs[h]):
        hit = next((ln for ln in lines if content in ln), None)
        if hit is None:
            bad.append("无出处:%s" % src[:40])
        elif ("[%s]" % time_s) not in hit or speaker not in hit:
            bad.append("时间/说话人不符:%s" % src[:40])
todo_contents = [r.cells[0].text.strip() for r in todo_table.rows[1:]]
for c in todo_contents:
    if not next((ln for ln in lines if c in ln), None):
        bad.append("待办无出处:%s" % c[:40])
check("provenance_verbatim", not bad,
      "决议%d+待办%d+风险%d 全部逐字溯源至 %s%s"
      % (len(entries[SECTIONS[0]]), todo_rows, len(entries[SECTIONS[2]]),
         os.path.relpath(TRANSCRIPT, HERE),
         "" if not bad else "；失败: " + "; ".join(bad)))

# ---------- 10) 噪声抑制：5 条噪声行的内容不得出现在文档任何位置 ----------
NOISE = {
    "09:00": "大家上午好，人到齐了我们就开始，今天主要过一下618大促的备战情况。",
    "09:01": "上周服务压测结果出来了，整体表现比预期好，细节我稍后单独同步。",
    "09:04": "预算这块我和财务核过了，大促推广费批了三百万。",
    "09:12": "等等，我刚才说错了，压测数据报高了，抱歉，我重新同步一版。",
    "09:15": "好，今天先到这里，下周同一时间复盘。",
}
all_text = "\n".join(texts) + "\n" + "\n".join(
    c.text for t in doc.tables for r in t.rows for c in r.cells)
leaked = [t for t, s in NOISE.items() if s in all_text or t + "]" in all_text]
check("noise_excluded", not leaked,
      "寒暄(09:00)/无关键词(09:01,09:04)/口误更正(09:12)/散会(09:15) 全部未混入%s"
      % ("" if not leaked else "；泄漏: %s" % leaked))

# ---------- 11) 「不能延期」行归风险 ----------
risk_hit = any("不能延期" in " ".join(g) for g in entries[SECTIONS[2]])
check("cannot_postpone_in_risk", risk_hit,
      "含「不能延期」的 09:10 行出现在三、风险与关注（且未混入决议/待办）")

# ---------- 12) 宋体（ascii + eastAsia） ----------
from docx.oxml.ns import qn  # noqa: E402
font_ok = True
for p in paras:
    for r in p.runs:
        ea = r._element.rPr.rFonts.get(qn("w:eastAsia")) if r._element.rPr is not None \
            and r._element.rPr.rFonts is not None else None
        if r.font.name != "宋体" or ea != "宋体":
            font_ok = False
check("font_simsun", font_ok, "全部正文 run 字体=宋体（w:ascii 与 w:eastAsia 一致）")

# ---------- 汇总 ----------
ok = all(r[1] for r in results)
print("\n== 回读结论: %s（%d/%d 项通过） =="
      % ("VERIFIED" if ok else "FAILED", sum(r[1] for r in results), len(results)))
sys.exit(0 if ok else 1)
