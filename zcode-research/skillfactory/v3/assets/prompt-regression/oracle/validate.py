#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate.py — prompt-regression 黄金集校验器（oracle 参照软件）

用法:
    python validate.py --golden golden.json
    python validate.py --golden golden.json --out out/validate.json

对黄金集做结构化校验，输出机器可读报告（默认 <脚本目录>/out/validate.json）。
校验项：
  C1 schema_top        顶层 JSON 结构合法（version / items，可选 description）
  C2 schema_items      每题字段与类型合法（恰含 id/domain/instruction/checks）
  C3 ids_unique        id 全局唯一
  C4 domain_coverage   六域齐全且各域题数≥下限，总题数=25
  C5 instruction       每题 instruction 长度适中且内含任务材料标记
  C6 checks_shape      每题 checks 3-5 条，且每条 check 结构可判定
全部通过 → ok=true，退出码 0；任一失败 → ok=false，退出码 1。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------- 常量与阈值
DOMAIN_MIN = {
    "doc-writing": {"label": "文档写作", "min": 6},
    "table-data": {"label": "表格数据", "min": 5},
    "meeting-minutes": {"label": "会议纪要", "min": 3},
    "ppt-outline": {"label": "PPT要点", "min": 3},
    "email-comm": {"label": "邮件沟通", "min": 4},
    "process-spec": {"label": "流程规范", "min": 4},
}
TOTAL_EXPECTED = 25
ITEM_KEYS = {"id", "domain", "instruction", "checks"}
TOP_KEYS_ALLOWED = {"version", "description", "items"}
TOP_KEYS_REQUIRED = {"version", "items"}

INSTR_MIN_LEN = 80    # 含任务材料的自含题干不会太短
INSTR_MAX_LEN = 2000  # 适中长度上限
MATERIAL_CUES = ["如下", "材料", "背景", "原文", "要点", "数据", "记录", "笔记", "素材", "「", "“"]

CHECKS_MIN, CHECKS_MAX = 3, 5
CHECK_KEYS_REQUIRED = {"name", "desc"}
CHECK_KEYS_ALLOWED = {"name", "desc", "type", "value"}
CHECK_TYPES = {"contains", "regex", "semantic"}

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
CHECK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")


# ---------------------------------------------------------------- 校验函数
def check_schema_top(data) -> tuple[bool, str, list]:
    """C1: 顶层结构。返回 (passed, detail, items)。"""
    if not isinstance(data, dict):
        return False, f"顶层必须是 JSON object，实际为 {type(data).__name__}", []
    keys = set(data.keys())
    missing = TOP_KEYS_REQUIRED - keys
    if missing:
        return False, f"顶层缺少必需键: {sorted(missing)}", []
    unknown = keys - TOP_KEYS_ALLOWED
    if unknown:
        return False, f"顶层出现未知键: {sorted(unknown)}（允许: {sorted(TOP_KEYS_ALLOWED)}）", []
    if not isinstance(data["version"], str) or not data["version"]:
        return False, "version 必须为非空字符串", []
    items = data["items"]
    if not isinstance(items, list) or not items:
        return False, "items 必须为非空数组", []
    if "description" in data and not isinstance(data["description"], str):
        return False, "description 必须为字符串", []
    return True, f"顶层结构合法（version={data['version']}，items={len(items)} 条）", items


def check_schema_items(items: list) -> tuple[bool, str, list]:
    """C2: 每题 schema。返回 (passed, detail, valid_items)。"""
    problems = []
    valid = []
    for i, it in enumerate(items):
        where = f"items[{i}]"
        if not isinstance(it, dict):
            problems.append(f"{where}: 必须为 object，实际为 {type(it).__name__}")
            continue
        keys = set(it.keys())
        if keys != ITEM_KEYS:
            problems.append(
                f"{where}: 键集合必须恰为 {sorted(ITEM_KEYS)}，"
                f"缺失 {sorted(ITEM_KEYS - keys)}，多余 {sorted(keys - ITEM_KEYS)}"
            )
            continue
        iid = it["id"]
        if not isinstance(iid, str) or not ID_RE.match(iid):
            problems.append(f"{where}.id 非法: {iid!r}（需匹配 {ID_RE.pattern}）")
            continue
        where = f"[{iid}]"
        if it["domain"] not in DOMAIN_MIN:
            problems.append(f"{where}.domain 非法: {it['domain']!r}（允许: {sorted(DOMAIN_MIN)}）")
            continue
        if not isinstance(it["instruction"], str) or not it["instruction"].strip():
            problems.append(f"{where}.instruction 必须为非空字符串")
            continue
        if not isinstance(it["checks"], list):
            problems.append(f"{where}.checks 必须为数组")
            continue
        valid.append(it)
    if problems:
        return False, f"{len(problems)} 处 schema 问题: " + "; ".join(problems[:5]) + ("…" if len(problems) > 5 else ""), valid
    return True, f"全部 {len(valid)} 题字段与类型合法（id/domain/instruction/checks）", valid


