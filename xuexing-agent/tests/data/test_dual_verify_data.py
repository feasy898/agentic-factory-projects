"""数据测试：双代理独立复验运行 × 真实题库（BACKLOG「双代理独立复验题库」数据闭环）。

锁定 2026-09-29 真实运行（tools/dual_agent_verify.py）的可追溯事实：
- ledger（night-reverify-20260929 独立解题台账）逐题覆盖全库、且与标答逐题判等；
- manifest（运行清单）计数与「现在重跑内核」的裁决逐位一致（清单未过期）；
- 回填记录的 agents 与 manifest 代理身份逐题一致、verified == total；
- 仲裁队列闭式 = 现场 arbitration_rows（2026-09-29 运行无分歧 → 空队列；
  引入新题/新分歧时须重跑工具并同步更新本闭式）；
- ledger 抽查：数值题在测试内现算重推（非抄串），并锁一处表面形 ≠ 标答的
  集合等值条目（证明台账是独立推导产物而非字符串复制）。
"""
import glob
import json
import os

import pytest

from xuexing.dual_verify import answers_match, arbitration_rows, verify_bank

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ITEM_FILES = sorted(glob.glob(os.path.join(ROOT, "data", "items", "*.json")))
VERIFICATION_DIR = os.path.join(ROOT, "data", "verification")
LEDGER_PATH = os.path.join(VERIFICATION_DIR, "ledger_night_20260929.json")
MANIFEST_PATH = os.path.join(VERIFICATION_DIR, "verify_manifest.json")
QUEUE_PATH = os.path.join(VERIFICATION_DIR, "arbitration_queue.json")

EXPECTED_AGENTS = ["m3-reviewer", "night-reverify-20260929"]


@pytest.fixture(scope="module")
def all_items():
    assert ITEM_FILES, "no item files found under data/items/"
    items = []
    for path in ITEM_FILES:
        with open(path, encoding="utf-8") as f:
            items.extend(json.load(f)["items"])
    return items


@pytest.fixture(scope="module")
def ledger():
    with open(LEDGER_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def manifest():
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def queue():
    with open(QUEUE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _answers_by_item(items, ledger_answers):
    out = {}
    for it in items:
        out[it["id"]] = {
            "m3-reviewer": it["answer"],  # key 通道：M3 独立审题员的解题产物即标答
            "night-reverify-20260929": ledger_answers.get(it["id"]),
        }
    return out


def test_run_artifacts_exist():
    for p in (LEDGER_PATH, MANIFEST_PATH, QUEUE_PATH):
        assert os.path.exists(p), f"missing run artifact: {p}"


def test_ledger_covers_real_bank(all_items, ledger):
    assert ledger["agent_id"] == "night-reverify-20260929"
    assert set(ledger["answers"]) == {it["id"] for it in all_items}
    assert all(isinstance(v, str) and v.strip() for v in ledger["answers"].values())


def test_manifest_matches_live_rerun(all_items, ledger, manifest):
    answers = _answers_by_item(all_items, ledger["answers"])
    report = verify_bank(all_items, answers)
    assert manifest["items_total"] == len(all_items)
    assert manifest["counts"] == report.counts()
    assert manifest["agreed_item_ids"] == list(report.agreed_item_ids)
    assert manifest["disputed_item_ids"] == list(report.disputed_item_ids)
    assert manifest["incomplete_item_ids"] == list(report.incomplete_item_ids)
    assert sorted(a["id"] for a in manifest["agents"]) == EXPECTED_AGENTS
    specs = {a["id"]: a["spec"] for a in manifest["agents"]}
    assert specs["m3-reviewer"] == "key"  # key 通道如实披露
    assert specs["night-reverify-20260929"].startswith("ledger:")


def test_backfilled_records_traceable(all_items, manifest):
    expected_agents = sorted(a["id"] for a in manifest["agents"])
    for it in all_items:
        rec = it.get("verification")
        assert isinstance(rec, dict), f"{it['id']}: missing verification record"
        assert rec.get("agents") == expected_agents, it["id"]
        assert rec.get("answers_agree") is True, it["id"]
    verified = sum(1 for it in all_items if isinstance(it.get("verification"), dict))
    assert verified == len(all_items)


def test_arbitration_queue_closed_form(all_items, ledger, queue):
    answers = _answers_by_item(all_items, ledger["answers"])
    live_rows = [dict(r) for r in arbitration_rows(all_items, answers)]
    assert queue["queue"] == live_rows
    # 2026-09-29 运行闭式：321 题双通道判等全部一致，无人工仲裁待办
    assert live_rows == [], (
        "出现分歧：先人工仲裁（改标答或改台账），重跑 tools/dual_agent_verify.py "
        "后再同步本闭式；分歧未仲裁前对应题不得回填 verification"
    )


def test_ledger_spot_checks_independently_recomputed(all_items, ledger):
    by_id = {it["id"]: it for it in all_items}
    # (id, 现算表达式) —— 测试内独立重推，台账与库内标答须同时等于该值
    checks = [
        ("m7_106", str(int(25 / 50 * 360))),            # 扇形圆心角 25/50×360°
        ("m8_36", str(5**2 - 2 * 3)),                   # x²+y²=(x+y)²-2xy
        ("m8_55", str(int((6**2 + 8**2) ** 0.5))),      # 勾股定理斜边
        ("m8_83", str(int((6 + 8) / 2))),               # 偶数个数据的中位数
        ("m9_14", str(2 + 5)),                          # x₁x₂+x₁+x₂
        ("m9_32", str(-1 + 4 + 5)),                     # y=-x²+4x+5 在 x=1（顶点不在 [0,1]）
        ("m9_59", str(int(6 * 360 / 36))),              # S=nπR²/360 → n=6π·360/(36π)
        ("m9_77", str(int(64 / 1.6))),                  # p=64/V，V=1.6
    ]
    missing = [iid for iid, _ in checks if iid not in by_id]
    assert missing == [], f"抽查题不在库中: {missing}"
    for iid, expected in checks:
        assert by_id[iid]["answer"] == expected, f"{iid}: 标答 {by_id[iid]['answer']!r} != 现算 {expected!r}"
        assert ledger["answers"][iid] == expected, f"{iid}: 台账 {ledger['answers'][iid]!r} != 现算 {expected!r}"


def test_ledger_is_derived_not_copied(all_items, ledger):
    """台账至少一条表面形与标答不同而判等：证明走的是规则表等值而非逐字复制。"""
    by_id = {it["id"]: it for it in all_items}
    divergent = [
        iid for iid, ans in ledger["answers"].items()
        if ans != by_id[iid]["answer"] and answers_match(by_id[iid]["answer"], ans, by_id[iid]["item_type"], by_id[iid].get("options"))
    ]
    assert "m9_30" in divergent  # 台账按推导序写 (3,0)和(-1,0)，标答 (-1,0)和(3,0)
    assert divergent, "台账与标答逐字全同：失去独立推导证据"
