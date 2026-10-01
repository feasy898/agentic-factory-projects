#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evaluate.py — 新媒体内容确定性评测 CLI（oracle 参照实现）

用法：
    python evaluate.py --input <markdown文件> --platform <dy|xhs|wx> --out <报告目录>

平台阈值（oracle 内置约定，全部确定性、无网络依赖）：
  平台  标题字数   正文字数(去空白)  单段上限  标签数    emoji 规则           最少段落数
  dy    10-30      50-300            120       3-8       >10 警告(不计失败)   2
  xhs   8-20       100-800           160       3-10      须在 2-15 区间(硬检) 3
  wx    10-64      300-3000          350       0-8       >20 警告(不计失败)   3

检查项（report.json 的 checks 数组，元素为 {name, pass, warning, detail}，warning 可缺省）：
  1. title_length      标题长度在平台区间内（标题 = 首个 "# " 一级标题行，无则取首个非空行）
  2. emoji_density     xhs：emoji 数量落在区间内，越界即失败；dy/wx：仅超上限时警告（pass 不受影响）
  3. body_length       正文长度在平台区间内（正文 = 去掉标题行后的全部文本，按去空白字符计）
  4. paragraph_max     最长段落（按空行分块，块内去空白字符数）不超过平台单段上限
  5. tag_count         #标签 数量（形如 "#xx"，排除 markdown 标题行）在平台区间内
  6. banned_words      命中内置极限词表（44 词：最好/第一/国家级/100%/No.1 等）即失败
  7. structure_hook    钩子：标题或首段含钩子词/问号视为有钩子；xhs 额外承认"标题带 emoji"
  8. structure_cta     CTA：正文含引导词（点赞/关注/收藏/评论/私信/在看/星标 等）之一
  9. structure_para    分段：正文段落数 ≥ 平台最少段落数

计分：总分 = 通过项 / 应检项（9 项全部应检；警告计入通过并单列 warning 标记）。

