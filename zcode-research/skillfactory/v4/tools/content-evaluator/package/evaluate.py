#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evaluate.py — 内容确定性评测器（content-evaluator 实现包）

CLI 契约（contract.md §2 / spec.md §3 R1–R10，冻结）：

    python evaluate.py --input <markdown文件> --platform <dy|xhs|wx> --out <报告目录>

- 三个参数均必填；--platform 仅接受 dy/xhs/wx；任一无效 → exit 2，不创建 --out。
- exit 0 = 报告已写出（无论红绿，本工具只报告不设门）；没有 exit 1。
- 产物：<out>/report.json + <out>/REPORT.md。
- 纯标准库、离线、无随机；同输入重复运行仅 generated_at（及 REPORT.md 生成时间行）不同。
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime

TOOL = "evaluate.py 1.0.0"

# ---- R2：9 项检查，名称与顺序冻结 ------------------------------------------
CHECK_ORDER = (
    "title_length", "emoji_density", "body_length", "paragraph_max",
    "tag_count", "banned_words", "structure_hook", "structure_cta",
    "structure_para",
)

# ---- R3：平台阈值（冻结） ---------------------------------------------------
# title/body = 去空白字数闭区间；para_max = 单段上限；tags = 标签数闭区间；
# emoji_soft = 软上限（超出仅警告）；emoji_hard = xhs 硬区间（越界即失败）；
# min_para = 最少段落数。
PLATFORMS = {
    "dy": {
        "label": "抖音", "title": (10, 30), "body": (50, 300),
        "para_max": 120, "tags": (3, 8), "emoji_soft": 10, "min_para": 2,
    },
    "xhs": {
        "label": "小红书", "title": (8, 20), "body": (100, 800),
        "para_max": 160, "tags": (3, 10), "emoji_hard": (2, 15), "min_para": 3,
    },
    "wx": {
        "label": "微信公众号", "title": (10, 64), "body": (300, 3000),
        "para_max": 350, "tags": (0, 8), "emoji_soft": 20, "min_para": 3,
    },
}

# ---- 内置词表（极限词 44 / 钩子词 33 / CTA 词 21） ---------------------------
# R5-6：44 词极限词表（正文=标题+正文全文、小写化后逐词计数）
BANNED_WORDS = (
    "第一", "全国第一", "最好", "最佳", "最强", "最高", "最大", "最低", "最便宜",
    "最先进", "最专业", "最全", "史上最", "史上最全", "顶级", "绝佳", "绝对", "终极",
    "极致", "完美", "唯一", "独家", "首个", "首创", "首选", "全网第一", "全网最低",
    "世界级", "国家级", "百分之百", "100%", "万能", "永久", "王牌",
    "冠军", "秒杀", "稳赚", "包治", "根治", "立竿见影", "史无前例", "绝无仅有",
    "遥遥领先", "no.1",
)

# R5-7：33 词钩子词表（标题或首段命中即过；另有问号兜底、xhs 标题 emoji 兜底）
HOOK_WORDS = (
    "为什么", "如何", "什么", "怎么", "居然", "竟然", "没想到", "万万没想到",
    "秘密", "揭秘", "真相", "干货", "攻略", "教程", "必看", "必读", "救命",
    "紧急", "注意", "避坑", "踩坑", "坑点", "技巧", "窍门", "妙招", "速看",
    "快看", "新手", "小白", "入门", "亲测", "实测", "冷知识",
)

# R5-8：21 词 CTA 引导词表（正文命中任一即过）
CTA_WORDS = (
    "点赞", "关注", "收藏", "评论", "转发", "分享", "私信", "留言", "在看",
    "星标", "码住", "马克", "mark", "双击", "小红心", "点亮", "订阅", "加购",
    "下单", "购买", "点击",
)

# ---- R5-8 修改建议文案（内置） ----------------------------------------------
SUGGESTIONS = {
    "title_length": "把标题字数调整到平台建议区间内，先给结论再放卖点。",
    "emoji_density": "按平台口径增减 emoji：小红书为硬区间 [2,15]，抖音/公众号超软上限仅警告但建议收敛。",
    "body_length": "把正文字数调整到平台建议区间内，删冗余或补干货。",
    "paragraph_max": "拆分超长段落，单段控制在平台单段上限以内。",
    "tag_count": "补充平台话题标签至建议区间（#标签1 #标签2 #标签3）。",
    "banned_words": "替换或删除命中的极限词，改用可证实的中性表述。",
    "structure_hook": "在标题或首段加入钩子词（为什么/如何/必看等）或一个问句。",
    "structure_cta": "结尾补充行动引导语（点赞/关注/收藏/评论等）。",
    "structure_para": "增加自然分段，达到平台最少段落数。",
}

