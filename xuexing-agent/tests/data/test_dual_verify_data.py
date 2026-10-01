"""数据测试：双代理独立复验运行 × 真实题库（BACKLOG「双代理独立复验题库」数据闭环）。

锁定三次真实运行的可追溯事实（内核均为 xuexing.dual_verify）：
- 2026-09-29 run（tools/dual_agent_verify.py，7-9 年级库 321 题）：
  m3-reviewer(key) × night-reverify-20260929(ledger)，manifest/ledger/队列见
  data/verification/ 原文件；
- 2026-09-30 run（_research_tmp/p34_dual_verify.py，同口径两通道，3-4 年级库 94 题）：
  p34-reviewer(key) × recheck-20260930(ledger)，独立落盘 verify_manifest_p34.json /
  ledger_p34_20260930.json / arbitration_queue_p34.json（不覆盖 7-9 存量清单）；
- 2026-09-30 run（_research_tmp/finalize_p12.py，同口径两通道，小学低段 1-2 年级
  库 96 题）：p12-editor-20260930(key) × step-p12-blind-20260930(ledger)，
  独立落盘 verify_manifest_p12_20260930.json / ledger_p12_blind_20260930.json /
  arbitration_queue_p12_20260930.json。
- 2026-09-30 deepen/扩库批 ×4（无独立 ledger/manifest：LLM 起草 + 人工逐题
  验算修正后复核，证据在 _research_tmp/g7_build_items.py 头部修正清单 /
  g7_review.txt、_research_tmp/m9_build.py 与 p5*/p6* 生成产物）：
  七年级 +93 题（m7_130..222，step-3.7-flash × g7-deepen-review-20260930）、
  九年级 +105 题（m9_106..210，step-3.7-flash × m9-deepen-review-20260930）、
  五年级 +50 题（47 llm_generated × p5-reviewer-20260930 + 3 original ×
  p56-author-20260930/p56-reverify-20260930）、六年级 +51 题（48 llm_generated
  × p6-reviewer-20260930 + 3 original × 同 p56 对），均 source=llm_generated
  或 original、题内 verification 记录 answers_agree=True；可追溯性由
  test_verification_agents_match_owning_run 按批次登记表强制（未登记批次的
  代理身份会直接失败，fail-closed）。
  注：data/verification/ledger_m8deep_blind_20260930.json 是八年级深挖批
  （m8_101..187，87 题）的盲解台账，该批题目尚未落库——它是无主产物，
  不构成本库运行，待八年级深挖批落库时再按本文件口径登记。

三次 ledger 运行各自验证：ledger 逐题覆盖其子库且与标答判等；manifest 与
现场重跑裁决逐位一致；回填记录 agents 与 manifest 代理身份一致、
verified == total；仲裁队列为空。另做全库并集检查：data/items/ 每题恰被
一次 ledger 运行或一个 deepen/扩库批覆盖，且题内 verification.agents 与
所属批次一致。ledger 抽查为测试内现算重推（非抄串）。
"""
import glob
import json
import os

import pytest

from xuexing.dual_verify import answers_match, arbitration_rows, verify_bank

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
VERIFICATION_DIR = os.path.join(ROOT, "data", "verification")

NIGHT_ITEM_FILES = sorted(
    os.path.join(ROOT, "data", "items", f"math_grade{g}_items.json") for g in (7, 8, 9))
P34_ITEM_FILES = sorted(
    os.path.join(ROOT, "data", "items", f"math_grade{g}_items.json") for g in (3, 4))
P12_ITEM_FILES = sorted(
    os.path.join(ROOT, "data", "items", f"math_grade{g}_items.json") for g in (1, 2))
ALL_ITEM_FILES = sorted(glob.glob(os.path.join(ROOT, "data", "items", "*.json")))