退出码：0 = 报告已写出（红绿均算，本工具只报告不设门）；2 = 参数或输入文件无效
"""

import argparse
import json
import os
import re
import sys
import time

TOOL_NAME = "evaluate.py"
TOOL_VERSION = "1.0.0"
DETAIL_MAX = 400

# ---------------------------------------------------------------- 平台配置 ----

PLATFORMS = {
    "dy": {
        "label": "抖音",
        "title": (10, 30),
        "body": (50, 300),
        "paragraph_max": 120,
        "tags": (3, 8),
        "min_paragraphs": 2,
        "emoji_mode": "warn",      # 仅超上限警告
        "emoji_max": 10,
    },
    "xhs": {
        "label": "小红书",
        "title": (8, 20),
        "body": (100, 800),
        "paragraph_max": 160,
        "tags": (3, 10),
        "min_paragraphs": 3,
        "emoji_mode": "range",     # 硬区间，越界即失败
        "emoji_range": (2, 15),
    },
    "wx": {
        "label": "微信公众号",
        "title": (10, 64),
        "body": (300, 3000),
        "paragraph_max": 350,
        "tags": (0, 8),
        "min_paragraphs": 3,
        "emoji_mode": "warn",
        "emoji_max": 20,
    },
}

# 44 个常见广告法极限词/绝对化用语（在 30+ 要求之上留了余量）
BANNED_WORDS = (
    "最好", "最佳", "最优", "最优秀", "最强", "最先进", "最高级", "最低价", "最便宜",
    "第一", "唯一", "首个", "首选", "顶级", "极品", "极致", "绝无仅有", "史无前例",
    "空前绝后", "万能", "百分之百", "100%", "国家级", "世界级", "全国第一", "全网第一",
    "全网最", "销量第一", "销量冠军", "排名第一", "no.1", "top1",
    "完美", "终极", "无敌", "永久", "彻底", "根治", "包治", "立竿见影",
    "纯天然", "零风险", "稳赚", "暴利",
)

HOOK_WORDS = (
    "为什么", "如何", "怎么", "怎样", "什么", "居然", "竟然", "万万没想到", "没想到",
    "揭秘", "秘密", "真相", "内幕", "干货", "攻略", "避坑", "踩坑", "千万别", "别再",
    "谁懂", "救命", "求求", "原来", "你以为", "普通人", "新手", "小白", "必看",
    "最后一个", "90%", "九成", "大多数人", "我猜", "说实话",
)

CTA_WORDS = (
    "点赞", "关注", "收藏", "码住", "转发", "评论", "留言", "私信", "私我",
    "在看", "星标", "分享", "双击", "长按", "评论区", "主页", "点击",
    "扣1", "扣个", "加微信", "蹲一个",
)

EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"   # 旗帜
    "\U0001F300-\U0001F5FF"   # 符号/物品/动物/食物
    "\U0001F600-\U0001F64F"   # 表情
    "\U0001F680-\U0001F6FF"   # 交通/符号
    "\U0001F700-\U0001F7FF"   # 炼金等
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"   # 补充表情/物品
    "\U0001FA00-\U0001FAFF"   # 扩展
    "\U00002600-\U000027BF"   # 杂项符号/装饰（含 ☕ ✨ ✅）
    "\U00002B00-\U00002BFF"   # ⭐ 等
    "\U000023E9-\U000023FA"   # ⏰ 等播放/时钟符号
    "\U00002763\U00002764"    # ❤ 等
    "\U00003030\U0000303D\U00003297\U00003299"
    "]"                       # 单字符类，无 '+'：按 emoji 码点逐个计数
)
HEADING_RE = re.compile(r"^#{1,6}\s+")
TAG_RE = re.compile(r"#([^\s#，。；：！？、\u3000（）()]+)")

ADVICE = {
    "title_length": "把标题改到平台区间内（字数见 checks 明细）：保留最核心的卖点词，删掉堆砌的修饰语。",
    "emoji_density": "按平台调整 emoji：xhs 需少量点缀（区间见明细）；dy/wx 宁少勿多，超过上限删掉装饰性 emoji。",
    "body_length": "正文长度对齐平台区间（见明细）：太短补具体细节/案例，太长拆篇或删冗余。",
    "paragraph_max": "拆分超长段落：一段只讲一个意思，每段控制在平台上限内（见明细），多用短句。",
    "tag_count": "按平台区间补/删 #标签（见明细）：优先 3-5 个内容垂类词 + 1-2 个热点词，避免无关蹭词。",
    "banned_words": "用可验证的表述替换极限词：'最好'→'实测下来对我最合适'，'第一'→'我用过的第一个'，并删掉 %、排名类绝对化承诺。",
    "structure_hook": "开头 1-2 句加钩子：提问（'你是不是也…？'）、反常识（'万万没想到…'）或痛点场景，xhs 可在标题加一个 emoji。",
    "structure_cta": "结尾加一句明确的行动引导：点赞/收藏/关注/评论区聊聊/私信我，二选一即可，不要堆砌。",
    "structure_para": "正文按平台最少段落数分段（见明细）：每段一个要点，段间空一行，提升可读性。",
}


def clip(text, limit=DETAIL_MAX):
    """压缩空白并截尾，保证报告 detail 单行可读。"""
    flat = re.sub(r"\s+", " ", (text or "")).strip()
    if len(flat) > limit:
        flat = flat[: limit - 3] + "..."
    return flat


# ---------------------------------------------------------------- 解析 ----

def parse_document(raw):
    """返回 (title, body_text, paragraphs)。

    标题 = 首个 '# ' 一级标题行的内容；没有一级标题时取首个非空行（不剔除）。
    正文 = 去掉该标题行后的全部文本；段落 = 正文按空行分块。
    """
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title = None
    title_idx = None
    for i, line in enumerate(lines):
        m = re.match(r"^#\s+(.+?)\s*$", line)
        if m:
            title, title_idx = m.group(1), i
            break
        if line.strip() and title is None and not line.strip().startswith("#"):
            # 没有标准一级标题：用首个非空非标题行充当标题，但正文保留原行
            title = line.strip()
            title_idx = i
            break
    if title is None:
        title = ""
    body_lines = [ln for j, ln in enumerate(lines) if j != title_idx]
    body_text = "\n".join(body_lines).strip()
    blocks = []
    for blk in re.split(r"\n\s*\n", body_text):
        blk = blk.strip()
        if blk:
            blocks.append(blk)
    return title, body_text, blocks


def visible_len(text):
    """去空白后的可见字符数（含标点、emoji、#）。"""
    return len(re.sub(r"\s+", "", text))


def count_emoji(text):
    """emoji 计数：按 emoji 码点逐个统计（ZWJ 组合表情按组成码点分别计）。"""
    return len(EMOJI_RE.findall(text))


def count_tags(text):
    """#标签 计数：排除 markdown 标题行，'#' 后紧跟非空白才算。"""
    n = 0
    for line in text.split("\n"):
        if HEADING_RE.match(line):
            continue
        n += len(TAG_RE.findall(line))
    return n


# ---------------------------------------------------------------- 检查项 ----

def check_title_length(title, cfg):
    lo, hi = cfg["title"]
    n = visible_len(title)
    ok = lo <= n <= hi
    if n == 0:
        return ok, "未找到标题（文件为空或只有空行）"
    if ok:
        return ok, "标题 %d 字，在区间 [%d, %d] 内：%s" % (n, lo, hi, clip(title, 60))
    return ok, "标题 %d 字，超出区间 [%d, %d]：%s" % (n, lo, hi, clip(title, 60))


