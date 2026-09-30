#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hotwords.py — 单位热词表管理器（package 实现）

CLI 契约（冻结，见 ../contract.md §2.1 / ../spec.md §4.1 R1-R9 与附录 A）：

    python hotwords.py [--store <json>] <add|list|remove|export> [参数...]

- 库结构：{"version": 1, "words": [{"word","category","note","weight"}, ...]}，
  落盘 indent=2 + ensure_ascii=False + 末尾换行，UTF-8 无 BOM、\\n 行尾，词条保持插入序。
- 退出码：0 成功；2 业务失败（重复、不存在、库缺失或损坏、format 非法——stderr 中文，
  前缀「错误：」）与参数语法错误（argparse，英文）。
- 确定性：无时间戳、无随机数、无网络，同输入连跑两次所有输出逐字节一致。

自包含：仅依赖 Python 标准库。
"""

import argparse
import json
import os
import sys

STORE_VERSION = 1
DEFAULT_WEIGHT = 20
DEFAULT_CATEGORY = "默认"
FORMATS = ("funasr", "plain")


def force_utf8_stdio():
    """Windows 控制台缺省 GBK：统一 stdout/stderr 为 UTF-8、\\n 行尾（逐字节确定性的前提）。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    except Exception:
        pass


def fail(message):
    """业务报错：stderr 中文、前缀「错误：」、退出码 2（契约 R7）。"""
    sys.stderr.write("错误：%s\n" % message)
    sys.stderr.flush()
    raise SystemExit(2)


def normalize_store(data, path):
    """读入后规整（契约 R8）：非法结构即业务报错；缺省补「默认 / 空备注 / 权重 20」。

    词条以 word, category, note, weight 键序重建，保证落盘布局确定（spec 附录 A.5）。
    """
    if not isinstance(data, dict):
        fail("热词库顶层必须是 JSON 对象：%s" % path)
    if data.get("version") != STORE_VERSION:
        fail("热词库版本不支持：%s（须为 %d）" % (data.get("version"), STORE_VERSION))
    words = data.get("words")
    if not isinstance(words, list):
        fail("热词库 words 必须是数组：%s" % path)
    normalized = []
    for item in words:
        if not isinstance(item, dict):
            fail("热词库词条必须是 JSON 对象：%s" % path)
        word = item.get("word")
        if not isinstance(word, str) or not word.strip():
            fail("词条 word 必须是非空字符串：%r" % (item,))
        category = item.get("category")
        if not isinstance(category, str) or not category.strip():
            category = DEFAULT_CATEGORY
        note = item.get("note")
        if not isinstance(note, str):
            note = ""
        weight = item.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, int):
            weight = DEFAULT_WEIGHT
        normalized.append({"word": word, "category": category, "note": note, "weight": weight})
    return {"version": STORE_VERSION, "words": normalized}


def load_store(path, for_create=False):
    """读库并规整。

    库文件缺失：add（for_create=True）返回空库以自动新建（R3）；其余操作按 R7 判失败。
    读取容忍 UTF-8 BOM（R2）。
    """
    if not os.path.isfile(path):
        if for_create:
            return {"version": STORE_VERSION, "words": []}
        fail("热词库不存在：%s" % path)
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        fail("热词库不是有效的 UTF-8 文件：%s" % path)
    try:
        data = json.loads(text)
    except ValueError as exc:
        fail("热词库文件损坏，无法解析 JSON：%s（%s）" % (path, exc))
    return normalize_store(data, path)


def save_store(path, store):
    """落盘（契约 R2）：indent=2 + ensure_ascii=False + 末尾换行；UTF-8 无 BOM、\\n 行尾。

    以字节写入，避免平台换行翻译，保证逐字节确定性。
    """
    text = json.dumps(store, ensure_ascii=False, indent=2) + "\n"
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))


