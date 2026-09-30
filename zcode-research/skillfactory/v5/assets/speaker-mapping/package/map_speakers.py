#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""map_speakers.py — 说话人标签映射工具（speaker-mapping 资产分发实现）

把「说话人分离（diarization）产出的转写稿」中的 SPEAKER_XX 标签替换为人名，
或扫描转写稿生成说话人清单与草稿映射。行为规格冻结于 ../spec.md（R1-R10），
接口契约见 ../contract.md §2；仅依赖 Python 标准库，无网络/无随机/无时间戳，
同一输入重复运行产物逐字节一致（确定性）。

用法：
    # 映射模式：按映射表把标签替换为人名
    python map_speakers.py --transcript T.txt --mapping m.json --out O.txt
    # 扫描模式：统计说话人与发言数，产出草稿映射（填名后可回喂 --mapping）
    python map_speakers.py --discover --transcript T.txt [--out draft.json]
    （扫描模式缺省打印 stdout，此时 stderr 为空；--out 时写文件并打 INFO 行）

退出码（实测口径，spec.md R6）：
    0  成功（含「有未映射标签，仅警告」）
    2  --transcript / --mapping 文件不存在；argparse 参数错误（含映射模式缺
       --mapping / --out）
    1  --mapping 不是合法 JSON，或顶层不是 JSON 对象
