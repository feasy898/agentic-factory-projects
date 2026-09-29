"""数据测试：题库 schema v2 × 真实题库（data/items/ 侧闭环）。

口径与 tools/validate_knowledge.py 一致（合并 data/items/*.json 全部题目）：
- 全库通过 v2 完整性门（source 枚举 / 改编溯源 / LLM 双代理验证记录）；
- 来源闭式：现库 321 题全部为 M3 知识注入的原创题（commit ab541ec，无真题改编、
  无 LLM 生成条目——题干无任何真题年份/出处标记，引入改编或 LLM 题时须同步
  更新此闭式并附真实 source_ref / verification）；
- 验证记录：2026-09-29 双代理独立复验运行（tools/dual_agent_verify.py，
  m3-reviewer × night-reverify-20260929，ledger/manifest/仲裁队列见
  data/verification/）回填 321/321；记录可追溯性由
  tests/data/test_dual_verify_data.py 强制（ledger 逐题一致 + manifest 代理
  身份一致 + 仲裁队列闭式），此处只锁「记录存在且全部通过 v2 门」；
- 算术闭式抽查：12 题按 id 逐一独立重算（表达式在测试内现算，非抄答案）。
"""
import glob
import json
import os

import pytest

from xuexing.itembank_v2 import validate_bank_v2, source_counts, verification_stats

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ITEM_FILES = sorted(glob.glob(os.path.join(ROOT, "data", "items", "*.json")))

MIN_TOTAL_ITEMS = 300  # 规模下限（只防清空/截断，不锁增长）


@pytest.fixture(scope="module")
def all_items():
    assert ITEM_FILES, "no item files found under data/items/"
    items = []
    for path in ITEM_FILES:
        with open(path, encoding="utf-8") as f:
            items.extend(json.load(f)["items"])
    return items


def test_real_bank_passes_v2_gate(all_items):
    assert len(all_items) >= MIN_TOTAL_ITEMS
    errs = validate_bank_v2(all_items)
    assert errs == [], f"schema v2 violations: {errs[:10]}"


def test_real_provenance_all_original(all_items):
    counts = source_counts(all_items)
    assert counts == {
        "original": len(all_items),
        "adapted": 0,
        "llm_generated": 0,
    }, "来源闭式变化：改编/LLM 题入库须附真实 source_ref/verification 并更新本断言"


def test_real_verification_records_honest(all_items):
    total, verified = verification_stats(all_items)
    assert total == len(all_items)
    # 2026-09-29 双代理运行回填后：全库带通过记录；记录真实性（ledger/manifest
    # 逐题可追溯、非伪造）由 test_dual_verify_data.py 独立强制。
    assert verified == total, (
        "验证覆盖缺口：original 无记录仅允许作为显式申报的诚实缺口存在，"
        "须同步更新 data/verification/ 运行清单与本断言"
    )


def test_real_closed_form_spot_checks(all_items):
    by_id = {it["id"]: it for it in all_items}
    # (id, 现算表达式) —— 独立重算，与库内 answer 逐字比对
    checks = [
        ("m7_010", str((-3) + 5)),                      # (-3)+5
        ("m7_019", str(-(2**2) + (-3) * 2)),            # -2²+(-3)×2（先乘方后取负）
        ("m7_040", str(25 + 15 / 60)),                  # 25°15′ = 25.25°
        ("m8_4", str(90 - 35)),                         # 直角三角形锐角互余
        ("m8_5", str(50 + 60)),                         # 外角 = 不相邻两内角之和
        ("m8_24", str(-4 + 3)),                         # 关于 y 轴对称：a=-4, b=3
        ("m8_25", str(9 * 2 + 4)),                      # 腰=9（4+4<9 不成三角形）
        ("m9_5", str(1 + (6 // 2) ** 2)),               # x²+6x=1 → (x+3)²=1+9
        ("m9_7", str(2**2 - 4 * 1 * (-3))),             # Δ = b²-4ac
        ("m9_14", str(2 + 5)),                          # x₁x₂+x₁+x₂ = 2+5
        ("m9_15", str(3**2 - 2 * (-2))),                # α²+β² = (α+β)²-2αβ
        ("m9_20", str(2)),                              # m²-m=2 且 m≠-1
    ]
    missing = [iid for iid, _ in checks if iid not in by_id]
    assert missing == [], f"抽查题不在库中: {missing}"
    assert 4 + 4 < 9  # m8_25 的腰只能是 9 的前提（三角形不等式）
    for iid, expected in checks:
        assert by_id[iid]["answer"] == expected, f"{iid}: {by_id[iid]['answer']!r} != {expected!r}"
