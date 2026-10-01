"""会话稳定占位符与容错还原（gov2 盲实现，依据 masking-placeholder spec §2/§2.1/§2.2/§2.3）。

冻结算法（§5.3.1 一字不差）::

    digest  = HMAC-SHA256(key=MASK_KEY, msg=f"{session_id}\\x1f{type}\\x1f{normalized}").hexdigest()
    digest8 = digest[:8]；同 session+type 内碰撞则升位（插入时检测）
    placeholder = "〔" + 中文标签 + "·" + digest8 + "〕"

- 会话稳定：同 session 同 (type, normalized) → 恒同占位符；跨 session 因 session_id
  参与摘要必不同；
- 归一化等价：同一实体的不同写法 → 同 normalized → 同占位符（masking/normalize.py）；
- 还原：T8.4 起整段走 restore_tolerant 容错扫描（改形占位符规范化后查表，命中才替换；
  未知形状原样保留）；RESTORE_PATTERN 保留为检测面。
"""
from __future__ import annotations

import hashlib
import hmac
import re
import threading
import unicodedata
from collections import OrderedDict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from masking.models import MappingEntry
from recognizers.models import EntityClass

PLACEHOLDER_OPEN = "〔"
PLACEHOLDER_SEPARATOR = "·"
PLACEHOLDER_CLOSE = "〕"

#: 摘要截断位数：首选 8 位；同 session+type 冲突逐级升位（插入期检测）；12 位仍碰撞抛错
DIGEST_WIDTHS: tuple[int, ...] = (8, 10, 12)

#: 还原形状正则（检测面）：非空标签（不含 〔〕·）+ 8–12 位小写 hex
RESTORE_PATTERN = re.compile(
    re.escape(PLACEHOLDER_OPEN)
    + r"([^" + re.escape(PLACEHOLDER_OPEN) + re.escape(PLACEHOLDER_CLOSE)
    + re.escape(PLACEHOLDER_SEPARATOR) + r"]+)"
    + re.escape(PLACEHOLDER_SEPARATOR)
    + r"([0-9a-f]{8,12})"
    + re.escape(PLACEHOLDER_CLOSE)
)

#: 摘要 msg 内分隔符（ASCII 单元分隔符）
_DIGEST_SEPARATOR = "\x1f"

# ── 容错改形匹配（spec §2.2；真实大模型对占位符 token 的输出随机性改形）────────

#: 括号与间隔号的同形变体（命中映射表才替换，放宽无害）
PLACEHOLDER_OPEN_VARIANTS = "〔【〖［["
PLACEHOLDER_CLOSE_VARIANTS = "〕】〗］]"
PLACEHOLDER_SEP_VARIANTS = "·・•‧⋅﹒．."

#: 改形候选最大扫描窗（字符）：规范形状 ≤32，容忍反引号/空白/换行改形放宽到 48；
#: 流式缓冲上限（remap.MAX_PLACEHOLDER_LEN）与之同源
PLACEHOLDER_TOLERANT_MAX_LEN = 48

#: hex 段转写易混字符兜底（仅作用于 digest 段；规范化后须 8–12 位 hex 且查表命中才替换）
_DIGEST_CONFUSABLE = str.maketrans({"o": "0", "i": "1", "l": "1"})

_OPEN_VARIANTS_RE = re.compile("[" + re.escape(PLACEHOLDER_OPEN_VARIANTS) + "]")
_CLOSE_VARIANTS_RE = re.compile("[" + re.escape(PLACEHOLDER_CLOSE_VARIANTS) + "]")
_SEP_VARIANTS_RE = re.compile("[" + re.escape(PLACEHOLDER_SEP_VARIANTS) + "]")
_MANGLE_NOISE_RE = re.compile(r"[\s`]+")   # 改形噪声：全部空白/换行/反引号
_DIGEST_SHAPE_RE = re.compile(r"[0-9a-f]{8,12}")


def canonical_placeholder(inside: str) -> str | None:
    """候选括号内文本 → 规范占位符键 ``〔标签·hex〕``；不可规范化返回 None。

    规范化三步（顺序固定，spec §2.2）：
    1. 剥除改形噪声（空白/换行/反引号）；剥后为空 → None；
    2. 按间隔号变体切分，必须恰 2 段（多段/单段=不是占位符）；两段均非空；
       标签段不得含任何括号变体；
    3. 摘要段 NFKC 全半角归一 → 小写 → 易混字符兜底（o→0、i/l→1）后必须为
       8–12 位 hex fullmatch。
    标签原样保留（查表键即注册键）。
    """
    compact = _MANGLE_NOISE_RE.sub("", inside)
    if not compact:
        return None
    parts = _SEP_VARIANTS_RE.split(compact)
    if len(parts) != 2:
        return None
    label, digest = parts
    if not label or not digest:
        return None
    if _OPEN_VARIANTS_RE.search(label) or _CLOSE_VARIANTS_RE.search(label):
        return None
    digest = unicodedata.normalize("NFKC", digest).lower().translate(_DIGEST_CONFUSABLE)
    if not _DIGEST_SHAPE_RE.fullmatch(digest):
        return None
    return f"{PLACEHOLDER_OPEN}{label}{PLACEHOLDER_SEPARATOR}{digest}{PLACEHOLDER_CLOSE}"


