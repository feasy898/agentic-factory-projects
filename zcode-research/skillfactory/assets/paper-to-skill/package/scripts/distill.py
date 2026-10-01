#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""distill.py — paper-to-skill 确定性蒸馏脚本（自研实现，行为按 spec.md R1–R7 冻结）。

CLI（contract §2.1，与参照实现同名同义）：
    python package/scripts/distill.py --source <来源.md> --outdir <输出目录> [--url <来源URL>]

产物（相对路径写死）：
    <outdir>/outline.json            结构统计 + 标题树（spec §5/R4/R5 的 8 顶层键 + 13 stats 键）
    <outdir>/draft_skill/SKILL.md    技能草稿（R6 五要素：front-matter/能力范围/分步方法/常见坑/来源引用）

实现边界：
  - 仅 Python 标准库；无随机、无时间戳、无网络访问（R7.1 同输入同参 → outline.json 字节一致）。
  - 不做语义摘要/改写：一切内容均为源文本的结构化摘取（标题/列表项/段落句）＋硬截断。
  - 源文件不存在/不可读 → stderr 含 ERROR、非 0 退出、不创建输出目录、不产出任何文件（R1.2）。

两个"格式冻结常量"的说明（均为 spec 明文规定，非本实现杜撰）：
  - GENERATOR_TAG = "oracle.py"：spec §5 冻结 outline.json 顶层 generator 键取值（同格式要求）；
  - stdout 前缀 "[oracle]"：spec R1.3 冻结成功输出为 5 行 "[oracle] ..."（等价实现口径，spec §0）。
  本脚本的真实身份在来源引用节的"生成方式"条目中如实标注（scripts/distill.py + 版本号）。
