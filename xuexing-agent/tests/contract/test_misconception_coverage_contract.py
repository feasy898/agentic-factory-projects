"""契约：misconception_coverage —— 误解库覆盖审计器（每 KP ≥N 条误解或显式声明无）。

闭式值均为手算可复核（specs/drafts/misconception_coverage.spec.md §3.4/§4 全部实测）：
夹具 KP 库 [k1, k2, k3]（min_per_kp=2），条目 k1×2（e1、e2）、k2×1（e3）、k3 豁免
"纯约定无误解"：
  counts = ((k1,2),(k2,1),(k3,0))；covered=(k1,)；deficient=(k2,)；exempt=(k3,)
  is_complete=False；min_per_kp=1 时 covered=(k1,k2)、deficient=()、is_complete=True
"""
import copy

import pytest

from xuexing.misconception_coverage import (
    Exemption,
    MisconceptionCoverageError,
    MisconceptionEntry,
    MisconceptionReport,
    audit,
    audit_dicts,
    parse_bank,
)
from xuexing.types import Misconception


# ---------- 自封闭夹具（不依赖 data/，KP 库与误解库显式可控） ----------

def _entry(mid, kp_id, sigs):
    return MisconceptionEntry(id=mid, kp_id=kp_id,
                              description=f"desc-{mid}", hint=f"hint-{mid}",
                              signature=tuple(sigs))


@pytest.fixture
def entries():
    return [
        _entry("e1", "k1", ["-2", "2a"]),
        _entry("e2", "k1", ["3/4"]),
        _entry("e3", "k2", ["x=5"]),
    ]


@pytest.fixture
def exemptions():
    return [Exemption(kp_id="k3", reason="纯约定内容，无典型错误模式可归纳")]


@pytest.fixture
def kp_ids():
    return ["k1", "k2", "k3"]


@pytest.fixture
def bank_data():
    return {
        "misconceptions": [
            {"id": "e1", "kp_id": "k1", "description": "符号错：-3+5 算成 -8",
             "hint": "异号相加取绝对值大者的符号。", "signature": ["-8"]},
            {"id": "e2", "kp_id": "k2", "description": "去括号漏变号",
             "hint": "括号前是负号，每一项都变号。", "signature": ["5-a-3"]},
        ],
        "exemptions": [
            {"kp_id": "k3", "reason": "纯约定内容，无典型错误模式可归纳"},
        ],
    }


# ---------- parse_bank：字段映射 + 纪律（I1/I2） ----------

def test_parse_bank_fields_and_order(bank_data):
    entries, exemptions = parse_bank(bank_data)
    assert [e.id for e in entries] == ["e1", "e2"]          # 文件内原序
    assert entries[0].kp_id == "k1"
    assert entries[0].description == "符号错：-3+5 算成 -8"
    assert entries[0].signature == ("-8",)                  # list -> tuple
    assert all(isinstance(e, MisconceptionEntry) for e in entries)
    assert exemptions == [Exemption(kp_id="k3", reason="纯约定内容，无典型错误模式可归纳")]
    assert all(isinstance(x, Exemption) for x in exemptions)


def test_parse_bank_exemptions_default_empty(bank_data):
    del bank_data["exemptions"]
    entries, exemptions = parse_bank(bank_data)
    assert [e.id for e in entries] == ["e1", "e2"]
    assert exemptions == []


def test_parse_bank_pure_and_deterministic(bank_data):
    snapshot = copy.deepcopy(bank_data)
    first, second = parse_bank(bank_data), parse_bank(bank_data)
    assert first == second                                  # dataclass 逐字段相等
    assert bank_data == snapshot                            # 不改输入


