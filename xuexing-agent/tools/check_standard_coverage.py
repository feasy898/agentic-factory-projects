"""课标覆盖检查器：knowledge json 的 standard_ref 与课标主题清单对照，报告缺口。

用法：
  python tools/check_standard_coverage.py                          # 全年级（7/8/9）
  python tools/check_standard_coverage.py --grades 7,8             # 只查指定年级子库
  python tools/check_standard_coverage.py --format json            # 机读报告

对照双向缺口：
  覆盖缺口 = 清单条目没有任何 KP 的 standard_ref 归属到它；
  归属缺口 = KP 的 standard_ref 归属不到清单任何条目。
退出码：0=全归属且全覆盖；1=有缺口（清单见 stdout）；2=输入/数据错误。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from xuexing.standard_coverage import (  # noqa: E402
    StandardCoverageError,
    check_coverage_dicts,
)

DEFAULT_CURRICULUM = os.path.join(ROOT, "data", "curriculum", "math_standard_2022_topics.json")
DEFAULT_KNOWLEDGE_DIR = os.path.join(ROOT, "data", "knowledge")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _merge_kps(grades, knowledge_dir):
    """按年级序合并 knowledge_points；跨文件重复 id 视为数据错误。"""
    merged = []
    seen = {}
    for grade in grades:
        path = os.path.join(knowledge_dir, f"math_grade{grade}.json")
        if not os.path.exists(path):
            raise StandardCoverageError(f"missing knowledge file: {path}")
        data = _load(path)
        for kp in data["knowledge_points"]:
            kp_id = kp.get("id")
            if kp_id in seen:
                raise StandardCoverageError(
                    f"duplicate kp id across files: {kp_id} ({seen[kp_id]} & {path})")
            seen[kp_id] = path
            merged.append(kp)
    return merged


def _report_text(rep, grades, n_kps):
    lines = []
    lines.append(f"课标覆盖检查：库={len(grades)} 个年级文件 / {n_kps} 个知识点 × "
                 f"清单={len(rep.topics)} 条（{', '.join(sorted({t.domain for t in rep.topics}))}）")
    by_domain = {}
    for t in rep.topics:
        by_domain.setdefault(t.domain, []).append(t)
    counts = {m.kp_id: m.topic_ids for m in rep.matches}
    names = {t.id: t.name for t in rep.topics}
    for domain, topics in by_domain.items():
        lines.append(f"== {domain}")
        for t in topics:
            owners = [kp_id for kp_id, ids in counts.items() if t.id in ids]
            mark = "x" if owners else "!"
            detail = f"{len(owners)} 个知识点" if owners else "覆盖缺口：无知识点引用"
            lines.append(f"  [{mark}] {t.id} {t.name}（{t.theme}）— {detail}")
    if rep.unmatched_kp_ids:
        lines.append("== 归属缺口（standard_ref 归属不到任何条目）")
        for kp_id in rep.unmatched_kp_ids:
            lines.append(f"  [!] {kp_id}")
    else:
        lines.append("== 归属缺口：无")
    if rep.uncovered_topic_ids:
        lines.append("== 覆盖缺口（清单条目无知识点引用）")
        for tid in rep.uncovered_topic_ids:
            lines.append(f"  [!] {tid} {names[tid]}")
    else:
        lines.append("== 覆盖缺口：无")
    lines.append(f"覆盖率：{len(rep.covered_topic_ids)}/{len(rep.topics)} = "
                 f"{rep.coverage_rate:.1%}")
    lines.append("COVERAGE OK" if rep.is_complete() else "COVERAGE FAILED")
    return "\n".join(lines)


def _report_json(rep, grades, n_kps):
    by_kp = {m.kp_id: m.topic_ids for m in rep.matches}
    out = {
        "grades": grades,
        "kp_count": n_kps,
        "topic_count": len(rep.topics),
        "coverage_rate": rep.coverage_rate,
        "complete": rep.is_complete(),
        "uncovered_topic_ids": list(rep.uncovered_topic_ids),
        "unmatched_kp_ids": list(rep.unmatched_kp_ids),
        "topics": [
            {
                "id": t.id,
                "name": t.name,
                "domain": t.domain,
                "theme": t.theme,
                "covered": t.id not in rep.uncovered_topic_ids,
                "matched_kp_ids": [k for k, ids in by_kp.items() if t.id in ids],
            }
            for t in rep.topics
        ],
        "matches": [{"kp_id": m.kp_id, "topic_ids": list(m.topic_ids)} for m in rep.matches],
    }
    return json.dumps(out, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser(description="课标覆盖检查器")
    ap.add_argument("--curriculum", default=DEFAULT_CURRICULUM,
                    help="课标主题清单 json（默认 data/curriculum/math_standard_2022_topics.json）")
    ap.add_argument("--knowledge-dir", default=DEFAULT_KNOWLEDGE_DIR,
                    help="knowledge 年级文件所在目录（默认 data/knowledge）")
    ap.add_argument("--grades", default="7,8,9", help="参与的年级，逗号分隔（默认 7,8,9）")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()
    try:
        grades = [int(g.strip()) for g in args.grades.split(",") if g.strip()]
        if not grades:
            raise StandardCoverageError("--grades is empty")
        kps = _merge_kps(grades, args.knowledge_dir)
        rep = check_coverage_dicts(kps, _load(args.curriculum))
    except StandardCoverageError as e:
        print(f"INPUT ERROR: {e}")
        return 2
    except (OSError, json.JSONDecodeError) as e:
        print(f"INPUT ERROR: {e}")
        return 2
    if args.format == "json":
        print(_report_json(rep, grades, len(kps)))
    else:
        print(_report_text(rep, grades, len(kps)))
    return 0 if rep.is_complete() else 1


if __name__ == "__main__":
    sys.exit(main())
