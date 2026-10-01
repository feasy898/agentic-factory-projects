"""T1.4 标签体系文档自验收：docs/contracts/labels.md 存在性 / 结构 / 与 taxonomy 常量一致性。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.t0_labels

exit 0 = 通过。检查项：
1. 文档存在性：docs/contracts/labels.md 存在且非占位（篇幅下限）；
2. 结构：十个章节标题齐备（EntityClass 总表 / 子类型 / 政务特有身份 / 密级词表 /
   白名单候选 / 占位符标签 / 不确定项清单 / 变更纪律 等）；
3. 与 taxonomy 常量一致性：recognizers.models.EntityClass 的 19 个常量值与中文标签、
   SENSITIVE_ATTR_SUBTYPES 的 9 个子类型值逐一出现在文档中（文档 ⊇ 代码值域）；
4. 与密级词表一致性：config/classification_terms.txt 当前词表与
   recognizers.rule.detect.DEFAULT_CLASSIFICATION_TERMS 兜底词逐一出现在文档中；
5. 标准对齐：文档引用 GB/T 45574-2025 及其公开摘要类别名（含"数据安全技术"更正口径）；
6. 不确定项显式标注：未逐字核对声明在文，且显式标注标记达到密度下限；
7. 公开仓卫生：ops.name_lint 全仓零命中（新文档/新代码一并受检）。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops import name_lint  # noqa: E402
from recognizers.models import SENSITIVE_ATTR_SUBTYPES, EntityClass  # noqa: E402
from recognizers.rule.detect import DEFAULT_CLASSIFICATION_TERMS  # noqa: E402

LABELS_DOC = REPO_ROOT / "docs" / "contracts" / "labels.md"
TERMS_FILE = REPO_ROOT / "config" / "classification_terms.txt"

RESULTS: list[tuple[bool, str]] = []


def _record(name: str, fn):
    try:
        detail = fn()
        RESULTS.append((True, f"PASS  {name}" + (f" — {detail}" if detail else "")))
    except Exception as exc:  # noqa: BLE001 — 汇总所有失败后统一退出
        RESULTS.append((False, f"FAIL  {name} — {type(exc).__name__}: {exc}"))


def _load_doc() -> str:
    if not LABELS_DOC.exists():
        raise FileNotFoundError(f"missing: {LABELS_DOC.relative_to(REPO_ROOT)}")
    text = LABELS_DOC.read_text(encoding="utf-8")
    if len(text) < 3000:
        raise AssertionError(f"document suspiciously thin: {len(text)} chars")
    return text


def check_exists() -> str:
    text = _load_doc()
    lines = text.splitlines()
    if len(lines) < 120:
        raise AssertionError(f"only {len(lines)} lines")
    assert "标签体系" in text and "冻结" in text, "not a labels contract document"
    return f"{LABELS_DOC.relative_to(REPO_ROOT)}: {len(lines)} lines, {len(text)} chars"


REQUIRED_SECTIONS = (
    "## 1. 定位与效力",
    "## 2. 依据与核实状态",
    "## 3. EntityClass 总表",
    "## 4. SENSITIVE_ATTR 子类型",
    "## 5. 政务特有身份",
    "## 6. 密级标识与内部资料词表",
    "## 7. 白名单词表",  # 标题后缀随落地状态演进（候选→已落地），前缀恒定（§9-7 回更纪律）
    "## 8. 占位符中文标签",
    "## 9. 不确定项清单",
    "## 10. 变更纪律",
)


def check_structure() -> str:
    text = _load_doc()
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    if missing:
        raise AssertionError(f"missing sections: {missing}")
    return f"{len(REQUIRED_SECTIONS)} sections present"


def check_entity_classes() -> str:
    text = _load_doc()
    problems: list[str] = []
    for member in EntityClass:
        if member.value not in text:
            problems.append(f"value missing: {member.value}")
        if member.label not in text:
            problems.append(f"label missing: {member.label}({member.value})")
    if problems:
        raise AssertionError("; ".join(problems))
    labels = [m.label for m in EntityClass]
    assert len(set(labels)) == len(labels), "label uniqueness broke in code constants"
    return f"{len(EntityClass)} EntityClass values + Chinese labels all in doc, labels unique"


def check_subtypes() -> str:
    text = _load_doc()
    problems = [s for s in sorted(SENSITIVE_ATTR_SUBTYPES) if s not in text]
    if problems:
        raise AssertionError(f"subtypes missing in doc: {problems}")
    for identity in ("低保", "特困", "社区矫正", "信访人"):
        assert identity in text, f"government identity not covered: {identity}"
    assert len(SENSITIVE_ATTR_SUBTYPES) == 9, "subtype count drifted (update doc too)"
    return f"{len(SENSITIVE_ATTR_SUBTYPES)} subtypes + 4 government identities in doc"


def check_terms() -> str:
    text = _load_doc()
    file_terms = [
        ln.strip() for ln in TERMS_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    problems = [t for t in file_terms if t not in text]
    problems += [t for t in DEFAULT_CLASSIFICATION_TERMS if t not in text]
    if problems:
        raise AssertionError(f"terms missing in doc: {problems}")
    assert "load_classification_terms" in text, "doc must cite the loader mechanism"
    assert "DEFAULT_CLASSIFICATION_TERMS" in text, "doc must mention the fallback wordlist"
    return (f"{len(file_terms)} file terms + {len(DEFAULT_CLASSIFICATION_TERMS)} "
            f"fallback terms in doc, loader cited")


STANDARD_CATEGORIES = (
    "生物识别", "宗教信仰", "特定身份", "医疗健康", "金融账户", "行踪轨迹", "未成年人",
)


def check_standard_alignment() -> str:
    text = _load_doc()
    for token in ("GB/T 45574-2025", "数据安全技术", "敏感个人信息处理安全要求",
                  "个人信息保护法"):
        assert token in text, f"standard reference missing: {token}"
    missing = [c for c in STANDARD_CATEGORIES if c not in text]
    if missing:
        raise AssertionError(f"standard categories missing in doc: {missing}")
    assert "二手" in text, "doc must state the summary is second-hand, not standard text"
    return f"standard designation + {len(STANDARD_CATEGORIES)} category names aligned"


def check_uncertainty_marked() -> str:
    text = _load_doc()
    assert "未逐字核对" in text, "core disclaimer (standard text not verified) missing"
    markers = sum(text.count(m) for m in ("未核实", "未核对", "推断", "未冻结", "范围决策"))
    assert markers >= 8, f"explicit uncertainty markers too few: {markers}"
    numbered = [ln for ln in text.splitlines() if ln.startswith("| ") and "未" in ln]
    assert len(numbered) >= 6, "uncertainty items should be enumerated with status column"
    return f"{markers} explicit markers, {len(numbered)} status-flagged table rows"


def check_name_lint() -> str:
    violations, scanned = name_lint.lint_repo(REPO_ROOT)
    assert not violations, "; ".join(f"{r}:{l}:{t}" for r, l, t in violations[:20])
    return f"{scanned} files scanned, 0 violations (includes new doc)"


def main() -> int:
    _record("labels:exists", check_exists)
    _record("labels:structure", check_structure)
    _record("labels:entity-class-consistency", check_entity_classes)
    _record("labels:subtype-consistency", check_subtypes)
    _record("labels:terms-consistency", check_terms)
    _record("labels:standard-alignment", check_standard_alignment)
    _record("labels:uncertainty-marked", check_uncertainty_marked)
    _record("name-lint", check_name_lint)

    for _, line in RESULTS:
        print(line)
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"T0 LABELS: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
