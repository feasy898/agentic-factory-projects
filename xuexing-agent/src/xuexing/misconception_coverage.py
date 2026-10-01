"""misconception_coverage —— 误解库覆盖审计器（误解库扩充管线的确定性内核）。

行为契约（specs/drafts/misconception_coverage.spec.md，本文件为参考实现）：
- 解析：误解库文件 dict（{"misconceptions": [...], "exemptions": [...]（可选）}）
  解析校验为 MisconceptionEntry / Exemption 列表——id 无空白非空、description/hint
  非空、signature 非空且元素为无首尾空白的非空字符串且条目内去重、豁免必附理由；
- 审计：对给定 KP id 清单逐个核对「误解条数 ≥ min_per_kp 或显式声明无误解」，
  产出确定性报告（逐 KP 计数、缺口 KP、豁免 KP、已覆盖 KP、总数）；
- 交叉一致性：条目 id 跨输入全局唯一、条目/豁免引用未知 KP、豁免与已有误解矛盾、
  同 KP 内 signature 跨条目重复都是数据错误；
- 纯函数：无 IO、无随机、无时钟；所有输出 tuple 化且顺序 = KP 输入原序 /
  文件内原序，同输入同输出。

注入装载约束（同 recommend/standard_coverage 规格 §2）：不用 from __future__ import
annotations——dataclass 字符串注解在 _regen_misconception_coverage 顶层模块名下会触发
未受保护的 sys.modules 解析；注解直接写真实对象。
"""
from dataclasses import dataclass

__all__ = [
    "MisconceptionCoverageError",
    "MisconceptionEntry",
    "Exemption",
    "MisconceptionReport",
    "parse_bank",
    "audit",
    "audit_dicts",
]


class MisconceptionCoverageError(ValueError):
    """misconception_coverage 模块所有校验失败的异常类型。"""


@dataclass
class MisconceptionEntry:
    """一条典型误解（审计侧解析产物；字段与 xuexing.types.Misconception 同形）。

    signature 是该误解下的典型错误答案（无首尾空白、条目内不重复，供
    attribute_error 确定性签名匹配）；hint 是教学提示。
    """

    id: str
    kp_id: str
    description: str
    hint: str
    signature: tuple


@dataclass
class Exemption:
    """「该 KP 无误解」的显式声明：必须给非空理由，且该 KP 名下不得已有误解。"""

    kp_id: str
    reason: str


@dataclass
class MisconceptionReport:
    """误解覆盖审计报告。

    - counts：每个输入 KP 恰一项 (kp_id, count)，按 KP 输入原序；
    - deficient_kp_ids：条数 < min_per_kp 且未豁免的 KP（缺口），输入原序；
    - exempt_kp_ids：显式声明无误解的 KP，输入原序；
    - covered_kp_ids：条数达标的 KP，输入原序。
    """

    kp_ids: tuple
    counts: tuple
    deficient_kp_ids: tuple
    exempt_kp_ids: tuple
    covered_kp_ids: tuple
    min_per_kp: int
    total_misconceptions: int

    def is_complete(self):
        """无缺口（每个 KP 条数达标或已显式豁免）时为 True。"""
        return not self.deficient_kp_ids


# ---------- 解析与校验 ----------

def _require_id(value, what):
    """无首尾空白的非空字符串校验，返回原值；否则抛 MisconceptionCoverageError。"""
    if not isinstance(value, str) or not value.strip():
        raise MisconceptionCoverageError(f"{what} must be a non-empty string, got {value!r}")
    if value != value.strip():
        raise MisconceptionCoverageError(f"{what} has surrounding whitespace: {value!r}")
    return value


def _require_text(value, what):
    """非空白字符串校验（内部空白自由），返回原值；否则抛 MisconceptionCoverageError。"""
    if not isinstance(value, str) or not value.strip():
        raise MisconceptionCoverageError(f"{what} must be a non-empty string, got {value!r}")
    return value