# emoji 码点区间（R4：逐码点统计；VS16/ZWJ/键帽组合符不计，ZWJ 组合按组成码点分别计）
EMOJI_RANGES = (
    (0x2600, 0x27BF),    # 杂项符号 + 钉子符（☕ ✨ ❤ ✅ …）
    (0x2B00, 0x2BFF),    # 杂项符号与箭头补充（⭐ …）
    (0x2934, 0x2935),    # ⤴ ⤵
    (0x231A, 0x231B),    # ⌚ ⌛
    (0x23E9, 0x23FA),    # 媒体控制符号（⏪ ⏰ ⏳ …）
    (0x1F1E6, 0x1F1FF),  # 区域指示符（旗帜）
    (0x1F300, 0x1F5FF),  # 杂项符号与象形文字
    (0x1F600, 0x1F64F),  # 表情
    (0x1F680, 0x1F6FF),  # 交通与地图
    (0x1F900, 0x1F9FF),  # 补充符号与象形文字
    (0x1FA00, 0x1FAFF),  # 扩展-A
)

HEADING_LINE_RE = re.compile(r"^#{1,6}\s")
PARA_SPLIT_RE = re.compile(r"\n\s*\n")

MARK_PASS = "\u2705 PASS"        # ✅ PASS
MARK_FAIL = "\u274c FAIL"        # ❌ FAIL
MARK_WARN = "\u26a0\ufe0f WARN"  # ⚠️ WARN


# ---- 文本解析（R4） ---------------------------------------------------------
def read_text(path):
    """按 utf-8-sig / utf-8 / gbk 依次尝试解码；全失败返回 None。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def visible_len(s):
    """去空白可见字符数（含标点、emoji、#）。"""
    return sum(1 for ch in s if not ch.isspace())


def split_title_body(text):
    """标题 = 首个 `# `（一级标题）行内容；无则取首个非空行充当标题（正文保留原行）。

    返回 (title, body)。有 h1 时标题行从正文移除；无 h1 时 body 为全文。
    """
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith("# "):
            return line[2:].strip(), "\n".join(lines[idx + 1:])
    for line in lines:
        if line.strip():
            return line.strip(), text
    return "", text


def split_paras(body):
    """段落 = 正文按空行（\\n\\s*\\n）分块、去空白后非空的块。"""
    return [p for p in PARA_SPLIT_RE.split(body) if p.strip()]


def is_emoji(ch):
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in EMOJI_RANGES)


def count_emoji(s):
    return sum(1 for ch in s if is_emoji(ch))


def _is_punct(ch):
    return unicodedata.category(ch).startswith("P")


def count_tags(text):
    """`#标签` 计数：逐行扫描，跳过 markdown 标题行；`#` 后紧跟非空白/非标点才算。"""
    n = 0
    for line in text.splitlines():
        if HEADING_LINE_RE.match(line):
            continue
        for i, ch in enumerate(line):
            if ch in ("#", "\uff03"):  # ASCII # 与全角 ＃
                nxt = line[i + 1] if i + 1 < len(line) else ""
                if nxt and not nxt.isspace() and not _is_punct(nxt):
                    n += 1
    return n


# ---- 检查项实现（R5） -------------------------------------------------------
def _mk(name, ok, detail, warning=False):
    return {"name": name, "pass": bool(ok), "warning": bool(warning),
            "detail": detail}


def _in_range(n, lo, hi):
    if lo <= n <= hi:
        return None
    return lo if n < lo else hi


def check_title_length(title, th):
    n = visible_len(title)
    lo, hi = th["title"]
    if n == 0:
        return _mk("title_length", False, "标题为空，未检测到一级标题或非空首行")
    out = _in_range(n, lo, hi)
    if out is None:
        return _mk("title_length", True, "标题 %d 字，在区间 [%d, %d] 内" % (n, lo, hi))
    return _mk("title_length", False, "标题 %d 字，超出区间 [%d, %d]" % (n, lo, hi))