def test_parse_bank_rejections(bank_data):
    def bad(mutate):
        data = copy.deepcopy(bank_data)
        mutate(data)
        return data

    cases = [
        lambda d: d.update(misconceptions="x"),                       # 非 list
        lambda d: d.update(exemptions="x"),                           # 豁免非 list
        lambda d: d["misconceptions"].append("not-a-dict"),           # 条目非 dict
        lambda d: d["misconceptions"][0].update(id="e2"),             # 条目 id 重复
        lambda d: d["misconceptions"][0].update(id=""),               # 空 id
        lambda d: d["misconceptions"][0].update(id=" e1"),            # id 首尾空白
        lambda d: d["misconceptions"][0].update(kp_id=""),            # 空 kp_id
        lambda d: d["misconceptions"][0].update(kp_id="k1 "),         # kp_id 首尾空白
        lambda d: d["misconceptions"][0].update(description="  "),    # 空白 description
        lambda d: d["misconceptions"][0].pop("hint"),                 # 缺 hint
        lambda d: d["misconceptions"][0].update(hint=""),             # 空 hint
        lambda d: d["misconceptions"][0].pop("signature"),            # 缺 signature
        lambda d: d["misconceptions"][0].update(signature=[]),        # 空 signature
        lambda d: d["misconceptions"][0].update(signature="x"),       # signature 非 list
        lambda d: d["misconceptions"][0].update(signature=[""]),      # 空串签名
        lambda d: d["misconceptions"][0].update(signature=[" -8"]),   # 签名首尾空白
        lambda d: d["misconceptions"][0].update(signature=[7]),       # 签名非 str
        lambda d: d["misconceptions"][0].update(signature=["x", "x"]),  # 条目内重复签名
        lambda d: d["exemptions"].append({"kp_id": "k4"}),            # 豁免缺 reason
        lambda d: d["exemptions"].append({"kp_id": "k4", "reason": " "}),  # 空白 reason
        lambda d: d["exemptions"].append({"kp_id": "k3", "reason": "r"}),  # 豁免 kp 文件内重复
        lambda d: d["exemptions"].append("not-a-dict"),               # 豁免非 dict
    ]
    for mutate in cases:
        with pytest.raises(MisconceptionCoverageError):
            parse_bank(bad(mutate))
    for worse in ({}, {"misconceptions": None}, "not-a-dict", None, []):
        with pytest.raises(MisconceptionCoverageError):
            parse_bank(worse)
    # 空 misconceptions list 合法（空文件），缺口交由 audit 报告
    entries, exemptions = parse_bank({"misconceptions": []})
    assert entries == [] and exemptions == []
    assert issubclass(MisconceptionCoverageError, ValueError)


# ---------- audit：报告闭式 + 分划（I3/I4） ----------

def test_audit_closed_form(kp_ids, entries, exemptions):
    rep = audit(kp_ids, entries, exemptions)
    assert isinstance(rep, MisconceptionReport)
    assert rep.kp_ids == ("k1", "k2", "k3")
    assert rep.counts == (("k1", 2), ("k2", 1), ("k3", 0))
    assert rep.covered_kp_ids == ("k1",)
    assert rep.deficient_kp_ids == ("k2",)                  # k3 豁免不进缺口
    assert rep.exempt_kp_ids == ("k3",)
    assert rep.min_per_kp == 2
    assert rep.total_misconceptions == 3
    assert rep.is_complete() is False


def test_audit_min_per_kp(kp_ids, entries, exemptions):
    rep = audit(kp_ids, entries, exemptions, min_per_kp=1)
    assert rep.covered_kp_ids == ("k1", "k2")
    assert rep.deficient_kp_ids == ()
    assert rep.exempt_kp_ids == ("k3",)
    assert rep.is_complete() is True
    rep3 = audit(kp_ids, entries, exemptions, min_per_kp=3)
    assert rep3.deficient_kp_ids == ("k1", "k2")            # k1 只有 2 条也成缺口
    assert rep3.counts == (("k1", 2), ("k2", 1), ("k3", 0))
    assert rep3.is_complete() is False


