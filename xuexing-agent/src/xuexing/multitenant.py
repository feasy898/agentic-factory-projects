"""机构多租户内核：org 维度数据隔离（BACKLOG P2「机构多租户」，specs/drafts/
multitenant.spec.md）。

职责：给 server 的两类会话状态加 org 命名空间——

  * OrgStore       学习者会话存储（responses / history / profile / administered），
                   对应 server 闭包里的 store；
  * AttemptCounter 每知识点作答计数，对应 server 闭包里的 attempt_counts；

外加两个键积木：

  * resolve_org    缺省机构归并（None/空白 → DEFAULT_ORG_ID）；归并由容器在
                   每次方法调用时强制执行，调用方不会因忘记归并而串域；
  * org_key        (org_id, learner_id) 的单射复合键（长度前缀法，分隔符歧义对
                   不碰撞），供需要扁平键的场景使用；容器内部以嵌套字典实现
                   同等的单射分域。

隔离语义：org_id 大小写敏感；同一 learner_id 在不同 org 下是完全独立的数据域。
org 维度只改变状态归属，不参与任何领域算法。

不做领域算法、不做鉴权/CRUD/持久化；HTTP 穿线（X-Org-Id 请求头、/orgs 枚举
端点）在 server.py（薄胶水层）。

确定性：纯标准库（本模块连 xuexing.types 都不需要）、无时钟、无随机、无
文件 IO；枚举一律升序；同输入同输出。
"""

DEFAULT_ORG_ID = "default"


def resolve_org(org_id):
    """缺省机构归并：None / 空串 / 纯空白 -> DEFAULT_ORG_ID；否则去首尾空白后
    原样返回（大小写敏感："OrgA" 与 "orga" 是两个机构，非 ASCII 原样保留）。
    对任意 str | None 全函数；非 str（且非 None）-> TypeError。
    """
    if org_id is None:
        return DEFAULT_ORG_ID
    if not isinstance(org_id, str):
        raise TypeError("org_id must be str or None")
    org = org_id.strip()
    return org if org else DEFAULT_ORG_ID


def org_key(org_id, learner_id):
    """(org_id, learner_id) 的单射复合键：f"{len(org_id)}:{org_id}{learner_id}"。

    长度前缀使拆分无歧义——org 含冒号等分隔符的歧义对不碰撞：
    org_key("a:x", "y") != org_key("a", "x:y")。确定性纯函数；
    两参数任一非 str -> TypeError。
    """
    if not isinstance(org_id, str) or not isinstance(learner_id, str):
        raise TypeError("org_id and learner_id must be str")
    return f"{len(org_id)}:{org_id}{learner_id}"


def _pair(org_id, learner_id):
    """容器公共入口：归并缺省机构 + learner_id 类型门。"""
    org = resolve_org(org_id)
    if not isinstance(learner_id, str):
        raise TypeError("learner_id must be str")
    return org, learner_id


class OrgStore:
    """org 分域的学习者会话存储：{org: {learner_id: entry}}。

    entry 形状与既有 server store 一致：起步 {"responses": [], "history": []}，
    可携带 "profile"（画像）与 "administered"（已出题 id）等附加键。
    所有方法先经 resolve_org 归并缺省机构（I2/I3）。
    """

    def __init__(self):
        self._data = {}

    def get(self, org_id, learner_id):
        """该 (org, learner) 的 entry dict；不存在 -> None（不建域）。"""
        org, lid = _pair(org_id, learner_id)
        return self._data.get(org, {}).get(lid)

    def entry(self, org_id, learner_id):
        """get-or-create：返回 entry（缺失则先建 {"responses": [], "history": []}）；
        同一对重复调用返回同一 dict（状态延续）。"""
        org, lid = _pair(org_id, learner_id)
        org_map = self._data.setdefault(org, {})
        if lid not in org_map:
            org_map[lid] = {"responses": [], "history": []}
        return org_map[lid]

    def set_profile(self, org_id, learner_id, profile):
        """在（必要时新建的）entry 上写 profile；无返回值。"""
        self.entry(org_id, learner_id)["profile"] = profile

    def has_profile(self, org_id, learner_id):
        """该 (org, learner) 是否已存画像（entry 存在且含 profile）。"""
        e = self.get(org_id, learner_id)
        return e is not None and "profile" in e

    def learner_ids(self, org_id):
        """该机构下已知学习者 id，升序去重；机构不存在 -> []。
        经 review/submit 建档的学习者即使无 profile 也计入。"""
        org = resolve_org(org_id)
        return sorted(self._data.get(org, {}))

    def org_ids(self):
        """出现过的机构 id，升序去重（值恒非空串：缺省已归并）。"""
        return sorted(self._data)


class AttemptCounter:
    """org 分域的每知识点作答计数：{org: {learner_id: {kp_id: n}}}。

    counts() 返回活字典（调用方可直接读、可整体传给只读选题器）；
    bump() 原子地 +1 并返回新值。所有方法先经 resolve_org 归并。
    """

    def __init__(self):
        self._data = {}

    def counts(self, org_id, learner_id):
        """该 (org, learner) 的 {kp_id: n} 计数字典（get-or-create，活引用）。"""
        org, lid = _pair(org_id, learner_id)
        return self._data.setdefault(org, {}).setdefault(lid, {})

    def bump(self, org_id, learner_id, kp_id):
        """计数 +1，返回新值（首计为 1）。kp_id 非 str -> TypeError。"""
        if not isinstance(kp_id, str):
            raise TypeError("kp_id must be str")
        c = self.counts(org_id, learner_id)
        c[kp_id] = c.get(kp_id, 0) + 1
        return c[kp_id]

    def get(self, org_id, learner_id, kp_id):
        """只读单值：未计过 -> 0。kp_id 非 str -> TypeError。"""
        if not isinstance(kp_id, str):
            raise TypeError("kp_id must be str")
        return self.counts(org_id, learner_id).get(kp_id, 0)