def check_emoji_density(count, th, platform):
    if platform == "xhs":
        lo, hi = th["emoji_hard"]
        if lo <= count <= hi:
            return _mk("emoji_density", True,
                       "emoji 共 %d 个，在区间 [%d, %d] 内" % (count, lo, hi))
        if count < lo:
            return _mk("emoji_density", False,
                       "emoji 共 %d 个，低于区间 [%d, %d]" % (count, lo, hi))
        return _mk("emoji_density", False,
                   "emoji 共 %d 个，超出区间 [%d, %d]" % (count, lo, hi))
    soft = th["emoji_soft"]
    if count > soft:
        return _mk("emoji_density", True,
                   "emoji 共 %d 个，超出软上限 %d（仅警告，不计失败）" % (count, soft),
                   warning=True)
    return _mk("emoji_density", True, "emoji 共 %d 个，未超软上限 %d" % (count, soft))


def check_body_length(body, th):
    n = visible_len(body)
    lo, hi = th["body"]
    out = _in_range(n, lo, hi)
    if out is None:
        return _mk("body_length", True, "正文 %d 字，在区间 [%d, %d] 内" % (n, lo, hi))
    return _mk("body_length", False, "正文 %d 字，超出区间 [%d, %d]" % (n, lo, hi))


def check_paragraph_max(paras, th):
    limit = th["para_max"]
    if not paras:
        return _mk("paragraph_max", False, "未检测到段落")
    mx = max(visible_len(p) for p in paras)
    if mx <= limit:
        return _mk("paragraph_max", True,
                   "最长段落 %d 字，未超单段上限 %d" % (mx, limit))
    return _mk("paragraph_max", False,
               "最长段落 %d 字，超出单段上限 %d" % (mx, limit))


def check_tag_count(text, th):
    n = count_tags(text)
    lo, hi = th["tags"]
    out = _in_range(n, lo, hi)
    if out is None:
        return _mk("tag_count", True, "标签 %d 个，在区间 [%d, %d] 内" % (n, lo, hi))
    if n < lo:
        return _mk("tag_count", False, "标签 %d 个，低于区间 [%d, %d]" % (n, lo, hi))
    return _mk("tag_count", False, "标签 %d 个，超出区间 [%d, %d]" % (n, lo, hi))


def check_banned_words(title, body):
    full = (title + "\n" + body).lower()
    hits = []
    for w in BANNED_WORDS:
        c = full.count(w.lower())
        if c:
            hits.append((w, c))
    if not hits:
        return _mk("banned_words", True, "未命中极限词（词表 %d 词）" % len(BANNED_WORDS))
    hits.sort(key=lambda kv: (-kv[1], kv[0]))
    total = sum(c for _, c in hits)
    detail = "命中 %d 个极限词（共 %d 次）：%s" % (
        len(hits), total, "、".join("%s×%d" % (w, c) for w, c in hits))
    return _mk("banned_words", False, detail)


def check_structure_hook(title, paras, th, platform):
    """标题或首段含钩子词或含问号 → pass；xhs 额外承认标题带 emoji。"""
    for w in HOOK_WORDS:
        if w in title:
            return _mk("structure_hook", True, "标题含钩子词「%s」" % w)
    if "?" in title or "\uff1f" in title:
        return _mk("structure_hook", True, "标题含问号")
    if platform == "xhs" and count_emoji(title) > 0:
        return _mk("structure_hook", True, "标题含 emoji（小红书钩子样式）")
    if paras:
        first = paras[0]
        for w in HOOK_WORDS:
            if w in first:
                return _mk("structure_hook", True, "首段含钩子词「%s」" % w)
        if "?" in first or "\uff1f" in first:
            return _mk("structure_hook", True, "首段含问号")
    return _mk("structure_hook", False, "标题与首段均未含钩子词或问号")


def check_structure_cta(body):
    low = body.lower()
    for w in CTA_WORDS:
        if w.lower() in low:
            return _mk("structure_cta", True, "正文含 CTA 引导词「%s」" % w)
    return _mk("structure_cta", False,
               "正文未含 CTA 引导词（词表 %d 词）" % len(CTA_WORDS))


