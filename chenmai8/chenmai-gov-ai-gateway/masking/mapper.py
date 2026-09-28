"""会话稳定占位符与可逆还原（开发指令 §5.3，冻结算法）。

占位符算法（§5.3.1，一字不差）::

    digest  = HMAC-SHA256(key=MASK_KEY, msg=f"{session_id}\\x1f{type}\\x1f{normalized}").hexdigest()
    digest8 = digest[:8]；同 session+type 内碰撞则升 10 位（插入时检测）
    placeholder = "〔" + 中文标签 + "·" + digest8 + "〕"     # 例：〔人名·7f3a2b1c〕

- 会话稳定：同 session 同值 → 恒同占位符；跨 session 因 session_id 参与摘要 → 不同；
- 归一化等价：同一实体的不同写法 → 同 normalized → 同占位符（见 masking/normalize.py）；
- 还原：正则扫描占位符形状，查会话映射替换为原值；未知形状原样保留。

v0 会话存储为进程内 LRU（SQLite 落盘 + TTL 由会话存储任务补全）。
"""
from __future__ import annotations

import hashlib
import hmac
import re
from collections import OrderedDict
from collections.abc import Iterable
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


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SessionMapper:
    """单个会话的占位符 ↔ 原值映射（内存态，形状即 MappingEntry）。"""

    def __init__(self, session_id: str, key: bytes) -> None:
        self.session_id = session_id
        self._key = key
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
        """占位符 → 原值（normalized）；映射表外的占位符形状原样保留。"""

        def _sub(match: re.Match[str]) -> str:
            entry = self._by_placeholder.get(match.group(0))
            return entry.normalized if entry is not None else match.group(0)

        return RESTORE_PATTERN.sub(_sub, text)

    def entries(self) -> list[MappingEntry]:
        return list(self._by_placeholder.values())


class SessionRegistry:
    """会话 → SessionMapper 的进程内 LRU 注册表（容量防失控，v0 不落盘）。"""

    def __init__(self, key: bytes, capacity: int = 1024) -> None:
        if not key:
            raise ValueError("masking key must be non-empty")
        self._key = key
        self._capacity = max(1, capacity)
        self._sessions: OrderedDict[str, SessionMapper] = OrderedDict()

    def get(self, session_id: str) -> SessionMapper:
        mapper = self._sessions.get(session_id)
        if mapper is None:
            mapper = SessionMapper(session_id, self._key)
            self._sessions[session_id] = mapper
        self._sessions.move_to_end(session_id)
        while len(self._sessions) > self._capacity:
            self._sessions.popitem(last=False)
        return mapper