def restore_tolerant(text: str, lookup: Callable[[str], str | None]) -> str:
    """整段容错还原扫描（spec §2.2 判定链）：改形占位符 → 规范键查表 → 命中替换。

    - 从当前位找下一个开括号变体；其后不再有 → 余下全部普通文本；
    - 开括号后 47 字符窗内找闭括号变体：找到 → 括号内文本经 canonical_placeholder
      规范化 → lookup：命中 → 输出原值；未命中/规范化失败 → 放行开括号字符本身，
      从开括号后一位重扫（输出逐字无损）；
    - 窗内无闭括号 → 放行开括号、后移一位重扫。
    与 StreamRestorer（remap.py）共用同一判定链，fuzz 断言整段与流式严格等价。
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        m = _OPEN_VARIANTS_RE.search(text, i)
        if m is None:
            out.append(text[i:])
            break
        open_at = m.start()
        if open_at > i:
            out.append(text[i:open_at])
        cm = _CLOSE_VARIANTS_RE.search(
            text, open_at + 1, min(n, open_at + PLACEHOLDER_TOLERANT_MAX_LEN - 1))
        if cm is not None:
            key = canonical_placeholder(text[open_at + 1:cm.start()])
            if key is not None:
                value = lookup(key)
                if value is not None:
                    out.append(value)
                    i = cm.end()
                    continue
            # 完整括号对但不可还原 → 放行开括号字符本身，其余重扫
            out.append(text[open_at])
            i = open_at + 1
            continue
        # 窗内无闭合 → 放行开括号，其余重扫
        out.append(text[open_at])
        i = open_at + 1
    return "".join(out)


def tolerant_placeholder_hits(text: str) -> list[str]:
    """泄漏检测面（比 RESTORE_PATTERN 宽）：全部可规范化为占位符形状的候选规范键。

    按出现序、不去重；不管是否仍在会话映射表内——改形残留只要形状可辨即算泄漏。
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        m = _OPEN_VARIANTS_RE.search(text, i)
        if m is None:
            break
        open_at = m.start()
        cm = _CLOSE_VARIANTS_RE.search(
            text, open_at + 1, min(n, open_at + PLACEHOLDER_TOLERANT_MAX_LEN - 1))
        if cm is not None:
            key = canonical_placeholder(text[open_at + 1:cm.start()])
            if key is not None:
                out.append(key)
                i = cm.end()
                continue
        i = open_at + 1
    return out


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SessionMapper:
    """单个会话的占位符 ↔ 原值映射（内存态）。

    on_insert：新条目首次插入后的回调（会话存储借此即时落盘；复用命中与
    hydrate 恢复不触发）。
    """

    def __init__(self, session_id: str, key: bytes,
                 *, on_insert: Callable[[MappingEntry], None] | None = None) -> None:
        self.session_id = session_id
        self._key = key
        self._on_insert = on_insert
        self._by_placeholder: dict[str, MappingEntry] = {}
        self._by_value: dict[tuple[str, str], str] = {}   # (type值, normalized) → placeholder

    def _digest(self, type_value: str, normalized: str) -> str:
        """摘要计算唯一入口（白盒覆写点：冻结 eval 以子类覆写复现碰撞升位路径）。"""
        msg = f"{self.session_id}{_DIGEST_SEPARATOR}{type_value}{_DIGEST_SEPARATOR}{normalized}"
        return hmac.new(self._key, msg.encode("utf-8"), hashlib.sha256).hexdigest()

    def placeholder_for(self, entity_type: EntityClass,
                        normalized: str) -> tuple[str, MappingEntry]:
        """该 (类别, 归一化值) 的占位符；首次插入，重复命中复用（first_seen 不变）。"""
        value_key = (entity_type.value, normalized)
        existing_ph = self._by_value.get(value_key)
        if existing_ph is not None:
            return existing_ph, self._by_placeholder[existing_ph]
        digest = self._digest(entity_type.value, normalized)
        for width in DIGEST_WIDTHS:
            placeholder = (
                f"{PLACEHOLDER_OPEN}{entity_type.label}{PLACEHOLDER_SEPARATOR}"
                f"{digest[:width]}{PLACEHOLDER_CLOSE}"
            )
            holder = self._by_placeholder.get(placeholder)
            if holder is None:
                entry = MappingEntry(
                    placeholder=placeholder, type=entity_type, normalized=normalized,
                    first_seen=_utc_now(), session_id=self.session_id,
                )
                self._by_placeholder[placeholder] = entry
                self._by_value[value_key] = placeholder
                if self._on_insert is not None:
                    self._on_insert(entry)
                return placeholder, entry
            if holder.normalized == normalized and holder.type is entity_type:
                # 极端序列：低宽度位先被异值占住、本值曾升位插入后同值再次到达
                # （经非快路径）→ 直接复用既有条目，不新插、不抛错
                self._by_value[value_key] = placeholder
                return placeholder, holder
            # 不同值占用了同宽度占位符 → 升位重试（插入期碰撞检测）
        raise RuntimeError(
            f"placeholder digest collision unresolved for session={self.session_id}")

    def mask(self, text: str,
             spans: Iterable[tuple[int, int, EntityClass, str]]) -> tuple[str, list[MappingEntry]]:
        """把 (start, end, 类别, normalized) 列表替换为占位符；条目按正文升序返回。"""
        entries: list[MappingEntry] = []
        masked = text
        for start, end, entity_type, normalized in sorted(spans, key=lambda s: s[0], reverse=True):
            placeholder, entry = self.placeholder_for(entity_type, normalized)
            masked = masked[:start] + placeholder + masked[end:]
            entries.append(entry)
        entries.reverse()
        return masked, entries

    def restore(self, text: str) -> str:
        """占位符 → 原值（normalized）；映射表外的占位符形状原样保留。

        容错扫描（§2.2）：改形占位符规范化后查表，命中才替换；非流式与流式
        （StreamRestorer）同一判定链。
        """
        return restore_tolerant(text, self.lookup)

    def lookup(self, placeholder: str) -> str | None:
        """单条占位符 → 原值；映射表外返回 None（流式状态机与容错还原的查找入口）。"""
        entry = self._by_placeholder.get(placeholder)
        return entry.normalized if entry is not None else None

    def hydrate(self, entries: Iterable[MappingEntry]) -> int:
        """从落盘行恢复映射；返回实际恢复条数。

        已在内存的占位符不覆盖（内存态为准）；恢复行不触发 on_insert。
        """
        restored = 0
        for entry in entries:
            if entry.placeholder in self._by_placeholder:
                continue
            value_key = (entry.type.value, entry.normalized)
            self._by_placeholder[entry.placeholder] = entry
            self._by_value.setdefault(value_key, entry.placeholder)
            restored += 1
        return restored

    def purge_expired(self, cutoff: datetime) -> int:
        """删除内存中 first_seen < cutoff 的条目（与落盘 TTL 同口径）；返回删除数。"""
        doomed = [ph for ph, entry in self._by_placeholder.items() if entry.first_seen < cutoff]
        for ph in doomed:
            entry = self._by_placeholder.pop(ph)
            key = (entry.type.value, entry.normalized)
            if self._by_value.get(key) == ph:
                del self._by_value[key]
        return len(doomed)

    def entries(self) -> list[MappingEntry]:
        return list(self._by_placeholder.values())


