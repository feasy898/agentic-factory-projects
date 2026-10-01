#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
runner.py — office-eval-suite（中文办公评测集 v2）资产确定性评测器

用法:
    python skillfactory/v4/assets/office-eval-suite/eval/runner.py <被测产物根> <参照产物根> [--out <path>]

四项检查（名称冻结，恒 4 项齐全，见 contract.md §5 / spec.md §4.4）:
  1. validate_all_green         被测校验器对被测 suite.json 全绿（exit 0 且报告 ok=true）
  2. ratio_difficulty_per_spec  八域精确配比 8/6/6/5/7/6/6/6（总 50）+ 难度分布
                                （每域三档齐备、中档占该域多数，全局中档占多数）与 spec 一致
  3. no_dup_vs_reference        内部无重复；与参照套件（oracle）完全相同题 ≤10（自评模式豁免跨集部分）
  4. legacy_export_v1_green     被测 export_legacy.py 对自身 suite.json 导出的 legacy 文件
                                能被 v1 校验器（skillfactory/v3/assets/prompt-regression/package/validate.py）通过

全过 → stdout 打印 JSON(ok=true) 且退出码 0；任一失败 → 打印 JSON(ok=false) 且退出码 1。
输出不含时间戳；同参数重复运行 stdout 逐字节一致（确定性）。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------- 冻结常量（与 spec.md §4 一致）
ASSET = "skillfactory/v4/assets/office-eval-suite/eval"

DOMAIN_TARGET = {  # 八域精确配比（总计 50）
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
ITEM_KEYS = {"id", "domain", "difficulty", "instruction", "checks"}

DUP_IDENTICAL_MAX = 10         # 与参照套件完全相同题的上限（contract.md §5）
SUBPROCESS_TIMEOUT = 180

# v1 校验器（检查 4 的裁判）：由本文件位置上溯到 skillfactory 根定位
V1_VALIDATOR = Path(__file__).resolve().parents[4] / "v3" / "assets" / "prompt-regression" / "package" / "validate.py"


def normalize(s: str) -> str:
    """归一化：删除全部空白字符（中英文查重同用）。"""
    return re.sub(r"\s+", "", s)


# ---------------------------------------------------------------- 路径解析（contract.md §1/§5）
def _layouts(base_root: Path):
    """给定目录的两种布局候选（root → package/）。"""
    return (("root", base_root), ("package", base_root / "package"))


def _trio(base: Path) -> tuple[Path, Path, Path]:
    return base / "suite.json", base / "validate.py", base / "export_legacy.py"


def resolve_candidate(root: Path):
    """被测产物根 → (suite.json, validate.py, export_legacy.py, 布局名或None, 已尝试路径, 解析方式)。

    解析顺序（contract.md §1）：
      1. root 布局：<root>/{suite.json, validate.py, export_legacy.py}
      2. package 布局：<root>/package/…
      3. 报告目录回退（单层、留痕）：若 <root> 恰为校验器报告目录（含 validate.json）
         且其父目录构成完整产物根，则回退解析到父目录（resolved_via=report-dir-parent）。
         普通空目录/随机目录不满足回退条件，仍判红。
    """
    tried = []
    for layout, base in _layouts(root):
        s, v, e = _trio(base)
        tried.extend((str(s), str(v), str(e)))
        if s.is_file() and v.is_file() and e.is_file():
            return s, v, e, layout, tried, "direct"
    if (root / "validate.json").is_file():  # 报告目录回退：仅一层，且父目录须三件齐备
        parent = root.parent
        for layout, base in _layouts(parent):
            s, v, e = _trio(base)
            tried.extend((str(s), str(v), str(e)))
            if s.is_file() and v.is_file() and e.is_file():
                return s, v, e, layout, tried, f"report-dir-parent({root} -> {parent})"
    return None, None, None, None, tried, "none"


def resolve_reference(root: Path):
    """参照产物根 → (参照 suite.json, 解析方式)；顺序 <ref>/oracle/ → <ref>/ → <ref>/package/，
    另含与被测侧一致的单层报告目录回退。"""
    for cand in (root / "oracle" / "suite.json", root / "suite.json", root / "package" / "suite.json"):
        if cand.is_file():
            return cand, "direct"
    if (root / "validate.json").is_file():
        parent = root.parent
        for cand in (parent / "oracle" / "suite.json", parent / "suite.json", parent / "package" / "suite.json"):
            if cand.is_file():
                return cand, f"report-dir-parent({root} -> {parent})"
    return None, "none"


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=SUBPROCESS_TIMEOUT)
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return proc.returncode, " | ".join(tail)
    except subprocess.TimeoutExpired:
        return -1, f"执行超时（>{SUBPROCESS_TIMEOUT}s）"
    except OSError as e:
        return -1, f"无法执行: {e}"