def check_ids_unique(valid: list) -> tuple[bool, str]:
    ids = [it["id"] for it in valid]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        return False, f"存在重复 id: {dup}"
    return True, f"{len(ids)} 个 id 全局唯一"


def check_domain_coverage(valid: list) -> tuple[bool, str, dict]:
    counts = {d: 0 for d in DOMAIN_MIN}
    for it in valid:
        counts[it["domain"]] += 1
    problems = []
    for d, cfg in DOMAIN_MIN.items():
        if counts[d] < cfg["min"]:
            problems.append(f"{cfg['label']}({d}) 仅 {counts[d]} 题 < 下限 {cfg['min']}")
    total = sum(counts.values())
    if total != TOTAL_EXPECTED:
        problems.append(f"总题数 {total} != 期望 {TOTAL_EXPECTED}")
    detail = "、".join(f"{DOMAIN_MIN[d]['label']}={counts[d]}/{DOMAIN_MIN[d]['min']}" for d in DOMAIN_MIN)
    detail = f"域覆盖: {detail}，共 {total} 题"
    if problems:
        return False, detail + "；问题: " + "; ".join(problems), counts
    return True, detail, counts


def check_instruction(valid: list) -> tuple[bool, str]:
    problems = []
    for it in valid:
        s = it["instruction"]
        n = len(s)
        if not (INSTR_MIN_LEN <= n <= INSTR_MAX_LEN):
            problems.append(f"{it['id']}: instruction 长度 {n} 超出 [{INSTR_MIN_LEN}, {INSTR_MAX_LEN}]")
            continue
        if not any(cue in s for cue in MATERIAL_CUES):
            problems.append(f"{it['id']}: instruction 未发现内嵌材料标记（ cues: {MATERIAL_CUES} ）")
    if problems:
        return False, f"{len(problems)} 题不合格: " + "; ".join(problems)
    lens = [len(it["instruction"]) for it in valid]
    return True, f"25 题 instruction 长度均在 [{INSTR_MIN_LEN},{INSTR_MAX_LEN}] 且含材料标记（min={min(lens)}, max={max(lens)} 字符）"


