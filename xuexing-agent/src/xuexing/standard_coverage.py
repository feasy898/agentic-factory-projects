"""standard_coverage —— 课标覆盖检查器（knowledge 的 standard_ref × 课标主题清单）。

行为契约（specs/drafts/standard_coverage.spec.md，本文件为参考实现）：
- 课标主题清单（领域 -> 主题 -> 条目，含 aliases 检索关键词）由 parse_topics 解析校验；
- 匹配规则：条目任一 alias 是 KP.standard_ref 的连续子串即归属该条目（纯子串匹配）；
- 对照产出双向缺口：清单中没有 KP 引用的条目（覆盖缺口）+ standard_ref 归属不到任何
  条目的 KP（归属缺口），外加逐 KP 归属表与覆盖率。
- 纯函数：无 IO、无随机、无时钟；所有输出列表化/tuple 化且顺序确定
  （条目按清单原序，KP 按输入原序），同输入同输出。

注入装载约束（同 recommend 规格 §2）：不用 from __future__ import annotations——
dataclass 字符串注解在 _regen_standard_coverage 顶层模块名下会触发未受保护的
sys.modules 解析；注解直接写真实对象。
"""
from dataclasses import dataclass

__all__ = [
    "StandardCoverageError",
    "Topic",
    "KPMatch",
    "CoverageReport",
    "parse_topics",
    "match_ref",
    "check_coverage",
    "check_coverage_dicts",
]


class StandardCoverageError(ValueError):
    """standard_coverage 模块所有校验失败的异常类型。"""


@dataclass
class Topic:
    """课标主题清单条目。aliases 是归属匹配用检索关键词（非空，元组）。"""

    id: str
    name: str
    domain: str
    theme: str
    requirement: str
    aliases: tuple


@dataclass
class KPMatch:
    """一个知识点的归属结果。topic_ids 为清单原序、去重后的条目 id 元组。"""

    kp_id: str
    topic_ids: tuple


@dataclass
class CoverageReport:
    """覆盖对照报告。

    - matches：每个输入 KP 恰一项，按输入原序；
    - uncovered_topic_ids：无任何 KP 引用的条目（覆盖缺口），清单原序；
    - unmatched_kp_ids：standard_ref 归属不到任何条目的 KP（归属缺口），输入原序；
    - matched_kp_ids / covered_topic_ids：对应的已归属侧（同序规则）。
    """

    topics: tuple
    matches: tuple
    uncovered_topic_ids: tuple
    unmatched_kp_ids: tuple
    matched_kp_ids: tuple
    covered_topic_ids: tuple

    @property
    def coverage_rate(self):
        """已覆盖条目数 / 清单条目总数（清单非空由构造校验保证）。"""
        return len(self.covered_topic_ids) / len(self.topics)

    def is_complete(self):
        """全归属且全覆盖（双向均无缺口）时为 True。"""
        return not self.uncovered_topic_ids and not self.unmatched_kp_ids


# ---------- 解析与校验 ----------

def _require_text(value, what):
    """非空白字符串校验，返回原值；否则抛 StandardCoverageError。"""
    if not isinstance(value, str) or not value.strip():
        raise StandardCoverageError(f"{what} must be a non-empty string, got {value!r}")
    return value


def _parse_topic(raw, domain, theme, seen_ids, seen_aliases):
    if not isinstance(raw, dict):
        raise StandardCoverageError(f"topic must be a dict, got {raw!r}")
    tid = _require_text(raw.get("id"), "topic id")
    if tid in seen_ids:
        raise StandardCoverageError(f"duplicate topic id: {tid}")
    seen_ids.add(tid)
    name = _require_text(raw.get("name"), f"topic {tid} name")
    _require_text(raw.get("requirement"), f"topic {tid} requirement")
    aliases = raw.get("aliases")
    if not isinstance(aliases, list) or not aliases:
        raise StandardCoverageError(f"topic {tid} aliases must be a non-empty list")
    cleaned = []
    for alias in aliases:
        if not isinstance(alias, str) or not alias.strip():
            raise StandardCoverageError(f"topic {tid} alias must be a non-empty string, got {alias!r}")
        if alias != alias.strip():
            raise StandardCoverageError(f"topic {tid} alias has surrounding whitespace: {alias!r}")
        if alias in seen_aliases:
            raise StandardCoverageError(f"duplicate alias across topics: {alias!r}")
        seen_aliases.add(alias)
        cleaned.append(alias)
    return Topic(id=tid, name=name, domain=domain, theme=theme,
                 requirement=raw["requirement"], aliases=tuple(cleaned))