def test_audit_partitions(kp_ids, entries, exemptions):
    rep = audit(kp_ids, entries, exemptions)
    assert set(rep.covered_kp_ids) | set(rep.deficient_kp_ids) | set(rep.exempt_kp_ids) \
        == set(kp_ids)
    assert not (set(rep.covered_kp_ids) & set(rep.deficient_kp_ids))
    assert not (set(rep.covered_kp_ids) & set(rep.exempt_kp_ids))
    assert not (set(rep.deficient_kp_ids) & set(rep.exempt_kp_ids))
    assert rep.total_misconceptions == len(entries)
    assert dict(rep.counts) == {"k1": 2, "k2": 1, "k3": 0}


def test_audit_input_order(kp_ids, entries, exemptions):
    rep = audit(list(reversed(kp_ids)), entries, exemptions)
    assert rep.kp_ids == ("k3", "k2", "k1")                 # 输入原序
    assert rep.deficient_kp_ids == ("k2",)
    assert rep.exempt_kp_ids == ("k3",)
    assert rep.covered_kp_ids == ("k1",)


def test_audit_exemption_semantics(kp_ids, entries):
    # 豁免 KP 无条数要求（0 条即合法豁免）
    rep = audit(["k1", "k9"], entries[:2], [Exemption("k9", "无误解")])
    assert rep.exempt_kp_ids == ("k9",)
    assert rep.deficient_kp_ids == ()                       # k1 有 2 条达标，k9 豁免
    assert rep.counts == (("k1", 2), ("k9", 0))
    assert rep.is_complete() is True
    # 豁免名下已有误解 -> 矛盾抛错
    with pytest.raises(MisconceptionCoverageError):
        audit(["k1", "k2"], entries, [Exemption("k1", "自称无误解")])
    # 豁免未知 KP -> 抛错
    with pytest.raises(MisconceptionCoverageError):
        audit(["k1"], entries, [Exemption("kz", "不存在")])
    # 重复豁免 -> 抛错
    with pytest.raises(MisconceptionCoverageError):
        audit(["k1", "k9"], [], [Exemption("k9", "r1"), Exemption("k9", "r2")])


def test_audit_entry_id_global_unique(kp_ids, entries):
    dup = list(entries) + [_entry("e1", "k2", ["x"])]       # 跨输入（模拟跨文件）重复
    with pytest.raises(MisconceptionCoverageError):
        audit(kp_ids, dup, [])
    with pytest.raises(MisconceptionCoverageError):
        audit(kp_ids, list(entries) + list(entries), [])    # 整体翻倍同样命中


def test_audit_unknown_kp_reference(kp_ids, entries):
    # kp 清单缺 k2，而条目 e3 引用 k2 -> 未知 KP 引用
    with pytest.raises(MisconceptionCoverageError):
        audit(["k1", "k3"], entries, [])
    # 无条目引用未知 KP 时，KP 清单里多出的 KP 只是缺口，不是错误
    rep = audit(["k1", "kx"], entries[:2], [])
    assert rep.deficient_kp_ids == ("kx",) and rep.is_complete() is False


def test_audit_signature_unique_per_kp(kp_ids, entries):
    # e3（k2）与 e5（k2）同 KP 且签名 x=5 重复 -> 归因歧义，抛错
    bad = list(entries) + [_entry("e5", "k2", ["x=5"])]
    with pytest.raises(MisconceptionCoverageError):
        audit(kp_ids, bad, [])
    # 同签名落到不同 KP（e4 属 k1）不冲突，合法
    cross = list(entries) + [_entry("e4", "k1", ["x=5", "9"])]
    rep = audit(kp_ids, cross, [])
    assert dict(rep.counts)["k1"] == 3


# ---------- 输入纪律（I6） ----------

def test_audit_kpid_validation(entries):
    with pytest.raises(MisconceptionCoverageError):
        audit(["k1", "k1"], entries, [])                    # 重复
    with pytest.raises(MisconceptionCoverageError):
        audit(["k1", ""], entries, [])                      # 空串
    with pytest.raises(MisconceptionCoverageError):
        audit(["k1", " k1 "], entries, [])                  # 首尾空白
    with pytest.raises(MisconceptionCoverageError):
        audit(["k1", 7], entries, [])                       # 非 str


