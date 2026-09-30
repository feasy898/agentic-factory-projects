#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""map_speakers.py —— 说话人标签→人名 映射 CLI（oracle 参照实现）。

针对说话人分离（diarization）产出的转写稿：
    [00:00:05] SPEAKER_00: 各位下午好……
把行首的说话人标签替换为人名；时间戳、冒号与正文一律不动。
未映射的标签原样保留，并向 stderr 输出 WARNING。

用法：
    # 映射模式：标签→人名
    python map_speakers.py --transcript T.txt --mapping m.json --out O.txt

    # --discover 模式：扫描转写稿，列出全部说话人标签与发言条数，
    # 输出 JSON 草稿映射（默认打印到 stdout，--out 可写入文件）
    python map_speakers.py --discover --transcript T.txt [--out draft.json]

映射文件格式（JSON 对象）：
    {"SPEAKER_00": "王总", "SPEAKER_01": "李工"}
    键 = 转写稿中的说话人标签；值 = 人名（空字符串视为未映射）。

说话人标签判定：行首（允许先出现一个 [时间戳] 方括号段）紧跟
“ASCII 字母/下划线开头、仅含字母数字下划点横杠的 token + 半角/全角冒号”。
中文名（如“王总：”）不会被识别为标签，因此已映射的稿子再次执行是幂等的。

退出码：0 成功（含“有未映射标签仅警告”的情形）；2 输入/参数错误。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROG = "map_speakers.py"

# 行首：可选 [任意非]方括号段（时间戳）→ 说话人标签 → 半角/全角冒号
LABEL_RE = re.compile(
    r"^(?P<pre>\s*(?:\[[^\]]*\]\s*)?)"        # 可选时间戳段及其后空白
    r"(?P<label>[A-Za-z_][A-Za-z0-9_\-]*)"    # 说话人标签（ASCII 标识符样式）
    r"(?P<sep>\s*[:：]\s*)"                   # 冒号（半角/全角）及后随空白
)

WARNING_PREFIX = f"[{PROG}] WARNING"


def _split_eol(raw: str) -> tuple[str, str]:
    """把一行拆成 (正文, 行尾符)，行尾 \r\n / \n / 无 原样保留。"""
    body = raw.rstrip("\r\n")
    return body, raw[len(body):]


def read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:  # 容忍 BOM；保留原始行尾
        return f.read()


def load_mapping(path: Path) -> dict[str, str]:
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as e:
        raise SystemExit(f"[{PROG}] ERROR: 映射文件不是合法 JSON：{path}（{e}）")
    if not isinstance(data, dict):
        raise SystemExit(f"[{PROG}] ERROR: 映射文件顶层必须是 JSON 对象：{path}")
    return {str(k): "" if v is None else str(v) for k, v in data.items()}


def scan_lines(text: str):
    """逐行产出 (body, eol, match_or_None)，match 含 label 及各命名分组。"""
    for raw in text.splitlines(keepends=True):
        body, eol = _split_eol(raw)
        yield body, eol, LABEL_RE.match(body)


def do_map(transcript: Path, mapping_path: Path, out_path: Path) -> int:
    if not transcript.is_file():
        print(f"[{PROG}] ERROR: 转写稿不存在：{transcript}", file=sys.stderr)
        return 2
    if not mapping_path.is_file():
        print(f"[{PROG}] ERROR: 映射文件不存在：{mapping_path}", file=sys.stderr)
        return 2
    mapping = load_mapping(mapping_path)

    replaced = 0
    unmapped: dict[str, int] = {}      # 未映射标签 -> 出现次数（按首次出现顺序）
    mapped_labels: set[str] = set()
    out_lines: list[str] = []

    for body, eol, m in scan_lines(read_text(transcript)):
        if m is None:
            out_lines.append(body + eol)           # 无标签行：逐字节原样
            continue
        label = m.group("label")
        name = mapping.get(label, "")
        if name:
            # 只替换标签本身这一段，pre（时间戳）与 sep（冒号）及正文不动
            out_lines.append(body[: m.start("label")] + name + body[m.end("label"):] + eol)
            replaced += 1
            mapped_labels.add(label)
        else:
            out_lines.append(body + eol)           # 未映射：原样保留
            unmapped[label] = unmapped.get(label, 0) + 1

    if out_path.parent and not out_path.parent.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write("".join(out_lines))

    for label, n in unmapped.items():
        print(f'{WARNING_PREFIX}: 未映射说话人标签 "{label}"，出现 {n} 次，已原样保留',
              file=sys.stderr)
    for label in mapping:
        if label not in mapped_labels and mapping[label]:
            print(f'{WARNING_PREFIX}: 映射键 "{label}" 在转写稿中未出现', file=sys.stderr)
    total_lines = len(out_lines)
    print(f"[{PROG}] INFO: 写出 {out_path}（共 {total_lines} 行，替换标签 {replaced} 处，"
          f"未映射标签 {len(unmapped)} 种）", file=sys.stderr)
    return 0


def do_discover(transcript: Path, out_path: Path | None) -> int:
    if not transcript.is_file():
        print(f"[{PROG}] ERROR: 转写稿不存在：{transcript}", file=sys.stderr)
        return 2

    counts: dict[str, int] = {}        # 按首次出现顺序
    for body, _eol, m in scan_lines(read_text(transcript)):
        if m is not None:
            label = m.group("label")
            counts[label] = counts.get(label, 0) + 1

    result = {
        "transcript": str(transcript),
        "total_utterances": sum(counts.values()),
        "speakers": [
            {"label": label, "utterances": n} for label, n in counts.items()
        ],
        "draft_mapping": {label: "" for label in counts},
    }
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if out_path:
        if out_path.parent and not out_path.parent.exists():
            out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(payload + "\n")
        print(f"[{PROG}] INFO: 发现 {len(counts)} 个说话人标签 / "
              f"{result['total_utterances']} 条发言，草稿映射已写出 {out_path}", file=sys.stderr)
    else:
        print(payload)
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog=PROG,
        description="把转写稿中的说话人标签替换为人名；或用 --discover 扫描标签并生成草稿映射。",
    )
    parser.add_argument("--transcript", required=True, metavar="TXT", help="转写稿 .txt 路径")
    parser.add_argument("--mapping", metavar="JSON", help="映射 JSON（键=标签，值=人名）；映射模式必填")
    parser.add_argument("--out", metavar="PATH", help="输出文件：映射模式=替换后的 .txt；--discover 模式=草稿 JSON（缺省打印到 stdout）")
    parser.add_argument("--discover", action="store_true", help="扫描模式：列出说话人标签与发言条数，输出 JSON 草稿映射")
    args = parser.parse_args(argv)

    transcript = Path(args.transcript)
    out_path = Path(args.out) if args.out else None

    if args.discover:
        return do_discover(transcript, out_path)

    if not args.mapping:
        parser.error("映射模式需要 --mapping <json>（扫描请加 --discover）")
    if not args.out:
        parser.error("映射模式需要 --out <txt>")
    return do_map(transcript, Path(args.mapping), out_path)


if __name__ == "__main__":
    sys.exit(main())
