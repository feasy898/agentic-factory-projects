#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""acceptor-agent 确定性评测器（G0-1 绿 / G0-2 红 / exit 2 用法错）。

用法：
  python eval/runner.py <被测产物根> <oracle根>
  python eval/runner.py                  # 自评：被测=本资产根

被测产物根解析：<root>/package/agent.md + <root>/package/schema/verdict.schema.json
             + <root>/package/example-verdict.json。

四项检查（全过 exit 0；任一失败 exit 1；无时间戳，确定性）：
  1) agent_md_sections       agent.md 含全部冻结节（职责/输出契约/禁令）与禁令关键句
  2) schema_fields           verdict schema 顶层字段恰等 + verdict 枚举 + check 项字段恰等
  3) example_verdict_valid   example-verdict.json 按规则校验通过（枚举/必填/evidence 非空/status 枚举/PASS⇔无 blocker）
  4) no_employment_promise   全部文本文件（agent.md/schema/example）不出现就业/收益承诺措辞
红路：空目录或缺任一文件 → exit 1；永不修成 exit 0。
用法错：参数个数 ∉ {0, 2} → exit 2。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSET_ROOT = os.path.normpath(os.path.join(HERE, ".."))
DEFAULT_ORACLE = os.path.join(ASSET_ROOT, "oracle")


def evaluate(candidate_root, oracle_root):
    checks = []

    def fail(name, detail):
        checks.append({"name": name, "passed": False, "detail": detail})

    def ok(name, detail):
        checks.append({"name": name, "passed": True, "detail": detail})

    exp_path = os.path.join(oracle_root, "expectations.json")
    if not os.path.isfile(exp_path):
        fail("oracle_present", "oracle/expectations.json 不存在: %s" % exp_path)
        return False, checks
    with open(exp_path, "rb") as f:
        exp = json.loads(f.read().decode("utf-8-sig"))

    agent_md = os.path.join(candidate_root, "package", "agent.md")
    schema_p = os.path.join(candidate_root, "package", "schema", "verdict.schema.json")
    example_p = os.path.join(candidate_root, "package", "example-verdict.json")
    for label, p in (("agent.md", agent_md), ("verdict.schema.json", schema_p), ("example-verdict.json", example_p)):
        if not os.path.isfile(p):
            fail("files_present", "缺 %s: %s" % (label, p))
            return False, checks
    ok("files_present", "package 三件齐备（agent.md / schema/verdict.schema.json / example-verdict.json）")

    agent_text = open(agent_md, "rb").read().decode("utf-8-sig")
    miss = [s for s in exp["agent_md_required_sections"] if s not in agent_text]
    miss += [p for p in exp["agent_md_required_prohibition_phrases"] if p not in agent_text]
    if miss:
        fail("agent_md_sections", "缺节/缺禁令关键句：%r" % miss)
    else:
        ok("agent_md_sections", "职责/输出契约/禁令三节齐备，禁令关键句在场")

    try:
        schema = json.loads(open(schema_p, "rb").read().decode("utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        fail("schema_fields", "schema 解析失败：%s" % exc)
        return False, checks
    top = set(schema)
    want = set(exp["schema_required_top_fields"])
    if top != want:
        fail("schema_fields", "顶层字段不恰等：多 %r 缺 %r" % (sorted(top - want), sorted(want - top)))
    elif sorted(schema["verdict"]["enum"]) != sorted(exp["verdict_enum"]):
        fail("schema_fields", "verdict 枚举不符：%r" % (schema["verdict"].get("enum"),))
    elif sorted(schema["checks"]["item_required"]) != sorted(exp["check_item_required"]):
        fail("schema_fields", "check 项字段不符：%r" % (schema["checks"].get("item_required"),))
    else:
        ok("schema_fields", "顶层 5 字段恰等；verdict 枚举与 check 项字段符合冻结口径")

    try:
        verdict = json.loads(open(example_p, "rb").read().decode("utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        fail("example_verdict_valid", "example 解析失败：%s" % exc)
        return False, checks
    problems = []
    if verdict.get("verdict") not in exp["verdict_enum"]:
        problems.append("verdict 枚举非法")
    if not str(verdict.get("deliverable_path", "")).strip():
        problems.append("deliverable_path 空")
    cs = verdict.get("checks")
    if not isinstance(cs, list) or len(cs) < schema["checks"]["min_items"]:
        problems.append("checks 非数组或不足 min_items")
    else:
        for c in cs:
            if sorted(c) != sorted(exp["check_item_required"]):
                problems.append("check 项字段不符：%r" % sorted(c))
                break
            if not isinstance(c["passed"], bool):
                problems.append("passed 非布尔")
            if not str(c["evidence"]).strip():
                problems.append("evidence 空")
            if c["status"] not in exp["check_status_enum"]:
                problems.append("status 非法：%r" % (c["status"],))
    if verdict.get("verdict") == "PASS" and verdict.get("blockers"):
        problems.append("PASS 与非空 blockers 矛盾")
    if not str(verdict.get("boundary_note", "")).strip():
        problems.append("boundary_note 空")
    if problems:
        fail("example_verdict_valid", "example 校验失败：%s" % "；".join(problems))
    else:
        ok("example_verdict_valid", "example verdict 按契约校验通过（%d checks，全 verified）" % len(cs))

    blob = agent_text + open(schema_p, "rb").read().decode("utf-8-sig") + open(example_p, "rb").read().decode("utf-8-sig")
    banned = ["保证就业", "包就业", "稳赚", "收益承诺", "涨薪保证"]
    hit = [w for w in banned if w in blob]
    if hit:
        fail("no_employment_promise", "出现就业/收益承诺措辞：%r" % hit)
    else:
        ok("no_employment_promise", "零就业/收益承诺措辞（承诺边界守住）")

    return all(c["passed"] for c in checks), checks


def main(argv):
    if len(argv) == 0:
        candidate, oracle = ASSET_ROOT, DEFAULT_ORACLE
    elif len(argv) == 2:
        candidate, oracle = argv
    else:
        print("用法：python eval/runner.py [<被测产物根> <oracle根>]；零参数=自评", file=sys.stderr)
        return 2
    ok, checks = evaluate(candidate, oracle)
    print(json.dumps({
        "ok": ok,
        "summary": {
            "total": len(checks),
            "pass": sum(1 for c in checks if c["passed"]),
            "fail": sum(1 for c in checks if not c["passed"]),
            "tested_root": os.path.abspath(candidate),
            "reference_root": os.path.abspath(oracle),
        },
        "checks": checks,
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