def check_emoji_density(text, cfg):
    n = count_emoji(text)
    if cfg["emoji_mode"] == "range":
        lo, hi = cfg["emoji_range"]
        if lo <= n <= hi:
            return True, False, "emoji 共 %d 个，在区间 [%d, %d] 内" % (n, lo, hi)
        side = "不足" if n < lo else "超出"
        return False, False, "emoji 共 %d 个，%s区间 [%d, %d]" % (n, side, lo, hi)
    hi = cfg["emoji_max"]
    if n > hi:
        return True, True, "emoji 共 %d 个，超过上限 %d（仅警告，不计失败）" % (n, hi)
    return True, False, "emoji 共 %d 个，未超上限 %d" % (n, hi)


def check_body_length(body_text, cfg):
    lo, hi = cfg["body"]
    n = visible_len(body_text)
    ok = lo <= n <= hi
    return ok, "正文 %d 字（去空白），%s区间 [%d, %d]" % (
        n, "在" if ok else "超出", lo, hi)


def check_paragraph_max(paragraphs, cfg):
    limit = cfg["paragraph_max"]
    if not paragraphs:
        return False, "正文没有可检段落"
    lens = [visible_len(p) for p in paragraphs]
    mx = max(lens)
    idx = lens.index(mx) + 1
    ok = mx <= limit
    return ok, "共 %d 段，最长第 %d 段 %d 字（上限 %d）：%s" % (
        len(paragraphs), idx, mx, limit, clip(paragraphs[idx - 1], 80))


def check_tag_count(text, cfg):
    lo, hi = cfg["tags"]
    n = count_tags(text)
    ok = lo <= n <= hi
    if n == 0:
        return ok, "未发现 #标签，要求区间 [%d, %d]" % (lo, hi)
    return ok, "#标签 共 %d 个，%s区间 [%d, %d]" % (n, "在" if ok else "超出", lo, hi)


def check_banned_words(text):
    lower = text.lower()
    hits = {}
    for w in BANNED_WORDS:
        c = lower.count(w)
        if c > 0:
            hits[w] = c
    if hits:
        ordered = sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))
        detail = "命中 %d 个极限词（共 %d 次）：%s" % (
            len(ordered), sum(hits.values()),
            "、".join("%s×%d" % (w, c) for w, c in ordered))
        return False, detail
    return True, "未命中 %d 词内置极限词表" % len(BANNED_WORDS)


def check_structure_hook(title, paragraphs, text, cfg):
    first_para = paragraphs[0] if paragraphs else ""
    probe = title + "\n" + first_para
    hit = [w for w in HOOK_WORDS if w in probe]
    if "？" in probe or "?" in probe:
        hit = hit + ["？(问句)"]
    if cfg["emoji_mode"] == "range" and count_emoji(title) > 0:
        hit = hit + ["标题带emoji"]
    if hit:
        return True, "有钩子（%s）：%s" % (
            "、".join(hit[:5]), clip(first_para or title, 60))
    return False, "标题与首段未见钩子（钩子词/问句/xhs标题emoji 均未命中）"


def check_structure_cta(body_text):
    hit = [w for w in CTA_WORDS if w in body_text]
    if hit:
        return True, "有 CTA（%s）" % "、".join(hit[:6])
    return False, "正文未见 CTA 引导词（%s 等）" % "、".join(CTA_WORDS[:6])


def check_structure_para(paragraphs, cfg):
    need = cfg["min_paragraphs"]
    n = len(paragraphs)
    if n >= need:
        return True, "正文分 %d 段，≥ 最少要求 %d 段" % (n, need)
    return False, "正文仅分 %d 段，少于最少要求 %d 段" % (n, need)


# ---------------------------------------------------------------- 报告 ----