class SessionRegistry:
    """会话 → SessionMapper 的进程内 LRU 注册表（容量防失控）。

    mapper_factory：LRU 未命中时的构造工厂（会话存储借此从库恢复映射行）；
    缺省纯内存构造。
    """

    def __init__(self, key: bytes, capacity: int = 1024,
                 *, mapper_factory: Callable[[str], SessionMapper] | None = None) -> None:
        if not key:
            raise ValueError("masking key must be non-empty")
        self._key = key
        self._capacity = max(1, capacity)
        self._mapper_factory = mapper_factory
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, SessionMapper] = OrderedDict()

    def get(self, session_id: str) -> SessionMapper:
        with self._lock:
            mapper = self._sessions.get(session_id)
            if mapper is None:
                mapper = (self._mapper_factory(session_id) if self._mapper_factory
                          else SessionMapper(session_id, self._key))
                self._sessions[session_id] = mapper
            self._sessions.move_to_end(session_id)
            while len(self._sessions) > self._capacity:
                self._sessions.popitem(last=False)
            return mapper

    def evict_where(self, predicate: Callable[[SessionMapper], bool]) -> int:
        """按条件换出会话；返回换出数。"""
        with self._lock:
            doomed = [sid for sid, mapper in self._sessions.items() if predicate(mapper)]
            for sid in doomed:
                del self._sessions[sid]
            return len(doomed)

    def apply(self, fn: Callable[[SessionMapper], None]) -> None:
        """对全部在册会话映射器就地应用 fn。"""
        with self._lock:
            for mapper in self._sessions.values():
                fn(mapper)
