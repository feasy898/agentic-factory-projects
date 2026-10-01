#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
oracle.py — paper-to-skill 参照实现（oracle）。

把一篇 Markdown 来源（论文/规范/工程博客）做确定性结构切分（标题层级 / 列表 /
代码块），再按模板蒸馏出技能骨架：

    <outdir>/draft_skill/SKILL.md   front-matter + 能力范围 + 分步方法 + 常见坑 + 来源引用
    <outdir>/outline.json           结构统计（一级/二级标题数、列表要点数、代码块数、标题树等）

设计约束：
- 仅用 Python 标准库；
- 纯确定性：同一输入 + 同一参数 => 字节级相同的输出（无随机、无时间戳、无网络访问）。

命令行契约：
    python oracle.py --source <md> --outdir <dir> [--url <来源URL>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

GENERATOR = "oracle.py"
VERSION = "1.0.0"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
LIST_RE = re.compile(r"^(\s*)(?:([-*+])|(\d{1,9})[.)])\s+(.+)$")
FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*(.*)$")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

# 常见坑关键词（对候选句做大小写不敏感匹配）
PITFALL_KEYWORDS = [
    "must not", "do not", "don't", "cannot", "can't", "avoid", "never",
    "warning", "caution", "careful", "pitfall", "mistake", "invalid",
    "malicious", "security", "not recommended",
    "注意", "避免", "不要", "禁止", "切勿", "谨慎", "慎用", "坑",
]

MAX_STEPS = 8          # 分步方法最多展示的章节数
MAX_TOPICS = 8         # 能力范围最多展示的主题数
MAX_PITFALLS = 6       # 常见坑最多展示条数
BULLET_TRUNC = 90      # 子要点截断长度
PITFALL_TRUNC = 120    # 坑条目截断长度


def strip_leading_html_comment(lines: list[str]) -> list[str]:
    """去掉文件头部的 HTML 注释块（我们给来源文件加的 provenance 头）。"""
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].lstrip().startswith("<!--"):
        while i < len(lines):
            if "-->" in lines[i]:
                return lines[i + 1:]
            i += 1
    return lines


def parse_markdown(text: str) -> dict:
    """结构切分：标题 / 列表项 / 围栏代码块 / 表格行。围栏内的内容不参与解析。"""
    raw_lines = text.splitlines()

    # 跳过来源自身的 YAML front-matter（若有）
    body_lines = raw_lines
    if raw_lines and raw_lines[0].strip() == "---":
        for i in range(1, len(raw_lines)):
            if raw_lines[i].strip() == "---":
                body_lines = raw_lines[i + 1:]
                break

    body_lines = strip_leading_html_comment(body_lines)

    headings: list[dict] = []
    list_items: list[dict] = []
    code_blocks: list[dict] = []
    paragraphs: list[dict] = []
    table_rows = 0

    fence_marker: str | None = None
    fence_lang = ""
    fence_start = 0

    for offset, line in enumerate(body_lines, start=1):  # offset 为正文内 1 起行号
        fm = FENCE_RE.match(line)
        if fm:
            marker = fm.group(2)
            if fence_marker is None:
                fence_marker = marker[:3]
                info = fm.group(3).strip()
                fence_lang = info.split()[0] if info else ""
                fence_start = offset
            elif marker.startswith(fence_marker):
                code_blocks.append({
                    "lang": fence_lang,
                    "start_line": fence_start,
                    "end_line": offset,
                    "line_count": offset - fence_start + 1,
                })
                fence_marker, fence_lang = None, ""
            continue
        if fence_marker is not None:
            continue

        if TABLE_ROW_RE.match(line):
            if not TABLE_SEP_RE.match(line):
                table_rows += 1
            continue  # 表格行计入统计，但不作为标题/列表/段落候选

        hm = HEADING_RE.match(line)
        if hm:
            headings.append({
                "level": len(hm.group(1)),
                "text": hm.group(2).strip(),
                "line": offset,
            })
            continue

        lm = LIST_RE.match(line)
        if lm:
            list_items.append({
                "ordered": lm.group(3) is not None,
                "indent": len(lm.group(1).expandtabs(4)),
                "text": lm.group(4).strip(),
                "line": offset,
            })
            continue

        stripped = line.strip()
        if stripped:
            paragraphs.append({"text": stripped, "line": offset})

    if fence_marker is not None:  # 未闭合围栏：按文件结尾闭合
        code_blocks.append({
            "lang": fence_lang,
            "start_line": fence_start,
            "end_line": len(body_lines),
            "line_count": len(body_lines) - fence_start + 1,
        })

    return {
        "body_line_count": len(body_lines),
        "headings": headings,
        "list_items": list_items,
        "code_blocks": code_blocks,
        "paragraphs": paragraphs,
        "table_rows": table_rows,
    }


