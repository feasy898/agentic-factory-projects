"""知识点图谱（kpgraph）—— 终版重生成实现。

节点为 KnowledgePoint，边为"先序边"（prereq -> kp：prereq 必须先于 kp 掌握）。
声明（KnowledgePoint.prereqs）与已加边独立存储、不自动同步，差异由 validate() 报告：
topological_order / descendants / children 只依据已加边；
ancestors / prereqs / frontier 只依据声明。

确定性：无随机源、无时钟；全部排序为 id 字典序或声明序（locale 无关）。
"""

from __future__ import annotations

import heapq
import json
from typing import Optional

from xuexing.types import KnowledgePoint

__all__ = ["KPGraphError", "KPGraph", "kpgraph_from_dict", "load_kpgraph"]


class KPGraphError(ValueError):
    """图谱构建/查询的领域错误（模块唯一异常类型）。"""


class KPGraph:
    """知识点有向图：add_kp/add_edge 构建，validate 校验，拓扑/闭包/前沿查询。"""

    def __init__(self) -> None:
        self._nodes: dict[str, KnowledgePoint] = {}
        self._children: dict[str, list[str]] = {}  # 只存已加边；每表无重复（幂等）

    # ---------- 构建 ----------

    def add_kp(self, kp: KnowledgePoint) -> None:
        if kp.id in self._nodes:
            raise KPGraphError(f"duplicate kp id: {kp.id}")
        # prereqs 声明此时不校验，由 validate() 事后报告
        self._nodes[kp.id] = kp
        self._children[kp.id] = []

    def add_edge(self, prereq_id: str, kp_id: str) -> None:
        # 检查顺序冻结：先端点存在性，后自环
        if prereq_id not in self._nodes or kp_id not in self._nodes:
            raise KPGraphError(f"unknown endpoint in edge {prereq_id} -> {kp_id}")
        if prereq_id == kp_id:
            raise KPGraphError("self loop")
        kids = self._children[prereq_id]
        if kp_id not in kids:  # 重复加边幂等
            kids.append(kp_id)

    # ---------- 校验 ----------

    def validate(self) -> list[str]:
        """四类检查（未知声明 prereq / 声明未加边 / 边未声明 / 边环），返回升序去重消息。"""
        errors: list[str] = []
        for kp_id, kp in self._nodes.items():
            for p in kp.prereqs:
                if p not in self._nodes:
                    errors.append(f"{kp_id}: unknown prereq {p}")
                elif kp_id not in self._children[p]:
                    errors.append(f"{kp_id}: prereq {p} missing edge")
        for p, kids in self._children.items():
            for c in kids:
                if p not in self._nodes[c].prereqs:
                    errors.append(f"edge {p}->{c} not declared in prereqs")
        if self._kahn()[1]:  # 环检测只看已加边
            errors.append("graph contains a prerequisite cycle")
        return sorted(set(errors))

    # ---------- 查询（容器一律新建；KnowledgePoint 与图共享实例） ----------

    def kps(self) -> list[KnowledgePoint]:
        return [self._nodes[kp_id] for kp_id in sorted(self._nodes)]

    def get(self, kp_id: str) -> Optional[KnowledgePoint]:
        return self._nodes.get(kp_id)

    def has(self, kp_id: str) -> bool:
        return kp_id in self._nodes

    def children(self, kp_id: str) -> list[str]:
        return sorted(self._children.get(kp_id, ()))

    def prereqs(self, kp_id: str) -> list[str]:
        kp = self._nodes.get(kp_id)
        return [] if kp is None else list(kp.prereqs)  # 保持声明序与重复项

    def ancestors(self, kp_id: str) -> set[str]:
        seen: set[str] = set()
        stack = [kp_id]
        while stack:
            for p in self.prereqs(stack.pop()):
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        return seen

    def descendants(self, kp_id: str) -> set[str]:
        seen: set[str] = set()
        stack = [kp_id]
        while stack:
            for c in self.children(stack.pop()):
                if c not in seen:
                    seen.add(c)
                    stack.append(c)
        return seen

    def topological_order(self) -> list[str]:
        order, cyclic = self._kahn()
        if cyclic:
            raise KPGraphError("cycle detected in topological_order")
        return order

    def frontier(self, mastery: dict[str, float], threshold: float) -> list[str]:
        """入选 ⟺ 自身 mastery（缺省 0.0）< threshold 且全部声明 prereq 的 mastery ≥ threshold。"""
        picked = [
            kp.id
            for kp in self.kps()
            if mastery.get(kp.id, 0.0) < threshold
            and all(mastery.get(p, 0.0) >= threshold for p in kp.prereqs)
        ]
        picked.sort(key=lambda k: (-len(self.descendants(k)), k))
        return picked

    # ---------- 内部 ----------

    def _kahn(self) -> tuple[list[str], bool]:
        """Kahn 拓扑排序，字典序破平；只依据已加边。返回 (order, 是否有边环)。"""
        indeg = {kid: 0 for kid in self._nodes}
        for kids in self._children.values():
            for c in kids:
                indeg[c] += 1
        heap = [kid for kid, d in indeg.items() if d == 0]
        heapq.heapify(heap)
        order: list[str] = []
        while heap:
            n = heapq.heappop(heap)
            order.append(n)
            for c in self._children[n]:
                indeg[c] -= 1
                if indeg[c] == 0:
                    heapq.heappush(heap, c)
        return order, len(order) != len(self._nodes)


def kpgraph_from_dict(data: dict) -> KPGraph:
    """从 dict 构图：拣选 8 个已知键；缺 knowledge_points/节点缺 id,name 透传原生 KeyError，
    非列表/非 dict 节点透传原生 TypeError；grade 经 int()、prereqs 经 list() 强转。"""
    g = KPGraph()
    for node in data["knowledge_points"]:
        g.add_kp(
            KnowledgePoint(
                id=node["id"],
                name=node["name"],
                subject=node.get("subject", "math"),
                grade=int(node.get("grade", 7)),
                cluster=node.get("cluster", ""),
                description=node.get("description", ""),
                standard_ref=node.get("standard_ref", ""),
                prereqs=list(node.get("prereqs", [])),
            )
        )
    # 先全部 add_kp，再按声明补边（重复声明由 add_edge 幂等兜住）
    for kp in g.kps():
        for p in kp.prereqs:
            g.add_edge(p, kp.id)
    return g


def load_kpgraph(path: str) -> KPGraph:
    with open(path, encoding="utf-8") as f:
        return kpgraph_from_dict(json.load(f))
