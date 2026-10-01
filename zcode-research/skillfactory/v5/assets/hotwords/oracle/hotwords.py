#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hotwords.py — 单位热词表管理器（oracle 参照实现）

命令行契约：
    python hotwords.py [--store <json>] <add|list|remove|export> [参数...]

子命令：
    add <词> [--category 类别] [--note 备注] [--weight N]
        追加词条（词 + 类别 + 备注 + 权重）；词与库内既有词条完全同字即报重复，退出码 2。
        库文件不存在时自动新建。类别默认「默认」，备注默认空，权重默认 20。
    list
        按类别分组列出全部热词：类别按字典序排序，类别内保持入库插入序。
    remove <词>
        按词删除；词不存在则报错，退出码 2。
    export --format <funasr|plain> [--out 文件]
        导出热词。funasr：每行「词 权重」（权重缺省 20，FunASR 热词文件格式）；
        plain：每行一个词。省略 --out 时写到标准输出。

热词库 JSON 结构（version 固定 1）：
    {"version": 1,
     "words": [{"word": str, "category": str, "note": str, "weight": int}, ...]}

退出码：0 成功；2 失败（重复 / 不存在 / 库缺失或损坏 / format 非法 / 参数语法错误）。
参数语法错误由 argparse 报出（英文、退出码 2）；业务错误一律 stderr 中文报错。

