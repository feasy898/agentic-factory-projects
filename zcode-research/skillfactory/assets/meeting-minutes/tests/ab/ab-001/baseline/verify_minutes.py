# -*- coding: utf-8 -*-
"""按 rubric 五维度独立复核产物（与 build_minutes.py 解耦，直接从 docx/json 反查）。"""
import json
import re
from pathlib import Path

from docx import Document

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[3] / "oracle" / "inputs" / "case1.txt"
src_text = SRC.read_text(encoding="utf-8")

fails = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail else ""))
    if not cond:
        fails.append(name)

# 1. 结构：python-docx 可打开，三个精确标题的节且顺序正确
doc = Document(str(HERE / "纪要.docx"))
expect = ["一、决议事项", "二、待办事项", "三、风险与关注"]
heads = [p.text.strip() for p in doc.paragraphs if p.style.name.startswith("Heading")]
got = [h for h in heads if h in expect]
check("结构-三节标题精确", got == expect, f"headings={got}")
check("结构-顺序正确", got.index(expect[0]) < got.index(expect[1]) < got.index(expect[2]))

# 2. 条数 + summary.json 四键一致、合计=7
body_prefix = re.compile(r"^【(\d{2}:\d{2}) · (.+?)】")
sections, cur = {}, None
for p in doc.paragraphs:
    t = p.text.strip()
    if t in expect:
        cur = t
        sections[cur] = []
    elif cur and t:
        sections[cur].append(t)
c_dec, c_risk = len(sections.get(expect[0], [])), len(sections.get(expect[2], []))
check("条数-决议=2", c_dec == 2, f"{c_dec}")
check("条数-风险=3", c_risk == 3, f"{c_risk}")
summary = json.loads((HERE / "summary.json").read_text(encoding="utf-8"))
check("summary-四键", set(summary) == {"决议事项", "待办事项", "风险与关注", "合计"}, str(list(summary)))
check("summary-与docx一致", summary["决议事项"] == c_dec and summary["风险与关注"] == c_risk)

# 3. 待办表格：唯一表、3 列、表头含 事项/负责人/期限、2 数据行
check("表格-唯一且位于待办节", len(doc.tables) == 1, f"tables={len(doc.tables)}")
tbl = doc.tables[0]
hdr = [c.text.strip() for c in tbl.rows[0].cells]
check("表格-3列", len(tbl.columns) == 3, str(hdr))
check("表格-表头含事项/负责人/期限", all(k in hdr for k in ["事项", "负责人", "期限"]), str(hdr))
n_data = len(tbl.rows) - 1
check("条数-待办=2", n_data == 2, f"data_rows={n_data}")
check("summary-合计=7", summary.get("合计") == 7 and c_dec + n_data + c_risk == 7,
      f"{c_dec}+{n_data}+{c_risk}")

# 4. 溯源：每条带【时间 · 说话人】前缀，内容为 case1.txt 原句逐字引用
entries = [(s, x) for s, items in sections.items() for x in items]
entries += [("二、待办事项", tbl.rows[i].cells[0].text.strip()) for i in range(1, len(tbl.rows))]
pref_ok = body_ok = True
for sec, e in entries:
    m = body_prefix.match(e)
    if not m:
        pref_ok = False
        print(f"  缺前缀: [{sec}] {e[:30]}")
        continue
    if e[m.end():] not in src_text:
        body_ok = False
        print(f"  原句查无出处: [{sec}] {e[m.end():][:40]}")
check("溯源-条目均带【时间 · 说话人】前缀", pref_ok, f"共{len(entries)}条")
check("溯源-内容均为原句逐字引用", body_ok, f"共{len(entries)}条")

# 5. 噪声抑制：5 行噪声原句与其时间戳均不得出现在文档任何位置（段落+表格）
noise = ["大家上午好，人到齐了我们就开始", "上周服务压测结果出来了", "预算这块我和财务核过了",
         "等等，我刚才说错了", "今天先到这里，下周同一时间复盘"]
all_text = "\n".join(p.text for p in doc.paragraphs) + "\n" + "\n".join(
    c.text for r in tbl.rows for c in r.cells)
noise_hits = [n for n in noise if n in all_text]
check("噪声-5行原句均未混入", not noise_hits, f"hits={noise_hits}")
noise_times = {"09:00", "09:01", "09:04", "09:12", "09:15"}
used_times = {m.group(1) for _, e in entries for m in [body_prefix.match(e)] if m}
check("噪声-时间戳未使用", not (noise_times & used_times), f"used={sorted(used_times)}")
risk_text = "\n".join(sections.get("三、风险与关注", []))
check("风险-含'不能延期'行(09:10)", "48小时发货的承诺不能延期" in risk_text)

print()
print("RESULT:", "ALL PASS" if not fails else f"FAILED: {fails}")
raise SystemExit(0 if not fails else 1)