def pick_title(doc: dict, fallback: str) -> str:
    for h in doc["headings"]:
        if h["level"] == 1:
            return h["text"]
    if doc["headings"]:
        return doc["headings"][0]["text"]
    return fallback


def split_sections(doc: dict) -> list[dict]:
    """按二级标题（无二级则一级）切分章节，用于生成“分步方法”。"""
    levels = {h["level"] for h in doc["headings"]}
    lvl = 2 if 2 in levels else (1 if 1 in levels else 0)
    if not lvl:
        return []
    tops = [h for h in doc["headings"] if h["level"] == lvl]
    sections = []
    total = doc["body_line_count"]
    for i, h in enumerate(tops):
        start = h["line"]
        end = tops[i + 1]["line"] - 1 if i + 1 < len(tops) else total
        sections.append({"title": h["text"], "start": start, "end": end})
    return sections


def bullets_in(section: dict, doc: dict, limit: int = 2) -> list[str]:
    out = []
    for li in doc["list_items"]:
        if section["start"] <= li["line"] <= section["end"]:
            text = li["text"]
            if len(text) > BULLET_TRUNC:
                text = text[: BULLET_TRUNC - 1] + "…"
            out.append(text)
            if len(out) >= limit:
                break
    return out


def extract_pitfalls(doc: dict, limit: int = MAX_PITFALLS) -> list[dict]:
    """按文档顺序扫描 标题/列表项/段落，取含警示关键词的句子。"""
    candidates = []
    for h in doc["headings"]:
        candidates.append({"kind": "heading", "text": h["text"], "line": h["line"]})
    for li in doc["list_items"]:
        candidates.append({"kind": "list", "text": li["text"], "line": li["line"]})
    for p in doc["paragraphs"]:
        candidates.append({"kind": "para", "text": p["text"], "line": p["line"]})
    candidates.sort(key=lambda c: c["line"])

    pitfalls, seen = [], set()
    for c in candidates:
        low = c["text"].lower()
        if not any(k in low for k in PITFALL_KEYWORDS):
            continue
        key = low[:60]
        if key in seen:
            continue
        seen.add(key)
        text = c["text"]
        if len(text) > PITFALL_TRUNC:
            text = text[: PITFALL_TRUNC - 1] + "…"
        pitfalls.append({"text": text, "line": c["line"]})
        if len(pitfalls) >= limit:
            break
    return pitfalls


def slugify(title: str) -> str:
    """规范合规的 name：小写字母/数字/连字符，<=64，无首尾/连续连字符。"""
    t = re.sub(r"[^a-z0-9\-]+", "-", title.lower())
    t = re.sub(r"-{2,}", "-", t).strip("-")
    t = t[:64].rstrip("-")
    return t or "paper-to-skill"


def yaml_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_description(title: str, stats: dict) -> str:
    desc = (
        f"从源文档《{title}》确定性蒸馏的技能骨架：涵盖 {stats['h1_count']} 个一级主题、"
        f"{stats['h2_count']} 个二级主题、{stats['list_item_count']} 条列表要点与 "
        f"{stats['code_block_count']} 个代码块。适用场景：需要把该来源文档转化为可执行的 "
        f"SKILL.md 草稿时使用。"
    )
    if len(desc) > 1024:
        desc = desc[:1023] + "…"
    return desc


