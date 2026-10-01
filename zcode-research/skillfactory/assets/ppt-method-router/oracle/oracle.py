#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""oracle.py — PPT 制作方式路由 参照实现（oracle，确定性关键词规则）

输入：意图文本 txt（一行或多行，整体视为一条用户意图）。
输出：stdout 打印一个 JSON 对象：{"method", "confidence", "reasons"}。

三类制作方式（method 取值）：
  editable_pptx  数据驱动可编辑汇报
  template_fill  套用既有公司模板
  visual_report  图文海报/信息图

关键词规则（意图文本含该词即命中，子串匹配、大小写不敏感）：
  template_fill : 模板 / 公司VI / 套用 / 品牌
  editable_pptx : 数据 / 表格 / 台账 / 月报 / 图表 / 汇报
  visual_report : 海报 / 一页 / 信息图 / 视觉 / 朋友圈 / 转发

裁定规则（确定性）：
  1) 仅命中一类         → 裁定为该类。
  2) 命中多类           → 按 template_fill > editable_pptx > visual_report
                          优先级裁定，reasons 中说明冲突与优先级依据。
  3) 一类未命中（无信号）→ 默认裁定 editable_pptx，confidence 取低值，
                          reasons 中说明为兜底行为。

confidence（置信度，两位小数，纯公式、无随机）：
  单类命中：0.80 + 0.05 × (命中关键词数 − 1)，上限 0.95
  多类命中：0.60 + 0.05 × (各类命中关键词总数 − 2)，上限 0.75（信号冲突压低置信度）
  无命中  ：固定 0.40（兜底默认）

用法：python oracle.py --input <意图.txt>
"""

import argparse
import json
import os
import sys

# 关键词表：列表顺序即裁定优先级（template_fill > editable_pptx > visual_report）
RULES = [
    ("template_fill", ("模板", "公司VI", "套用", "品牌")),
    ("editable_pptx", ("数据", "表格", "台账", "月报", "图表", "汇报")),
    ("visual_report", ("海报", "一页", "信息图", "视觉", "朋友圈", "转发")),
]

METHOD_DESC = {
    "template_fill": "template_fill(套用既有公司模板)",
    "editable_pptx": "editable_pptx(数据驱动可编辑汇报)",
    "visual_report": "visual_report(图文海报/信息图)",
}

DEFAULT_METHOD = "editable_pptx"   # 无任何信号时的兜底裁定
DEFAULT_CONF = 0.40


def classify(text):
    """对意图文本做确定性分类，返回 (method, confidence, reasons)。"""
    lowered = text.lower()
    found = []          # [(category, [keywords...])]，保持优先级顺序
    for cat, keywords in RULES:
        hits = [k for k in keywords if k.lower() in lowered]
        if hits:
            found.append((cat, hits))

    reasons = []
    for cat, hits in found:
        reasons.append("命中[%s]关键词：%s" % (METHOD_DESC[cat], "、".join(hits)))

    if not found:
        reasons.append("未命中任何类别关键词（无信号），按兜底规则默认裁定 %s，置信度低"
                       % METHOD_DESC[DEFAULT_METHOD])
        return DEFAULT_METHOD, DEFAULT_CONF, reasons

    if len(found) == 1:
        cat, hits = found[0]
        conf = min(0.95, round(0.80 + 0.05 * (len(hits) - 1), 2))
        reasons.append("仅命中单一类别信号，裁定为 %s，置信度随命中关键词数量递增"
                       % METHOD_DESC[cat])
        return cat, conf, reasons

    cats = [cat for cat, _ in found]
    total_hits = sum(len(hits) for _, hits in found)
    winner = cats[0]   # RULES 顺序即优先级，取第一个命中的类别
    losers = cats[1:]
    conf = min(0.75, round(0.60 + 0.05 * (total_hits - 2), 2))
    reasons.append(
        "多类信号同时出现（%s），按优先级 template_fill > editable_pptx > "
        "visual_report 裁定为 %s" % (" > ".join(cats), METHOD_DESC[winner]))
    reasons.append(
        "冲突说明：%s 信号同样存在但优先级较低；若实际以该方式为准，建议人工复核"
        % (", ".join(METHOD_DESC[c] for c in losers)))
    return winner, conf, reasons


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="PPT 制作方式路由 参照实现（关键词规则 oracle）；stdout 输出 JSON")
    ap.add_argument("--input", required=True, help="意图文本 txt 文件路径")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.input):
        print("输入文件不存在: %s" % args.input, file=sys.stderr)
        return 2

    with open(args.input, "r", encoding="utf-8-sig") as f:
        text = f.read().strip()

    method, confidence, reasons = classify(text)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(
        {"method": method, "confidence": confidence, "reasons": reasons},
        ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
