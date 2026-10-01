#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
runner.py — prompt-regression 资产确定性评测器

用法:
    python skillfactory/v3/assets/prompt-regression/eval/runner.py <被测产物根> <参照产物根> [--out <path>]

四项检查（名称冻结，恒 4 项齐全，见 contract.md §4 / spec.md §4.3）:
  1. validate_all_green          被测校验器对被测黄金集全绿（exit 0 且报告 ok=true）
  2. domain_coverage_per_spec    域配比与 spec 一致（六域下限 6/5/3/3/4/4，总 25 题）
  3. no_duplicate_vs_reference   内部无重复；与参照黄金集完全相同题 ≤5（自评模式豁免跨集部分）
  4. sampled_checks_decidable    固定种子抽 3 题，逐条 check 脚本化可判性复核

全过 → stdout 打印 JSON(ok=true) 且退出码 0；任一失败 → 打印 JSON(ok=false) 且退出码 1。
输出不含时间戳；同参数重复运行 stdout 逐字节一致（确定性）。
"""
from __future__ import annotations

import argparse
import json
import random
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
ASSET = "skillfactory/v3/assets/prompt-regression/eval"
SEED = 20260930
SAMPLE_N = 3

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

INSTR_MIN_LEN, INSTR_MAX_LEN = 80, 2000
MATERIAL_CUES = ["如下", "材料", "背景", "原文", "要点", "数据", "记录", "笔记", "素材", "「", "“"]

CHECK_TYPES = {"contains", "regex", "semantic"}
DUP_IDENTICAL_MAX = 5          # 与参照集完全相同题的上限
MIN_CONTAINS_LEN = 2           # oracle 观测最小值 = 2
MIN_REGEX_LITERALS = 2         # oracle 观测最小值 = 2（如「回滚」）
MIN_SEMANTIC_DESC = 8          # oracle 观测最小值 = 9
MIN_SEMANTIC_CJK = 3           # oracle 观测最小值 = 4（如「篇幅约150-250字」）
SUBPROCESS_TIMEOUT = 180

# 恒真探针表：正向 regex/contains 若对全部探针命中，则视为恒真不可判（含空串探针）
PROBES = [
    "",
    "今天天气不错，大家出去散步，顺便吃了午饭。",
    "会议纪要：待办事项、责任人、截止时间。",
    "ABCDEFG 1234567890 !@#$%^&*()",
    "的总计合计金额为350000元，占比34.3%，由华东区域上报。",
]

LIT_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def normalize(s: str) -> str:
    """归一化：删除全部空白字符（中英文查重同用）。"""
    return re.sub(r"\s+", "", s)


def literal_count(pattern: str) -> int:
    return sum(1 for ch in pattern if LIT_RE.match(ch))


# ---------------------------------------------------------------- 路径解析（contract.md §1/§4）
def _layouts(base_root: Path):
    """给定目录的两种布局候选（root → package/）。"""
    return (("root", base_root), ("package", base_root / "package"))


def resolve_candidate(root: Path):
    """被测产物根 → (golden.json, validate.py, 布局名或None, 已尝试路径, 解析方式)。

    解析顺序（contract.md §1）：
      1. root 布局：<root>/golden.json + <root>/validate.py
      2. package 布局：<root>/package/…
      3. 报告目录回退（单层、留痕）：若 <root> 恰为校验器报告目录（含 validate.json）
         且其父目录构成完整产物根，则回退解析到父目录（resolved_via=report-dir-parent）。
         普通空目录/随机目录不满足回退条件，仍判红。
    """
    tried = []
    for layout, base in _layouts(root):
        g, v = base / "golden.json", base / "validate.py"
        tried.append(str(g))
        tried.append(str(v))
        if g.is_file() and v.is_file():
            return g, v, layout, tried, "direct"
    if (root / "validate.json").is_file():  # 报告目录回退：仅一层，且父目录须两文件齐备
        parent = root.parent
        for layout, base in _layouts(parent):
            g, v = base / "golden.json", base / "validate.py"
            tried.append(str(g))
            tried.append(str(v))
            if g.is_file() and v.is_file():
                return g, v, layout, tried, f"report-dir-parent({root} -> {parent})"
    return None, None, None, tried, "none"


def resolve_reference(root: Path):
    """参照产物根 → (参照 golden.json, 解析方式)；顺序 <ref>/oracle/ → <ref>/ → <ref>/package/，
    另含与被测侧一致的单层报告目录回退。"""
    for cand in (root / "oracle" / "golden.json", root / "golden.json", root / "package" / "golden.json"):
        if cand.is_file():
            return cand, "direct"
    if (root / "validate.json").is_file():
        parent = root.parent
        for cand in (parent / "oracle" / "golden.json", parent / "golden.json", parent / "package" / "golden.json"):
            if cand.is_file():
                return cand, f"report-dir-parent({root} -> {parent})"
    return None, "none"


# ---------------------------------------------------------------- 检查 1：validate_all_green
def run_validate_all_green(validate_py: Path, golden: Path) -> tuple[bool, str, dict]:
    """子进程执行被测校验器，显式 --out 到临时文件，不污染产物目录。"""
    if validate_py is None or golden is None:
        return False, "前置失败：被测产物根未解析出 validate.py + golden.json（布局约定见 contract.md §1）", {}
    try:
        with tempfile.TemporaryDirectory(prefix="pr_runner_") as td:
            out_path = Path(td) / "validate.json"
            proc = subprocess.run(
                [sys.executable, str(validate_py), "--golden", str(golden), "--out", str(out_path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=SUBPROCESS_TIMEOUT,
            )
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
                return False, f"被测校验器退出码 {proc.returncode}（须为 0）。输出尾部: {' | '.join(tail)}", {}
            if not out_path.is_file():
                return False, "被测校验器退出码 0 但未产出报告文件（--out 契约未履行，见 contract.md §3）", {}
            try:
                report = json.loads(out_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                return False, f"被测校验器报告 JSON 解析失败: {e}", {}
    except subprocess.TimeoutExpired:
        return False, f"被测校验器执行超时（>{SUBPROCESS_TIMEOUT}s）", {}
    except OSError as e:
        return False, f"无法执行被测校验器: {e}", {}

    ok = report.get("ok")
    sub = report.get("summary", {}).get("validator_checks", {}) if isinstance(report, dict) else {}
    failed_names = [c.get("name") for c in report.get("checks", []) if isinstance(c, dict) and not c.get("passed")]
    if ok is not True:
        return False, f"被测校验器报告 ok={ok!r}（须 true）；失败项: {failed_names}", {}
    detail = (f"被测校验器全绿：{sub.get('passed', '?')}/{sub.get('total', '?')} 项通过，"
              f"items={report.get('summary', {}).get('items', '?')}，"
              f"checks_in_golden={report.get('summary', {}).get('checks_in_golden', '?')}")
    return True, detail, report if isinstance(report, dict) else {}


# ---------------------------------------------------------------- 检查 2：domain_coverage_per_spec
def run_domain_coverage(items) -> tuple[bool, str, dict]:
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
        return False, detail + "；问题: " + "; ".join(problems), counts
    return True, detail + "（与 spec 一致）", counts


# ---------------------------------------------------------------- 检查 3：no_duplicate_vs_reference
def run_no_duplicate(items, cand_golden: Path, ref_golden: Path) -> tuple[bool, str, dict]:
    cand_norm = [normalize(it["instruction"]) for it in items]
    # 内部唯一性（任何模式都执行）
    dup = sorted({s for s in cand_norm if cand_norm.count(s) > 1})
    if dup:
        ids = [it["id"] for it, s in zip(items, cand_norm) if s in dup]
        return False, f"内部重复：{len(set(dup))} 组归一化后完全相同的 instruction，涉及题 {ids}", {}

    self_eval = bool(cand_golden and ref_golden
                     and cand_golden.resolve() == ref_golden.resolve())
    try:
        ref_data = json.loads(ref_golden.read_text(encoding="utf-8"))
        ref_norm = [normalize(it["instruction"]) for it in ref_data.get("items", [])]
    except Exception as e:  # 参照集损坏
        return False, f"参照黄金集无法解析（{ref_golden}）: {e}", {}

    ref_set = set(ref_norm)
    identical = [it["id"] for it, s in zip(items, cand_norm) if s in ref_set]

    # 与参照集相似度审计信息（每题取与参照集的最大相似度）
    sims = []
    for s in cand_norm:
        sims.append(max((SequenceMatcher(None, s, r).ratio() for r in ref_norm), default=0.0))
    max_sim = max(sims, default=0.0)
    mean_sim = sum(sims) / len(sims) if sims else 0.0

    extra = {
        "self_eval": self_eval,
        "identical_vs_reference": len(identical),
        "identical_ids": identical,
        "max_similarity_vs_reference": round(max_sim, 4),
        "mean_similarity_vs_reference": round(mean_sim, 4),
    }
    if self_eval:
        detail = (f"自评模式（被测黄金集与参照黄金集为同一文件）: 内部唯一性通过（{len(set(cand_norm))} 条归一化唯一）；"
                  f"跨集查重按 spec §4.3 E2.3 豁免；相似度审计 max={max_sim:.4f}")
        return True, detail, extra
    if len(identical) > DUP_IDENTICAL_MAX:
        detail = (f"与参照黄金集完全相同题 {len(identical)} > 上限 {DUP_IDENTICAL_MAX}（{identical}）；"
                  f"相似度审计 max={max_sim:.4f} mean={mean_sim:.4f}")
        return False, detail, extra
    detail = (f"内部 {len(set(cand_norm))} 条归一化唯一；与参照集完全相同题 {len(identical)} ≤ {DUP_IDENTICAL_MAX}；"
              f"相似度审计 max={max_sim:.4f} mean={mean_sim:.4f}")
    return True, detail, extra


# ---------------------------------------------------------------- 检查 4：sampled_checks_decidable
def review_check(c) -> tuple[str, str, bool, str]:
    """单条 check 可判性复核 → (name, type, ok, note)。"""
    name = c.get("name") if isinstance(c, dict) else None
    ctype = c.get("type", "semantic") if isinstance(c, dict) else None
    where = f"{name or '?'}"

    def bad(note: str) -> tuple[str, str, bool, str]:
        return where, str(ctype), False, note

    if not isinstance(c, dict):
        return bad("check 必须为 object")
    desc = c.get("desc")
    if not isinstance(desc, str) or not (1 <= len(desc) <= 300):
        return bad(f"desc 长度非法（须 1-300 字符）: {desc!r}")
    if ctype not in CHECK_TYPES:
        return bad(f"type 非法: {ctype!r}（允许: {sorted(CHECK_TYPES)}）")

    if ctype == "contains":
        v = c.get("value")
        if not isinstance(v, str) or len(v) < MIN_CONTAINS_LEN:
            return bad(f"contains value 须为长度≥{MIN_CONTAINS_LEN} 的字符串: {v!r}")
        if all(v in p for p in PROBES):
            return bad(f"contains value 对全部探针恒真（不可判）: {v!r}")
        return where, ctype, True, "contains 可判"

    if ctype == "regex":
        v = c.get("value")
        if not isinstance(v, str) or not v:
            return bad("regex 必须提供非空 value")
        try:
            pat = re.compile(v)
        except re.error as e:
            return bad(f"regex 编译失败: {e}")
        if literal_count(v) < MIN_REGEX_LITERALS:
            return bad(f"regex 字面字符仅 {literal_count(v)} 个（<{MIN_REGEX_LITERALS}，疑似恒真模式）: {v!r}")
        if "(?!" in v:
            tokens = [t for t in re.split(r"[^\w]+", v) if len(t) >= 2]
            if not tokens:
                return bad(f"否定型 regex 未禁止任何长度≥2 的具体内容（等于什么都没禁止）: {v!r}")
            return where, ctype, True, f"否定型 regex 可判（禁止: {tokens[:3]}）"
        hits = [bool(pat.search(p)) for p in PROBES]
        if all(hits):
            return bad(f"正向 regex 对全部探针恒真（不可判）: {v!r}")
        return where, ctype, True, "正向 regex 可判"

    # semantic
    cjk = len(CJK_RE.findall(desc))
    if len(desc) < MIN_SEMANTIC_DESC:
        return bad(f"semantic desc 过短（{len(desc)} < {MIN_SEMANTIC_DESC}，裁判无判据）: {desc!r}")
    if cjk < MIN_SEMANTIC_CJK:
        return bad(f"semantic desc 汉字过少（{cjk} < {MIN_SEMANTIC_CJK}）: {desc!r}")
    return where, ctype, True, "semantic 判据具体可执行"


def run_sampled_decidable(items) -> tuple[bool, str, dict]:
    ids = [it["id"] for it in items]
    if len(ids) < SAMPLE_N:
        return False, f"前置失败：题数 {len(ids)} < {SAMPLE_N}，无法抽样", {}
    sampled = random.Random(SEED).sample(items, SAMPLE_N)

    samples, problems = [], []
    for it in sampled:
        sid = it["id"]
        q_problems = []
        if set(it.keys()) != ITEM_KEYS:
            q_problems.append(f"键集非法: {sorted(it.keys())}")
        n = len(it["instruction"])
        if not (INSTR_MIN_LEN <= n <= INSTR_MAX_LEN):
            q_problems.append(f"instruction 长度 {n} 超出 [{INSTR_MIN_LEN}, {INSTR_MAX_LEN}]")
        if not any(cue in it["instruction"] for cue in MATERIAL_CUES):
            q_problems.append("instruction 未发现材料标记")
        check_rows = [dict(zip(("name", "type", "ok", "note"), review_check(c))) for c in it["checks"]]
        bad_rows = [r for r in check_rows if not r["ok"]]
        q_ok = not q_problems and not bad_rows
        if q_problems:
            problems.append(f"{sid}: " + "; ".join(q_problems))
        for r in bad_rows:
            problems.append(f"{sid}.{r['name']}: {r['note']}")
        samples.append({"id": sid, "domain": it["domain"], "ok": q_ok,
                        "question_problems": q_problems, "checks": check_rows})

    extra = {"samples": samples}
    if problems:
        return False, f"抽样 {SAMPLE_N} 题可判性复核发现 {len(problems)} 处问题: " + "; ".join(problems), extra
    n_checks = sum(len(s["checks"]) for s in samples)
    return True, (f"抽样 {SAMPLE_N} 题（{[s['id'] for s in samples]}）共 {n_checks} 条 check 全部可判"
                  f"（种子 {SEED}；人工复核脚本化，明细见 samples 字段）"), extra


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="prompt-regression 资产确定性评测器")
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

    golden, validate_py, layout, tried, via = resolve_candidate(cand_root)
    layout_out = layout if layout else "none"

    cand_data = None
    items: list = []
    if golden is not None:
        try:
            cand_data = json.loads(golden.read_text(encoding="utf-8"))
            items = cand_data.get("items", []) if isinstance(cand_data, dict) else []
        except (json.JSONDecodeError, OSError):
            cand_data = None
            items = []

    # 1) 被测校验器全绿
    if golden:
        ok1, detail1, report = run_validate_all_green(validate_py, golden)
        if via.startswith("report-dir-parent"):
            detail1 = f"[解析回退 {via}] " + detail1
    else:
        ok1, detail1, report = (False, "前置失败：被测产物根未解析出 validate.py + golden.json；已尝试: "
                                + "; ".join(tried), {})
    record("validate_all_green", ok1, detail1, candidate_layout=layout_out, resolved_via=via)

    # 2) 域配比
    if items:
        ok2, detail2, counts = run_domain_coverage(items)
    else:
        ok2, detail2, counts = False, "前置失败：golden.json 无法加载或无 items", {}
    record("domain_coverage_per_spec", ok2, detail2, domains=counts)

    # 3) 查重（内部唯一 + 跨集 ≤5，自评豁免跨集）
    ref_golden, ref_via = resolve_reference(ref_root)
    if not items:
        ok3, detail3, extra3 = False, "前置失败：被测 golden.json 无法加载", {}
    elif ref_golden is None:
        ok3, detail3, extra3 = False, (f"参照黄金集未找到；已依次尝试: {ref_root / 'oracle' / 'golden.json'}、"
                                       f"{ref_root / 'golden.json'}、{ref_root / 'package' / 'golden.json'}"
                                       f"（及各自的报告目录回退）"), {}
    else:
        ok3, detail3, extra3 = run_no_duplicate(items, golden, ref_golden)
    record("no_duplicate_vs_reference", ok3, detail3, **extra3)

    # 4) 抽样可判性
    if items:
        ok4, detail4, extra4 = run_sampled_decidable(items)
    else:
        ok4, detail4, extra4 = False, "前置失败：被测 golden.json 无法加载", {}
    record("sampled_checks_decidable", ok4, detail4, **extra4)

    all_ok = all(r["passed"] for r in results)
    passed_n = sum(1 for r in results if r["passed"])
    sampled_ids = [s.get("id") for s in extra4.get("samples", [])]

    out = {
        "tool": "runner.py",
        "asset": ASSET,
        "candidate": args.candidate,
        "reference": args.reference,
        "candidate_layout": layout_out,
        "resolved_via": via,
        "reference_resolved_via": ref_via,
        "self_eval": bool(extra3.get("self_eval", False)),
        "sampled_ids": sampled_ids,
        "ok": all_ok,
        "summary": {
            "checks": {"total": len(results), "passed": passed_n, "failed": len(results) - passed_n},
            "items": len(items),
            "domains": counts,
            "checks_in_golden": sum(len(it.get("checks", [])) for it in items if isinstance(it, dict)),
            "identical_vs_reference": extra3.get("identical_vs_reference"),
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
