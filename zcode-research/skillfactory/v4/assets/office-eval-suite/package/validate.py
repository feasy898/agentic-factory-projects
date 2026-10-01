#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate.py — office-eval-suite package 套件结构校验器（v2）

契约（contract.md §3，语义 = spec.md §4.1 R1–R8）:
    用法:   python validate.py --suite <suite.json 路径> [--out <报告输出路径>]
    --suite 必填；--out 缺省写 <脚本所在目录>/out/validate.json
    stdout:  逐项 [PASS]/[FAIL] <name>: <detail> + 汇总行（ALL GREEN ✓ / FAILED ✗）
    报告:    {tool, asset, suite, generated_at, ok,
              summary:{validator_checks:{total,passed,failed}, items, domains,
                       difficulty, checks_in_suite},
              checks:[{name, passed, detail}]}
    退出码:  0 = 恰 9 项且全过；1 = 任一失败（前序失败按依赖跳过，跳过项不入 checks）

九项检查（名称冻结，按依赖顺序执行）:
    load_json → schema_top → { schema_items / ids_unique / domain_ratio /
                               difficulty_distribution / instruction_quality /
                               instructions_distinct / checks_shape }
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
ASSET = "skillfactory/v4/assets/office-eval-suite/package"

# ---------------------------------------------------------------- 冻结常量（spec.md §4.1 R1–R8）
DOMAIN_TARGET = {  # 八域精确配比（R4，总计 50）
    "doc-writing": {"label": "文档写作", "target": 8},
    "table-data": {"label": "表格数据", "target": 6},
    "meeting-minutes": {"label": "会议纪要", "target": 6},
    "ppt-outline": {"label": "PPT要点", "target": 5},
    "email-comm": {"label": "邮件沟通", "target": 7},
    "process-spec": {"label": "流程规范", "target": 6},
    "info-extraction": {"label": "信息抽取", "target": 6},
    "rewrite-polish": {"label": "改写润色", "target": 6},
}
TOTAL_EXPECTED = 50
DIFFICULTIES = ("易", "中", "难")
DIFF_MAJOR = "中"
TOP_KEYS = {"version", "description", "items"}                     # R1
ITEM_KEYS = {"id", "domain", "difficulty", "instruction", "checks"}  # R2
CHECK_KEYS = {"name", "desc", "type", "value"}                     # R8
CHECK_TYPES = {"contains", "regex", "semantic"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")
MATERIAL_CUES = ["如下", "材料", "背景", "原文", "要点", "数据", "记录", "笔记", "素材",
                 "时间线", "规则", "条文", "条款", "对话", "邮件", "说明", "简历", "议程"]  # R6，18 词
INSTR_MIN_LEN, INSTR_MAX_LEN = 80, 2000
CHECKS_MIN, CHECKS_MAX = 3, 5
DESC_MAX = 300
DETAIL_PROBLEM_CAP = 8  # detail 里最多罗列的问题条数


def _cap(problems: list[str]) -> str:
    shown = problems[:DETAIL_PROBLEM_CAP]
    suffix = f" …（共 {len(problems)} 处，仅列前 {DETAIL_PROBLEM_CAP} 处）" if len(problems) > DETAIL_PROBLEM_CAP else ""
    return "; ".join(shown) + suffix


def normalize(s: str) -> str:
    """归一化：删除全部空白字符（R7 题干互异用）。"""
    return re.sub(r"\s+", "", s)


# ---------------------------------------------------------------- 九项检查
def check_load_json(path: Path) -> tuple[bool, str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"无法读取套件文件: {e}", None
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
        if it["domain"] not in DOMAIN_TARGET:
            problems.append(f"items[{idx}]({it.get('id', '?')}) domain 非法: {it['domain']!r}（不在八域枚举内）")
        if it["difficulty"] not in DIFFICULTIES:
            problems.append(f"items[{idx}]({it.get('id', '?')}) difficulty 非法: {it['difficulty']!r}（须为 {'|'.join(DIFFICULTIES)}）")
        if not isinstance(it["instruction"], str) or len(it["instruction"]) == 0:
            problems.append(f"items[{idx}]({it.get('id', '?')}) instruction 须为非空字符串")
        if not isinstance(it["checks"], list):
            problems.append(f"items[{idx}]({it.get('id', '?')}) checks 须为数组")
    if problems:
        return False, f"题目 schema 非法: {_cap(problems)}"
    return True, (f"{len(items)} 题键集恰为 {sorted(ITEM_KEYS)}，id 正则/八域枚举/难度三档/"
                  f"instruction 非空/checks 数组全部合法")


def check_ids_unique(data: dict) -> tuple[bool, str]:
    items = [it for it in data.get("items", []) if isinstance(it, dict)]
    ids = [it.get("id") for it in items]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        return False, f"id 不唯一: {dups}"
    return True, f"{len(ids)} 个 id 全局唯一"


def check_domain_ratio(data: dict) -> tuple[bool, str]:
    items = data.get("items", [])
    counts = {d: 0 for d in DOMAIN_TARGET}
    unknown = Counter()
    for it in items:
        dom = it.get("domain") if isinstance(it, dict) else None
        if dom in counts:
            counts[dom] += 1
        else:
            unknown[repr(dom)] += 1
    problems = []
    for d, cfg in DOMAIN_TARGET.items():
        if counts[d] != cfg["target"]:
            problems.append(f"{cfg['label']}({d}) {counts[d]} 题 != 目标 {cfg['target']}")
    total = sum(counts.values())
    if total != TOTAL_EXPECTED:
        problems.append(f"总题数 {total} != 期望 {TOTAL_EXPECTED}")
    if unknown:
        problems.append(f"出现八域之外的 domain: {dict(unknown)}")
    detail = "、".join(f"{DOMAIN_TARGET[d]['label']}={counts[d]}/{DOMAIN_TARGET[d]['target']}" for d in DOMAIN_TARGET)
    detail = f"域配比: {detail}，共 {total} 题"
    if problems:
        return False, detail + "；问题: " + "; ".join(problems)
    return True, detail + "（八域精确配比，与 spec R4 一致）"


def check_difficulty_distribution(data: dict) -> tuple[bool, str]:
    items = data.get("items", [])
    per_diff: dict[str, Counter] = {d: Counter() for d in DOMAIN_TARGET}
    global_diff: Counter = Counter()
    for it in items:
        if not isinstance(it, dict):
            continue
        dom, diff = it.get("domain"), it.get("difficulty")
        if dom in per_diff and diff in DIFFICULTIES:
            per_diff[dom][diff] += 1
            global_diff[diff] += 1
    problems = []
    for d, cnt in per_diff.items():
        label = DOMAIN_TARGET[d]["label"]
        n_dom = sum(cnt.values())
        missing = [t for t in DIFFICULTIES if cnt[t] < 1]
        if missing:
            problems.append(f"{label}({d}) 缺难度档: {'、'.join(missing)}")
        if n_dom > 0 and cnt[DIFF_MAJOR] * 2 <= n_dom:
            problems.append(f"{label}({d}) 中档 {cnt[DIFF_MAJOR]}/{n_dom} 未占多数（须 >50%）")
    g_total = sum(global_diff.values())
    if g_total > 0 and global_diff[DIFF_MAJOR] * 2 <= g_total:
        problems.append(f"全局中档 {global_diff[DIFF_MAJOR]}/{g_total} 未占多数（须 >50%）")
    detail = ("难度分布: " + "；".join(
        f"{DOMAIN_TARGET[d]['label']} 易{per_diff[d]['易']}/中{per_diff[d]['中']}/难{per_diff[d]['难']}"
        for d in DOMAIN_TARGET)
        + f"；全局 易{global_diff['易']}/中{global_diff['中']}/难{global_diff['难']}")
    if problems:
        return False, detail + "；问题: " + "; ".join(problems)
    return True, detail + "（每域三档齐备且中档占多数，全局中档占多数）"


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
            problems.append(f"{sid}: 未发现材料标记（cue 表: {'/'.join(MATERIAL_CUES[:9])}…共{len(MATERIAL_CUES)}词）")
            continue
        n_ok += 1
    if problems:
        return False, f"题干自含性不合格 {len(problems)} 题: {_cap(problems)}"
    return True, f"{n_ok} 题 instruction 长度均在 [{INSTR_MIN_LEN}, {INSTR_MAX_LEN}] 且含材料标记（18 词 cue 表）"


def check_instructions_distinct(data: dict) -> tuple[bool, str]:
    items = [it for it in data.get("items", []) if isinstance(it, dict)]
    norm: list[str] = []
    for it in items:
        instr = it.get("instruction")
        norm.append(normalize(instr) if isinstance(instr, str) else repr(instr))
    dups = sorted({s for s in norm if norm.count(s) > 1})
    if dups:
        ids = [it.get("id", "?") for it, s in zip(items, norm) if s in dups]
        return False, f"{len(dups)} 组归一化后完全相同的 instruction，涉及 id: {ids[:DETAIL_PROBLEM_CAP]}"
    return True, f"{len(set(norm))} 条 instruction 去空白归一化后两两互异"


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
    return True, (f"全卷 {n_checks} 条 check：每题数量 {CHECKS_MIN}-{CHECKS_MAX}、name 合法且题内唯一、"
                  f"desc 1-{DESC_MAX} 字、type 枚举（缺省 semantic）、contains/regex value 非空、regex 可编译，全部合法")


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="office-eval-suite package 套件结构校验器")
    ap.add_argument("--suite", required=True, help="suite.json 路径")
    ap.add_argument("--out", default=None, help="报告输出路径（缺省 <脚本目录>/out/validate.json）")
    args = ap.parse_args()
    suite_path = Path(args.suite)

    checks: list[dict] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")

    # 依赖链: load_json → schema_top → 其余七项（相互独立，均防御式实现）
    data: object = None
    ok1, detail1, data = check_load_json(suite_path)
    record("load_json", ok1, detail1)

    ok2, detail2 = (False, "前置失败：suite.json 未加载") if data is None else check_schema_top(data)
    if data is not None:
        record("schema_top", ok2, detail2)

    if data is not None and ok2:
        for name, fn in (
            ("schema_items", check_schema_items),
            ("ids_unique", check_ids_unique),
            ("domain_ratio", check_domain_ratio),
            ("difficulty_distribution", check_difficulty_distribution),
            ("instruction_quality", check_instruction_quality),
            ("instructions_distinct", check_instructions_distinct),
            ("checks_shape", check_checks_shape),
        ):
            ok_i, detail_i = fn(data)  # type: ignore[arg-type]
            record(name, ok_i, detail_i)

    total = len(checks)
    n_passed = sum(1 for c in checks if c["passed"])
    ok = total == 9 and n_passed == total

    items = data.get("items", []) if isinstance(data, dict) else []
    n_items = len(items) if isinstance(items, list) else 0
    domains = {d: 0 for d in DOMAIN_TARGET}
    difficulty = {t: 0 for t in DIFFICULTIES}
    checks_in_suite = 0
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        dom, diff = it.get("domain"), it.get("difficulty")
        if isinstance(dom, str):
            domains[dom] = domains.get(dom, 0) + 1
        if diff in difficulty:
            difficulty[diff] += 1
        cks = it.get("checks")
        if isinstance(cks, list):
            checks_in_suite += len(cks)

    items_label = f"{n_items} 题 / {checks_in_suite} 条 check" if n_items else "前置失败，后续检查按依赖跳过"
    verdict = "ALL GREEN ✓" if ok else "FAILED ✗"
    print(f"{verdict}（{n_passed}/{total} 项校验通过，{items_label}）")

    report = {
        "tool": TOOL,
        "asset": ASSET,
        "suite": str(suite_path),
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "ok": ok,
        "summary": {
            "validator_checks": {"total": total, "passed": n_passed, "failed": total - n_passed},
            "items": n_items,
            "domains": domains,
            "difficulty": difficulty,
            "checks_in_suite": checks_in_suite,
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
