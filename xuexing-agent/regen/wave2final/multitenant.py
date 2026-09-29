"""multitenant —— 机构多租户内核（冻结契约 specs/frozen/multitenant.spec.md §3.1–3.5）。

会话状态按 (org_id, learner_id) 分域：org 只改变状态归属，不涉任何领域算法。
仅标准库；零 IO、零时钟、零随机；无全局可变状态（全部状态在实例内）。
HTTP 穿线（X-Org-Id、GET /orgs）属 server 薄胶水层，不在重生成范围。
"""
from __future__ import annotations

__all__ = ["DEFAULT_ORG_ID", "OrgStore", "AttemptCounter", "org_key", "resolve_org"]


DEFAULT_ORG_ID: str = "default"


def _require_str(value: object, name: str) -> None:
    """严格 str 门（I12）：None 或任何非 str（含 bool）→ TypeError。"""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str, got {type(value).__name__}")


def resolve_org(org_id: str | None) -> str:
    """缺省机构归并（I2）：None/""/纯空白 → DEFAULT_ORG_ID；其余去首尾空白原样返回。

    不做大小写折叠、不做 Unicode 规范化；非 str 且非 None → TypeError。
    """
    if org_id is None:
        return DEFAULT_ORG_ID
    _require_str(org_id, "org_id")
    org = org_id.strip()
    return org if org else DEFAULT_ORG_ID


def org_key(org_id: str, learner_id: str) -> str:
    """(org, learner) 的单射复合键（I1，格式冻结 §3.3）。

    长度前缀（org 的十进制字符长度）+ ":" + org + learner 直接相连，
    使任意分隔符歧义对（org 含 ":" 等）与空串参数都不碰撞、可无歧义拆分。
    """
    _require_str(org_id, "org_id")
    _require_str(learner_id, "learner_id")
    return f"{len(org_id)}:{org_id}{learner_id}"


class OrgStore:
    """org 分域的学习者会话存储 {org: {learner_id: entry}}（I3/I4）。

    容器公共入口（I12）：先对 org 位做 resolve_org 归并（org 门先于 learner 门），
    再对 learner_id 严格 str。只读方法（get/has_profile）不建域。
    """

    def __init__(self) -> None:
        self._domains: dict[str, dict[str, dict]] = {}

    @staticmethod
    def _gate(org_id: str | None, learner_id: str) -> str:
        org = resolve_org(org_id)
        _require_str(learner_id, "learner_id")
        return org

    def get(self, org_id: str | None, learner_id: str) -> dict | None:
        """该 (org, learner) 的 entry；不存在返回 None 且不建任何域。"""
        org = self._gate(org_id, learner_id)
        entry = self._domains.get(org)
        if entry is None:
            return None
        return entry.get(learner_id)

    def entry(self, org_id: str | None, learner_id: str) -> dict:
        """get-or-create；缺失则建起步形状 {"responses": [], "history": []}，同对恒同一 dict。"""
        org = self._gate(org_id, learner_id)
        domain = self._domains.setdefault(org, {})
        entry = domain.get(learner_id)
        if entry is None:
            entry = {"responses": [], "history": []}
            domain[learner_id] = entry
        return entry

    def set_profile(self, org_id: str | None, learner_id: str, profile) -> None:
        """在（必要时新建的）entry 上写 profile。"""
        self.entry(org_id, learner_id)["profile"] = profile

    def has_profile(self, org_id: str | None, learner_id: str) -> bool:
        """entry 存在且含 "profile" 键；只读，不建域。"""
        org = self._gate(org_id, learner_id)
        domain = self._domains.get(org)
        if domain is None:
            return False
        entry = domain.get(learner_id)
        return entry is not None and "profile" in entry

    def learner_ids(self, org_id: str | None) -> list[str]:
        """该机构已知学习者 id，升序；无档 → []。"""
        org = resolve_org(org_id)
        return sorted(self._domains.get(org, {}))

    def org_ids(self) -> list[str]:
        """出现过的机构 id，升序去重；全新 store → []（列表可为空，元素值恒非空白）。"""
        return sorted(self._domains)


class AttemptCounter:
    """org 分域的每知识点选题计数 {org: {learner_id: {kp_id: n}}}（I5/I12）。

    入口类型门与 OrgStore 同构：org 位归并（org 门先于 learner 门），
    learner_id/kp_id 严格 str。
    """

    def __init__(self) -> None:
        self._domains: dict[str, dict[str, dict[str, int]]] = {}

    @staticmethod
    def _gate(org_id: str | None, learner_id: str) -> str:
        org = resolve_org(org_id)
        _require_str(learner_id, "learner_id")
        return org

    def counts(self, org_id: str | None, learner_id: str) -> dict[str, int]:
        """get-or-create，返回活字典；同对恒同一 dict。"""
        org = self._gate(org_id, learner_id)
        return self._domains.setdefault(org, {}).setdefault(learner_id, {})

    def bump(self, org_id: str | None, learner_id: str, kp_id: str) -> int:
        """计数 +1 并返回新值（首计为 1）。"""
        org = self._gate(org_id, learner_id)
        _require_str(kp_id, "kp_id")
        per_learner = self._domains.setdefault(org, {}).setdefault(learner_id, {})
        per_learner[kp_id] = per_learner.get(kp_id, 0) + 1
        return per_learner[kp_id]

    def get(self, org_id: str | None, learner_id: str, kp_id: str) -> int:
        """只读单值，未计过 → 0，不建域。"""
        org = self._gate(org_id, learner_id)
        _require_str(kp_id, "kp_id")
        domain = self._domains.get(org)
        if domain is None:
            return 0
        per_learner = domain.get(learner_id)
        if per_learner is None:
            return 0
        return per_learner.get(kp_id, 0)