def parse_topics(data):
    """解析课标主题清单 dict（domains -> themes -> topics），返回 Topic 列表（清单原序）。

    校验（失败抛 StandardCoverageError）：结构逐层存在且非空；topic id/name/requirement
    非空字符串；aliases 非空列表且每个 alias 为无首尾空白的非空字符串；topic id 全局唯一、
    alias 全局唯一。解析不改输入。
    """
    if not isinstance(data, dict):
        raise StandardCoverageError(f"curriculum data must be a dict, got {data!r}")
    domains = data.get("domains")
    if not isinstance(domains, list) or not domains:
        raise StandardCoverageError("curriculum data must contain a non-empty 'domains' list")
    topics = []
    seen_ids = set()
    seen_aliases = set()
    for domain in domains:
        if not isinstance(domain, dict):
            raise StandardCoverageError(f"domain must be a dict, got {domain!r}")
        domain_name = _require_text(domain.get("domain"), "domain name")
        themes = domain.get("themes")
        if not isinstance(themes, list) or not themes:
            raise StandardCoverageError(f"domain {domain_name!r} must contain a non-empty 'themes' list")
        for theme in themes:
            if not isinstance(theme, dict):
                raise StandardCoverageError(f"theme must be a dict, got {theme!r}")
            theme_name = _require_text(theme.get("theme"), f"theme name in domain {domain_name!r}")
            raw_topics = theme.get("topics")
            if not isinstance(raw_topics, list) or not raw_topics:
                raise StandardCoverageError(
                    f"theme {theme_name!r} in domain {domain_name!r} must contain a non-empty 'topics' list")
            for raw in raw_topics:
                topics.append(_parse_topic(raw, domain_name, theme_name, seen_ids, seen_aliases))
    return topics


# ---------- 匹配 ----------

def match_ref(ref, topics):
    """单个 standard_ref 的归属：返回命中条目 id 元组（清单原序、去重）。

    ref 为 None 或全空白 -> ()；非字符串 -> StandardCoverageError；topics 为空 -> 
    StandardCoverageError（清单不能为空）。匹配 = 任一 alias 是 ref 的连续子串。
    """
    if not topics:
        raise StandardCoverageError("topics must be non-empty")
    if ref is None:
        return ()
    if not isinstance(ref, str):
        raise StandardCoverageError(f"standard_ref must be a string or None, got {ref!r}")
    if not ref.strip():
        return ()
    return tuple(t.id for t in topics if any(a in ref for a in t.aliases))


# ---------- 对照报告 ----------

def check_coverage(kps, topics):
    """KP 对象序列 × 条目清单 -> CoverageReport。

    每个 KP 需有 .id 与 .standard_ref（str）属性（xuexing.types.KnowledgePoint 即满足；
    缺属性由原生 AttributeError 传播，属性非 str 抛 StandardCoverageError）；
    standard_ref 为 None 视为空。kp id 重复、清单为空均抛 StandardCoverageError。
    输出顺序：matches 按 kps 输入原序，条目类输出按清单原序。不改入参。
    """
    if not topics:
        raise StandardCoverageError("topics must be non-empty")
    kp_list = list(kps)
    matches = []
    matched = set()
    covered = set()
    seen_kp = set()
    for kp in kp_list:
        kp_id = kp.id
        if not isinstance(kp_id, str) or not kp_id.strip():
            raise StandardCoverageError(f"kp id must be a non-empty string, got {kp_id!r}")
        if kp_id in seen_kp:
            raise StandardCoverageError(f"duplicate kp id: {kp_id}")
        seen_kp.add(kp_id)
        ref = kp.standard_ref
        if ref is None:
            ref = ""
        if not isinstance(ref, str):
            raise StandardCoverageError(
                f"kp {kp_id} standard_ref must be a string or None, got {ref!r}")
        hit_ids = tuple(t.id for t in topics if any(a in ref for a in t.aliases))
        matched.update(hit_ids)
        covered.update(hit_ids)
        matches.append(KPMatch(kp_id=kp_id, topic_ids=hit_ids))
    topic_ids = tuple(t.id for t in topics)
    covered_ids = tuple(tid for tid in topic_ids if tid in covered)
    return CoverageReport(
        topics=tuple(topics),
        matches=tuple(matches),
        uncovered_topic_ids=tuple(tid for tid in topic_ids if tid not in covered),
        unmatched_kp_ids=tuple(m.kp_id for m in matches if not m.topic_ids),
        matched_kp_ids=tuple(m.kp_id for m in matches if m.topic_ids),
        covered_topic_ids=covered_ids,
    )


@dataclass
class _KPLike:
    """knowledge json 的 knowledge_points dict 的轻量适配（内部用）。"""

    id: str
    standard_ref: str


def check_coverage_dicts(kp_dicts, topics_data):
    """knowledge json 形状（dict 列表）的便捷入口。

    每个 KP dict 必须含非空字符串 "id"；"standard_ref" 可省略或为 str/None（缺省视为
    空）。topics_data 为 parse_topics 接受的清单 dict。其余语义同 check_coverage。
    """
    topics = parse_topics(topics_data)
    if not isinstance(kp_dicts, (list, tuple)):
        raise StandardCoverageError(f"kp_dicts must be a list, got {kp_dicts!r}")
    kps = []
    for raw in kp_dicts:
        if not isinstance(raw, dict):
            raise StandardCoverageError(f"kp entry must be a dict, got {raw!r}")
        kp_id = raw.get("id")
        if not isinstance(kp_id, str) or not kp_id.strip():
            raise StandardCoverageError(f"kp id must be a non-empty string, got {kp_id!r}")
        kps.append(_KPLike(id=kp_id, standard_ref=raw.get("standard_ref")))
    return check_coverage(kps, topics)
