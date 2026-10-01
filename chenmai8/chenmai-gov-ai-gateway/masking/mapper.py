"""会话稳定占位符与可逆还原（开发指令 §5.3，冻结算法）。

占位符算法（§5.3.1，一字不差）::

    digest  = HMAC-SHA256(key=MASK_KEY, msg=f"{session_id}\\x1f{type}\\x1f{normalized}").hexdigest()
    digest8 = digest[:8]；同 session+type 内碰撞则升 10 位（插入时检测）
    placeholder = "〔" + 中文标签 + "·" + digest8 + "〕"     # 例：〔人名·7f3a2b1c〕

- 会话稳定：同 session 同值 → 恒同占位符；跨 session 因 session_id 参与摘要 → 不同；
- 归一化等价：同一实体的不同写法 → 同 normalized → 同占位符（见 masking/normalize.py）；
- 还原：正则扫描占位符形状，查会话映射替换为原值；未知形状原样保留。

会话存储（内存 LRU + SQLite 落盘 + TTL）见 masking/session_store.py；本模块的
SessionMapper 通过 ``on_insert`` 回调向外暴露新条目、``hydrate`` 支持从落盘行恢复，
自身不感知存储介质。
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

#: 摘要截断位数：首选 8 位；同 session+type 冲突时逐级升位（插入时检测）
DIGEST_WIDTHS: tuple[int, ...] = (8, 10, 12)

#: 占位符形状（还原扫描用）：中文标签非空、摘要 8–12 位小写 hex
RESTORE_PATTERN = re.compile(
    re.escape(PLACEHOLDER_OPEN) + r"([^" + re.escape(PLACEHOLDER_OPEN)
    + re.escape(PLACEHOLDER_CLOSE) + PLACEHOLDER_SEPARATOR + r"]+)"
    + re.escape(PLACEHOLDER_SEPARATOR) + r"([0-9a-f]{8,12})"
    + re.escape(PLACEHOLDER_CLOSE)
)

#: 还原时单条映射查找键（type 归一为字符串值，与摘要 msg 一致）
_DIGEST_SEPARATOR = "\x1f"

# ── 容错改形匹配（T8.4；gate_final b6 一轮 U8 GOVCLOUD 腿实锤增补）─────────
# 真实大模型回复会把占位符 token **改形**（模型输出随机性）：反引号/代码样式
# 包裹、空白与换行插入拆开、hex 大小写与全半角转写、同形括号（〔→【[）与
# 间隔号（·→・•.）替换。改形一旦超出 RESTORE_PATTERN 的匹配面（或形状匹配但
# 查表键不等，如 ``〔人名 ·…〕``），还原即漏配，改形残留直达客户端。
# 容错还原的判定链：候选括号对 → 剥噪声规范化 → 规范键查会话映射表 →
# **命中才替换**。结构〔标签·hex8-12〕本身足够特异，加上映射表命中这道
# 终审闸，普通文本（【注·见附件】、markdown 链接等）不可能被误替。

#: 括号与间隔号的同形变体（模型转写常见面；命中映射表才替换，放宽无害）
PLACEHOLDER_OPEN_VARIANTS = "〔【〖［["
PLACEHOLDER_CLOSE_VARIANTS = "〕】〗］]"
PLACEHOLDER_SEP_VARIANTS = "·・•‧⋅﹒．."

#: 改形候选最大扫描窗（字符）：规范形状 ≤32（标签2-3 + hex8-12），容忍反引号/
#: 空白/换行改形放宽到 48；流式缓冲上限（remap.MAX_PLACEHOLDER_LEN）与之同源
PLACEHOLDER_TOLERANT_MAX_LEN = 48

#: hex 部分转写易混字符兜底（仅 digest 应用；规范化后须是 8-12 位 hex 且
#: 命中映射表才替换——无误替面）。O→0 / I·l→1 是模型转写最常见混淆。
_DIGEST_CONFUSABLE = str.maketrans({"o": "0", "i": "1", "l": "1"})

_OPEN_VARIANTS_RE = re.compile("[" + re.escape(PLACEHOLDER_OPEN_VARIANTS) + "]")
_CLOSE_VARIANTS_RE = re.compile("[" + re.escape(PLACEHOLDER_CLOSE_VARIANTS) + "]")
_SEP_VARIANTS_RE = re.compile("[" + re.escape(PLACEHOLDER_SEP_VARIANTS) + "]")
_MANGLE_NOISE_RE = re.compile(r"[\s`]+")  # 改形噪声：空白/换行/反引号
_DIGEST_SHAPE_RE = re.compile(r"[0-9a-f]{8,12}")


def canonical_placeholder(inside: str) -> str | None:
    """候选括号内文本 → 规范占位符键（``〔标签·hex〕``）；不可规范化返回 ``None``。

    规范化三步（顺序固定）：①剥除改形噪声（空白/换行/反引号）；②按间隔号
    变体切成「标签+摘要」两段（多段/单段=不是占位符）；③摘要经 NFKC 全半角
    归一 + 小写 + 易混字符兜底后须为 8–12 位 hex。标签须不含任何括号变体。
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
    """整段容错还原扫描：改形占位符 → 规范键查表 → 命中替换为原值。

    与 :class:`masking.remap.StreamRestorer` 的流式状态机共用同一判定链
    （canonical_placeholder + lookup），fuzz 断言保证整段与流式严格等价。
    不可还原的候选（查表未命中/形状不足）逐字原样放行——未知形状不放行也
    不吞掉，与既有契约一致。
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        m = _OPEN_VARIANTS_RE.search(text, i)
        if m is None:  # 其后不再有开括号变体 → 全部普通文本
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
            # （内部若再出现开括号自然开启新候选）
            out.append(text[open_at])
            i = open_at + 1
            continue
        # 窗内无闭合 → 放行开括号，其余重扫（含正文里孤立的开括号变体）
        out.append(text[open_at])
        i = open_at + 1
    return "".join(out)


def tolerant_placeholder_hits(text: str) -> list[str]:
    """检测文本中全部「可规范化为占位符形状」的候选（规范键，不去重）。

    泄漏检测面（比 RESTORE_PATTERN 宽）：还原正则不可见的改形残留（静默泄漏）
    也能抓到。真实大模型腿的「占位符零泄漏」断言以此为准——改形残留只要形状
    可辨即算泄漏，无论是否仍在会话映射表内。
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
    """单个会话的占位符 ↔ 原值映射（内存态，形状即 MappingEntry）。

    ``on_insert``：新条目首次插入后的回调（会话存储借此即时落盘；
    复用命中与 hydrate 恢复不触发）。
    """

    def __init__(self, session_id: str, key: bytes,
                 *, on_insert: Callable[[MappingEntry], None] | None = None) -> None:
        self.session_id = session_id
        self._key = key
        self._on_insert = on_insert
        self._by_placeholder: dict[str, MappingEntry] = {}
        self._by_value: dict[tuple[str, str], str] = {}  # (type值, normalized) → placeholder

    def _digest(self, type_value: str, normalized: str) -> str:
        msg = f"{self.session_id}{_DIGEST_SEPARATOR}{type_value}{_DIGEST_SEPARATOR}{normalized}"
        return hmac.new(self._key, msg.encode("utf-8"), hashlib.sha256).hexdigest()

    def placeholder_for(self, entity_type: EntityClass, normalized: str) -> tuple[str, MappingEntry]:
        """返回该 (类别, 归一化值) 的占位符；首次插入，重复命中复用（含 first_seen 不变）。"""
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
                # 极端小概率：低宽度位与异值同串碰撞后，同值再次到达——直接复用既有条目
                self._by_value[value_key] = placeholder
                return placeholder, holder
            # 不同值占用了同宽度占位符 → 升位重试（§5.3.1 插入期碰撞检测）
        raise RuntimeError(
            f"placeholder digest collision unresolved for session={self.session_id}"
        )  # pragma: no cover — 8/10/12 位 hex 碰撞概率可忽略

    def mask(self, text: str, spans: Iterable[tuple[int, int, EntityClass, str]]) -> tuple[str, list[MappingEntry]]:
        """把 (start, end, 类别, normalized) 列表替换为占位符；返回 (脱敏文本, 新增/复用条目)。"""
        entries: list[MappingEntry] = []
        masked = text
        for start, end, entity_type, normalized in sorted(spans, key=lambda s: s[0], reverse=True):
            placeholder, entry = self.placeholder_for(entity_type, normalized)
            masked = masked[:start] + placeholder + masked[end:]
            entries.append(entry)
        entries.reverse()  # 恢复为正文顺序
        return masked, entries

    def restore(self, text: str) -> str:
        """占位符 → 原值（normalized）；映射表外的占位符形状原样保留。

        T8.4 起走 :func:`restore_tolerant` 容错扫描：模型对占位符的改形
        （反引号/空白/换行/全半角/同形括号·间隔号）先规范化再查表，命中才
        替换——非流式响应与流式（StreamRestorer）同一判定链。
        """
        return restore_tolerant(text, self.lookup)

    def lookup(self, placeholder: str) -> str | None:
        """单条占位符 → 原值；映射表外返回 None（流式还原状态机的查找入口）。"""
        entry = self._by_placeholder.get(placeholder)
        return entry.normalized if entry is not None else None

    def hydrate(self, entries: Iterable[MappingEntry]) -> int:
        """从落盘行恢复映射（进程重启/会话被 LRU 换出后）；返回实际恢复条数。

        已在内存中的占位符不覆盖（内存态为准）；恢复行不触发 ``on_insert``。
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
        """删除内存中 ``first_seen < cutoff`` 的条目（与落盘 TTL 同口径）；返回删除数。"""
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

    ``mapper_factory``：LRU 未命中时的构造工厂（会话存储借此在构造时从
    SQLite 恢复该会话的映射行）；缺省为纯内存构造（v0 形态）。
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
        """按条件换出会话（TTL 清理用）；返回换出数。"""
        with self._lock:
            doomed = [sid for sid, mapper in self._sessions.items() if predicate(mapper)]
            for sid in doomed:
                del self._sessions[sid]
            return len(doomed)

    def apply(self, fn: Callable[[SessionMapper], None]) -> None:
        """对全部在册会话映射器就地应用 ``fn``（TTL 条目清理用）。"""
        with self._lock:
            for mapper in self._sessions.values():
                fn(mapper)