# ---------------------------------------------------------------- 子命令
def cmd_add(args):
    word = args.word.strip()
    if not word:
        fail("热词不能为空")
    store = load_store(args.store, for_create=True)
    for item in store["words"]:
        if item["word"] == word:
            fail("热词「%s」已存在（类别：%s），不可重复添加" % (word, item["category"]))
    category = args.category if args.category and args.category.strip() else DEFAULT_CATEGORY
    note = args.note if args.note else ""
    weight = DEFAULT_WEIGHT if args.weight is None else args.weight
    store["words"].append({"word": word, "category": category, "note": note, "weight": weight})
    save_store(args.store, store)
    message = "已添加：%s（类别：%s，权重：%d）" % (word, category, weight)
    if note:
        message += " 备注：%s" % note
    sys.stdout.write(message + "\n")


def cmd_list(args):
    store = load_store(args.store)
    words = store["words"]
    if not words:
        sys.stdout.write("（空库：共 0 词）\n")
        return
    groups = {}
    for item in words:
        groups.setdefault(item["category"], []).append(item)
    for category in sorted(groups):  # 类别字典序；组内保持插入序（R4）
        group = groups[category]
        sys.stdout.write("[%s]（%d 词）\n" % (category, len(group)))
        for item in group:
            line = "  - %s  权重%d" % (item["word"], item["weight"])
            if item["note"]:
                line += "  %s" % item["note"]
            sys.stdout.write(line + "\n")
    sys.stdout.write("共 %d 词，%d 类\n" % (len(words), len(groups)))


def cmd_remove(args):
    target = args.word.strip()
    if not target:
        fail("热词不能为空")
    store = load_store(args.store)
    words = store["words"]
    for index, item in enumerate(words):
        if item["word"] == target:
            removed = words.pop(index)
            save_store(args.store, store)
            sys.stdout.write("已删除：%s（类别：%s）\n" % (removed["word"], removed["category"]))
            return
    fail("热词「%s」不存在，无法删除" % target)


def cmd_export(args):
    if args.format not in FORMATS:
        fail("未知导出格式：%s（可选：%s、%s）" % (args.format, FORMATS[0], FORMATS[1]))
    store = load_store(args.store)
    words = store["words"]
    if args.format == "funasr":
        content = "".join("%s %d\n" % (item["word"], item["weight"]) for item in words)
    else:
        content = "".join("%s\n" % item["word"] for item in words)
    if args.out:
        with open(args.out, "wb") as f:
            f.write(content.encode("utf-8"))
        sys.stdout.write("已导出 %d 条热词 → %s（格式 %s）\n" % (len(words), args.out, args.format))
    else:
        sys.stdout.write(content)


# ---------------------------------------------------------------- 参数面
def build_parser():
    parser = argparse.ArgumentParser(
        prog="hotwords.py", description="单位热词表管理器：管理热词库（词/类别/备注/权重），"
                                        "支持增删查与 FunASR / 纯文本导出")
    parser.add_argument("--store", default="./store.json",
                        help="热词库 JSON 路径（默认 ./store.json，须写在子命令之前）")
    sub = parser.add_subparsers(dest="command", metavar="{add,list,remove,export}", required=True)

    p_add = sub.add_parser("add", help="追加热词（与既有词完全同字即报错，退出码 2）")
    p_add.add_argument("word", help="热词（strip 后须非空）")
    p_add.add_argument("--category", default=None, help="类别（默认「默认」）")
    p_add.add_argument("--note", default=None, help="备注（默认空）")
    p_add.add_argument("--weight", type=int, default=DEFAULT_WEIGHT, help="权重（默认 20）")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="按类别分组列出（类别字典序、组内插入序）")
    p_list.set_defaults(func=cmd_list)

    p_remove = sub.add_parser("remove", help="按词删除（不存在即报错，退出码 2）")
    p_remove.add_argument("word", help="要删除的热词")
    p_remove.set_defaults(func=cmd_remove)

    p_export = sub.add_parser("export", help="导出热词（--format 必填）")
    p_export.add_argument("--format", required=True,
                          help="导出格式：funasr（每行「词 权重」）| plain（每行一词）")
    p_export.add_argument("--out", default=None, help="输出文件路径（缺省写标准输出）")
    p_export.set_defaults(func=cmd_export)
    return parser


def main(argv=None):
    force_utf8_stdio()
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