def _parse_entry(raw, seen_ids):
    if not isinstance(raw, dict):
        raise MisconceptionCoverageError(f"misconception entry must be a dict, got {raw!r}")
    mid = _require_id(raw.get("id"), "misconception id")
    if mid in seen_ids:
        raise MisconceptionCoverageError(f"duplicate misconception id: {mid}")
    seen_ids.add(mid)
    kp_id = _require_id(raw.get("kp_id"), f"misconception {mid} kp_id")
    description = _require_text(raw.get("description"), f"misconception {mid} description")
    hint = _require_text(raw.get("hint"), f"misconception {mid} hint")
    signature = raw.get("signature")
    if not isinstance(signature, list) or not signature:
        raise MisconceptionCoverageError(
            f"misconception {mid} signature must be a non-empty list")
    cleaned = []
    for sig in signature:
        if not isinstance(sig, str) or not sig.strip():
            raise MisconceptionCoverageError(
                f"misconception {mid} signature must be a non-empty string, got {sig!r}")
        if sig != sig.strip():
            raise MisconceptionCoverageError(
                f"misconception {mid} signature has surrounding whitespace: {sig!r}")
        if sig in cleaned:
            raise MisconceptionCoverageError(
                f"misconception {mid} has duplicate signature {sig!r}")
        cleaned.append(sig)
    return MisconceptionEntry(id=mid, kp_id=kp_id, description=description,
                              hint=hint, signature=tuple(cleaned))


def _parse_exemption(raw, seen_kp):
    if not isinstance(raw, dict):
        raise MisconceptionCoverageError(f"exemption entry must be a dict, got {raw!r}")
    kp_id = _require_id(raw.get("kp_id"), "exemption kp_id")
    if kp_id in seen_kp:
        raise MisconceptionCoverageError(f"duplicate exemption for kp: {kp_id}")
    seen_kp.add(kp_id)
    reason = _require_text(raw.get("reason"), f"exemption {kp_id} reason")
    return Exemption(kp_id=kp_id, reason=reason)


def parse_bank(data):
    """解析误解库文件 dict，返回 (entries, exemptions) 二元组（文件内原序）。

    data 形状：{"misconceptions": [...], "exemptions": [...]（可选，缺省为空列表）}。
    校验失败抛 MisconceptionCoverageError（规则见模块 docstring 与规格 §3.3）。
    解析不改输入；纯函数。
    """
    if not isinstance(data, dict):
        raise MisconceptionCoverageError(f"bank data must be a dict, got {data!r}")
    if "misconceptions" not in data:
        raise MisconceptionCoverageError("bank data must contain a 'misconceptions' list")
    raw_mcs = data["misconceptions"]
    if not isinstance(raw_mcs, list):
        raise MisconceptionCoverageError(
            f"'misconceptions' must be a list, got {raw_mcs!r}")
    raw_exemptions = data.get("exemptions", [])
    if not isinstance(raw_exemptions, list):
        raise MisconceptionCoverageError(
            f"'exemptions' must be a list, got {raw_exemptions!r}")
    entries = []
    seen_ids = set()
    for raw in raw_mcs:
        entries.append(_parse_entry(raw, seen_ids))
    exemptions = []
    seen_kp = set()
    for raw in raw_exemptions:
        exemptions.append(_parse_exemption(raw, seen_kp))
    return entries, exemptions


# ---------- 审计 ----------

