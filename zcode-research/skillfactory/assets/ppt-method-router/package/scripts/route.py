#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""route.py — PPT 方法意图路由（单条，确定性规则）

用法：
  python scripts/route.py --input <意图.txt>

契约（package/../../contract.md §2.1，与 oracle 同构）：
  stdout  恰一行 JSON：{"method": "...", "confidence": <0..1>, "reasons": ["...", ...]}
  退出码  0 成功；2 输入文件不存在/不可读（stderr 提示，stdout 无 JSON）
  日志一律走 stderr，stdout 除结果 JSON 外不得有任何内容。

行为规则（依据 spec.md §3 固化，纯规则、无随机、无外部输入）：
  R1 关键词表（子串匹配、大小写不敏感）：
     template_fill : 模板、公司VI、套用、品牌
     editable_pptx : 数据、表格、台账、月报、图表、汇报
     visual_report : 海报、一页、信息图、视觉、朋友圈、转发
  R3 仅一类命中   → 该类；confidence = 0.80 + 0.05×(命中词数−1)，上限 0.95
  R4 多类命中     → 按优先级 template_fill > editable_pptx > visual_report 取最高；
                    confidence = 0.60 + 0.05×(各类命中词总数−2)，上限 0.75（冲突压低置信度）
  R5 无任何命中   → 兜底 editable_pptx，confidence = 0.40，reasons 如实说明无信号
"""
import argparse
import json
import sys

# 规则表：列表顺序即优先级（template_fill > editable_pptx > visual_report）
RULES = [
    ("template_fill", "套用既有公司模板",
     ["模板", "公司vi", "套用", "品牌"]),
    ("editable_pptx", "数据驱动可编辑汇报",
     ["数据", "表格", "台账", "月报", "图表", "汇报"]),
    ("visual_report", "图文海报/信息图",
     ["海报", "一页", "信息图", "视觉", "朋友圈", "转发"]),
]
PRIORITY_CHAIN = "template_fill > editable_pptx > visual_report"
FALLBACK_METHOD = "editable_pptx"
FALLBACK_CONFIDENCE = 0.40


def fmt_conf(value):
    """0.90 -> "0.9"、0.40 -> "0.4"、0.95 -> "0.95"（用于 reasons 文案）。"""
    return ("%.2f" % value).rstrip("0").rstrip(".")


def match_categories(text):
    """对整段意图文本做子串匹配（双方 lower()），返回 [(method, label, 命中词列表)]。"""
    lowered = text.lower()
    hits = []
    for method, label, keywords in RULES:
        found = [kw for kw in keywords if kw in lowered]
        if found:
            hits.append((method, label, found))
    return hits


def route(text):
    """确定性路由：返回 {method, confidence, reasons}。"""
    hits = match_categories(text)

    # R5 无信号兜底：不编造命中词，如实说明并给低置信
    if not hits:
        return {
            "method": FALLBACK_METHOD,
            "confidence": FALLBACK_CONFIDENCE,
            "reasons": [
                "未命中任何类别关键词（无信号）：意图文本中未出现 template_fill / "
                "editable_pptx / visual_report 三组信号词中的任何一个",
                "按无信号兜底默认裁定为 editable_pptx（数据驱动可编辑汇报），"
                "置信度固定低值 0.4，不代表有正向证据；建议先向用户澄清用途再进入执行",
            ],
        }

    total_hits = sum(len(found) for _, _, found in hits)
    reasons = ["命中[%s(%s)]关键词：%s" % (method, label, "、".join(found))
               for method, label, found in hits]

    # R3 仅单一类别命中
    if len(hits) == 1:
        method, label, found = hits[0]
        confidence = round(min(0.95, 0.80 + 0.05 * (len(found) - 1)), 2)
        reasons.append(
            "仅单一类别命中、无信号冲突；置信度 = 0.80 + 0.05×(命中词数−1) 上限 0.95，"
            "本条命中 %d 词 → %s" % (len(found), fmt_conf(confidence)))
        return {"method": method, "confidence": confidence, "reasons": reasons}

    # R4 多类命中：按优先级裁定，冲突压低置信度
    method, label, _ = hits[0]  # RULES 列表顺序即优先级，命中类按序排列，取第一个
    appeared = " > ".join(m for m, _, _ in hits)
    confidence = round(min(0.75, 0.60 + 0.05 * (total_hits - 2)), 2)
    reasons.append(
        "多类信号同时出现（%s），按优先级 %s 裁定为 %s(%s)"
        % (appeared, PRIORITY_CHAIN, method, label))
    reasons.append(
        "冲突说明：意图同时携带 %d 类制作信号（共 %d 个命中词），制作方向可能未定，"
        "置信度上限压至 0.75（本条 %s）；建议人工复核或向用户确认主用途后再移交执行"
        % (len(hits), total_hits, fmt_conf(confidence)))
    return {"method": method, "confidence": confidence, "reasons": reasons}


def read_intent(path):
    """读取意图文本：UTF-8（容许 BOM），整文件视为一条意图并 strip()。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read().strip(), None
    except FileNotFoundError:
        return None, "输入文件不存在: %s" % path
    except UnicodeDecodeError:
        return None, "输入文件不是有效的 UTF-8 文本（本技能仅支持 UTF-8±BOM）: %s" % path
    except OSError as exc:
        return None, "输入文件读取失败: %s（%s）" % (path, exc)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="PPT 方法意图路由：editable_pptx / template_fill / visual_report")
    parser.add_argument("--input", required=True, help="意图文本文件路径（UTF-8，容许 BOM）")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    text, err = read_intent(args.input)
    if err is not None:
        print(err, file=sys.stderr)
        return 2

    result = route(text)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
