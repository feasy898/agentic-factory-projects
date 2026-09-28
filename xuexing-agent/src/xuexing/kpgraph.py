"""知识点图谱：节点 + 先序边，提供拓扑、祖先/后代、前沿（可学点）计算。"""
from __future__ import annotations

import json
from typing import Optional

from .types import KnowledgePoint


class KPGraphError(ValueError):
    pass


class KPGraph:
    def __init__(self) -> None:
        self._kps: dict[str, KnowledgePoint] = {}
        self._children: dict[str, list[str]] = {}

    # ----- 构建与校验 -----
    def add_kp(self, kp: KnowledgePoint) -> None:
        if kp.id in self._kps:
            raise KPGraphError(f"duplicate kp id: {kp.id}")
        self._kps[kp.id] = kp
        self._children.setdefault(kp.id, [])

    def add_edge(self, prereq_id: str, kp_id: str) -> None:
        """prereq_id 必须先于 kp_id 掌握。"""
        if prereq_id not in self._kps or kp_id not in self._kps:
            raise KPGraphError(f"unknown endpoint in edge {prereq_id} -> {kp_id}")
        if prereq_id == kp_id:
            raise KPGraphError("self loop")
        if kp_id not in self._children[prereq_id]:
            self._children[prereq_id].append(kp_id)

    def validate(self) -> list[str]:
        errors: list[str] = []
        for kp in self._kps.values():
            for p in kp.prereqs:
                if p not in self._kps:
                    errors.append(f"{kp.id}: unknown prereq {p}")
                elif not self._has_direct_edge(p, kp.id):
                    errors.append(f"{kp.id}: prereq {p} missing edge")
        for p, kids in self._children.items():
            for c in kids:
                if p not in self._kps[c].prereqs:
                    errors.append(f"edge {p}->{c} not declared in prereqs")
        if self._find_cycle() is not None:
            errors.append("graph contains a prerequisite cycle")
        return sorted(set(errors))

    def _has_direct_edge(self, a: str, b: str) -> bool:
        return b in self._children.get(a, [])

    def _find_cycle(self) -> Optional[list[str]]:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {k: WHITE for k in self._kps}

        def dfs(u: str, stack: list[str]) -> Optional[list[str]]:
            color[u] = GRAY
            stack.append(u)
            for v in self._children.get(u, []):
                if color[v] == GRAY:
                    return stack[stack.index(v):] + [v]
                if color[v] == WHITE:
                    found = dfs(v, stack)
                    if found:
                        return found
            stack.pop()
            color[u] = BLACK
            return None

        for k in sorted(self._kps):
            if color[k] == WHITE:
                found = dfs(k, [])
                if found:
                    return found
        return None

    # ----- 查询 -----
    def kps(self) -> list[KnowledgePoint]:
        return [self._kps[k] for k in sorted(self._kps)]

    def get(self, kp_id: str) -> Optional[KnowledgePoint]:
        return self._kps.get(kp_id)

    def has(self, kp_id: str) -> bool:
        return kp_id in self._kps

    def children(self, kp_id: str) -> list[str]:
        return sorted(self._children.get(kp_id, []))

    def prereqs(self, kp_id: str) -> list[str]:
        kp = self._kps.get(kp_id)
        return list(kp.prereqs) if kp else []

    def ancestors(self, kp_id: str) -> set[str]:
        seen: set[str] = set()
        stack = list(self.prereqs(kp_id))
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            stack.extend(self.prereqs(u))
        return seen

    def descendants(self, kp_id: str) -> set[str]:
        seen: set[str] = set()
        stack = list(self.children(kp_id))
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            stack.extend(self.children(u))
        return seen

    def topological_order(self) -> list[str]:
        """返回知识点 id 列表：任何先序都在其后代之前。确定性：同层按 id 排序。"""
        indeg = {k: 0 for k in self._kps}
        for kids in self._children.values():
            for c in kids:
                indeg[c] += 1
        ready = sorted(k for k, d in indeg.items() if d == 0)
        order: list[str] = []
        while ready:
            u = ready.pop(0)
            order.append(u)
            new_ready = []
            for v in sorted(self._children.get(u, [])):
                indeg[v] -= 1
                if indeg[v] == 0:
                    new_ready.append(v)
            ready = sorted(set(ready) | set(new_ready))
        if len(order) != len(self._kps):
            raise KPGraphError("cycle detected in topological_order")
        return order

    def frontier(self, mastery: dict[str, float], threshold: float) -> list[str]:
        """前沿知识点：自身低于阈值、且所有先序都 >= 阈值（当前可学）。按影响降序。"""
        result = []
        for kp in self._kps.values():
            if mastery.get(kp.id, 0.0) >= threshold:
                continue
            if all(mastery.get(p, 0.0) >= threshold for p in kp.prereqs):
                result.append(kp.id)
        impact = {k: len(self.descendants(k)) for k in result}
        return sorted(result, key=lambda k: (-impact[k], k))


def load_kpgraph(path: str) -> KPGraph:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return kpgraph_from_dict(data)


def kpgraph_from_dict(data: dict) -> KPGraph:
    g = KPGraph()
    for kp in data["knowledge_points"]:
        g.add_kp(
            KnowledgePoint(
                id=kp["id"],
                name=kp["name"],
                subject=kp.get("subject", "math"),
                grade=int(kp.get("grade", 7)),
                cluster=kp.get("cluster", ""),
                description=kp.get("description", ""),
                standard_ref=kp.get("standard_ref", ""),
                prereqs=list(kp.get("prereqs", [])),
            )
        )
    for kp in g.kps():
        for p in kp.prereqs:
            g.add_edge(p, kp.id)
    return g