# ---------------------------------------------------------------- 检查 1：validate_all_green
def run_validate_all_green(validate_py: Path | None, suite: Path | None) -> tuple[bool, str, dict]:
    """子进程执行被测校验器，显式 --out 到临时文件，不污染产物目录。"""
    if validate_py is None or suite is None:
        return False, "前置失败：被测产物根未解析出 suite.json + validate.py（布局约定见 contract.md §1）", {}
    with tempfile.TemporaryDirectory(prefix="oes_runner_") as td:
        out_path = Path(td) / "validate.json"
        rc, tail = _run([sys.executable, str(validate_py), "--suite", str(suite), "--out", str(out_path)])
        if rc != 0:
            return False, f"被测校验器退出码 {rc}（须为 0）。输出尾部: {tail}", {}
        if not out_path.is_file():
            return False, "被测校验器退出码 0 但未产出报告文件（--out 契约未履行，见 contract.md §3）", {}
        try:
            report = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return False, f"被测校验器报告 JSON 解析失败: {e}", {}

    ok = report.get("ok")
    sub = report.get("summary", {}).get("validator_checks", {}) if isinstance(report, dict) else {}
    failed_names = [c.get("name") for c in report.get("checks", []) if isinstance(c, dict) and not c.get("passed")]
    if ok is not True:
        return False, f"被测校验器报告 ok={ok!r}（须 true）；失败项: {failed_names}", {}
    detail = (f"被测校验器全绿：{sub.get('passed', '?')}/{sub.get('total', '?')} 项通过，"
              f"items={report.get('summary', {}).get('items', '?')}，"
              f"checks_in_suite={report.get('summary', {}).get('checks_in_suite', '?')}")
    return True, detail, report if isinstance(report, dict) else {}