def check_checks_shape(valid: list) -> tuple[bool, str, dict]:
    problems = []
    total_checks = 0
    min_c, max_c = None, None
    for it in valid:
        cid = it["id"]
        checks = it["checks"]
        n = len(checks)
        total_checks += n
        min_c = n if min_c is None else min(min_c, n)
        max_c = n if max_c is None else max(max_c, n)
        if not (CHECKS_MIN <= n <= CHECKS_MAX):
            problems.append(f"{cid}: checks 共 {n} 条，超出 [{CHECKS_MIN},{CHECKS_MAX}]")
            continue
        seen_names = set()
        for j, c in enumerate(checks):
            where = f"{cid}.checks[{j}]"
            if not isinstance(c, dict):
                problems.append(f"{where}: 必须为 object")
                continue
            keys = set(c.keys())
            if not CHECK_KEYS_REQUIRED <= keys:
                problems.append(f"{where}: 缺少必需键 {sorted(CHECK_KEYS_REQUIRED - keys)}")
                continue
            unknown = keys - CHECK_KEYS_ALLOWED
            if unknown:
                problems.append(f"{where}: 未知键 {sorted(unknown)}")
                continue
            name = c["name"]
            if not isinstance(name, str) or not CHECK_NAME_RE.match(name):
                problems.append(f"{where}.name 非法: {name!r}")
            elif name in seen_names:
                problems.append(f"{where}.name 重复: {name}")
            seen_names.add(name)
            desc = c["desc"]
            if not isinstance(desc, str) or not (1 <= len(desc) <= 300):
                problems.append(f"{where}.desc 必须为 1-300 字符字符串")
            ctype = c.get("type", "semantic")
            if ctype not in CHECK_TYPES:
                problems.append(f"{where}.type 非法: {ctype!r}（允许: {sorted(CHECK_TYPES)}）")
                continue
            if ctype in {"contains", "regex"}:
                val = c.get("value")
                if not isinstance(val, str) or not val:
                    problems.append(f"{where}: type={ctype} 必须提供非空 value")
                    continue
                if ctype == "regex":
                    try:
                        re.compile(val)
                    except re.error as e:
                        problems.append(f"{where}.value 正则编译失败: {e}")
    detail = f"每题 checks 数量区间 [{min_c},{max_c}]，共 {total_checks} 条 check"
    if problems:
        return False, detail + f"；{len(problems)} 处问题: " + "; ".join(problems[:8]) + ("…" if len(problems) > 8 else ""), {"total": total_checks, "min": min_c, "max": max_c}
    return True, detail + "，全部结构可判定（name/desc 唯一且合法，contains/regex 均带可编译 value）", {"total": total_checks, "min": min_c, "max": max_c}


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="prompt-regression 黄金集校验器")
    ap.add_argument("--golden", required=True, help="golden.json 路径")
    ap.add_argument("--out", default=None, help="报告输出路径（默认: <脚本目录>/out/validate.json）")
    args = ap.parse_args()

    golden_path = Path(args.golden)
    out_path = Path(args.out) if args.out else Path(__file__).resolve().parent / "out" / "validate.json"

    results: list[dict] = []

    def record(name: str, passed: bool, detail: str) -> None:
        results.append({"name": name, "passed": bool(passed), "detail": detail})
        mark = "PASS" if passed else "FAIL"
        print(f"[{mark}] {name}: {detail}")

    # 读取
    try:
        raw = golden_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        load_ok, load_detail = True, f"JSON 解析成功（{golden_path}）"
    except FileNotFoundError:
        load_ok, load_detail = False, f"文件不存在: {golden_path}"
        data = None
    except json.JSONDecodeError as e:
        load_ok, load_detail = False, f"JSON 解析失败: {e}"
        data = None
    record("load_json", load_ok, load_detail)

    items: list = []
    if data is not None:
        ok, detail, items = check_schema_top(data)
        record("schema_top", ok, detail)
        if items:
            ok, detail, valid = check_schema_items(items)
            record("schema_items", ok, detail)
            if valid:
                record("ids_unique", *check_ids_unique(valid))
                ok, detail, counts = check_domain_coverage(valid)
                record("domain_coverage", ok, detail)
                record("instruction_quality", *check_instruction(valid))
                ok, detail, cstats = check_checks_shape(valid)
                record("checks_shape", ok, detail)

    all_ok = all(r["passed"] for r in results)
    passed_n = sum(1 for r in results if r["passed"])
    # 统计域计数（不依赖 detail 字符串）
    domain_counts = {d: 0 for d in DOMAIN_MIN}
    for it in items:
        if isinstance(it, dict) and it.get("domain") in domain_counts:
            domain_counts[it["domain"]] += 1
    checks_total = sum(len(it.get("checks", [])) for it in items if isinstance(it, dict))

    report = {
        "tool": "validate.py",
        "asset": "skillfactory/v3/assets/prompt-regression/oracle",
        "golden": str(golden_path),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ok": all_ok,
        "summary": {
            "validator_checks": {"total": len(results), "passed": passed_n, "failed": len(results) - passed_n},
            "items": len(items),
            "domains": domain_counts,
            "checks_in_golden": checks_total,
        },
        "checks": results,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("-" * 60)
    print(f"结果: {'ALL GREEN ✓' if all_ok else 'FAILED ✗'}（{passed_n}/{len(results)} 项校验通过，"
          f"{len(items)} 题 / {checks_total} 条 check）")
    print(f"报告: {out_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
