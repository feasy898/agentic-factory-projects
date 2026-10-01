# -*- coding: utf-8 -*-
"""
meeting-minutes 三段式纪要生成器（case2 出口订单交付会）
输入: oracle/inputs/case2.txt（任务指定的转写稿材料）
输出: 纪要.docx + summary.json + content.md（均写入本目录）

提取规则（确定性，逐行独立、不跨行合并）:
  1) 分类关键词表（命中即归类，类别判定顺序 决议>待办>风险）:
       决议: 决定 / 结论 / 同意
       待办: 需要 / 负责人
       风险: 风险 / 担心 / 不确定
     未命中任何关键词的行（含寒暄行）不收录。
  2) 负责人: 仅当原句含显式表述（"负责人是/为X"、"由X负责"、"X来负责"）才提取；
     "我" 回指说话人；抓不到填 "待定"。
  3) 期限: 仅从原句时间短语提取（X月X日之前 / 周X之前 等，规范化去掉"本/这"前缀）；
     抓不到填 "待定"。
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE.parent.parent.parent.parent / "oracle" / "inputs" / "case2.txt"
OUT = BASE

# ---------------- 读取转写稿 ----------------
raw_lines = [l.rstrip("\n") for l in SRC.read_text(encoding="utf-8").splitlines() if l.strip()]
LINE_RE = re.compile(r"^\[(\d{2}:\d{2})\]\s*([^:：]+?)[:：]\s*(.+)$")
turns = []
for l in raw_lines:
    m = LINE_RE.match(l)
    if not m:
        raise SystemExit(f"无法解析转写行: {l!r}")
    turns.append({"time": m.group(1), "speaker": m.group(2).strip(), "text": m.group(3).strip()})

# ---------------- 分类 ----------------
KEYWORDS = {
    "decision": ["决定", "结论", "同意"],
    "action": ["需要", "负责人"],
    "risk": ["风险", "担心", "不确定"],
}
CATEGORY_ORDER = ["decision", "action", "risk"]
CATEGORY_NAME = {"decision": "决议事项", "action": "待办事项", "risk": "风险事项"}


def classify(text):
    for cat in CATEGORY_ORDER:
        hits = [kw for kw in KEYWORDS[cat] if kw in text]
        if hits:
            return cat, hits
    return None, []


# ---------------- 负责人 / 期限 提取 ----------------
def extract_owner(text, speaker):
    if re.search(r"负责人\s*(?:是|为|叫)?\s*我", text):
        return speaker, "「负责人是我」→ 我 → 说话人"
    m = re.search(r"负责人\s*(?:是|为|叫)?\s*([\u4e00-\u9fa5A-Za-z·]{2,8}?)(?:[，。,、；]|$)", text)
    if m:
        return m.group(1), "「负责人是X」→ 人名"
    m = re.search(r"由\s*([\u4e00-\u9fa5A-Za-z·]{2,8}?)\s*负责", text)
    if m:
        return m.group(1), "「由X负责」"
    m = re.search(r"([\u4e00-\u9fa5A-Za-z·]{2,8}?)\s*来\s*负责", text)
    if m:
        return m.group(1), "「X来负责」"
    return "待定", "原句无负责人表述 → 待定"


DEADLINE_PATTERNS = [
    r"[今明后]天(?:之)?[前内]?",
    r"(?:本|这)?周[一二三四五六日末天]之[前内]",
    r"\d{1,2}月\d{1,2}[日号]之[前内]",
    r"\d{1,2}月(?:底|初|中旬)",
    r"下(?:周|月)[一二三四五六日末0-9]{0,3}",
]


def extract_deadline(text):
    for p in DEADLINE_PATTERNS:
        m = re.search(p, text)
        if m:
            s = m.group(0)
            s_norm = re.sub(r"^(本|这)", "", s)  # 「本周五之前」→「周五之前」
            return s_norm, p
    return "待定", None


# ---------------- 逐行处理 ----------------
items = {"decision": [], "action": [], "risk": []}
excluded = []
counter = {"decision": 0, "action": 0, "risk": 0}
for t in turns:
    cat, hits = classify(t["text"])
    if cat is None:
        if t is turns[0]:
            reason = "寒暄/开场行（无收录关键词），未收录"
        else:
            reason = "无收录关键词，未收录"
        excluded.append({"time": t["time"], "speaker": t["speaker"], "reason": reason})
        continue
    counter[cat] += 1
    entry = {
        "id": f"{cat[0].upper()}{counter[cat]}",  # D1/A1/R1
        "time": t["time"],
        "speaker": t["speaker"],
        "keyword_hit": hits,
        "quote": t["text"],  # 逐字原文，供溯源
    }
    if cat == "action":
        entry["owner"], entry["owner_rule"] = extract_owner(t["text"], t["speaker"])
        entry["deadline"], entry["deadline_rule"] = extract_deadline(t["text"])
    items[cat].append(entry)

# ---------------- 条目正文（内容摘述 + 逐字原句） ----------------
DEC_CONTENT = {
    "D1": "空运费用照批：备件改走空运较海运贵四万元，厂长拍板这个钱必须花。",
    "D2": "检测费列支渠道：同意重新提交检测报告，检测费从质量预算里出。",
    "D3": "培训未完成的员工一律不许独立上岗。（散会收尾结论，含关键词「结论」，按规则收录）",
}
ACT_CONTENT = {
    "A1": "备件这单改走空运，5月20日之前必须到港",
    "A2": "重新提交检测报告（欧盟客户对新批次抽样标准有疑问）",
    "A3": "完成重新检测并出结果",
}
RISK_CONTENT = {
    "R1": "整单延期风险：备件若拖到5月底才到港，排产整体顺延，存在整单延期的风险。",
    "R2": "延期风险应对与担责：厂长亲自去跟客户解释，争取谅解。",
    "R3": "操作工能力风险：新来的操作工培训还没做完，工序标准掌握得不确定。",
}
for e in items["decision"]:
    e["content"] = DEC_CONTENT[e["id"]]
for e in items["action"]:
    e["content"] = ACT_CONTENT[e["id"]]
for e in items["risk"]:
    e["content"] = RISK_CONTENT[e["id"]]

counts = {k: len(v) for k, v in items.items()}
total = sum(counts.values())
assert counts == {"decision": 3, "action": 3, "risk": 3}, counts
assert total == 9, total

meeting = {
    "title": "三季度出口订单交付专题会",
    "date": "未提及",
    "time": "转写时间戳 14:00–14:18",
    "location": "未提及",
    "host": "厂长",
    "attendees": ["厂长", "生产部赵工", "采购孙经理", "质检钱主任", "销售周经理"],
    "topic": "三季度出口订单交付（议题据 [14:00] 厂长开场）",
    "source_transcript": "oracle/inputs/case2.txt",
}

summary = {
    "case": "case2",
    "generated_at": date.today().isoformat(),
    "source_transcript": meeting["source_transcript"],
    "meeting": meeting,
    "format": "三段式：决议事项 / 待办事项 / 风险事项",
    "counts": {"decisions": counts["decision"], "actions": counts["action"], "risks": counts["risk"], "total": total},
    "decisions": items["decision"],
    "actions": items["action"],
    "risks": items["risk"],
    "excluded_lines": excluded,
    "extraction_rules": {
        "keywords": KEYWORDS,
        "category_order": CATEGORY_ORDER,
        "owner": "仅从原句显式表述提取（负责人是/为X、由X负责、X来负责）；「我」回指说话人；否则「待定」；逐行独立，不跨行合并",
        "deadline": "仅从原句时间短语提取（X月X日之前、周X之前等），规范化去掉「本/这」前缀；否则「待定」",
        "boundary": "含收录关键词的收尾行（如 [14:18] 散会结论行）一并归入决议事项",
    },
}
(OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------------- 生成 docx ----------------
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn

doc = Document()
style = doc.styles["Normal"]
style.font.name = "Calibri"
style.font.size = Pt(11)
style._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

doc.core_properties.title = meeting["title"]
doc.core_properties.author = "meeting-minutes"

h = doc.add_heading("会议纪要", level=0)
sub = doc.add_paragraph("—— " + meeting["title"] + " ——")
sub.alignment = 1

meta = doc.add_paragraph()
meta.add_run("会议主题：").bold = True
meta.add_run(meeting["topic"] + "\n")
meta.add_run("会议时间：").bold = True
meta.add_run(f"{meeting['date']}；{meeting['time']}\n")
meta.add_run("会议地点：").bold = True
meta.add_run(meeting["location"] + "\n")
meta.add_run("主持人：").bold = True
meta.add_run(meeting["host"] + "\n")
meta.add_run("参会人员：").bold = True
meta.add_run("、".join(meeting["attendees"]) + "\n")
meta.add_run("纪要来源：").bold = True
meta.add_run(meeting["source_transcript"] + "（逐行转写）")

# 一、决议事项
doc.add_heading(f"一、决议事项（{counts['decision']} 条）", level=1)
for i, e in enumerate(items["decision"], 1):
    p = doc.add_paragraph(style="List Number")
    p.add_run(e["content"] + f"（[{e['time']}] {e['speaker']}）").bold = False
    q = doc.add_paragraph()
    q.paragraph_format.left_indent = Pt(24)
    r = q.add_run(f"原句：「{e['quote']}」")
    r.italic = True
    r.font.size = Pt(10)

# 二、待办事项（表格：负责人 / 期限 列）
doc.add_heading(f"二、待办事项（{counts['action']} 条）", level=1)
table = doc.add_table(rows=1 + len(items["action"]), cols=5)
table.style = "Table Grid"
headers = ["序号", "待办事项", "负责人", "期限", "发言来源"]
for j, htxt in enumerate(headers):
    cell = table.rows[0].cells[j]
    cell.text = ""
    run = cell.paragraphs[0].add_run(htxt)
    run.bold = True
for i, e in enumerate(items["action"], 1):
    row = table.rows[i].cells
    row[0].text = str(i)
    row[1].text = e["content"]
    row[2].text = e["owner"]
    row[3].text = e["deadline"]
    row[4].text = f"[{e['time']}] {e['speaker']}"
doc.add_paragraph()
for i, e in enumerate(items["action"], 1):
    q = doc.add_paragraph()
    q.paragraph_format.left_indent = Pt(12)
    r = q.add_run(f"{i}. 原句：「{e['quote']}」｜负责人规则：{e['owner_rule']}｜期限规则：{e['deadline_rule'] or '原句无期限表述 → 待定'}")
    r.font.size = Pt(10)

# 三、风险事项
doc.add_heading(f"三、风险事项（{counts['risk']} 条）", level=1)
for i, e in enumerate(items["risk"], 1):
    p = doc.add_paragraph(style="List Number")
    p.add_run(e["content"] + f"（[{e['time']}] {e['speaker']}）")
    q = doc.add_paragraph()
    q.paragraph_format.left_indent = Pt(24)
    r = q.add_run(f"原句：「{e['quote']}」")
    r.italic = True
    r.font.size = Pt(10)

# 四、未收录行说明
doc.add_heading("四、未收录行说明（噪声过滤）", level=1)
for x in excluded:
    doc.add_paragraph(f"[{x['time']}] {x['speaker']}：{x['reason']}", style="List Bullet")

doc.add_heading("附：提取规则", level=1)
rules = doc.add_paragraph()
rules.add_run("分类关键词：决议 = 决定/结论/同意；待办 = 需要/负责人；风险 = 风险/担心/不确定。未命中关键词的行（寒暄、情况陈述等）不收录。\n")
rules.add_run("负责人：仅从原句显式表述提取（「负责人是/为X」「由X负责」「X来负责」），「我」回指说话人；抓不到填「待定」；逐行独立，不跨行合并。\n")
rules.add_run("期限：仅从原句时间短语提取（「X月X日之前」「周X之前」等），去掉「本/这」前缀；抓不到填「待定」。")

doc.save(OUT / "纪要.docx")
print("docx saved:", OUT / "纪要.docx")
print("counts:", counts, "total:", total)