LEDGER_PATH = os.path.join(VERIFICATION_DIR, "ledger_night_20260929.json")
MANIFEST_PATH = os.path.join(VERIFICATION_DIR, "verify_manifest.json")
QUEUE_PATH = os.path.join(VERIFICATION_DIR, "arbitration_queue.json")
P34_LEDGER_PATH = os.path.join(VERIFICATION_DIR, "ledger_p34_20260930.json")
P34_MANIFEST_PATH = os.path.join(VERIFICATION_DIR, "verify_manifest_p34.json")
P34_QUEUE_PATH = os.path.join(VERIFICATION_DIR, "arbitration_queue_p34.json")
P12_LEDGER_PATH = os.path.join(VERIFICATION_DIR, "ledger_p12_blind_20260930.json")
P12_MANIFEST_PATH = os.path.join(VERIFICATION_DIR, "verify_manifest_p12_20260930.json")
P12_QUEUE_PATH = os.path.join(VERIFICATION_DIR, "arbitration_queue_p12_20260930.json")

NIGHT_AGENTS = ["m3-reviewer", "night-reverify-20260929"]
P34_AGENTS = ["p34-reviewer", "recheck-20260930"]
P12_AGENTS = ["p12-editor-20260930", "step-p12-blind-20260930"]
# deepen/扩库批（代理对与落库记录原序一致；未登记批次落库即失败，fail-closed）
DEEPEN_AGENTS_BY_GRADE = {
    "m7": [["step-3.7-flash", "g7-deepen-review-20260930"]],
    "m9": [["step-3.7-flash", "m9-deepen-review-20260930"]],
    # 五/六年级：llm 生成题走 reviewer 对，3+3 道 original 题走 p56 作者/复验对
    "p5": [["step-3.7-flash", "p5-reviewer-20260930"],
           ["p56-author-20260930", "p56-reverify-20260930"]],
    "p6": [["step-3.7-flash", "p6-reviewer-20260930"],
           ["p56-author-20260930", "p56-reverify-20260930"]],
}


def _load_items(paths):
    assert paths, "no item files found under data/items/"
    items = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            items.extend(json.load(f)["items"])
    return items


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _answers_by_item(items, key_agent, ledger_agent, ledger_answers):
    out = {}
    for it in items:
        out[it["id"]] = {
            key_agent: it["answer"],  # key 通道：独立审题员的解题产物即标答
            ledger_agent: ledger_answers.get(it["id"]),
        }
    return out


@pytest.fixture(scope="module")
def night_items():
    return _load_items(NIGHT_ITEM_FILES)


@pytest.fixture(scope="module")
def night_bank(night_items, ledger):
    """night 运行的子库 = 现库中台账覆盖的存量题（2026-09-29 时点的 7-9 库）；
    其后 g7/m9 deepen 批扩出的题不属于该运行，由并集检查与代理登记表覆盖。"""
    ids = set(ledger["answers"])
    return [it for it in night_items if it["id"] in ids]


@pytest.fixture(scope="module")
def p34_items():
    return _load_items(P34_ITEM_FILES)


@pytest.fixture(scope="module")
def all_items():
    return _load_items(ALL_ITEM_FILES)


@pytest.fixture(scope="module")
def ledger():
    return _load(LEDGER_PATH)


@pytest.fixture(scope="module")
def manifest():
    return _load(MANIFEST_PATH)


@pytest.fixture(scope="module")
def queue():
    return _load(QUEUE_PATH)


@pytest.fixture(scope="module")
def p34_ledger():
    return _load(P34_LEDGER_PATH)


@pytest.fixture(scope="module")
def p34_manifest():
    return _load(P34_MANIFEST_PATH)


@pytest.fixture(scope="module")
def p34_queue():
    return _load(P34_QUEUE_PATH)


@pytest.fixture(scope="module")
def p12_items():
    return _load_items(P12_ITEM_FILES)


@pytest.fixture(scope="module")
def p12_ledger():
    return _load(P12_LEDGER_PATH)


@pytest.fixture(scope="module")
def p12_manifest():
    return _load(P12_MANIFEST_PATH)