def render_skill_md(source_arg: str, outdir_arg: str, url: str | None,
                    title: str, doc: dict, stats: dict) -> str:
    name = slugify(title)
    desc = build_description(title, stats)

    meta_lines = [
        "metadata:",
        f"  generator: {GENERATOR}",
        f"  source: {yaml_quote(source_arg)}",
    ]
    if url:
        meta_lines.append(f"  source_url: {yaml_quote(url)}")

    lines: list[str] = []
    lines.append("---")
    lines.append(f"name: {name}")
    lines.append(f"description: {yaml_quote(desc)}")
    lines.extend(meta_lines)
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}（蒸馏骨架）")
    lines.append("")
    lines.append("> 由 `oracle.py` 从源文档确定性蒸馏生成（无随机、无时间戳、无网络访问）。")
    lines.append(f"> 重新生成：`python oracle.py --source {source_arg} --outdir {outdir_arg}`")
    lines.append("> 注：正式发布时，front-matter 的 `name` 须与技能目录名一致（agentskills.io 规范）。")
    lines.append("")

    # —— 能力范围 ——
    lines.append("## 能力范围")
    lines.append("")
    lines.append(
        f"- 源结构统计：{stats['line_count']} 行 / {stats['h1_count']} 个一级标题 / "
        f"{stats['h2_count']} 个二级标题 / {stats['list_item_count']} 条列表要点 / "
        f"{stats['code_block_count']} 个代码块"
    )
    seen_topics = set()
    topics = 0
    for h in doc["headings"]:
        if h["level"] not in (1, 2):
            continue
        if h["level"] == 1 and h["text"] == title:
            continue
        if h["text"] in seen_topics:
            continue
        seen_topics.add(h["text"])
        text = h["text"] if len(h["text"]) <= 60 else h["text"][:59] + "…"
        lines.append(f"  - {text}（原文 L{h['line']}）")
        topics += 1
        if topics >= MAX_TOPICS:
            break
    if topics == 0:
        lines.append("  - （源文档未检出 H1/H2 标题，请人工补充能力范围）")
    lines.append("- 结构细节（标题树 / 代码块语言分布）见 `../outline.json`。")
    lines.append("")

    # —— 分步方法 ——
    lines.append("## 分步方法")
    lines.append("")
    sections = split_sections(doc)
    if sections:
        for i, sec in enumerate(sections[:MAX_STEPS], start=1):
            sec_title = sec["title"] if len(sec["title"]) <= 60 else sec["title"][:59] + "…"
            lines.append(f"{i}. **{sec_title}**（原文 L{sec['start']}）")
            for b in bullets_in(sec, doc):
                lines.append(f"   - {b}")
        if len(sections) > MAX_STEPS:
            lines.append(f"   - ……（源文档共 {len(sections)} 节，此处仅展开前 {MAX_STEPS} 节）")
    else:
        ordered = [li for li in doc["list_items"] if li["ordered"] and li["indent"] == 0]
        if ordered:
            for i, li in enumerate(ordered[:MAX_STEPS], start=1):
                text = li["text"] if len(li["text"]) <= BULLET_TRUNC else li["text"][: BULLET_TRUNC - 1] + "…"
                lines.append(f"{i}. {text}（原文 L{li['line']}）")
        else:
            lines.append("1. 通读来源文档，人工梳理核心流程（源文档未检出可用标题/有序列表结构）。")
            lines.append("2. 将流程落成上面「能力范围」约束下的操作步骤。")
    lines.append("")

    # —— 常见坑 ——
    lines.append("## 常见坑")
    lines.append("")
    pitfalls = extract_pitfalls(doc)
    if pitfalls:
        for p in pitfalls:
            lines.append(f"- {p['text']}（原文 L{p['line']}）")
    else:
        lines.append("- （源文档未检出显式警示句；蒸馏时请人工补充常见坑。）")
    lines.append("")

    # —— 来源引用 ——
    lines.append("## 来源引用")
    lines.append("")
    lines.append(f"- 源文件：`{source_arg}`")
    if url:
        lines.append(f"- 来源 URL：{url}")
    lines.append(f"- 源标题：{title}")
    lines.append(
        f"- 结构统计：H1={stats['h1_count']}，H2={stats['h2_count']}，"
        f"列表要点={stats['list_item_count']}，代码块={stats['code_block_count']}"
        f"（完整统计见 `../outline.json`）"
    )
    lines.append(
        f"- 生成方式：`{GENERATOR}` v{VERSION} 确定性蒸馏（仅标准库；无随机/时间戳/网络）；"
        f"命令：`python oracle.py --source {source_arg} --outdir {outdir_arg}`"
    )
    lines.append("")
    return "\n".join(lines)