# ---------------------------------------------------------------- 检查 2：ratio_difficulty_per_spec
def run_ratio_difficulty(items) -> tuple[bool, str, dict]:
    """八域精确配比 + 难度分布（每域三档齐备、中档占多数，全局中档占多数）直接核对被测 suite.json。"""
    counts = {d: 0 for d in DOMAIN_TARGET}
    unknown_dom: Counter = Counter()
    per_diff: dict[str, Counter] = {d: Counter() for d in DOMAIN_TARGET}
    global_diff: Counter = Counter()
    for it in items:
        dom = it.get("domain") if isinstance(it, dict) else None
        diff = it.get("difficulty") if isinstance(it, dict) else None
        if dom in counts:
            counts[dom] += 1
            if diff in DIFFICULTIES:
                per_diff[dom][diff] += 1
                global_diff[diff] += 1
        else:
            unknown_dom[repr(dom)] += 1

    problems = []
    for d, cfg in DOMAIN_TARGET.items():
        if counts[d] != cfg["target"]:
            problems.append(f"{cfg['label']}({d}) {counts[d]} 题 != 目标 {cfg['target']}")
        cnt = per_diff[d]
        n_dom = sum(cnt.values())
        missing = [t for t in DIFFICULTIES if cnt[t] < 1]
        if missing:
            problems.append(f"{cfg['label']}({d}) 缺难度档: {'、'.join(missing)}")
        if n_dom > 0 and cnt[DIFF_MAJOR] * 2 <= n_dom:
            problems.append(f"{cfg['label']}({d}) 中档 {cnt[DIFF_MAJOR]}/{n_dom} 未占多数（须 >50%）")
    total = sum(counts.values())
    if total != TOTAL_EXPECTED:
        problems.append(f"总题数 {total} != 期望 {TOTAL_EXPECTED}")
    if unknown_dom:
        problems.append(f"出现八域之外的 domain: {dict(unknown_dom)}")
    g_total = sum(global_diff.values())
    if g_total > 0 and global_diff[DIFF_MAJOR] * 2 <= g_total:
        problems.append(f"全局中档 {global_diff[DIFF_MAJOR]}/{g_total} 未占多数")

    detail = ("、".join(f"{DOMAIN_TARGET[d]['label']}={counts[d]}/{DOMAIN_TARGET[d]['target']}" for d in DOMAIN_TARGET))
    detail = (f"域配比: {detail}，共 {total} 题；难度: "
              + "；".join(f"{DOMAIN_TARGET[d]['label']} 易{per_diff[d]['易']}/中{per_diff[d]['中']}/难{per_diff[d]['难']}"
                          for d in DOMAIN_TARGET))
    if problems:
        return False, detail + "；问题: " + "; ".join(problems), counts
    return True, detail + "（八域精确配比 + 难度分布与 spec 一致）", counts


# ---------------------------------------------------------------- 检查 3：no_dup_vs_reference
def run_no_dup(items, cand_suite: Path, ref_suite: Path | None, ref_via: str) -> tuple[bool, str, dict]:
    cand_norm = [normalize(it["instruction"]) for it in items if isinstance(it, dict) and "instruction" in it]
    # 内部唯一性（任何模式都执行）
    dup = sorted({s for s in cand_norm if cand_norm.count(s) > 1})
    if dup:
        return False, f"内部重复：{len(dup)} 组归一化后完全相同的 instruction", {}

    if ref_suite is None:
        return False, ("参照套件未找到；已依次尝试: <ref>/oracle/suite.json、<ref>/suite.json、"
                       "<ref>/package/suite.json（及各自的报告目录回退）"), {"self_eval": False}

    self_eval = bool(cand_suite and ref_suite and cand_suite.resolve() == ref_suite.resolve())
    try:
        ref_data = json.loads(ref_suite.read_text(encoding="utf-8"))
        ref_norm = [normalize(it["instruction"]) for it in ref_data.get("items", []) if isinstance(it, dict)]
    except Exception as e:  # 参照集损坏
        return False, f"参照套件无法解析（{ref_suite}）: {e}", {"self_eval": self_eval}

    ref_set = set(ref_norm)
    identical = []
    for it in items:
        if isinstance(it, dict) and normalize(it.get("instruction", "")) in ref_set:
            identical.append(it.get("id"))

    # 与参照集相似度审计信息（每题取与参照集的最大相似度）
    sims = [max((SequenceMatcher(None, s, r).ratio() for r in ref_norm), default=0.0) for s in cand_norm]
    max_sim = max(sims, default=0.0)
    mean_sim = sum(sims) / len(sims) if sims else 0.0

    extra = {
        "self_eval": self_eval,
        "reference_resolved_via": ref_via,
        "identical_vs_reference": len(identical),
        "identical_ids": identical,
        "max_similarity_vs_reference": round(max_sim, 4),
        "mean_similarity_vs_reference": round(mean_sim, 4),
    }
    if self_eval:
        detail = (f"自评模式（被测 suite.json 与参照 suite.json 为同一文件）: 内部唯一性通过"
                  f"（{len(set(cand_norm))} 条归一化唯一）；跨集查重按 spec §4.4 E3 豁免；相似度审计 max={max_sim:.4f}")
        return True, detail, extra
    if len(identical) > DUP_IDENTICAL_MAX:
        detail = (f"与参照套件完全相同题 {len(identical)} > 上限 {DUP_IDENTICAL_MAX}（{identical}）；"
                  f"相似度审计 max={max_sim:.4f} mean={mean_sim:.4f}")
        return False, detail, extra
    detail = (f"内部 {len(set(cand_norm))} 条归一化唯一；与参照套件完全相同题 {len(identical)} ≤ {DUP_IDENTICAL_MAX}；"
              f"相似度审计 max={max_sim:.4f} mean={mean_sim:.4f}")
    return True, detail, extra


