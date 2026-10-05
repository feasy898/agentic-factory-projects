"""M3 可逆脱敏核心：会话稳定占位符（masking-placeholder spec §2，冻结算法）。

重生成实现，依据 specs/masking-placeholder.md，未读原实现源码。冻结点：

```
digest  = HMAC-SHA256(key=MASK_KEY, msg=f"{session_id}\x1f{type}\x1f{normalized}").hexdigest()
digest8 = digest[:8]；同 session+type 内碰撞则升位（插入时检测）
placeholder = "〔" + 中文标签 + "·" + digest8 + "〕"      # 例：〔人名·7f3a2b1c〕
```

- 分隔符 ``\\x1f``（ASCII 单元分隔符）；key/msg 均 UTF-8；
- 升位序列 ``DIGEST_WIDTHS = (8, 10, 12)`` 逐级重试，12 位仍碰撞抛 RuntimeError；
- 三条设计语义（冻结）：会话稳定（同 session 同 (type, normalized) 恒同占位符，
  ``first_seen`` 不变）；跨 session 必不同（session_id 参与摘要）；归一化等价
  （上游统一调 ``masking.normalize.normalize_value`` 后传入）；
- 还原形状正则（§2.1 冻结）：``〔 + 不含 〔〕· 的非空标签 + · + [0-9a-f]{8,12} + 〕``；
  ``restore`` 整段替换、映射表外占位符形状原样保留；``lookup`` 单条查找未命中 None；
  ``mask`` span 按 start 降序替换（避免位移），返回条目按正文升序。

会话存储（spec §3–4：SQLite 落盘 + LRU + TTL）不在本 pilot 的 gate 范围
（evals.m3_masking 不覆盖，evals.m7_audit C 节覆盖）；此处保留 ``on_insert``
回调位供写路径承接。
"""
from __future__ import annotations

import hashlib
import hmac
import re
import threading
from datetime import datetime, timezone
from typing import Callable, Iterable

from masking.models import MappingEntry
from masking.normalize import normalize_value
from recognizers.models import EntityClass

# ── 冻结常量（§2）───────────────────────────────────────────────────
OPEN_MARK = "〔"        # U+3014
CLOSE_MARK = "〕"       # U+3015
LABEL_SEP = "·"         # U+00B7
DIGEST_MSG_SEP = "\x1f"  # ASCII 单元分隔符（摘要 msg 内）
DIGEST_WIDTHS = (8, 10, 12)  # 升位序列，逐级重试

# 还原形状正则（§2.1）：〔 + 非空标签（不含 〔〕·）+ · + hex8-12 + 〕
RESTORE_PATTERN = re.compile(
    re.escape(OPEN_MARK) + r"([^" + re.escape(OPEN_MARK + CLOSE_MARK + LABEL_SEP) + r"]+)·"
    + r"([0-9a-f]{8,12})" + re.escape(CLOSE_MARK)
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SessionMapper:
    """单会话映射器：占位符生成（纯 HMAC 确定性）+ 内存映射 + 可逆还原。

    纯 HMAC 派生保证跨实例/重启后同 (session, type, normalized) 仍得同一占位符；
    内存表仅承载“已插入条目”的复用与升位检测。线程安全（内部锁）。
    """

    def __init__(self, session_id: str, key: bytes,
                 on_insert: Callable[[MappingEntry], None] | None = None) -> None:
        self.session_id = session_id
        self._key = key
        self._on_insert = on_insert
        self._lock = threading.RLock()
        self._entries: dict[str, MappingEntry] = {}  # placeholder → entry
        self._by_value: dict[tuple[str, str], MappingEntry] = {}  # (type.value, normalized) → entry

    # ── 摘要（§2 冻结；白盒测试以同名签名覆写此方法）────────────────
    def _digest(self, type_value: str, normalized: str) -> str:
        msg = f"{self.session_id}{DIGEST_MSG_SEP}{type_value}{DIGEST_MSG_SEP}{normalized}"
        return hmac.new(self._key, msg.encode("utf-8"), hashlib.sha256).hexdigest()

    # ── 占位符生成（插入期碰撞检测 + 升位 + 同值复用）────────────────
    def placeholder_for(self, etype: EntityClass | str, normalized: str) -> tuple[str, MappingEntry]:
        """返回 (占位符, 条目)；同值重复请求复用既有条目对象（first_seen 不变）。"""
        cls = etype if isinstance(etype, EntityClass) else EntityClass(str(etype))
        type_value = cls.value
        with self._lock:
            existing = self._by_value.get((type_value, normalized))
            if existing is not None:
                return existing.placeholder, existing

            digest = self._digest(type_value, normalized)
            label = cls.label
            for width in DIGEST_WIDTHS:
                placeholder = f"{OPEN_MARK}{label}{LABEL_SEP}{digest[:width]}{CLOSE_MARK}"
                if placeholder not in self._entries:
                    entry = MappingEntry(
                        placeholder=placeholder,
                        type=type_value,
                        normalized=normalized,
                        first_seen=_now_iso(),
                        session_id=self.session_id,
                        preserve_semantic=False,
                    )
                    self._entries[placeholder] = entry
                    self._by_value[(type_value, normalized)] = entry
                    if self._on_insert is not None:
                        self._on_insert(entry)
                    return placeholder, entry
        raise RuntimeError(
            f"placeholder collision unresolved at width {DIGEST_WIDTHS[-1]} "
            f"(session={self.session_id!r}, type={type_value}, value={normalized!r})"
        )

    # ── 查找 / 还原 / 脱敏（§2.1 冻结语义）──────────────────────────
    def lookup(self, placeholder: str) -> str | None:
        """单条查找，未命中返回 None（流式状态机的查找入口）。"""
        with self._lock:
            entry = self._entries.get(placeholder)
        return None if entry is None else entry.normalized

    def lookup_entry(self, placeholder: str) -> MappingEntry | None:
        with self._lock:
            return self._entries.get(placeholder)

    def restore(self, text: str) -> str:
        """整段正则替换；映射表外的占位符形状原样保留（不吞不放行语义）。"""

        def _sub(match: re.Match[str]) -> str:
            entry = self._entries.get(match.group(0))
            return match.group(0) if entry is None else entry.normalized

        return RESTORE_PATTERN.sub(_sub, text)

    def mask(self, text: str,
             spans: Iterable[tuple[int, int, EntityClass | str, str]]) -> tuple[str, list[MappingEntry]]:
        """span=(start, end, 类别, 原值)：按 start 降序替换避免位移；条目按正文升序返回。"""
        out = text
        collected: list[MappingEntry] = []
        for start, end, etype, value in sorted(spans, key=lambda s: s[0], reverse=True):
            placeholder, entry = self.placeholder_for(etype, normalize_value(etype, value))
            out = out[:start] + placeholder + out[end:]
            collected.append(entry)
        collected.reverse()
        return out, collected

    # ── 只读视图 ────────────────────────────────────────────────────
    def entries(self) -> list[MappingEntry]:
        with self._lock:
            return list(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)


__all__ = [
    "CLOSE_MARK",
    "DIGEST_MSG_SEP",
    "DIGEST_WIDTHS",
    "LABEL_SEP",
    "OPEN_MARK",
    "RESTORE_PATTERN",
    "SessionMapper",
]