确定性：无时间戳、无随机数、无网络。库内词条保持插入序，类别按字典序排序，
JSON 落盘固定 indent=2 + ensure_ascii=False + 末尾换行——同输入连跑两次，产物逐字节一致。
"""

import argparse
import json
import os
import sys

DEFAULT_CATEGORY = "默认"
DEFAULT_WEIGHT = 20
STORE_VERSION = 1


class StoreError(Exception):
    """业务错误：main 捕获后 stderr 中文报错并退出码 2。"""


def _force_utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def load_store(path, allow_missing=False):
    """读取并规整热词库。allow_missing=True 且文件不存在时返回空库（不落盘）。"""
    if not os.path.exists(path):
        if allow_missing:
            return {"version": STORE_VERSION, "words": []}
        raise StoreError("热词库不存在：%s" % path)
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        raise StoreError("热词库不可解析：%s（%s）" % (path, exc))
    return normalize(data, path)


def normalize(data, path):
    """校验并补全热词库结构，返回带全部四键的词条列表。"""
    if not isinstance(data, dict):
        raise StoreError("热词库顶层必须是 JSON 对象：%s" % path)
    version = data.get("version", STORE_VERSION)
    if version != STORE_VERSION:
        raise StoreError("热词库 version 不支持：%r（仅支持 %d）" % (version, STORE_VERSION))
    words = data.get("words", [])
    if not isinstance(words, list):
        raise StoreError("热词库 words 字段必须是数组：%s" % path)
    normalized = []
    for idx, item in enumerate(words, 1):
        if not isinstance(item, dict):
            raise StoreError("热词库第 %d 条词条必须是对象：%s" % (idx, path))
        word = item.get("word")
        if not isinstance(word, str) or not word.strip():
            raise StoreError("热词库第 %d 条词条缺少非空 word：%s" % (idx, path))
        category = item.get("category")
        if not (isinstance(category, str) and category.strip()):
            category = DEFAULT_CATEGORY
        note = item.get("note")
        if not isinstance(note, str):
            note = ""
        weight = item.get("weight", DEFAULT_WEIGHT)
        if isinstance(weight, bool) or not isinstance(weight, int):
            weight = DEFAULT_WEIGHT
        normalized.append({
            "word": word.strip(),
            "category": category.strip(),
            "note": note,
            "weight": weight,
        })
    return {"version": STORE_VERSION, "words": normalized}


def save_store(path, data):
    """落盘热词库：indent=2、ensure_ascii=False、末尾换行（确定性字节布局）。"""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def cmd_add(args):
    store = load_store(args.store, allow_missing=True)
    word = args.word.strip()
    if not word:
        raise StoreError("add：词不能为空")
    category = args.category.strip() or DEFAULT_CATEGORY
    for item in store["words"]:
        if item["word"] == word:
            raise StoreError("热词「%s」已存在（类别：%s），不可重复添加" % (word, item["category"]))
    store["words"].append({
        "word": word,
        "category": category,
        "note": args.note,
        "weight": args.weight,
    })
    save_store(args.store, store)
    line = "已添加：%s（类别：%s，权重：%d）" % (word, category, args.weight)
    if args.note:
        line += " 备注：%s" % args.note
    print(line)


def cmd_list(args):
    store = load_store(args.store)
    words = store["words"]
    if not words:
        print("（空库：共 0 词）")
        return 0
    groups = {}
    for item in words:
        groups.setdefault(item["category"], []).append(item)
    for category in sorted(groups):
        members = groups[category]
        print("[%s]（%d 词）" % (category, len(members)))
        for item in members:
            line = "  - %s  权重%d" % (item["word"], item["weight"])
            if item["note"]:
                line += "  %s" % item["note"]
            print(line)
    print("共 %d 词，%d 类" % (len(words), len(groups)))
    return 0


def cmd_remove(args):
    store = load_store(args.store)
    word = args.word.strip()
    if not word:
        raise StoreError("remove：词不能为空")
    for idx, item in enumerate(store["words"]):
        if item["word"] == word:
            del store["words"][idx]
            save_store(args.store, store)
            print("已删除：%s（类别：%s）" % (word, item["category"]))
            return 0
    raise StoreError("热词「%s」不存在，无法删除" % word)


def cmd_export(args):
    if args.format not in ("funasr", "plain"):
        raise StoreError("export：--format 仅支持 funasr|plain，收到 %r" % args.format)
    store = load_store(args.store)
    words = store["words"]
    lines = []
    for item in words:
        if args.format == "funasr":
            lines.append("%s %d" % (item["word"], item["weight"]))
        else:
            lines.append(item["word"])
    payload = "\n".join(lines) + ("\n" if lines else "")
    if args.out:
        parent = os.path.dirname(os.path.abspath(args.out))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
        print("已导出 %d 条热词 → %s（格式 %s）" % (len(words), args.out, args.format))
    else:
        sys.stdout.write(payload)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="hotwords.py",
        description="单位热词表管理器（oracle 参照实现）",
    )
    parser.add_argument("--store", default="store.json",
                        help="热词库 JSON 路径（默认 ./store.json，须写在子命令之前）")
    sub = parser.add_subparsers(dest="command", metavar="<add|list|remove|export>")

    p_add = sub.add_parser("add", help="追加词条（重复报错）")
    p_add.add_argument("word", help="热词")
    p_add.add_argument("--category", default=DEFAULT_CATEGORY, help="类别（默认「默认」）")
    p_add.add_argument("--note", default="", help="备注（默认空）")
    p_add.add_argument("--weight", type=int, default=DEFAULT_WEIGHT, help="权重（默认 20）")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="按类别分组列出")
    p_list.set_defaults(func=cmd_list)

    p_rm = sub.add_parser("remove", help="按词删除")
    p_rm.add_argument("word", help="要删除的热词")
    p_rm.set_defaults(func=cmd_remove)

    p_ex = sub.add_parser("export", help="导出 FunASR / 纯文本热词文件")
    p_ex.add_argument("--format", required=True, help="funasr|plain")
    p_ex.add_argument("--out", default=None, help="输出文件路径（省略则写标准输出）")
    p_ex.set_defaults(func=cmd_export)
    return parser


def main(argv=None):
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        parser.print_help(sys.stderr)
        print("错误：缺少子命令（add|list|remove|export）", file=sys.stderr)
        return 2
    try:
        return args.func(args) or 0
    except StoreError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