def check_structure_para(paras, th):
    n, need = len(paras), th["min_para"]
    if n >= need:
        return _mk("structure_para", True, "段落 %d 段，达到最少 %d 段" % (n, need))
    return _mk("structure_para", False, "段落 %d 段，少于最少 %d 段" % (n, need))


# ---- 评测主流程（R2/R6） ----------------------------------------------------
def evaluate(text, platform, input_path):
    th = PLATFORMS[platform]
    title, body = split_title_body(text)
    paras = split_paras(body)

    checks = [
        check_title_length(title, th),
        check_emoji_density(count_emoji(title + "\n" + body), th, platform),
        check_body_length(body, th),
        check_paragraph_max(paras, th),
        check_tag_count(body, th),
        check_banned_words(title, body),
        check_structure_hook(title, paras, th, platform),
        check_structure_cta(body),
        check_structure_para(paras, th),
    ]
    assert tuple(c["name"] for c in checks) == CHECK_ORDER

    passed = sum(1 for c in checks if c["pass"])
    applied = len(checks)
    warn = sum(1 for c in checks if c["pass"] and c["warning"])
    ratio = round(passed / applied, 4) if applied else 0.0

    ts = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    return {
        "tool": TOOL,
        "input": input_path,
        "platform": platform,
        "platform_label": th["label"],
        "generated_at": ts,
        "summary": {"applied": applied, "pass": passed,
                    "fail": applied - passed, "warn": warn},
        "score": {"passed": passed, "applied": applied, "ratio": ratio,
                  "text": "%d/%d" % (passed, applied)},
        "checks": checks,
    }


# ---- REPORT.md 渲染（R8） ---------------------------------------------------
def render_report_md(report):
    th = PLATFORMS[report["platform"]]
    in_name = os.path.basename(report["input"])
    sm, sc = report["summary"], report["score"]
    pct = "%.1f" % (sc["passed"] * 100.0 / sc["applied"]) if sc["applied"] else "0.0"

    lines = [
        "# 内容评测报告（%s · %s）" % (report["platform_label"], in_name),
        "",
        "- **输入文件**：%s" % report["input"],
        "- **平台**：%s（%s）" % (report["platform_label"], report["platform"]),
        "- **生成时间**：%s" % report["generated_at"],
        "- **总分：%s**（%s%%）" % (sc["text"], pct),
        "- **汇总**：应检 %d 项，通过 %d / 失败 %d / 警告 %d" % (
            sm["applied"], sm["pass"], sm["fail"], sm["warn"]),
        "",
        "| 检查项 | 结果 | 说明 |",
        "|---|---|---|",
    ]
    for c in report["checks"]:
        mark = MARK_FAIL if not c["pass"] else (
            MARK_WARN if c["warning"] else MARK_PASS)
        lines.append("| `%s` | %s | %s |" % (c["name"], mark, c["detail"]))

    lines.append("")
    lines.append("## 修改建议")
    lines.append("")
    fails = [c for c in report["checks"] if not c["pass"]]
    warns = [c for c in report["checks"] if c["pass"] and c["warning"]]
    if not fails and not warns:
        lines.append("全部通过，无需修改。")
    else:
        for c in fails + warns:
            lines.append("- 【%s】%s" % (c["name"], SUGGESTIONS[c["name"]]))
    return "\n".join(lines) + "\n"


# ---- CLI（R1/R9） -----------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="evaluate.py",
        description="对一篇 markdown 文案按目标平台做合规与结构打分（确定性，只报告不设门）")
    ap.add_argument("--input", required=True, help="输入 markdown 文件路径")
    ap.add_argument("--platform", required=True,
                    choices=tuple(PLATFORMS), help="目标平台：dy/xhs/wx")
    ap.add_argument("--out", required=True, help="报告输出目录")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.input):
        print("错误：--input 不是文件: %s" % args.input, file=sys.stderr)
        return 2
    text = read_text(args.input)
    if text is None:
        print("错误：--input 无法解码（utf-8-sig/utf-8/gbk 均失败）: %s"
              % args.input, file=sys.stderr)
        return 2

    report = evaluate(text, args.platform, os.path.abspath(args.input))
    os.makedirs(args.out, exist_ok=True)
    json_path = os.path.join(args.out, "report.json")
    md_path = os.path.join(args.out, "REPORT.md")
    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_report_md(report))
    print("报告已写出：%s（总分 %s）" % (args.out, report["score"]["text"]))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