@pytest.fixture(scope="module")
def p12_queue():
    return _load(P12_QUEUE_PATH)


# ---------- 运行产物存在 ----------

def test_run_artifacts_exist():
    for p in (LEDGER_PATH, MANIFEST_PATH, QUEUE_PATH,
              P34_LEDGER_PATH, P34_MANIFEST_PATH, P34_QUEUE_PATH,
              P12_LEDGER_PATH, P12_MANIFEST_PATH, P12_QUEUE_PATH):
        assert os.path.exists(p), f"missing run artifact: {p}"


# ---------- 2026-09-29 run（7-9 年级存量 321 题；扩库后子库按台账圈定） ----------

def test_night_ledger_covers_real_bank(night_items, ledger):
    assert ledger["agent_id"] == "night-reverify-20260929"
    # 闭式：该运行覆盖 2026-09-29 存量 321 题；g7/m9 deepen 扩库后 7-9 库为
    # 519 题，扩出部分归 deepen 批（见并集检查），台账不得含库外孤儿 id
    assert len(ledger["answers"]) == 321
    assert set(ledger["answers"]) <= {it["id"] for it in night_items}
    assert all(isinstance(v, str) and v.strip() for v in ledger["answers"].values())


def test_night_manifest_matches_live_rerun(night_bank, ledger, manifest):
    answers = _answers_by_item(night_bank, "m3-reviewer", "night-reverify-20260929",
                               ledger["answers"])
    report = verify_bank(night_bank, answers)
    assert manifest["items_total"] == len(night_bank) == 321
    assert manifest["counts"] == report.counts()
    assert manifest["agreed_item_ids"] == list(report.agreed_item_ids)
    assert manifest["disputed_item_ids"] == list(report.disputed_item_ids)
    assert manifest["incomplete_item_ids"] == list(report.incomplete_item_ids)
    assert sorted(a["id"] for a in manifest["agents"]) == NIGHT_AGENTS
    specs = {a["id"]: a["spec"] for a in manifest["agents"]}
    assert specs["m3-reviewer"] == "key"  # key 通道如实披露
    assert specs["night-reverify-20260929"].startswith("ledger:")


def test_night_backfilled_records_traceable(night_bank, manifest):
    expected_agents = sorted(a["id"] for a in manifest["agents"])
    for it in night_bank:
        rec = it.get("verification")
        assert isinstance(rec, dict), f"{it['id']}: missing verification record"
        assert rec.get("agents") == expected_agents, it["id"]
        assert rec.get("answers_agree") is True, it["id"]
    verified = sum(1 for it in night_bank if isinstance(it.get("verification"), dict))
    assert verified == len(night_bank)


def test_night_arbitration_queue_closed_form(night_bank, ledger, queue):
    answers = _answers_by_item(night_bank, "m3-reviewer", "night-reverify-20260929",
                               ledger["answers"])
    live_rows = [dict(r) for r in arbitration_rows(night_bank, answers)]
    assert queue["queue"] == live_rows
    # 2026-09-29 运行闭式：321 题双通道判等全部一致，无人工仲裁待办
    assert live_rows == [], (
        "出现分歧：先人工仲裁（改标答或改台账），重跑 tools/dual_agent_verify.py "
        "后再同步本闭式；分歧未仲裁前对应题不得回填 verification"
    )


def test_ledger_spot_checks_independently_recomputed(night_items, ledger):
    by_id = {it["id"]: it for it in night_items}
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


def test_ledger_is_derived_not_copied(night_items, ledger):
    """台账至少一条表面形与标答不同而判等：证明走的是规则表等值而非逐字复制。"""
    by_id = {it["id"]: it for it in night_items}
    divergent = [
        iid for iid, ans in ledger["answers"].items()
        if ans != by_id[iid]["answer"] and answers_match(by_id[iid]["answer"], ans, by_id[iid]["item_type"], by_id[iid].get("options"))
    ]
    assert "m9_30" in divergent  # 台账按推导序写 (3,0)和(-1,0)，标答 (-1,0)和(3,0)
    assert divergent, "台账与标答逐字全同：失去独立推导证据"