"""

import argparse
import json
import os
import re
import sys

VERSION = "1.0.0"                       # 本实现（package/scripts/distill.py）的版本
GENERATOR_TAG = "oracle.py"             # spec §5 冻结的产物 generator 标记
STDOUT_TAG = "oracle"                   # spec R1.3 冻结的 stdout 行前缀（[<tag>] ...）
FALLBACK_NAME = "paper-to-skill"        # spec R6.1：slug 为空时的回退技能名
REGEN_ENTRY = "package/scripts/distill.py"  # 重跑命令入口（spec §0.3 的验收姿势口径）

# ---------------------------------------------------------------------------
# 规则表（spec R3/R6 逐条对应的正则与关键词，措辞即口径）

RE_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")          # R3.1
RE_LIST = re.compile(r"^(\s*)(?:([-*+])|(\d{1,9})[.)])\s+(.+)$")  # R3.2
RE_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*(.*)$")              # R3.3
RE_TABLE_ROW = re.compile(r"^\|.*\|$")                           # R3.4（整行 |...|）
RE_TABLE_SEP = re.compile(r"^[\s|:\-]+$")                        # R3.4（分隔行）

# R6.5 警示关键词：16 英 + 8 中，共 24 个，大小写不敏感子串匹配
WARN_KEYWORDS = (
    "must not", "do not", "don't", "cannot", "can't", "avoid", "never",
    "warning", "caution", "careful", "pitfall", "mistake", "invalid",
    "malicious", "security", "not recommended",
    "注意", "避免", "不要", "禁止", "切勿", "谨慎", "慎用", "坑",
)


# ---------------------------------------------------------------------------
# 小工具

def clip(text, limit):
    """硬截断：超 limit 字符 → 前 limit-1 字符 + '…'（R6.3/R6.5 口径）。"""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def yaml_scalar(value):
    """R6.1 yaml_quote：\\ → \\\\ 、" → \\" ，外层双引号。"""
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def slugify(title):
    """R6.1：小写 → 非 [a-z0-9-] 连续段替换为 - → 折叠 - → 去首尾 - → 截 64 再去尾 - → 空则回退。"""
    s = re.sub(r"[^a-z0-9-]+", "-", title.lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    s = s[:64].rstrip("-")
    return s or FALLBACK_NAME


# ---------------------------------------------------------------------------
# R2 输入预处理

def load_text(path):
    """R2.1：utf-8-sig 读取（容忍 BOM），坏字节以 U+FFFD 替换；通用换行归一为 \\n。"""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        return fh.read()


def drop_own_frontmatter(lines):
    """R2.2：首行 strip 后恰为 --- 时跳到下一个 --- 行，取其后；无闭合则全文保留。"""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return lines[i + 1:]
    return lines


def drop_leading_comment(lines):
    """R2.3：跳过开头空行后，首行以 <!-- 开头则丢弃直到含 --> 的行（含）；未闭合不剥离。"""
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].startswith("<!--"):
        for j in range(i, len(lines)):
            if "-->" in lines[j]:
                return lines[j + 1:]
    return lines


# ---------------------------------------------------------------------------
# R3 结构切分（逐行扫描正文；围栏内的行不参与任何规则）

def scan(body_lines):
    headings, items, paragraphs, blocks = [], [], [], []
    table_rows = 0
    open_char = None          # 当前所处围栏的字符（` / ~）；None = 不在围栏内
    block = None              # {"language": str, "lines": int}

    for no, raw in enumerate(body_lines, 1):   # 正文内 1 起行号（R2.4）
        if open_char is not None:              # 围栏内：只找同字符闭围栏
            block["lines"] += 1
            m = RE_FENCE.match(raw)
            if m and m.group(1)[0] == open_char:
                blocks.append(block)
                block, open_char = None, None
            continue

        m = RE_FENCE.match(raw)                # 开围栏：语言取 info 首个空格前 token
        if m:
            info = m.group(2).strip()
            open_char = m.group(1)[0]
            block = {"language": info.split()[0] if info else "plain", "lines": 1}
            continue

        m = RE_HEADING.match(raw)              # 标题：# 必须在行首（引用块不算）
        if m:
            headings.append({"level": len(m.group(1)), "text": m.group(2).strip(), "line": no})
            continue

        m = RE_LIST.match(raw.expandtabs(4))   # 列表项：indent 按 tab=4 空格展开
        if m:
            items.append({
                "ordered": m.group(3) is not None,
                "indent": len(m.group(1)),
                "text": m.group(4).strip(),
                "line": no,
            })
            continue

        row = raw.strip()
        if RE_TABLE_ROW.match(row):            # 表格行只计数；分隔行不计；不进候选池
            if not RE_TABLE_SEP.match(row):
                table_rows += 1
            continue

        if row:                                # R3.5 段落候选
            paragraphs.append({"text": row, "line": no})

    if block is not None:                      # R3.3 未闭合围栏按文件结尾闭合
        blocks.append(block)

    return headings, items, paragraphs, blocks, table_rows


# ---------------------------------------------------------------------------
# R4 统计 / R5 标题树

def stats_of(full_text, headings, items, blocks, table_rows):
    h1 = sum(1 for h in headings if h["level"] == 1)
    h2 = sum(1 for h in headings if h["level"] == 2)
    h3 = sum(1 for h in headings if h["level"] == 3)
    h4p = len(headings) - h1 - h2 - h3
    ordered = sum(1 for it in items if it["ordered"])
    langs = {}
    for b in blocks:
        langs[b["language"]] = langs.get(b["language"], 0) + 1
    # stats 键固定 13 个、按 spec §5 表格顺序输出
    return {
        "line_count": len(full_text.splitlines()),   # 全文口径（含 front-matter/头注释，R2.4）
        "char_count": len(full_text),
        "h1_count": h1,
        "h2_count": h2,
        "h3_count": h3,
        "h4_to_h6_count": h4p,
        "heading_count": len(headings),
        "list_item_count": len(items),
        "unordered_list_item_count": len(items) - ordered,
        "ordered_list_item_count": ordered,
        "code_block_count": len(blocks),
        "code_line_count": sum(b["lines"] for b in blocks),   # 含首尾围栏标记行
        "code_block_languages": {k: langs[k] for k in sorted(langs)},
        "table_row_count": table_rows,
    }


def heading_tree(headings):
    """R5：栈构建——弹出所有 level ≥ 自身的栈顶，挂到剩余栈顶 children；栈空挂根。"""
    roots, stack = [], []
    for h in headings:
        node = {"level": h["level"], "text": h["text"], "line": h["line"], "children": []}
        while stack and stack[-1]["level"] >= h["level"]:
            stack.pop()
        (stack[-1]["children"] if stack else roots).append(node)
        stack.append(node)
    return roots


# ---------------------------------------------------------------------------
# R6 draft_skill/SKILL.md 生成

def pick_title(headings, source):
    """R6.2：第一个 H1 → 第一个任意级标题 → 源文件名 stem。"""
    for h in headings:
        if h["level"] == 1:
            return h["text"]
    if headings:
        return headings[0]["text"]
    return os.path.splitext(os.path.basename(source))[0]


def regen(args, include_url):
    cmd = "python %s --source %s --outdir %s" % (REGEN_ENTRY, args.source, args.outdir)
    if include_url and args.url:
        cmd += " --url %s" % args.url
    return cmd


def fm_lines(title, st, args):
    """R6.1 front-matter：name / description / metadata 三键。"""
    desc = ("从源文档《%s》确定性蒸馏的技能骨架：涵盖 %d 个一级主题、%d 个二级主题、"
            "%d 条列表要点与 %d 个代码块。适用场景：需要把该来源文档转化为可执行的 "
            "SKILL.md 草稿时使用。" % (title, st["h1_count"], st["h2_count"],
                                      st["list_item_count"], st["code_block_count"]))
    if len(desc) > 1024:
        desc = desc[:1023] + "…"
    out = ["---",
           "name: %s" % yaml_scalar(slugify(title)),
           "description: %s" % yaml_scalar(desc),
           "metadata:",
           "  generator: %s" % GENERATOR_TAG,
           "  source: %s" % yaml_scalar(args.source)]
    if args.url:
        out.append("  source_url: %s" % yaml_scalar(args.url))
    out.append("---")
    return out


def sec_scope(title, st, headings):
    """R6.3 能力范围：统计行 + ≤8 条 H1/H2 子 bullet + outline 指引。"""
    out = ["## 能力范围", "",
           "- 源结构：%d 行 / %d 个一级标题 / %d 个二级标题 / %d 条列表要点 / %d 个代码块。"
           % (st["line_count"], st["h1_count"], st["h2_count"],
              st["list_item_count"], st["code_block_count"])]
    seen, subs = set(), []
    for h in headings:
        if h["level"] not in (1, 2) or (h["level"] == 1 and h["text"] == title):
            continue
        if h["text"] in seen:
            continue
        seen.add(h["text"])
        subs.append("  - %s（原文 L%d）" % (clip(h["text"], 60), h["line"]))
        if len(subs) == 8:
            break
    if subs:
        out.extend(subs)
    else:
        out.append("  - （源文档没有可用的 H1/H2 标题，主题清单需人工补充。）")
    out.append("- 完整结构统计与标题树见 `../outline.json`。")
    return out


def sec_steps(headings, items):
    """R6.4 分步方法：三级回退（章节切片 → 顶层有序列表 → 固定通用两步）。"""
    out = ["## 分步方法", ""]
    level = 2 if any(h["level"] == 2 for h in headings) else (1 if any(h["level"] == 1 for h in headings) else None)

    if level is not None:                                   # 分支 1
        starts = [h for h in headings if h["level"] == level]
        total = len(starts)
        for n, h in enumerate(starts[:8], 1):
            end = next((o["line"] for o in headings
                        if o["line"] > h["line"] and o["level"] <= level), float("inf"))
            out.append("%d. **%s**（原文 L%d）" % (n, clip(h["text"], 60), h["line"]))
            for it in [x for x in items if h["line"] < x["line"] < end][:2]:
                out.append("   - %s" % clip(it["text"], 90))
        if total > 8:
            out.append("- 源文档共 %d 节，此处仅展开前 8 节。" % total)
        return out

    tops = [x for x in items if x["ordered"] and x["indent"] == 0]   # 分支 2
    if tops:
        for n, x in enumerate(tops[:8], 1):
            out.append("%d. %s（原文 L%d）" % (n, x["text"], x["line"]))
        return out

    out.append("1. 通读来源文档（`--source` 指向的 Markdown 全文），圈出可执行的方法、流程与判据。")  # 分支 3
    out.append("2. 将流程落成 `SKILL.md` 草稿，按五要素补全为可交付技能。")
    return out


def sec_pitfalls(headings, items, paragraphs):
    """R6.5 常见坑：候选池=标题+列表项+段落（不含表格行），命中警示词取前 6。"""
    pool = [(h["line"], h["text"]) for h in headings]
    pool += [(x["line"], x["text"]) for x in items]
    pool += [(p["line"], p["text"]) for p in paragraphs]
    pool.sort(key=lambda e: e[0])

    out = ["## 常见坑", ""]
    picked, seen = [], set()
    for no, text in pool:
        low = text.lower()
        if not any(k in low for k in WARN_KEYWORDS):
            continue
        key = text[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        picked.append("- %s（原文 L%d）" % (clip(text, 120), no))
        if len(picked) == 6:
            break
    if picked:
        out.extend(picked)
    else:
        out.append("- （源文档未命中警示关键词，常见坑需人工补充。）")
    return out


def sec_sources(title, st, args):
    """R6.6 来源引用：固定 4–5 条 bullet。"""
    out = ["## 来源引用", "", "- 源文件：%s" % args.source]
    if args.url:
        out.append("- 来源 URL：%s" % args.url)
    out.append("- 源标题：%s" % title)
    out.append("- 结构统计：H1 %d / H2 %d / 列表要点 %d / 代码块 %d，完整数据见 `../outline.json`。"
               % (st["h1_count"], st["h2_count"], st["list_item_count"], st["code_block_count"]))
    out.append("- 生成方式：paper-to-skill 包 scripts/distill.py v%s（产物 generator 标记按 spec §5 "
               "冻结为 %s；无网络/无随机/无时间戳，内容均为源文本结构化摘取）；完整重跑命令：%s"
               % (VERSION, GENERATOR_TAG, regen(args, include_url=True)))
    return out


def render_skill(title, st, headings, items, paragraphs, args):
    lines = []
    lines.extend(fm_lines(title, st, args))
    lines.append("")
    lines.append("# %s（蒸馏骨架）" % title)                     # R6.2 题头
    lines.append("")
    lines.append("> 本文件由 paper-to-skill 包 scripts/distill.py 从源文档确定性蒸馏生成："
                 "一切内容均为源文本的结构化摘取（标题/列表/段落），未做语义摘要或改写。")
    lines.append("> 重新生成：%s" % regen(args, include_url=bool(args.url)))
    lines.append("> 发布前核对：front-matter 的 name 必须与技能目录名一致，并按方法论补全为成品。")
    lines.append("")
    lines.extend(sec_scope(title, st, headings))
    lines.append("")
    lines.extend(sec_steps(headings, items))
    lines.append("")
    lines.extend(sec_pitfalls(headings, items, paragraphs))
    lines.append("")
    lines.extend(sec_sources(title, st, args))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主流程（R1 命令行契约）

def run(argv):
    ap = argparse.ArgumentParser(
        description="知识蒸馏器：把一篇 Markdown 来源确定性蒸馏成技能骨架（spec R1–R7）")
    ap.add_argument("--source", required=True, help="来源 Markdown 路径（必填）")
    ap.add_argument("--outdir", required=True, help="输出目录（不存在自动创建；已存在则复用）")
    ap.add_argument("--url", default=None, help="来源 URL（可选）")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.source):                    # R1.2：先于任何落盘动作
        sys.stderr.write("ERROR: source file not found: %s\n" % args.source)
        return 2
    try:
        full_text = load_text(args.source)
    except OSError as exc:
        sys.stderr.write("ERROR: cannot read source file %s: %s\n" % (args.source, exc))
        return 2

    body = drop_leading_comment(drop_own_frontmatter(full_text.splitlines()))   # R2.2 → R2.3
    headings, items, paragraphs, blocks, table_rows = scan(body)                # R3
    st = stats_of(full_text, headings, items, blocks, table_rows)               # R4
    title = pick_title(headings, args.source)

    outline = {                                            # spec §5：顶层键固定 8 个
        "generator": GENERATOR_TAG,
        "generator_version": VERSION,
        "deterministic": True,
        "source": args.source,
        "source_url": args.url,
        "source_title": title,
        "stats": st,
        "outline": heading_tree(headings),                 # R5
    }

    os.makedirs(args.outdir, exist_ok=True)               # R1.4：此处才创建输出目录（R1.2 失败路径已在上方返回）
    draft_dir = os.path.join(args.outdir, "draft_skill")
    os.makedirs(draft_dir, exist_ok=True)

    outline_path = os.path.join(args.outdir, "outline.json")
    with open(outline_path, "w", encoding="utf-8", newline="\n") as fh:   # R7：LF、无时间戳
        fh.write(json.dumps(outline, ensure_ascii=False, indent=2) + "\n")

    skill_path = os.path.join(draft_dir, "SKILL.md")
    with open(skill_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_skill(title, st, headings, items, paragraphs, args))

    # R1.3：stdout 恰好 5 行（source / title / stats / wrote ×2）
    print("[%s] source: %s" % (STDOUT_TAG, args.source))
    print("[%s] title: %s" % (STDOUT_TAG, title))
    print("[%s] stats: lines=%d chars=%d h1=%d h2=%d h3=%d h4plus=%d headings=%d lists=%d "
          "unordered=%d ordered=%d code_blocks=%d code_lines=%d tables=%d"
          % (STDOUT_TAG, st["line_count"], st["char_count"], st["h1_count"], st["h2_count"],
             st["h3_count"], st["h4_to_h6_count"], st["heading_count"], st["list_item_count"],
             st["unordered_list_item_count"], st["ordered_list_item_count"],
             st["code_block_count"], st["code_line_count"], st["table_row_count"]))
    print("[%s] wrote: %s" % (STDOUT_TAG, outline_path))
    print("[%s] wrote: %s" % (STDOUT_TAG, skill_path))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(run(sys.argv[1:]))