def audit(kp_ids, entries, exemptions=(), min_per_kp=2):
    """KP id 序列 × 误解条目 × 豁免声明 -> MisconceptionReport。

    - kp_ids：非空无空白 str 的可迭代对象，重复抛错；
    - entries：元素需有 .id/.kp_id（MisconceptionEntry 或 xuexing.types.Misconception
      均可）；id 全局重复、引用未知 KP、同 KP 内 signature 跨条目重复均抛错；
    - exemptions：元素需有 .kp_id/.reason；未知 KP、重复、与已有误解矛盾均抛错；
    - min_per_kp：int（bool 不算）且 >=1，否则抛错。
    输出顺序全部按 kp_ids 输入原序；不改入参；空 KP 库（无条目）合法且 is_complete()
    为 True。"""
    if isinstance(min_per_kp, bool) or not isinstance(min_per_kp, int) or min_per_kp < 1:
        raise MisconceptionCoverageError(
            f"min_per_kp must be an int >= 1, got {min_per_kp!r}")
    kp_list = []
    seen_kp = set()
    for kp_id in kp_ids:
        _require_id(kp_id, "kp id")
        if kp_id in seen_kp:
            raise MisconceptionCoverageError(f"duplicate kp id: {kp_id}")
        seen_kp.add(kp_id)
        kp_list.append(kp_id)

    by_kp = {kp_id: [] for kp_id in kp_list}
    seen_entry_ids = set()
    for entry in entries:
        entry_id = getattr(entry, "id", None)
        if not isinstance(entry_id, str) or not entry_id.strip():
            raise MisconceptionCoverageError(
                f"entry id must be a non-empty string, got {entry_id!r}")
        if entry_id in seen_entry_ids:
            raise MisconceptionCoverageError(f"duplicate entry id: {entry_id}")
        seen_entry_ids.add(entry_id)
        kp_id = getattr(entry, "kp_id", None)
        if kp_id not in by_kp:
            raise MisconceptionCoverageError(
                f"entry {entry_id}: unknown kp {kp_id!r}")
        by_kp[kp_id].append((entry_id, tuple(getattr(entry, "signature", ()))))

    exempt_set = set()
    for ex in exemptions:
        kp_id = getattr(ex, "kp_id", None)
        if kp_id not in by_kp:
            raise MisconceptionCoverageError(f"exemption: unknown kp {kp_id!r}")
        if kp_id in exempt_set:
            raise MisconceptionCoverageError(f"duplicate exemption for kp: {kp_id}")
        if by_kp[kp_id]:
            raise MisconceptionCoverageError(
                f"exemption for {kp_id} contradicts "
                f"{len(by_kp[kp_id])} existing misconception(s)")
        exempt_set.add(kp_id)

    # 同 KP 内 signature 跨条目不得重复：重复会让 attribute_error 的首个命中归因歧义。
    seen_sig = {}
    for kp_id, pairs in by_kp.items():
        for entry_id, sigs in pairs:
            for sig in sigs:
                if sig in seen_sig.setdefault(kp_id, set()):
                    raise MisconceptionCoverageError(
                        f"kp {kp_id}: signature {sig!r} duplicated "
                        f"across misconceptions (e.g. {entry_id})")
                seen_sig[kp_id].add(sig)

    counts = tuple((kp_id, len(by_kp[kp_id])) for kp_id in kp_list)
    deficient = tuple(kp for kp, n in counts if n < min_per_kp and kp not in exempt_set)
    exempt = tuple(kp for kp in kp_list if kp in exempt_set)
    covered = tuple(kp for kp, n in counts if n >= min_per_kp)
    return MisconceptionReport(
        kp_ids=tuple(kp_list),
        counts=counts,
        deficient_kp_ids=deficient,
        exempt_kp_ids=exempt,
        covered_kp_ids=covered,
        min_per_kp=min_per_kp,
        total_misconceptions=len(seen_entry_ids),
    )


def audit_dicts(kp_dicts, bank_data, min_per_kp=2):
    """knowledge json 形状（dict 列表）× 误解库文件 dict 的便捷入口。

    每个 KP dict 必须含非空字符串 "id"；bank_data 先过 parse_bank（解析错误原样抛出）。
    其余语义同 audit。
    """
    if not isinstance(kp_dicts, (list, tuple)):
        raise MisconceptionCoverageError(f"kp_dicts must be a list, got {kp_dicts!r}")
    kp_ids = []
    for raw in kp_dicts:
        if not isinstance(raw, dict):
            raise MisconceptionCoverageError(f"kp entry must be a dict, got {raw!r}")
        kp_ids.append(_require_id(raw.get("id"), "kp id"))
    entries, exemptions = parse_bank(bank_data)
    return audit(kp_ids, entries, exemptions, min_per_kp)