def test_audit_min_per_kp_validation(kp_ids, entries):
    for bad_min in (0, -1, "2", 2.0, None, True):
        with pytest.raises(MisconceptionCoverageError):
            audit(kp_ids, entries, [], min_per_kp=bad_min)


def test_audit_purity(kp_ids, entries, exemptions):
    kp_snap, entry_snap, ex_snap = (copy.deepcopy(kp_ids), copy.deepcopy(entries),
                                    copy.deepcopy(exemptions))
    rep = audit(kp_ids, entries, exemptions)
    assert kp_ids == kp_snap and entries == entry_snap and exemptions == ex_snap
    with pytest.raises(AttributeError):                     # 报告字段是 tuple，改不动
        rep.deficient_kp_ids.append("x")
    with pytest.raises(AttributeError):
        rep.counts[0].append("x")
    assert rep.counts[0] == ("k1", 2)                       # 未被上一句破坏


def test_audit_empty_kp_universe():
    rep = audit([], [], [])
    assert rep.kp_ids == () and rep.counts == ()
    assert rep.deficient_kp_ids == () and rep.exempt_kp_ids == () and rep.covered_kp_ids == ()
    assert rep.total_misconceptions == 0
    assert rep.is_complete() is True                        # 对空集命题为真（诚实空库）
    with pytest.raises(MisconceptionCoverageError):
        audit([], [_entry("e1", "k1", ["x"])], [])          # 有条目即未知 KP


# ---------- 鸭子类型兼容（I7） ----------

def test_audit_accepts_types_misconception(kp_ids, entries, exemptions):
    duck = [Misconception(id="d1", kp_id="k1", description="d", hint="h",
                          signature=["s1"]),
            Misconception(id="d2", kp_id="k2", description="d", hint="h",
                          signature=["s2"])]
    rep_duck = audit(kp_ids, duck, exemptions)
    rep_entry = audit(kp_ids, [_entry("d1", "k1", ["s1"]), _entry("d2", "k2", ["s2"])],
                      exemptions)
    assert rep_duck == rep_entry                            # types.Misconception 可直接传入


# ---------- audit_dicts：入口等价 + 校验（I8） ----------

def test_dicts_entry_equivalence(kp_ids, entries, exemptions, bank_data):
    rep_dicts = audit_dicts([{"id": k} for k in kp_ids], bank_data)
    rep_objs = audit(kp_ids, [_entry("e1", "k1", ["-8"]), _entry("e2", "k2", ["5-a-3"])],
                     [Exemption("k3", "纯约定内容，无典型错误模式可归纳")])
    assert rep_dicts == rep_objs
    assert rep_dicts.counts == (("k1", 1), ("k2", 1), ("k3", 0))
    assert rep_dicts.is_complete() is False


def test_dicts_entry_validation(bank_data):
    with pytest.raises(MisconceptionCoverageError):
        audit_dicts("not-a-list", bank_data)
    with pytest.raises(MisconceptionCoverageError):
        audit_dicts(["not-a-dict"], bank_data)
    with pytest.raises(MisconceptionCoverageError):
        audit_dicts([{"kp_id": "k1"}], bank_data)           # 缺 id
    with pytest.raises(MisconceptionCoverageError):
        audit_dicts([{"id": ""}], bank_data)                # 空 id
    with pytest.raises(MisconceptionCoverageError):
        audit_dicts([{"id": "k1"}], {"misconceptions": "x"})  # 库非法原样抛出


# ---------- 确定性（I9） ----------

def test_determinism(kp_ids, entries, exemptions, bank_data):
    assert audit(kp_ids, entries, exemptions) == audit(kp_ids, entries, exemptions)
    assert audit(kp_ids, entries, exemptions, min_per_kp=1) == \
        audit(kp_ids, entries, exemptions, min_per_kp=1)
    assert audit_dicts([{"id": k} for k in kp_ids], bank_data) == \
        audit_dicts([{"id": k} for k in kp_ids], bank_data)
