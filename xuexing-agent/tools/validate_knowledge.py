"""知识库验证器：图谱/题库/误解库/母题库的合并完整性检查。

用法：python tools/validate_knowledge.py [--min-items-per-kp 3] [--min-mc-per-kp 2]
退出码 0=通过；非 0=有错误（错误清单打印到 stdout）。

图谱口径为 1-9 年级（math_grade1..math_grade9 模式化路径）：初中 7-9 是
存量主体库，缺文件视为错误；小学 1-6 待学段扩张落库（BACKLOG），缺位只
记 pending 不报错，落库后自动并入检查。
"""
import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from xuexing.itembank import itembank_from_dict  # noqa: E402
from xuexing.itembank_v2 import validate_bank_v2, verification_stats  # noqa: E402
from xuexing.kpgraph import kpgraph_from_dict  # noqa: E402
from xuexing.misconception_coverage import audit, parse_bank  # noqa: E402

GRADE_FILES = {
    grade: os.path.join(ROOT, "data", "knowledge", f"math_grade{grade}.json")
    for grade in range(1, 10)
}
# 存量主体（缺文件=错误）；1-6 年级文件允许缺位（落库前记 pending）。
CORE_GRADES = frozenset((7, 8, 9))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-items-per-kp", type=int, default=3)
    ap.add_argument("--min-mc-per-kp", type=int, default=2,
                    help="每个知识点最少的典型误解条数（或显式声明无误解）")
    args = ap.parse_args()
    errors: list[str] = []

    # ---------- 1) 知识点图谱：合并各年级文件（1-9；1-6 允许待落库） ----------
    merged_kps: list[dict] = []
    seen_kp: dict[str, str] = {}
    pending_grades: list[int] = []
    for grade, path in GRADE_FILES.items():
        if not os.path.exists(path):
            if grade in CORE_GRADES:
                errors.append(f"missing knowledge file: {path}")
            else:
                pending_grades.append(grade)
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for kp in data["knowledge_points"]:
            if kp["id"] in seen_kp:
                errors.append(f"duplicate kp id across files: {kp['id']} ({seen_kp[kp['id']]} & {path})")
                continue
            seen_kp[kp["id"]] = path
            merged_kps.append(kp)
            if not str(kp.get("standard_ref", "")).strip():
                errors.append(f"{kp['id']}: empty standard_ref")
            if not str(kp.get("description", "")).strip():
                errors.append(f"{kp['id']}: empty description")
            if not kp.get("cluster"):
                errors.append(f"{kp['id']}: empty cluster")
            if not 1 <= int(kp.get("grade", 0)) <= 9:
                errors.append(f"{kp['id']}: grade out of 1-9")

    graph = None
    if merged_kps:
        try:
            graph = kpgraph_from_dict({"knowledge_points": merged_kps})
            errs = graph.validate()
            errors.extend(f"kpgraph: {e}" for e in errs)
        except Exception as e:  # noqa: BLE001
            errors.append(f"kpgraph build failed: {e}")
    kp_ids = set(seen_kp)

    # ---------- 2) 题库：data/items/ 全量年级文件（glob 通配） ----------
    all_items = []
    seen_stem: dict[str, str] = {}
    seen_item: dict[str, str] = {}
    item_files = sorted(glob.glob(os.path.join(ROOT, "data", "items", "*.json")))
    if not item_files:
        errors.append("no item files found")
    for path in item_files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for it in data["items"]:
            if it["id"] in seen_item:
                errors.append(f"duplicate item id: {it['id']} ({seen_item[it['id']]} & {path})")
                continue
            seen_item[it["id"]] = path
            stem = str(it.get("stem", "")).strip()
            if stem in seen_stem:
                errors.append(f"duplicate stem: {it['id']} == {seen_stem[stem]}")
            else:
                seen_stem[stem] = it["id"]
            all_items.append(it)
    if all_items:
        bank = itembank_from_dict({"items": all_items})
        errs = bank.validate_all(valid_kp_ids=kp_ids)
        errors.extend(f"itembank: {e}" for e in errs)
        # schema v2 完整性：source 枚举/改编溯源/LLM 双代理验证记录
        errors.extend(f"item v2: {e}" for e in validate_bank_v2(all_items))
        # 覆盖率：每个知识点至少 N 道主知识点题
        primary_count: dict[str, int] = {}
        for it in all_items:
            kps = it.get("kps") or []
            if kps:
                primary_count[kps[0]] = primary_count.get(kps[0], 0) + 1
        for kp_id in sorted(kp_ids):
            n = primary_count.get(kp_id, 0)
            if n < args.min_items_per_kp:
                errors.append(f"coverage: {kp_id} has {n} primary items (< {args.min_items_per_kp})")

    # ---------- 3) 误解库：结构校验 + 覆盖门（每 KP ≥ N 条或显式声明无） ----------
    all_entries, all_exemptions = [], []
    mc_files = sorted(glob.glob(os.path.join(ROOT, "data", "misconceptions", "*.json")))
    if not mc_files:
        errors.append("no misconception files found")
    for path in mc_files:
        tag = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        try:
            entries, exemptions = parse_bank(data)
        except Exception as e:  # noqa: BLE001
            errors.append(f"misconception bank {tag}: {e}")
            continue
        all_entries.extend(entries)
        all_exemptions.extend(exemptions)
    mc_ids = {e.id for e in all_entries}
    try:
        rep = audit(kp_ids, all_entries, all_exemptions, min_per_kp=args.min_mc_per_kp)
        errors.extend(
            f"misconception coverage: {kp} has {count} (< {args.min_mc_per_kp}, "
            f"且无'无误解'声明)"
            for kp, count in rep.counts if kp in rep.deficient_kp_ids)
    except Exception as e:  # noqa: BLE001
        errors.append(f"misconception coverage: {e}")
    for it in all_items:
        for m in it.get("misconceptions", []):
            if m not in mc_ids:
                errors.append(f"{it['id']}: unknown misconception {m}")

    # ---------- 4) 母题库 ----------
    arch_files = sorted(glob.glob(os.path.join(ROOT, "data", "archetypes", "*.json")))
    if not arch_files:
        errors.append("no archetype files found")
    seen_arch: set[str] = set()
    arch_per_grade: dict[str, int] = {}
    for path in arch_files:
        grade_tag = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        count = 0
        for a in data.get("archetypes", []):
            if a["id"] in seen_arch:
                errors.append(f"duplicate archetype id: {a['id']}")
            seen_arch.add(a["id"])
            for field in ("name", "pattern", "example"):
                if not str(a.get(field, "")).strip():
                    errors.append(f"{a['id']}: empty {field}")
            if not a.get("kp_ids"):
                errors.append(f"{a['id']}: no kp_ids")
            for k in a.get("kp_ids", []):
                if k not in kp_ids:
                    errors.append(f"{a['id']}: unknown kp {k}")
            if not a.get("variant_axes"):
                errors.append(f"{a['id']}: no variant_axes")
            count += 1
        arch_per_grade[grade_tag] = count
        if count < 6:
            errors.append(f"{grade_tag}: only {count} archetypes (< 6)")

    # ---------- 输出 ----------
    if errors:
        print(f"VALIDATION FAILED: {len(errors)} errors")
        for e in errors[:80]:
            print(f"  - {e}")
        if len(errors) > 80:
            print(f"  ... and {len(errors) - 80} more")
        return 1
    total_items, verified_items = verification_stats(all_items)
    pending = (
        f", grades {','.join(map(str, pending_grades))} pending"
        if pending_grades else ""
    )
    print(
        f"VALIDATION OK: {len(kp_ids)} kps, {len(all_items)} items, "
        f"{len(mc_ids)} misconceptions (>= {args.min_mc_per_kp} per kp "
        f"or exempt, {len(all_exemptions)} exempt), {len(seen_arch)} archetypes, "
        f"schema v2 source ok, {verified_items}/{total_items} items dual-agent-verified"
        f"{pending}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
