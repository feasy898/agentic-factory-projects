# -*- coding: utf-8 -*-
"""对产物做 rubric 逐维度校验：owner/deadline/边界收录/条数/表格/噪声/逐字溯源/一致性。
安全约束（解析不可信 XML）：docx 为本脚本生成的受信产物，经 python-docx 读取；
不解析任何外部/不可信 XML，不启用外部实体。
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE.parent.parent.parent.parent / "oracle" / "inputs" / "case2.txt"

raw = SRC.read_text(encoding="utf-8")
S = json.loads((BASE / "summary.json").read_text(encoding="utf-8"))

from docx import Document
doc = Document(BASE / "纪要.docx")
docx_paras = [p.text for p in doc.paragraphs]
docx_tables = [[[c.text for c in row.cells] for row in t.rows] for t in doc.tables]
docx_all = "\n".join(docx_paras) + "\n" + "\n".join("\n".join(r) for t in docx_tables for r in t)

results = []
def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))

# --- R1 负责人解析: [14:09] 「负责人是我」→ 说话人 质检钱主任, 期限=周五之前
a9 = next(e for e in S["actions"] if e["time"] == "14:09")
check("R1 负责人解析[14:09] owner=质检钱主任", a9["owner"] == "质检钱主任", f"owner={a9['owner']}")
check("R1b 期限[14:09]=周五之前", a9["deadline"] == "周五之前", f"deadline={a9['deadline']}")

# --- R2 期限解析: [14:05] → 5月20日之前
a5 = next(e for e in S["actions"] if e["time"] == "14:05")
check("R2 期限解析[14:05]=5月20日之前", a5["deadline"] == "5月20日之前", f"deadline={a5['deadline']}")

# --- R3 待定: [14:08] owner 与 期限 均=待定
a8 = next(e for e in S["actions"] if e["time"] == "14:08")
check("R3 [14:08] owner=待定 且 deadline=待定", a8["owner"] == "待定" and a8["deadline"] == "待定",
      f"owner={a8['owner']}, deadline={a8['deadline']}")

# --- R4 边界收录: [14:18] 收尾行归入决议
d18 = [e for e in S["decisions"] if e["time"] == "14:18"]
check("R4 边界收录[14:18]入决议", len(d18) == 1 and "结论：培训未完成的员工一律不许独立上岗。散会" in d18[0]["quote"],
      f"decisions@14:18={len(d18)}")
check("R4b [14:18] 原句在 docx 中", len(d18) == 1 and d18[0]["quote"] in docx_all)

# --- R5 条数: 3/3/3 且合计=9, summary 与 docx 标题一致
c = S["counts"]
check("R5 条数 决议3/待办3/风险3", c["decisions"] == 3 and c["actions"] == 3 and c["risks"] == 3, str(c))
check("R5b 合计=9", c["total"] == 9 and c["decisions"] + c["actions"] + c["risks"] == c["total"], f"total={c['total']}")
check("R5c summary条目数组长度与计数一致",
      len(S["decisions"]) == c["decisions"] and len(S["actions"]) == c["actions"] and len(S["risks"]) == c["risks"])
check("R5d docx 标题计数与 summary 一致",
      f"一、决议事项（{c['decisions']} 条）" in docx_all and f"二、待办事项（{c['actions']} 条）" in docx_all
      and f"三、风险事项（{c['risks']} 条）" in docx_all)

# --- R6 待办为含 负责人/期限 列的表格, 且与 summary 一致
act_table = None
for t in docx_tables:
    if t and ("负责人" in t[0] and "期限" in t[0]):
        act_table = t
        break
check("R6 docx 存在含 负责人/期限 列的待办表格", act_table is not None)
if act_table:
    hdr = act_table[0]
    i_owner, i_dl = hdr.index("负责人"), hdr.index("期限")
    body = act_table[1:]
    check("R6b 表格数据行数=3", len(body) == 3, f"rows={len(body)}")
    ok_all, det = True, []
    for e in S["actions"]:
        hit = any(r[i_owner] == e["owner"] and r[i_dl] == e["deadline"] for r in body)
        ok_all &= hit
        det.append(f"[{e['time']}] owner={e['owner']},deadline={e['deadline']} -> {'ok' if hit else 'MISS'}")
    check("R6c 表格 负责人/期限 与 summary.json 一致", ok_all, "; ".join(det))

# --- R7 噪声过滤: 排除 {14:00,14:02,14:03,14:13}; 其原句不出现在任何产物条目/docx
excluded_times = {x["time"] for x in S["excluded_lines"]}
check("R7 排除行=14:00/14:02/14:03/14:13", excluded_times == {"14:00", "14:02", "14:03", "14:13"},
      f"excluded={sorted(excluded_times)}")
check("R7b 收录条目不含排除时间戳",
      not ({e['time'] for sec in ('decisions', 'actions', 'risks') for e in S[sec]} & excluded_times))
excl_texts = ["下午好，人都到了就开会", "2号线的主轴轴承坏了", "我已经安排夜班", "提醒一下，德国客户要求7月15日前必须交付"]
hit = [t for t in excl_texts if t in docx_all]
check("R7c 排除行原句未混入 docx", not hit, f"混入:{hit}")
in_sum = json.dumps(S, ensure_ascii=False)
hit2 = [t for t in excl_texts if t in in_sum]
check("R7d 排除行原句未混入 summary.json", not hit2, f"混入:{hit2}")

# --- R8 逐字溯源: 9 条目的 quote 均可在 case2.txt 逐字找到
quotes = [e["quote"] for sec in ("decisions", "actions", "risks") for e in S[sec]]
missing = [q for q in quotes if q not in raw]
check("R8 全部条目原句逐字可溯源(case2.txt)", len(quotes) == 9 and not missing, f"quotes={len(quotes)}, missing={missing}")
missing_doc = [q for q in quotes if q not in docx_all]
check("R8b 全部条目原句逐字出现在 docx", not missing_doc, f"missing={missing_doc}")

# --- 汇总
n_pass = sum(1 for _, ok, _ in results if ok)
for name, ok, det in results:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {det}" if det else ""))
print(f"\n{n_pass}/{len(results)} checks passed")
sys.exit(0 if n_pass == len(results) else 1)