def build_outline(source_arg: str, url: str | None, title: str, doc: dict, stats: dict) -> dict:
    root: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for h in doc["headings"]:
        node = {"level": h["level"], "text": h["text"], "line": h["line"], "children": []}
        while stack and stack[-1][0] >= h["level"]:
            stack.pop()
        (stack[-1][1]["children"] if stack else root).append(node)
        stack.append((h["level"], node))

    langs: dict[str, int] = {}
    for cb in doc["code_blocks"]:
        key = cb["lang"] if cb["lang"] else "plain"
        langs[key] = langs.get(key, 0) + 1

    outline = {
        "generator": GENERATOR,
        "generator_version": VERSION,
        "deterministic": True,
        "source": source_arg,
        "source_url": url,
        "source_title": title,
        "stats": stats,
        "outline": root,
    }
    return outline


def compute_stats(text: str, doc: dict) -> dict:
    headings = doc["headings"]
    return {
        "line_count": len(text.splitlines()),
        "char_count": len(text),
        "h1_count": sum(1 for h in headings if h["level"] == 1),
        "h2_count": sum(1 for h in headings if h["level"] == 2),
        "h3_count": sum(1 for h in headings if h["level"] == 3),
        "h4_to_h6_count": sum(1 for h in headings if h["level"] >= 4),
        "heading_count": len(headings),
        "list_item_count": len(doc["list_items"]),
        "unordered_list_item_count": sum(1 for li in doc["list_items"] if not li["ordered"]),
        "ordered_list_item_count": sum(1 for li in doc["list_items"] if li["ordered"]),
        "code_block_count": len(doc["code_blocks"]),
        "code_line_count": sum(cb["line_count"] for cb in doc["code_blocks"]),
        "code_block_languages": _code_block_languages(doc),
        "table_row_count": doc["table_rows"],
    }


def _code_block_languages(doc: dict) -> dict[str, int]:
    langs: dict[str, int] = {}
    for cb in doc["code_blocks"]:
        key = cb["lang"] if cb["lang"] else "plain"
        langs[key] = langs.get(key, 0) + 1
    return dict(sorted(langs.items()))


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        prog="oracle.py",
        description="paper-to-skill 参照实现：把 Markdown 来源确定性蒸馏成 SKILL.md 骨架 + outline.json 结构统计。",
    )
    ap.add_argument("--source", required=True, help="来源 Markdown 文件路径")
    ap.add_argument("--outdir", required=True, help="输出目录（生成 draft_skill/SKILL.md 与 outline.json）")
    ap.add_argument("--url", default=None, help="（可选）来源 URL，写入来源引用")
    args = ap.parse_args(argv)

    src = Path(args.source)
    if not src.is_file():
        print(f"[oracle] ERROR: source not found: {args.source}", file=sys.stderr)
        return 2

    text = src.read_text(encoding="utf-8-sig", errors="replace")
    doc = parse_markdown(text)
    title = pick_title(doc, src.stem)
    stats = compute_stats(text, doc)

    outdir = Path(args.outdir)
    skill_dir = outdir / "draft_skill"
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_md = render_skill_md(args.source, args.outdir, args.url, title, doc, stats)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(skill_md, encoding="utf-8", newline="\n")

    outline = build_outline(args.source, args.url, title, doc, stats)
    outline_path = outdir / "outline.json"
    outline_path.write_text(
        json.dumps(outline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )

    print(f"[oracle] source : {args.source}")
    print(f"[oracle] title  : {title}")
    print(f"[oracle] stats  : h1={stats['h1_count']} h2={stats['h2_count']} "
          f"lists={stats['list_item_count']} code_blocks={stats['code_block_count']}")
    print(f"[oracle] wrote  : {skill_path}")
    print(f"[oracle] wrote  : {outline_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