# ---------- 2026-09-30 run（3-4 年级 94 题，同口径平行闭式） ----------

def test_p34_ledger_covers_real_bank(p34_items, p34_ledger):
    assert p34_ledger["agent_id"] == "recheck-20260930"
    assert set(p34_ledger["answers"]) == {it["id"] for it in p34_items}
    assert all(isinstance(v, str) and v.strip() for v in p34_ledger["answers"].values())


def test_p34_manifest_matches_live_rerun(p34_items, p34_ledger, p34_manifest):
    answers = _answers_by_item(p34_items, "p34-reviewer", "recheck-20260930",
                               p34_ledger["answers"])
    report = verify_bank(p34_items, answers)
    assert p34_manifest["items_total"] == len(p34_items)
    assert p34_manifest["counts"] == report.counts()
    assert p34_manifest["agreed_item_ids"] == list(report.agreed_item_ids)
    assert p34_manifest["disputed_item_ids"] == list(report.disputed_item_ids)
    assert p34_manifest["incomplete_item_ids"] == list(report.incomplete_item_ids)
    assert sorted(a["id"] for a in p34_manifest["agents"]) == P34_AGENTS
    specs = {a["id"]: a["spec"] for a in p34_manifest["agents"]}
    assert specs["p34-reviewer"] == "key"  # key 通道如实披露
    assert specs["recheck-20260930"].startswith("ledger:")


def test_p34_backfilled_records_traceable(p34_items, p34_manifest):
    expected_agents = sorted(a["id"] for a in p34_manifest["agents"])
    for it in p34_items:
        rec = it.get("verification")
        assert isinstance(rec, dict), f"{it['id']}: missing verification record"
        assert rec.get("agents") == expected_agents, it["id"]
        assert rec.get("answers_agree") is True, it["id"]
    verified = sum(1 for it in p34_items if isinstance(it.get("verification"), dict))
    assert verified == len(p34_items)


def test_p34_arbitration_queue_closed_form(p34_items, p34_ledger, p34_queue):
    answers = _answers_by_item(p34_items, "p34-reviewer", "recheck-20260930",
                               p34_ledger["answers"])
    live_rows = [dict(r) for r in arbitration_rows(p34_items, answers)]
    assert p34_queue["queue"] == live_rows
    # 2026-09-30 运行闭式：94 题双通道判等全部一致，无人工仲裁待办
    assert live_rows == [], (
        "出现分歧：先人工仲裁（改标答或改台账），重跑 _research_tmp/p34_dual_verify.py "
        "后再同步本闭式；分歧未仲裁前对应题不得回填 verification"
    )


