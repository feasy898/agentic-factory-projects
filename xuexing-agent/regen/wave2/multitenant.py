"""multitenant —— 机构多租户内核（重生成实现）。

唯一权威契约：specs/frozen/multitenant.spec.md（冻结定稿）。
单文件、仅标准库（本模块连 xuexing.types 都不需要，规格 §2）、零第三方、
零文件/网络 IO、零时钟/随机。内核只提供键派生与两个 org 分域容器，不含任何
领域算法；HTTP 穿线（X-Org-Id → §3.6–3.7）属 server 薄胶水层，不在重生成范围。

冻结要点（不变量编号对应规格 §4）：
- I1  org_key：十进制长度前缀 + ":" + org + learner，单射且确定性；
      两参数严格 str，无缺省归并。
- I2  resolve_org：None/""/纯空白 → DEFAULT_ORG_ID；其余 str 去首尾空白原样
      返回（大小写敏感、不做 Unicode 规范化）；非 str 且非 None（含 bool）→
      TypeError。
- I3/I4  OrgStore：同 learner 异 org 互为独立对象；同对重复访问返回同一活
      dict（状态延续）；新档起步形状恒为 {"responses": [], "history": []}；
      get 未档 → None 且不建域；枚举恒升序去重，org_ids() 列表本身可为空。
- I5  AttemptCounter：{org: {learner_id: {kp_id: n}}}，bump 返回新值（首计 1）、
      get 未计过 → 0、counts 返回活字典；隔离与缺省归并同 OrgStore。
- I12 类型门不对称：容器全部方法 org 位类型 str | None（None/""/纯空白归并、
      不报错；非 str 且非 None → TypeError），learner_id/kp_id 严格 str
      （None 或任何非 str → TypeError）；org 门先于 learner 门，learner 门
      先于 kp 门。
"""
from __future__ import annotations

DEFAULT_ORG_ID: str = "default"


def resolve_org(org_id: str | None) -> str:
    """缺省机构归并（§3.2 / I2）。全函数：对 str | None 输入只可能 TypeError。"""
    if org_id is None:
        return DEFAULT_ORG_ID
    if not isinstance(org_id, str):
        raise TypeError(
            f"org_id must be str or None, got {type(org_id).__name__}")
    stripped = org_id.strip()
    if stripped == "":
        return DEFAULT_ORG_ID
    return stripped


def org_key(org_id: str, learner_id: str) -> str:
    """(org_id, learner_id) 的单射复合键（§3.3 / I1）。

    冻结格式：org_id 的十进制字符长度 + ":" + org_id + learner_id（后两段直接
    相连、无额外分隔）。长度前缀使拆分无歧义，故单射对任意输入成立；本函数
    不做归并（归并只发生在 resolve_org 与容器入口），两参数严格 str。
    """
    _type_gate(org_id, "org_id")
    _type_gate(learner_id, "learner_id")
    return f"{len(org_id)}:{org_id}{learner_id}"


def _type_gate(value: object, name: str) -> None:
    """严格 str 类型门（I12 的 learner/kp/org_key 维度）。"""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str, got {type(value).__name__}")


class OrgStore:
    """org 分域的学习者会话存储 {org: {learner_id: entry}}（§3.4 / I3）。

    容器公共入口：每个方法先对 org 参数执行 resolve_org 归并（容器强制），
    再对 learner_id 做严格类型门；org 门先于 learner 门（I12）。
    entry 形状由容器起步：{"responses": [], "history": []}，随业务可携带
    "profile"、"administered" 等附加键（写入方为调用方，容器不解释）。
    """

    def __init__(self) -> None:
        self._domains: dict[str, dict[str, dict]] = {}

    def _gates(self, org_id: str | None, learner_id: str) -> tuple[str, str]:
        org = resolve_org(org_id)  # org 门：None 归并；非 str 非 None → TypeError
        _type_gate(learner_id, "learner_id")  # learner 门：严格 str
        return org, learner_id

    def get(self, org_id: str | None, learner_id: str) -> dict | None:
        """该 (org, learner) 的 entry；不存在返回 None，不建域（I3）。"""
        org, lid = self._gates(org_id, learner_id)
        return self._domains.get(org, {}).get(lid)

    def entry(self, org_id: str | None, learner_id: str) -> dict:
        """get-or-create；同一对重复调用返回同一 dict（状态延续）。"""
        org, lid = self._gates(org_id, learner_id)
        return self._domains.setdefault(org, {}).setdefault(
            lid, {"responses": [], "history": []})

    def set_profile(self, org_id: str | None, learner_id: str,
                    profile) -> None:
        """在（必要时经 entry 新建的）entry 上写 profile。"""
        org, lid = self._gates(org_id, learner_id)
        entry = self._domains.setdefault(org, {}).setdefault(
            lid, {"responses": [], "history": []})
        entry["profile"] = profile

    def has_profile(self, org_id: str | None, learner_id: str) -> bool:
        """entry 存在且含 "profile" 键；画像不跨 org。"""
        entry = self.get(org_id, learner_id)
        return entry is not None and "profile" in entry

    def learner_ids(self, org_id: str | None) -> list[str]:
        """该机构下已知学习者 id，升序去重；机构无档 → []。"""
        return sorted(self._domains.get(resolve_org(org_id), {}))

    def org_ids(self) -> list[str]:
        """出现过的机构 id，升序去重；全新 store → []（I4：列表本身可为空，
        元素值经归并语义恒非空串/纯空白）。"""
        return sorted(self._domains)


class AttemptCounter:
    """org 分域的每知识点计数 {org: {learner_id: {kp_id: n}}}（§3.5 / I5）。

    入口类型门与 OrgStore 同构：org 门先于 learner 门，learner 门先于 kp 门。
    """

    def __init__(self) -> None:
        self._counts: dict[str, dict[str, dict[str, int]]] = {}

    def _gates(self, org_id: str | None, learner_id: str) -> tuple[str, str]:
        org = resolve_org(org_id)
        _type_gate(learner_id, "learner_id")
        return org, learner_id

    def counts(self, org_id: str | None, learner_id: str) -> dict[str, int]:
        """get-or-create，返回活字典；同一对重复调用返回同一 dict。"""
        org, lid = self._gates(org_id, learner_id)
        return self._counts.setdefault(org, {}).setdefault(lid, {})

    def bump(self, org_id: str | None, learner_id: str, kp_id: str) -> int:
        """计数 +1 并返回新值（首计为 1）。"""
        org, lid = self._gates(org_id, learner_id)
        _type_gate(kp_id, "kp_id")
        per_kp = self._counts.setdefault(org, {}).setdefault(lid, {})
        per_kp[kp_id] = per_kp.get(kp_id, 0) + 1
        return per_kp[kp_id]

    def get(self, org_id: str | None, learner_id: str, kp_id: str) -> int:
        """只读单值，未计过 → 0。"""
        org, lid = self._gates(org_id, learner_id)
        _type_gate(kp_id, "kp_id")
        return self._counts.get(org, {}).get(lid, {}).get(kp_id, 0)