# ---------------------------------------------------------------- 检查 4：legacy_export_v1_green
def run_legacy_export_v1(export_py: Path | None, suite: Path | None) -> tuple[bool, str, dict]:
    """被测 export_legacy.py 对自身 suite.json 导出 → v1 校验器裁判。

    通过条件：导出 exit 0 且产物可解析；v1 校验器 exit 0 且报告 ok==true。
    """
    if export_py is None:
        return False, "前置失败：被测产物根未解析出 export_legacy.py（布局约定见 contract.md §1）", {}
    if suite is None:
        return False, "前置失败：被测产物根未解析出 suite.json", {}
    if not V1_VALIDATOR.is_file():
        return False, f"前置失败：v1 校验器不存在: {V1_VALIDATOR}", {}

    with tempfile.TemporaryDirectory(prefix="oes_runner_") as td:
        legacy_path = Path(td) / "golden-legacy.json"
        export_report = Path(td) / "export-legacy.json"
        v1_report = Path(td) / "v1-validate.json"

        rc, tail = _run([sys.executable, str(export_py), "--suite", str(suite),
                         "--out", str(legacy_path), "--report", str(export_report)])
        if rc != 0:
            return False, f"被测 export_legacy.py 退出码 {rc}（须为 0）。输出尾部: {tail}", {}
        if not legacy_path.is_file():
            return False, "被测 export_legacy.py 退出码 0 但未产出导出文件（--out 契约未履行，见 contract.md §4）", {}
        try:
            legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return False, f"导出产物 JSON 解析失败: {e}", {}
        n_exported = len(legacy.get("items", [])) if isinstance(legacy, dict) else 0
        exp_summary = {}
        try:
            exp_summary = json.loads(export_report.read_text(encoding="utf-8"))
        except Exception:
            pass

        rc, tail = _run([sys.executable, str(V1_VALIDATOR), "--golden", str(legacy_path), "--out", str(v1_report)])
        if rc != 0:
            return False, (f"v1 校验器对导出产物退出码 {rc}（须为 0）——legacy 兼容性不成立。"
                           f"导出 {n_exported} 题；输出尾部: {tail}"), {"exported_items": n_exported}
        try:
            report = json.loads(v1_report.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return False, f"v1 校验器报告 JSON 解析失败: {e}", {"exported_items": n_exported}
        if report.get("ok") is not True:
            failed_names = [c.get("name") for c in report.get("checks", []) if isinstance(c, dict) and not c.get("passed")]
            return False, (f"v1 校验器报告 ok={report.get('ok')!r}（须 true）；失败项: {failed_names}；"
                           f"导出 {n_exported} 题"), {"exported_items": n_exported}

    taken = exp_summary.get("per_domain_taken", {})
    detail = (f"legacy 兼容导出 → v1 校验器全绿：导出 {n_exported} 题"
              f"（六域配比 {taken if taken else 'N/A'}），v1 校验 "
              f"{report.get('summary', {}).get('validator_checks', {}).get('passed', '?')}/"
              f"{report.get('summary', {}).get('validator_checks', {}).get('total', '?')} 项通过")
    return True, detail, {"exported_items": n_exported, "per_domain_taken": taken}


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="office-eval-suite 资产确定性评测器")
    ap.add_argument("candidate", help="被测产物根")
    ap.add_argument("reference", help="参照产物根")
    ap.add_argument("--out", default=None, help="评测报告输出路径（缺省仅打印 stdout）")
    args = ap.parse_args()

    cand_root, ref_root = Path(args.candidate), Path(args.reference)
    results: list[dict] = []

    def record(name: str, passed: bool, detail: str, **extra) -> None:
        entry = {"name": name, "passed": bool(passed), "detail": detail}
        entry.update(extra)
        results.append(entry)
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")

    suite, validate_py, export_py, layout, tried, via = resolve_candidate(cand_root)
    layout_out = layout if layout else "none"

    cand_data = None
    items: list = []
    if suite is not None:
        try:
            cand_data = json.loads(suite.read_text(encoding="utf-8"))
            items = cand_data.get("items", []) if isinstance(cand_data, dict) else []
        except (json.JSONDecodeError, OSError):
            cand_data = None
            items = []

    # 1) 被测校验器全绿
    if suite is not None and validate_py is not None:
        ok1, detail1, _report = run_validate_all_green(validate_py, suite)
        if via.startswith("report-dir-parent"):
            detail1 = f"[解析回退 {via}] " + detail1
    else:
        ok1, detail1 = False, ("前置失败：被测产物根未解析出 suite.json + validate.py + export_legacy.py；已尝试: "
                               + "; ".join(tried))
    record("validate_all_green", ok1, detail1, candidate_layout=layout_out, resolved_via=via)

    # 2) 配比与难度分布
    if items:
        ok2, detail2, counts = run_ratio_difficulty(items)
    else:
        ok2, detail2, counts = False, "前置失败：suite.json 无法加载或无 items", {}
    record("ratio_difficulty_per_spec", ok2, detail2, domains=counts)

    # 3) 查重（内部唯一 + 跨集 ≤10，自评豁免跨集）
    ref_suite, ref_via = resolve_reference(ref_root)
    if not items:
        ok3, detail3, extra3 = False, "前置失败：被测 suite.json 无法加载", {}
    else:
        ok3, detail3, extra3 = run_no_dup(items, suite, ref_suite, ref_via)
    record("no_dup_vs_reference", ok3, detail3, **extra3)

    # 4) legacy 导出 → v1 校验器
    if suite is not None and export_py is not None:
        ok4, detail4, extra4 = run_legacy_export_v1(export_py, suite)
    else:
        ok4, detail4, extra4 = False, "前置失败：被测产物根未解析出 suite.json + export_legacy.py", {}
    record("legacy_export_v1_green", ok4, detail4, **extra4)

    all_ok = all(r["passed"] for r in results)
    passed_n = sum(1 for r in results if r["passed"])

    out = {
        "tool": "runner.py",
        "asset": ASSET,
        "candidate": args.candidate,
        "reference": args.reference,
        "candidate_layout": layout_out,
        "resolved_via": via,
        "reference_resolved_via": extra3.get("reference_resolved_via", ref_via),
        "self_eval": bool(extra3.get("self_eval", False)),
        "sampled_ids": [],
        "ok": all_ok,
        "summary": {
            "checks": {"total": len(results), "passed": passed_n, "failed": len(results) - passed_n},
            "items": len(items),
            "domains": counts,
            "checks_in_suite": sum(len(it.get("checks", [])) for it in items if isinstance(it, dict)),
            "identical_vs_reference": extra3.get("identical_vs_reference"),
            "exported_items_v1": extra4.get("exported_items"),
        },
        "checks": results,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    print("-" * 60)
    print(text)
    print(f"结果: {'ALL GREEN ✓' if all_ok else 'FAILED ✗'}（{passed_n}/{len(results)} 项评测通过）")
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"报告: {out_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
