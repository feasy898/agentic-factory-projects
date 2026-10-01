"""双代理独立复验题库 CLI（BACKLOG P2「双代理独立复验题库」数据侧工具）。

对 data/items/*.json 全库运行双代理裁决（内核 src/xuexing/dual_verify.py）：
- 代理通道 --agent NAME=SPEC（可重复，须恰 >=2 个）：
    key          代理答案 = 库内标答（建模「其独立解题产物即标答」的历史通道，
                 如 M3 知识注入的独立审题员；manifest 里如实记录为 key 通道）；
    ledger:PATH  代理答案 = 独立解题台账（{"agent_id": NAME, "answers": {item_id: 答案}}）。
- 默认 dry-run：打印裁决摘要 + 写 data/verification/verify_manifest.json（运行清单）
  与 data/verification/arbitration_queue.json（分歧 → 人工仲裁队列；disagree 题
  一律不回填 verification）。
- --apply：把全部 agree 题的 {"agents": [...], "answers_agree": true} 回填进年级
  源文件（verification 键追加在题 dict 末尾；其余字段与行格式原样保留）。

用法：
  python tools/dual_agent_verify.py --agent m3-reviewer=key \
      --agent night-reverify-20260929=ledger:data/verification/ledger_night_20260929.json
  python tools/dual_agent_verify.py ... --apply
退出码：0=运行成功；2=用法/数据错误。
"""
import argparse
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from xuexing.dual_verify import (  # noqa: E402
    arbitration_rows,
    backfill_item,
    verify_bank,
    verification_record,
)
from xuexing.itembank_v2 import validate_bank_v2  # noqa: E402

GRADE_FILES = {
    7: os.path.join(ROOT, "data", "items", "math_grade7_items.json"),
    8: os.path.join(ROOT, "data", "items", "math_grade8_items.json"),
    9: os.path.join(ROOT, "data", "items", "math_grade9_items.json"),
}
VERIFICATION_DIR = os.path.join(ROOT, "data", "verification")
MANIFEST_PATH = os.path.join(VERIFICATION_DIR, "verify_manifest.json")
QUEUE_PATH = os.path.join(VERIFICATION_DIR, "arbitration_queue.json")


def load_grade_files():
    """[(grade, 原始 dict, items list)] 按年级升序。"""
    out = []
    for grade in sorted(GRADE_FILES):
        with open(GRADE_FILES[grade], encoding="utf-8") as f:
            data = json.load(f)
        out.append((grade, data, data["items"]))
    return out


def load_agent(name, spec, items):
    """解析一个代理通道 → (name, {item_id: answer}, source 描述)。"""
    if spec == "key":
        # key 通道：代理答案即库内标答（历史独立解题通道的诚实建模）。
        return name, {it["id"]: it["answer"] for it in items}, "key"
    if spec.startswith("ledger:"):
        path = os.path.abspath(os.path.join(ROOT, spec[len("ledger:"):]))
        if not os.path.exists(path):
            print(f"ledger not found: {path}", file=sys.stderr)
            sys.exit(2)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("agent_id") != name:
            print(f"ledger agent_id {data.get('agent_id')!r} != --agent name {name!r}", file=sys.stderr)
            sys.exit(2)
        answers = data.get("answers")
        if not isinstance(answers, dict):
            print(f"ledger {path}: missing answers dict", file=sys.stderr)
            sys.exit(2)
        return name, {k: v for k, v in answers.items() if isinstance(v, str)}, f"ledger:{os.path.relpath(path, ROOT)}"
    print(f"bad agent spec: {name}={spec}（须为 key 或 ledger:PATH）", file=sys.stderr)
    sys.exit(2)


def dump_grade(data):
    """保持源文件行格式：items 每题一行紧凑 JSON。"""
    lines = ",\n".join("    " + json.dumps(it, ensure_ascii=False) for it in data["items"])
    return '{\n  "items": [\n%s\n  ]\n}\n' % lines


