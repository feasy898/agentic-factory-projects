# -*- coding: utf-8 -*-
"""从 summary.json 渲染 content.md（完整文本内容 + 结构说明，供评审阅读）。"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
S = json.loads((BASE / "summary.json").read_text(encoding="utf-8"))
m = S["meeting"]
c = S["counts"]

L = []
L.append("# 会议纪要（case2 · 三季度出口订单交付会）— 完整文本与结构说明\n")
L.append("> 本文件为评审用完整内容镜像：与 `纪要.docx`、`summary.json` 同源生成（同一份提取结果）。\n")

L.append("## 0. 文件清单\n")
L.append("| 文件 | 说明 |")
L.append("|---|---|")
L.append("| `纪要.docx` | 三段式会议纪要（决议事项 / 待办事项 / 风险事项，待办为含负责人、期限列的表格） |")
L.append("| `summary.json` | 结构化结果：计数、条目（含逐字原句与提取规则）、排除行、规则说明 |")
L.append("| `content.md` | 本文件：完整文本内容 + 结构说明 |")
L.append("| `build_minutes.py` / `gen_content.py` / `verify_minutes.py` | 生成与校验脚本（中间文件） |\n")

L.append("## 1. 会议信息\n")
L.append(f"- **会议主题**：{m['topic']}")
L.append(f"- **会议时间**：{m['date']}；{m['time']}")
L.append(f"- **会议地点**：{m['location']}")
L.append(f"- **主持人**：{m['host']}")
L.append(f"- **参会人员**：{'、'.join(m['attendees'])}")
L.append(f"- **纪要来源**：`{m['source_transcript']}`（逐行转写）\n")

L.append("## 2. 纪要正文（与 docx 一致）\n")
L.append("# 会议纪要\n")
L.append(f"—— {m['title']} ——\n")

L.append(f"## 一、决议事项（{c['decisions']} 条）\n")
for i, e in enumerate(S["decisions"], 1):
    L.append(f"{i}. **{e['content']}**（[{e['time']}] {e['speaker']}；命中关键词：{'、'.join(e['keyword_hit'])}）")
    L.append(f"   - 原句：「{e['quote']}」")
L.append("")

L.append(f"## 二、待办事项（{c['actions']} 条）\n")
L.append("| 序号 | 待办事项 | 负责人 | 期限 | 发言来源 |")
L.append("|---|---|---|---|---|")
for i, e in enumerate(S["actions"], 1):
    L.append(f"| {i} | {e['content']} | {e['owner']} | {e['deadline']} | [{e['time']}] {e['speaker']} |")
L.append("")
for i, e in enumerate(S["actions"], 1):
    L.append(f"{i}. 原句：「{e['quote']}」")
    L.append(f"   - 负责人规则：{e['owner_rule']}")
    L.append(f"   - 期限规则：{e['deadline_rule'] or '原句无期限表述 → 待定'}")
L.append("")

L.append(f"## 三、风险事项（{c['risks']} 条）\n")
for i, e in enumerate(S["risks"], 1):
    L.append(f"{i}. **{e['content']}**（[{e['time']}] {e['speaker']}；命中关键词：{'、'.join(e['keyword_hit'])}）")
    L.append(f"   - 原句：「{e['quote']}」")
L.append("")

L.append(f"合计收录条目：{c['total']}（决议 {c['decisions']} + 待办 {c['actions']} + 风险 {c['risks']}）。\n")

L.append("## 3. 未收录行说明（噪声过滤）\n")
L.append("| 时间 | 发言人 | 处理 |")
L.append("|---|---|---|")
for x in S["excluded_lines"]:
    L.append(f"| [{x['time']}] | {x['speaker']} | {x['reason']} |")
L.append("")

r = S["extraction_rules"]
L.append("## 4. 提取规则说明（确定性提取）\n")
L.append("1. **分类（关键词命中即归类，类别判定顺序：决议 → 待办 → 风险）**")
L.append(f"   - 决议关键词：{' / '.join(r['keywords']['decision'])}")
L.append(f"   - 待办关键词：{' / '.join(r['keywords']['action'])}")
L.append(f"   - 风险关键词：{' / '.join(r['keywords']['risk'])}")
L.append("   - 未命中任何关键词的行不收录（含寒暄行 [14:00] 与无关键词行 [14:02]/[14:03]/[14:13]）。")
L.append("2. **负责人**：" + r["owner"] + "。")
L.append("   - 例：[14:09]「负责人是我，本周五之前出结果」→「负责人是我」→ 我 → 说话人 → **质检钱主任**。")
L.append("   - 反例：[14:08]「我们需要重新提交检测报告」原句无负责人表述 → **待定**（不与 [14:09] 跨行合并）。")
L.append("3. **期限**：" + r["deadline"] + "。")
L.append("   - 例：[14:05]「5月20日之前必须到港」→ **5月20日之前**；[14:09]「本周五之前」→ 规范化为 **周五之前**。")
L.append("4. **边界收录**：" + r["boundary"] + "。本例 [14:18]「结论：培训未完成的员工一律不许独立上岗。散会…」虽为收尾行，含关键词「结论」，必须归入决议事项。\n")

L.append("## 5. 分类结果总表（逐行）\n")
L.append("| 时间 | 发言人 | 分类 | 命中关键词 |")
L.append("|---|---|---|---|")
rows = []
for sec, cat in [("decisions", "决议事项"), ("actions", "待办事项"), ("risks", "风险事项")]:
    for e in S[sec]:
        rows.append((e["time"], e["speaker"], cat, "、".join(e["keyword_hit"])))
for x in S["excluded_lines"]:
    rows.append((x["time"], x["speaker"], "未收录", "—"))
rows.sort(key=lambda r: r[0])
for t, sp, cat, kw in rows:
    L.append(f"| [{t}] | {sp} | {cat} | {kw} |")
L.append("")
L.append("> 逐行明细见 `summary.json`（每条含 time/speaker/keyword_hit/quote）。\n")

(BASE / "content.md").write_text("\n".join(L), encoding="utf-8")
print("content.md written")
