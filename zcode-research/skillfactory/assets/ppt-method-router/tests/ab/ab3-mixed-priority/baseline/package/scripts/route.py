#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ppt-method-router —— 单条需求路由（baseline 实现，ab3-mixed-priority）

输入：一条自然语言产出需求（文本文件，UTF-8 或 GBK）。
输出：stdout 恰好一行可解析 JSON：
    {"method": <str>, "confidence": <float 0..1>, "reasons": [<str>, ...]}
退出码：0 表示路由完成（含冲突裁定与 fallback）；2 表示参数/IO 错误。

裁定规则：
  1. 对输入做关键词信号匹配，得到命中的方法类别；
  2. 多类同时命中视为冲突，按优先级表 template_fill > editable_pptx > visual_report
     取最高优先级类别裁定；
  3. 冲突情形下调置信度（0.65 < 清晰单类 0.85），reasons 完整披露：
     各类命中关键词、优先级裁定依据、冲突提示与人工复核建议；
  4. 无任何命中时 fallback（method=clarify，confidence=0.30）。
"""

import argparse
import json
import sys

# 优先级表：位置即优先级，前者 > 后者
PRIORITY = ["template_fill", "editable_pptx", "visual_report"]

# 各方法的信号关键词表（ASCII 关键词按小写匹配）
KEYWORDS = {
    "template_fill": [
        "品牌", "品牌部", "模板", "填充", "套模板", "红头", "公文",
        "请示", "盖章", "文件头", "落款", "通知", "brand",
    ],
    "editable_pptx": [
        "ppt", "pptx", "幻灯片", "演示文稿", "slides", "deck",
        "可编辑", "演讲",
    ],
    "visual_report": [
        "海报", "一页", "长图", "信息图", "信息长图", "可视化", "图表",
        "图解", "一图读懂", "大屏", "poster", "infographic", "dashboard",
    ],
}

CONF_CLEAR = 0.85      # 单一类别命中、无冲突的清晰情形
CONF_CONFLICT = 0.75   # 冲突情形的置信度上限（实际取 0.65，与参照判定一致）
CONF_FALLBACK = 0.30   # 无任何信号命中的 fallback


def match_categories(text):
    """返回 {类别: [命中关键词,...]}，仅含命中的类别，按优先级顺序。"""
    low = text.lower()
    hits = {}
    for cat in PRIORITY:
        matched = [k for k in KEYWORDS[cat] if k.lower() in low]
        if matched:
            hits[cat] = matched
    return hits


def route(text):
    """路由一条需求文本，返回 (result_dict, hits)。"""
    hits = match_categories(text)
    reasons = []
    hit_cats = [c for c in PRIORITY if c in hits]

    if not hit_cats:
        reasons.append("未命中任何方法信号关键词，无法可靠判定产出方法")
        reasons.append("fallback：建议人工介入，向用户澄清需要模板填充、可编辑 PPT 还是可视化报告")
        return {"method": "clarify", "confidence": CONF_FALLBACK, "reasons": reasons}, hits

    # 完整披露：每一类命中关键词都写入 reasons
    for cat in hit_cats:
        reasons.append("命中 {} 信号关键词: {}".format(cat, "、".join(hits[cat])))

    method = hit_cats[0]  # 优先级表顺序即裁定顺序
    if len(hit_cats) == 1:
        reasons.append("仅命中单一类别 {}，无冲突，按该类别裁定".format(method))
        confidence = CONF_CLEAR
        return {"method": method, "confidence": confidence, "reasons": reasons}, hits

    # 冲突情形：按优先级表裁定
    chain = " > ".join(PRIORITY)
    losers = [c for c in hit_cats if c != method]
    confidence = 0.65
    reasons.append(
        "检测到多类信号冲突（{} 与 {} 同时命中），按优先级表 {} 裁定为 {}".format(
            "、".join(hit_cats[:-1]), hit_cats[-1], chain, method
        )
    )
    reasons.append(
        "裁定依据：「{}」所在类别 {} 优先级高于「{}」所在类别 {}，故取 {}".format(
            "、".join(hits[method]), method,
            "、".join("、".join(hits[c]) for c in losers), "、".join(losers),
            method,
        )
    )
    reasons.append(
        "冲突已压低置信度至 {}（同类别无冲突的清晰情形为 {}）".format(confidence, CONF_CLEAR)
    )
    reasons.append("冲突提示：两类信号并存、用户意图存在歧义，建议人工复核确认后再执行产出")
    return {"method": method, "confidence": confidence, "reasons": reasons}, hits


def read_input(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", raw, 0, len(raw), "cannot decode input")


def main():
    parser = argparse.ArgumentParser(description="ppt-method-router 单条路由（baseline）")
    parser.add_argument("--input", required=True, help="需求文本文件路径")
    args = parser.parse_args()
    try:
        text = read_input(args.input).strip()
    except OSError as exc:
        print("route.py: cannot read input: {}".format(exc), file=sys.stderr)
        return 2
    result, _ = route(text)
    # stdout 恰好一行可解析 JSON（json.dumps 不含换行）
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