def main():
    ap = argparse.ArgumentParser(description="双代理独立复验题库")
    ap.add_argument("--agent", action="append", required=True, metavar="NAME=SPEC",
                    help="key 或 ledger:PATH；至少两个")
    ap.add_argument("--apply", action="store_true", help="回填 verification 进年级源文件")
    ap.add_argument("--date", default=date.today().isoformat(), help="manifest 运行日期（默认今天）")
    args = ap.parse_args()

    grades = load_grade_files()
    items = [it for _, _, its in grades for it in its]
    ids = [it["id"] for it in items]
    if len(set(ids)) != len(ids):
        print("duplicate item ids across grade files", file=sys.stderr)
        return 2

    agents = {}
    for spec in args.agent:
        name, _, rest = spec.partition("=")
        if not name or not rest:
            print(f"bad --agent {spec!r}（须 NAME=SPEC）", file=sys.stderr)
            return 2
        if name in agents:
            print(f"duplicate agent name: {name}", file=sys.stderr)
            return 2
        loaded = load_agent(name, rest, items)
        missing = [i for i in ids if i not in loaded[1]]
        agents[name] = {"answers": loaded[1], "source": loaded[2], "missing": missing}
    if len(agents) < 2:
        print("need >=2 agents for dual verification", file=sys.stderr)
        return 2

    answers_by_item = {}
    for it in items:
        per_agent = {}
        for name, info in agents.items():
            per_agent[name] = info["answers"].get(it["id"])
        answers_by_item[it["id"]] = per_agent

    report = verify_bank(items, answers_by_item)
    rows = arbitration_rows(items, answers_by_item)

    counts = report.counts()
    print(f"dual verify: {len(items)} items | agree={counts['agree']} "
          f"disagree={counts['disagree']} incomplete={counts['incomplete']} | "
          f"agents={sorted(agents)}")
    for row in rows:
        print(f"  DISPUTE {row['item_id']}: key={row['key_answer']!r} "
              f"agent={row['agent']} proposed={row['proposed']!r}")

    os.makedirs(VERIFICATION_DIR, exist_ok=True)
    manifest = {
        "run_date": args.date,
        "tool": "tools/dual_agent_verify.py",
        "kernel": "xuexing.dual_verify",
        "agents": [
            {"id": name, "spec": info["source"],
             "answers": len(info["answers"]),
             "missing_item_ids": info["missing"]}
            for name, info in sorted(agents.items())
        ],
        "items_total": len(items),
        "counts": counts,
        "agreed_item_ids": list(report.agreed_item_ids),
        "disputed_item_ids": list(report.disputed_item_ids),
        "incomplete_item_ids": list(report.incomplete_item_ids),
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(QUEUE_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"note": "分歧=具体提案与标答不符；仲裁前不回填 verification",
                   "queue": list(rows)},
                  f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"manifest -> {os.path.relpath(MANIFEST_PATH, ROOT)}")
    print(f"arbitration queue ({len(rows)} rows) -> {os.path.relpath(QUEUE_PATH, ROOT)}")

    if args.apply:
        agree_set = set(report.agreed_item_ids)
        records = dict(report.records)
        applied = 0
        for grade, data, its in grades:
            changed = False
            for i, it in enumerate(its):
                if it["id"] in agree_set:
                    its[i] = backfill_item(it, records[it["id"]])
                    changed = True
                    applied += 1
            if changed:
                errs = validate_bank_v2(its)
                if errs:
                    print(f"refusing to write grade{grade}: v2 violations {errs[:3]}", file=sys.stderr)
                    return 2
                with open(GRADE_FILES[grade], "w", encoding="utf-8", newline="\n") as f:
                    f.write(dump_grade(data))
                print(f"backfilled grade{grade}: {os.path.relpath(GRADE_FILES[grade], ROOT)}")
        print(f"applied verification records: {applied}/{len(items)} "
              f"（disagree/incomplete 不回填）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
