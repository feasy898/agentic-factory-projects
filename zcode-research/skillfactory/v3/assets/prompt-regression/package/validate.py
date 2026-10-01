#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate.py — prompt-regression package 黄金集结构校验器

契约（contract.md §3，语义 = spec.md §4.1 R1–R6）:
    用法:   python validate.py --golden <golden.json 路径> [--out <报告输出路径>]
    --golden 必填；--out 缺省写 <脚本所在目录>/out/validate.json
    stdout:  逐项 [PASS]/[FAIL] <name>: <detail> + 汇总行（ALL GREEN ✓ / FAILED ✗）
    报告:    {tool, asset, golden, generated_at, ok,
              summary:{validator_checks:{total,passed,failed}, items, domains, checks_in_golden},
              checks:[{name, passed, detail}]}
    退出码:  0 = 全过；1 = 任一失败

七项检查（名称冻结，按依赖顺序执行；前序失败时后续按依赖跳过，跳过项不入 checks）:
    load_json → schema_top → { schema_items / ids_unique / domain_coverage /
                               instruction_quality / checks_shape }
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TOOL = "validate.py"
ASSET = "skillfactory/v3/assets/prompt-regression/package"

# ---------------------------------------------------------------- 冻结常量（spec.md §4.1 R1–R6）
DOMAIN_MIN = {
    "doc-writing": {"label": "文档写作", "min": 6},
    "table-data": {"label": "表格数据", "min": 5},
    "meeting-minutes": {"label": "会议纪要", "min": 3},
    "ppt-outline": {"label": "PPT要点", "min": 3},
    "email-comm": {"label": "邮件沟通", "min": 4},
    "process-spec": {"label": "流程规范", "min": 4},
}
TOTAL_EXPECTED = 25
TOP_KEYS = {"version", "description", "items"}
ITEM_KEYS = {"id", "domain", "instruction", "checks"}
CHECK_KEYS = {"name", "desc", "type", "value"}
CHECK_TYPES = {"contains", "regex", "semantic"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")
MATERIAL_CUES = ["如下", "材料", "背景", "原文", "要点", "数据", "记录", "笔记", "素材", "「", "“"]
INSTR_MIN_LEN, INSTR_MAX_LEN = 80, 2000
CHECKS_MIN, CHECKS_MAX = 3, 5
DESC_MAX = 300
DETAIL_PROBLEM_CAP = 8  # detail 里最多罗列的问题条数


def _cap(problems: list[str]) -> str:
    shown = problems[:DETAIL_PROBLEM_CAP]
    suffix = f" …（共 {len(problems)} 处，仅列前 {DETAIL_PROBLEM_CAP} 处）" if len(problems) > DETAIL_PROBLEM_CAP else ""
    return "; ".join(shown) + suffix


def check_load_json(path: Path) -> tuple[bool, str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"无法读取黄金集文件: {e}", None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return False, f"JSON 解析失败: {e}", None
    n_items = len(data.get("items", [])) if isinstance(data, dict) else 0
    return True, f"已加载（UTF-8 JSON 解析成功，items={n_items}）", data


def check_schema_top(data: object) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, f"顶层须为 object，实为 {type(data).__name__}"
    problems = []
    v = data.get("version")
    if not isinstance(v, str) or len(v) == 0:
        problems.append(f"version 须为非空字符串，实为 {v!r}")
    items = data.get("items")
    if not isinstance(items, list) or len(items) == 0:
        problems.append(f"items 须为非空数组，实为 {type(items).__name__}（len={len(items) if isinstance(items, list) else 'N/A'}）")
    unknown = sorted(set(data.keys()) - TOP_KEYS)
    if unknown:
        problems.append(f"存在未知顶层键: {unknown}（允许 {sorted(TOP_KEYS)}）")
    if problems:
        return False, "顶层结构非法: " + _cap(problems)
    return True, (f"顶层结构合法（version={v!r}，items={len(items)} 题，"
                  f"顶层键 {sorted(data.keys())} 均在允许集合内）")


def check_schema_items(data: dict) -> tuple[bool, str]:
    items = data.get("items", [])
    problems = []
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            problems.append(f"items[{idx}] 须为 object，实为 {type(it).__name__}")
            continue
        keys = set(it.keys())
        if keys != ITEM_KEYS:
            problems.append(f"items[{idx}]({it.get('id', '?')}) 键集非法: {sorted(keys)}（须恰为 {sorted(ITEM_KEYS)}）")
            continue
        if not isinstance(it["id"], str) or not ID_RE.match(it["id"]):
            problems.append(f"items[{idx}] id 非法: {it['id']!r}")
        if it["domain"] not in DOMAIN_MIN:
            problems.append(f"items[{idx}]({it.get('id', '?')}) domain 非法: {it['domain']!r}")
        if not isinstance(it["instruction"], str) or len(it["instruction"]) == 0:
            problems.append(f"items[{idx}]({it.get('id', '?')}) instruction 须为非空字符串")
        if not isinstance(it["checks"], list):
            problems.append(f"items[{idx}]({it.get('id', '?')}) checks 须为数组")
    if problems:
        return False, f"题目 schema 非法: {_cap(problems)}"
    return True, f"{len(items)} 题键集恰为 {sorted(ITEM_KEYS)}，id 正则/六域枚举/instruction 非空/checks 数组全部合法"


def check_ids_unique(data: dict) -> tuple[bool, str]:
    items = [it for it in data.get("items", []) if isinstance(it, dict)]
    ids = [it.get("id") for it in items]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        return False, f"id 不唯一: {dups}"
    return True, f"{len(ids)} 个 id 全局唯一（且均匹配 ID 正则的前提已在 schema_items 校验）"


def check_domain_coverage(data: dict) -> tuple[bool, str]:
    items = data.get("items", [])
    counts = {d: 0 for d in DOMAIN_MIN}
    unknown = Counter()
    for it in items:
        dom = it.get("domain") if isinstance(it, dict) else None
        if dom in counts:
            counts[dom] += 1
        else:
            unknown[repr(dom)] += 1
    problems = []
    for d, cfg in DOMAIN_MIN.items():
        if counts[d] < cfg["min"]:
            problems.append(f"{cfg['label']}({d}) 仅 {counts[d]} 题 < 下限 {cfg['min']}")
    total = sum(counts.values())
    if total != TOTAL_EXPECTED:
        problems.append(f"总题数 {total} != 期望 {TOTAL_EXPECTED}")
    if unknown:
        problems.append(f"出现六域之外的 domain: {dict(unknown)}")
    detail = "、".join(f"{DOMAIN_MIN[d]['label']}={counts[d]}/{DOMAIN_MIN[d]['min']}" for d in DOMAIN_MIN)
    detail = f"域配比: {detail}，共 {total} 题"
    if problems:
        return False, detail + "；问题: " + "; ".join(problems)
    return True, detail + "（与 spec R4 配比一致）"


def check_instruction_quality(data: dict) -> tuple[bool, str]:
    problems = []
    n_ok = 0
    for it in data.get("items", []):
        if not isinstance(it, dict):
            continue
        sid, instr = it.get("id", "?"), it.get("instruction")
        if not isinstance(instr, str):
            problems.append(f"{sid}: instruction 非字符串")
            continue
        n = len(instr)
        if not (INSTR_MIN_LEN <= n <= INSTR_MAX_LEN):
            problems.append(f"{sid}: 长度 {n} 超出 [{INSTR_MIN_LEN}, {INSTR_MAX_LEN}]")
            continue
        if not any(cue in instr for cue in MATERIAL_CUES):
            problems.append(f"{sid}: 未发现材料标记（cue 表: {'/'.join(MATERIAL_CUES[:9])}…）")
            continue
        n_ok += 1
    if problems:
        return False, f"题干自含性不合格 {len(problems)} 题: {_cap(problems)}"
    return True, f"{n_ok} 题 instruction 长度均在 [{INSTR_MIN_LEN}, {INSTR_MAX_LEN}] 且含材料标记"


def check_checks_shape(data: dict) -> tuple[bool, str]:
    problems = []
    n_checks = 0
    for it in data.get("items", []):
        if not isinstance(it, dict):
            continue
        sid, checks = it.get("id", "?"), it.get("checks")
        if not isinstance(checks, list):
            problems.append(f"{sid}: checks 非数组")
            continue
        n_checks += len(checks)
        if not (CHECKS_MIN <= len(checks) <= CHECKS_MAX):
            problems.append(f"{sid}: checks 数量 {len(checks)} 超出 [{CHECKS_MIN}, {CHECKS_MAX}]")
        seen_names: set[str] = set()
        for j, c in enumerate(checks):
            where = f"{sid}.checks[{j}]"
            if not isinstance(c, dict):
                problems.append(f"{where} 须为 object")
                continue
            unknown = sorted(set(c.keys()) - CHECK_KEYS)
            if unknown:
                problems.append(f"{where} 未知键: {unknown}（允许 {sorted(CHECK_KEYS)}）")
            name = c.get("name")
            if not isinstance(name, str) or not NAME_RE.match(name):
                problems.append(f"{where} name 非法: {name!r}")
            elif name in seen_names:
                problems.append(f"{where} name 题内重复: {name!r}")
            seen_names.add(name if isinstance(name, str) else f"<{j}>")
            desc = c.get("desc")
            if not isinstance(desc, str) or not (1 <= len(desc) <= DESC_MAX):
                problems.append(f"{where} desc 须为 1-{DESC_MAX} 字符字符串，实为 {desc!r}"[:160])
            ctype = c.get("type", "semantic")
            if ctype not in CHECK_TYPES:
                problems.append(f"{where} type 非法: {ctype!r}（允许 {sorted(CHECK_TYPES)}）")
                continue
            if ctype in ("contains", "regex"):
                v = c.get("value")
                if not isinstance(v, str) or len(v) == 0:
                    problems.append(f"{where} type={ctype} 须带非空字符串 value")
                elif ctype == "regex":
                    try:
                        re.compile(v)
                    except re.error as e:
                        problems.append(f"{where} regex 编译失败: {e}")
    if problems:
        return False, f"checks 形状不合格 {len(problems)} 处: {_cap(problems)}"
    return True, f"25 题共 {n_checks} 条 check：数量 3-5、name 合法且题内唯一、desc 1-{DESC_MAX} 字、type 枚举/缺省 semantic、contains/regex value 非空、regex 可编译，全部合法"


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="prompt-regression package 黄金集结构校验器")
    ap.add_argument("--golden", required=True, help="golden.json 路径")
    ap.add_argument("--out", default=None, help="报告输出路径（缺省 <脚本目录>/out/validate.json）")
    args = ap.parse_args()
    golden_path = Path(args.golden)

    checks: list[dict] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")

    # 依赖链: load_json → schema_top → 其余五项（相互独立，均防御式实现）
    data: object = None
    ok1, detail1, data = check_load_json(golden_path)
    record("load_json", ok1, detail1)

    ok2, detail2 = (False, "前置失败：golden.json 未加载") if data is None else check_schema_top(data)
    if data is not None:
        record("schema_top", ok2, detail2)

    if data is not None and ok2:
        for name, fn in (
            ("schema_items", check_schema_items),
            ("ids_unique", check_ids_unique),
            ("domain_coverage", check_domain_coverage),
            ("instruction_quality", check_instruction_quality),
            ("checks_shape", check_checks_shape),
        ):
            ok_i, detail_i = fn(data)  # type: ignore[arg-type]
            record(name, ok_i, detail_i)

    total = len(checks)
    n_passed = sum(1 for c in checks if c["passed"])
    ok = total == 7 and n_passed == total

    items = data.get("items", []) if isinstance(data, dict) else []
    n_items = len(items) if isinstance(items, list) else 0
    domains = {d: 0 for d in DOMAIN_MIN}
    checks_in_golden = 0
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        dom = it.get("domain")
        if isinstance(dom, str):
            domains[dom] = domains.get(dom, 0) + 1
        cks = it.get("checks")
        if isinstance(cks, list):
            checks_in_golden += len(cks)

    items_label = f"{n_items} 题 / {checks_in_golden} 条 check" if n_items else "前置失败，后续检查按依赖跳过"
    verdict = "ALL GREEN ✓" if ok else "FAILED ✗"
    print(f"{verdict}（{n_passed}/{total} 项校验通过，{items_label}）")

    report = {
        "tool": TOOL,
        "asset": ASSET,
        "golden": str(golden_path),
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "ok": ok,
        "summary": {
            "validator_checks": {"total": total, "passed": n_passed, "failed": total - n_passed},
            "items": n_items,
            "domains": domains,
            "checks_in_golden": checks_in_golden,
        },
        "checks": checks,
    }
    out_path = Path(args.out) if args.out else Path(__file__).resolve().parent / "out" / "validate.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"报告: {out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