def build_report(input_path, platform, cfg, checks):
    fails = [c for c in checks if not c["pass_"]]
    warns = [c for c in checks if c["pass_"] and c.get("warning")]
    passed = len(checks) - len(fails)
    return {
        "tool": "%s %s" % (TOOL_NAME, TOOL_VERSION),
        "input": os.path.abspath(input_path),
        "platform": platform,
        "platform_label": cfg["label"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {
            "applied": len(checks),
            "pass": passed,
            "fail": len(fails),
            "warn": len(warns),
        },
        "score": {
            "passed": passed,
            "applied": len(checks),
            "ratio": round(passed / len(checks), 4) if checks else 0.0,
            "text": "%d/%d" % (passed, len(checks)),
        },
        "checks": [
            {"name": c["name"],
             "pass": c["pass_"],
             "warning": c.get("warning", False),
             "detail": c["detail"]}
            for c in checks
        ],
    }


def write_report_md(report, out_dir):
    s = report["summary"]
    lines = ["# 内容评测报告（%s · %s）" % (
        report["platform_label"], os.path.basename(report["input"])), ""]
    lines.append("- 输入文件：`%s`" % report["input"])
    lines.append("- 平台：%s（%s）" % (report["platform"], report["platform_label"]))
    lines.append("- 生成时间：%s（%s）" % (report["generated_at"], report["tool"]))
    lines.append("- **总分：%s**（%.1f%%）" % (
        report["score"]["text"], report["score"]["ratio"] * 100))
    lines.append("- 汇总：应检 %d 项，通过 %d / 失败 %d / 警告 %d" % (
        s["applied"], s["pass"], s["fail"], s["warn"]))
    lines.append("")
    lines.append("| 检查项 | 结果 | 说明 |")
    lines.append("|---|---|---|")
    for c in report["checks"]:
        if not c["pass"]:
            mark = "❌ FAIL"
        elif c["warning"]:
            mark = "⚠️ WARN"
        else:
            mark = "✅ PASS"
        lines.append("| `%s` | %s | %s |" % (
            c["name"], mark, c["detail"].replace("|", "\\|")))
    lines.append("")
    lines.append("## 修改建议")
    lines.append("")
    failed = [c for c in report["checks"] if not c["pass"]]
    warned = [c for c in report["checks"] if c["pass"] and c["warning"]]
    if not failed and not warned:
        lines.append("- 全部通过，无需修改。")
    else:
        for c in failed:
            lines.append("- **%s**：%s" % (c["name"], ADVICE[c["name"]]))
        for c in warned:
            lines.append("- **%s**（警告，不计失败）：%s" % (c["name"], ADVICE[c["name"]]))
    lines.append("")
    path = os.path.join(out_dir, "REPORT.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return path


def read_input(path):
    with open(path, "rb") as f:
        raw_bytes = f.read()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", raw_bytes, 0, 1, "无法按 utf-8/gbk 解码")


def main(argv):
    ap = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="新媒体内容确定性评测：标题/emoji/正文/段落/标签/极限词/结构")
    ap.add_argument("--input", required=True, help="待评测 markdown 文件")
    ap.add_argument("--platform", required=True, choices=sorted(PLATFORMS),
                    help="目标平台：dy=抖音 / xhs=小红书 / wx=微信公众号")
    ap.add_argument("--out", required=True, help="报告输出目录")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.input):
        print("错误：--input 不是文件: %s" % args.input, file=sys.stderr)
        return 2
    cfg = PLATFORMS[args.platform]
    os.makedirs(args.out, exist_ok=True)

    try:
        raw = read_input(args.input)
    except UnicodeDecodeError as exc:
        print("错误：输入文件无法解码: %s" % exc, file=sys.stderr)
        return 2

    title, body_text, paragraphs = parse_document(raw)
    full_text = title + "\n" + body_text if title else body_text

    checks = []
    ok, detail = check_title_length(title, cfg)
    checks.append(dict(name="title_length", pass_=ok, detail=detail))
    ok, warn, detail = check_emoji_density(full_text, cfg)
    checks.append(dict(name="emoji_density", pass_=ok, warning=warn, detail=detail))
    ok, detail = check_body_length(body_text, cfg)
    checks.append(dict(name="body_length", pass_=ok, detail=detail))
    ok, detail = check_paragraph_max(paragraphs, cfg)
    checks.append(dict(name="paragraph_max", pass_=ok, detail=detail))
    ok, detail = check_tag_count(full_text, cfg)
    checks.append(dict(name="tag_count", pass_=ok, detail=detail))
    ok, detail = check_banned_words(full_text)
    checks.append(dict(name="banned_words", pass_=ok, detail=detail))
    ok, detail = check_structure_hook(title, paragraphs, full_text, cfg)
    checks.append(dict(name="structure_hook", pass_=ok, detail=detail))
    ok, detail = check_structure_cta(body_text)
    checks.append(dict(name="structure_cta", pass_=ok, detail=detail))
    ok, detail = check_structure_para(paragraphs, cfg)
    checks.append(dict(name="structure_para", pass_=ok, detail=detail))

    report = build_report(args.input, args.platform, cfg, checks)
    json_path = os.path.join(args.out, "report.json")
    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    md_path = write_report_md(report, args.out)

    s = report["summary"]
    print("[%s] %s -> 总分 %s（通过 %d / 失败 %d / 警告 %d）" % (
        cfg["label"], os.path.basename(args.input),
        report["score"]["text"], s["pass"], s["fail"], s["warn"]))
    print("report.json -> %s" % json_path)
    print("REPORT.md   -> %s" % md_path)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