"""

import argparse
import json
import os
import re
import sys

TOOL = "map_speakers.py"

# R2（冻结）：行首锚定；可选先出现一个 [...] 段（时间戳）及其后空白；标签 token
# 为 ASCII 字母/下划线开头，后续仅字母/数字/下划线/横杠；冒号半角 : 或全角 ：，
# sep 含冒号后的空白。正文中段的 SPEAKER_xx: 不匹配（行首锚定，spec 探针 7）。
LABEL_RE = re.compile(
    r"^(?P<pre>\s*(?:\[[^\]]*\]\s*)?)(?P<label>[A-Za-z_][A-Za-z0-9_\-]*)(?P<sep>\s*[:：]\s*)"
)

_EOL_RE = re.compile(r"\r\n|\r|\n")


def _split_eol(line):
    """拆出一行为 (正文, 行尾)；行尾 ∈ {"\\r\\n", "\\n", "\\r", ""}，按原文保留（R3）。"""
    for eol in ("\r\n", "\n", "\r"):
        if line.endswith(eol):
            return line[:-len(eol)], eol
    return line, ""


def _split_lines(text):
    """按行切分并保留行尾（不丢任何字节；末行可能无行尾）。"""
    lines = []
    start = 0
    for m in _EOL_RE.finditer(text):
        lines.append(text[start:m.end()])
        start = m.end()
    if start < len(text):
        lines.append(text[start:])
    return lines


def _read_transcript(path):
    """读转写稿：utf-8-sig 容忍 BOM；newline='' 保留原始行尾（R3）。"""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return _split_lines(f.read())


def _write_text(path, text):
    """写出 UTF-8；newline='' 不做任何行尾翻译（R3 字节不变式）。"""
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _warn(msg):
    sys.stderr.write("[%s] WARNING: %s\n" % (TOOL, msg))


def _info(msg):
    sys.stderr.write("[%s] INFO: %s\n" % (TOOL, msg))


def _is_name(value):
    """映射值是否可用作人名：非空字符串（空字符串值视为未映射，spec R7）。"""
    return isinstance(value, str) and value != ""


def _die2(message):
    sys.stderr.write("[%s] 错误: %s\n" % (TOOL, message))
    return 2


def cmd_map(args):
    """映射模式（R3/R4/R5/R9）。"""
    if not os.path.isfile(args.transcript):
        return _die2("转写稿不存在: %s" % args.transcript)
    if not os.path.isfile(args.mapping):
        return _die2("映射文件不存在: %s" % args.mapping)
    try:
        with open(args.mapping, "r", encoding="utf-8-sig") as f:
            mapping = json.load(f)
    except Exception as exc:  # R6：非合法 JSON → SystemExit(str) 语义，exit 1
        raise SystemExit("[%s] 错误: 映射文件不是合法 JSON (%s)" % (TOOL, exc))
    if not isinstance(mapping, dict):
        raise SystemExit("[%s] 错误: 映射文件顶层必须是 JSON 对象" % TOOL)

    lines = _read_transcript(args.transcript)
    unmapped = {}    # label -> 出现次数（保持首次出现顺序）
    seen = set()     # 转写稿中出现过的全部标签（判定 R5「映射键未出现」）
    replaced = 0
    out_lines = []
    for line in lines:
        body, eol = _split_eol(line)
        m = LABEL_RE.match(body)
        if m is None:
            out_lines.append(line)          # 无标签行：整行原样保留
            continue
        label = m.group("label")
        seen.add(label)
        name = mapping.get(label)
        if _is_name(name):
            # R3：只替换 label span；pre（时间戳）/sep（冒号与空白）/正文逐字节不动
            out_lines.append(body[:m.start("label")] + name + body[m.end("label"):] + eol)
            replaced += 1
        else:
            out_lines.append(line)          # 未映射：原样保留（R3/R4）
            unmapped[label] = unmapped.get(label, 0) + 1

    _write_text(args.out, "".join(out_lines))

    for label, count in unmapped.items():   # R4：按标签汇总，一次一条
        _warn('未映射说话人标签 "%s"，出现 %d 次，已原样保留' % (label, count))
    for key, value in mapping.items():      # R5：非空值键在转写稿中未出现
        if _is_name(value) and key not in seen:
            _warn('映射键 "%s" 在转写稿中未出现' % key)
    _info("写出 %s（共 %d 行，替换标签 %d 处，未映射标签 %d 种）"
          % (args.out, len(lines), replaced, len(unmapped)))
    return 0


def cmd_discover(args):
    """扫描模式（R7/R9）。"""
    if not os.path.isfile(args.transcript):
        return _die2("转写稿不存在: %s" % args.transcript)
    order = []      # 首次出现顺序（partial 的 SPEAKER_03 排第 2 的判分要点）
    counts = {}
    total = 0
    for line in _read_transcript(args.transcript):
        body, _eol = _split_eol(line)
        m = LABEL_RE.match(body)
        if m is None:
            continue
        label = m.group("label")
        total += 1
        if label not in counts:
            counts[label] = 0
            order.append(label)
        counts[label] += 1
    speakers = [{"label": label, "utterances": counts[label]} for label in order]
    text = _format_discover(args.transcript, total, speakers)
    if args.out:
        _write_text(args.out, text)
        _info("发现 %d 个说话人标签 / %d 条发言，草稿映射已写出 %s"
              % (len(speakers), total, args.out))
    else:                                   # R1：缺省打印 stdout，此时 stderr 为空
        sys.stdout.write(text)
    return 0


def _format_discover(transcript, total, speakers):
    """R7 schema；产物形态 = json.dumps(..., ensure_ascii=False, indent=2) + 结尾换行，
    与 oracle 基线实文件逐字节一致（spec.md 附录 A.4 为转录件、与实文件有出入，
    以 eval/runner.py 检查 4 对照 oracle/out 实文件的判定为准；空列表/对象内联为
    json.dumps 固有行为，与 discover__empty.json 基线相符）。"""
    doc = {
        "transcript": transcript,
        "total_utterances": total,
        "speakers": speakers,
        "draft_mapping": {sp["label"]: "" for sp in speakers},
    }
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description="把转写稿中的说话人标签替换为人名（映射模式），"
                    "或扫描转写稿生成说话人清单与草稿映射（--discover）。")
    parser.add_argument("--transcript", required=True, help="转写稿路径（必填）")
    parser.add_argument("--mapping", help="映射 JSON 路径（映射模式必填）")
    parser.add_argument("--out", help="输出路径（映射模式必填；扫描模式缺省打印 stdout）")
    parser.add_argument("--discover", action="store_true",
                        help="扫描模式：统计说话人并产出草稿映射")
    args = parser.parse_args(argv)
    if args.discover:
        return cmd_discover(args)
    if not args.mapping or not args.out:
        # R1：映射模式还需 --mapping 与 --out（缺则 argparse exit 2）
        parser.error("映射模式需要 --mapping 与 --out（扫描请加 --discover）")
    return cmd_map(args)


if __name__ == "__main__":
    # stderr/stdout 强制 UTF-8：Windows 下重定向流缺省用本地编码（如 cp936），
    # 会让中文 WARNING 存档不再是 UTF-8 —— 确定性要求固定编码。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