def test_p34_ledger_spot_checks_independently_recomputed(p34_items, p34_ledger):
    by_id = {it["id"]: it for it in p34_items}
    # (id, 现算表达式) —— 测试内独立重推，台账与库内标答须同时等于该值
    checks = [
        ("p3_014", str(125 * 4)),               # 三位数乘一位数
        ("p3_027", str(20 * 30)),               # 估算 24≈20、32≈30
        ("p3_043", str(435 - 168)),             # 连续退位减法
        ("p4_011", str(240 * 35)),              # 因数末尾有0
        ("p4_015", str(23 * 15 + 8)),           # 有余数除法验算
        ("p4_027", str(100 * 45 + 2 * 45)),     # 分配律简算
        ("p4_041", str((28 - 10 * 2) // 2)),    # 鸡兔同笼假设法（全是鸡，补腿差）
        ("p4_047", str(10 + 10 + 5)),           # 等腰三角形周长（腰=10）
    ]
    missing = [iid for iid, _ in checks if iid not in by_id]
    assert missing == [], f"抽查题不在库中: {missing}"
    for iid, expected in checks:
        assert by_id[iid]["answer"] == expected, f"{iid}: 标答 {by_id[iid]['answer']!r} != 现算 {expected!r}"
        assert p34_ledger["answers"][iid] == expected, f"{iid}: 台账 {p34_ledger['answers'][iid]!r} != 现算 {expected!r}"


# ---------- 2026-09-30 run（小学低段 1-2 年级 96 题，同口径平行闭式） ----------

def test_p12_ledger_covers_real_bank(p12_items, p12_ledger):
    assert p12_ledger["agent_id"] == "step-p12-blind-20260930"
    assert set(p12_ledger["answers"]) == {it["id"] for it in p12_items}
    assert all(isinstance(v, str) and v.strip() for v in p12_ledger["answers"].values())


def test_p12_manifest_matches_live_rerun(p12_items, p12_ledger, p12_manifest):
    answers = _answers_by_item(p12_items, "p12-editor-20260930", "step-p12-blind-20260930",
                               p12_ledger["answers"])
    report = verify_bank(p12_items, answers)
    assert p12_manifest["items_total"] == len(p12_items)
    assert p12_manifest["counts"] == report.counts()
    assert p12_manifest["agreed_item_ids"] == list(report.agreed_item_ids)
    assert p12_manifest["disputed_item_ids"] == list(report.disputed_item_ids)
    assert p12_manifest["incomplete_item_ids"] == list(report.incomplete_item_ids)
    assert sorted(a["id"] for a in p12_manifest["agents"]) == P12_AGENTS
    specs = {a["id"]: a["spec"] for a in p12_manifest["agents"]}
    assert specs["p12-editor-20260930"] == "key"  # key 通道如实披露
    assert specs["step-p12-blind-20260930"].startswith("ledger:")


def test_p12_backfilled_records_traceable(p12_items, p12_manifest):
    expected_agents = sorted(a["id"] for a in p12_manifest["agents"])
    for it in p12_items:
        rec = it.get("verification")
        assert isinstance(rec, dict), f"{it['id']}: missing verification record"
        assert rec.get("agents") == expected_agents, it["id"]
        assert rec.get("answers_agree") is True, it["id"]
    verified = sum(1 for it in p12_items if isinstance(it.get("verification"), dict))
    assert verified == len(p12_items)


def test_p12_arbitration_queue_closed_form(p12_items, p12_ledger, p12_queue):
    answers = _answers_by_item(p12_items, "p12-editor-20260930", "step-p12-blind-20260930",
                               p12_ledger["answers"])
    live_rows = [dict(r) for r in arbitration_rows(p12_items, answers)]
    assert p12_queue["queue"] == live_rows
    # 2026-09-30 运行闭式：96 题双通道判等全部一致，无人工仲裁待办
    #（首轮运行曾有 2 分歧：p1_047 仲裁改标答、p2_023 改题干锁表述后重跑盲解）
    assert live_rows == [], (
        "出现分歧：先人工仲裁（改标答或改台账），重跑 _research_tmp/finalize_p12.py "
        "后再同步本闭式；分歧未仲裁前对应题不得回填 verification"
    )


def test_p12_ledger_spot_checks_independently_recomputed(p12_items, p12_ledger):
    by_id = {it["id"]: it for it in p12_items}
    # (id, 现算表达式) —— 测试内独立重推，台账与库内标答须同时等于该值
    checks = [
        ("p1_009", str(9 + 4)),        # 凑十法 9+4
        ("p1_016", str(16 - 9)),       # 退位减 16-9
        ("p1_033", str(8 + 2)),        # 数列规律 2、4、6、8（+2）
        ("p1_046", str(4 + 1 + 3)),    # 排队：前4人+小刚+后3人
        ("p2_002", str(45 - 18)),      # 笔算退位减 45-18
        ("p2_008", str(6 * 7)),        # 表内乘法 六七四十二
        ("p2_016", str(56 // 8)),      # 用口诀求商
        ("p2_025", str(9 * 5)),        # 分针指9=9大格×5分
        ("p2_037", str(6 - 1)),        # 刻度1到6：末端减起点
    ]
    missing = [iid for iid, _ in checks if iid not in by_id]
    assert missing == [], f"抽查题不在库中: {missing}"
    for iid, expected in checks:
        assert by_id[iid]["answer"] == expected, f"{iid}: 标答 {by_id[iid]['answer']!r} != 现算 {expected!r}"
        assert p12_ledger["answers"][iid] == expected, f"{iid}: 台账 {p12_ledger['answers'][iid]!r} != 现算 {expected!r}"


# ---------- 各运行与 deepen 批的并集：全库每题恰属一批、互不交叉 ----------

def test_runs_cover_own_banks_without_overlap(all_items, ledger, p34_ledger, p12_ledger):
    night_ids = set(ledger["answers"])
    p34_ids = set(p34_ledger["answers"])
    p12_ids = set(p12_ledger["answers"])
    all_ids = {it["id"] for it in all_items}
    assert len(all_items) == len(all_ids), "duplicate item id across files"
    assert not (night_ids & p34_ids) and not (night_ids & p12_ids) \
        and not (p34_ids & p12_ids), "两运行覆盖重叠"
    assert p34_ids == {i for i in all_ids if i.startswith(("p3_", "p4_"))}, (
        "p34 运行须恰好覆盖全部 3-4 年级题")
    assert p12_ids == {i for i in all_ids if i.startswith(("p1_", "p2_"))}, (
        "p12 运行须恰好覆盖全部 1-2 年级题")
    # 7-9 库 = night 存量 321 + g7 deepen 93（m7_130..222）+ m9 deepen 105
    #（m9_106..210）；deepen 批无独立台账，题内 verification 记录即为覆盖凭证
    m_ids = {i for i in all_ids if i.startswith(("m7_", "m8_", "m9_"))}
    deepen_ids = m_ids - night_ids
    assert night_ids | deepen_ids == m_ids and not (night_ids & deepen_ids), (
        "night 与 deepen 批须合并覆盖全部 7-9 年级题且互不重叠")
    assert len(night_ids) == 321 and len(p34_ids) == 94 and len(p12_ids) == 96
    assert len(deepen_ids) == 198, (
        "deepen 批规模变化（现 198=93+105）：新增批次须先登记 "
        "DEEPEN_AGENTS_BY_GRADE 并在本闭式同步")
    # 五/六年级扩库批 101 题（3+3 original × p56 对 + 47+48 llm × reviewer）
    # 不在任何 ledger 运行内，由代理登记表覆盖（见下一测试）
    p56_ids = {i for i in all_ids if i.startswith(("p5_", "p6_"))}
    assert len(p56_ids) == 101
    # 全库划分：每题恰属一个 ledger 运行或一个扩库批
    assert night_ids | p34_ids | p12_ids | deepen_ids | p56_ids == all_ids


def test_verification_agents_match_owning_run(all_items, ledger):
    night_ids = set(ledger["answers"])
    for it in all_items:
        rec = it.get("verification")
        assert isinstance(rec, dict) and rec.get("answers_agree") is True, it["id"]
        iid = it["id"]
        if iid in night_ids:
            assert rec["agents"] == NIGHT_AGENTS, iid
        elif iid.startswith(("p3_", "p4_")):
            assert rec["agents"] == P34_AGENTS, iid
        elif iid.startswith(("p1_", "p2_")):
            assert rec["agents"] == P12_AGENTS, iid
        else:
            grade = iid.split("_", 1)[0]
            allowed = DEEPEN_AGENTS_BY_GRADE.get(grade)
            assert allowed is not None, (
                f"{iid}: deepen 批 {grade} 未登记代理身份（先登记再落库）")
            assert rec["agents"] in allowed, iid
