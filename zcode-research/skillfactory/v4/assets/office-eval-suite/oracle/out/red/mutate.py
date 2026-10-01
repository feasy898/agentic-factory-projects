#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mutate.py — 生成 8 个变异 suite（红灯测试夹具），输出到同目录 red-*.json"""
import json
import copy
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] / "suite.json"
OUT = Path(__file__).resolve().parent

base = json.loads(BASE.read_text(encoding="utf-8"))


def dump(name, suite):
    (OUT / f"{name}.json").write_text(json.dumps(suite, ensure_ascii=False), encoding="utf-8")


# 1 schema: 题目键集被破坏（instruction 键名拼错）
s = copy.deepcopy(base)
s["items"][0]["instrcution"] = s["items"][0].pop("instruction")
dump("red-schema", s)
# 2 唯一 id: dw-02 复制 dw-01 的 id
s = copy.deepcopy(base)
s["items"][1]["id"] = s["items"][0]["id"]
dump("red-dup-id", s)
# 3 配比: 把一个 doc-writing 题改成 rewrite-polish（8→7, 6→7）
s = copy.deepcopy(base)
s["items"][7]["domain"] = "rewrite-polish"
dump("red-ratio", s)
# 4 难度分布-缺档: mm-06（items[19]）难→中（会议纪要无「难」档）
s = copy.deepcopy(base)
s["items"][19]["difficulty"] = "中"
dump("red-diff-tier", s)
# 5 难度分布-多数: po-02（items[21]）中→易（PPT要点 易2/中2/难1，中不再占多数）
s = copy.deepcopy(base)
s["items"][21]["difficulty"] = "易"
dump("red-diff-majority", s)
# 6 材料缺失: instruction 缩短且无任何材料标记
s = copy.deepcopy(base)
s["items"][0]["instruction"] = "撰写一份通知，周五交。"
dump("red-material", s)
# 7 checks 数量: 删到 2 条（<3）
s = copy.deepcopy(base)
s["items"][0]["checks"] = s["items"][0]["checks"][:2]
dump("red-checkcount", s)
# 8 regex 不可编译
s = copy.deepcopy(base)
s["items"][0]["checks"][0]["value"] = "([未闭合"
dump("red-regex", s)
print("mutated:", sorted(p.name for p in OUT.glob("red-*.json")))
