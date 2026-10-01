"""流式还原状态机（gov2 盲实现，依据 masking-placeholder spec §5）。

问题：上游把回答切成 SSE 增量块，占位符可能被切进相邻两个 chunk，逐块整段
正则替换必然漏配。

状态机（spec 一字不差；单响应实例不可跨响应复用）：
1. 扫描到开括号变体（〔【〖［[ 之一）即开始缓冲（候选态），不再放行任何字符；
2. 候选凑成完整括号对（闭括号变体在开括号后 47 字符窗内）→ 内文经
   masking.mapper.canonical_placeholder 规范化（容错改形）成规范键 → 查映射表：
   命中 → 替换为原值发出；未命中/规范化失败 → 原样放行开括号字符本身，其余重扫
   （未知形状不放行也不吞掉）；
3. 缓冲超过 MAX_PLACEHOLDER_LEN（=48，与 mapper.PLACEHOLDER_TOLERANT_MAX_LEN 同源）
   仍无闭括号 → 判定普通文本：放行候选首字符（开括号），其余重扫；
4. flush()：流结束，残留候选按普通文本原样放行。

不变式：任意 1..N 字符切块方式下，feed()*k + flush() 拼接输出恒等于整段
SessionMapper.restore（restore_tolerant）的结果（冻结 eval 以 1–7 字符随机切块
fuzz 500 条钉死）。
"""
from __future__ import annotations

from collections.abc import Callable

from masking.mapper import (
    _CLOSE_VARIANTS_RE,
    _OPEN_VARIANTS_RE,
    PLACEHOLDER_TOLERANT_MAX_LEN,
    canonical_placeholder,
)

#: 占位符候选缓冲上限（字符）：与 mapper.PLACEHOLDER_TOLERANT_MAX_LEN 同源——
#: 规范形状 ≤32，容忍改形噪声放宽到 48；超窗仍无闭合即判定普通文本放行开括号
MAX_PLACEHOLDER_LEN = PLACEHOLDER_TOLERANT_MAX_LEN

#: 还原查找函数形状：占位符 → 原值；未知形状返回 None（原样放行）
LookupFn = Callable[[str], str | None]


class StreamRestorer:
    """SSE 文本增量流的占位符还原状态机（单响应实例，不可跨响应复用）。

    状态只有一项：_pending——以开括号变体开头、尚未能判定完整/废弃的候选缓冲
    （长度恒 ≤ MAX_PLACEHOLDER_LEN，有界即安全）。
    """

    __slots__ = ("_lookup", "_pending")

    def __init__(self, lookup: LookupFn) -> None:
        if not callable(lookup):
            raise TypeError("lookup must be callable(placeholder) -> str | None")
        self._lookup = lookup
        self._pending = ""

    @property
    def pending_len(self) -> int:
        """当前缓冲长度（观测口；恒 ≤ MAX_PLACEHOLDER_LEN）。"""
        return len(self._pending)

    def feed(self, text: str) -> str:
        """喂入一个上游文本增量，返回本块可安全发出的还原文本（可能为空串）。"""
        if not text:
            return ""
        data = self._pending + text
        self._pending = ""
        out: list[str] = []
        i, n = 0, len(data)
        while i < n:
            m = _OPEN_VARIANTS_RE.search(data, i)
            if m is None:   # 其后不再有开括号变体 → 全部普通文本
                out.append(data[i:])
                break
            open_at = m.start()
            if open_at > i:  # 候选前的普通文本直接放行
                out.append(data[i:open_at])
            cm = _CLOSE_VARIANTS_RE.search(
                data, open_at + 1, min(n, open_at + MAX_PLACEHOLDER_LEN - 1))
            if cm is not None:
                # 完整括号对：规范化（容错改形）→ 查表，命中才替换
                key = canonical_placeholder(data[open_at + 1:cm.start()])
                if key is not None:
                    value = self._lookup(key)
                    if value is not None:
                        out.append(value)
                        i = cm.end()
                        continue
                # 完整括号对但不可还原 → 放行开括号字符本身，其余重扫
                out.append(data[open_at])
                i = open_at + 1
                continue
            if n - open_at < MAX_PLACEHOLDER_LEN - 1:
                # 仍可能是被切块的占位符前缀 → 缓冲等待下一增量（有界）
                self._pending = data[open_at:]
                break
            # 超窗仍无闭合 → 普通文本：放行开括号本身，其余重扫
            out.append(data[open_at])
            i = open_at + 1
        return "".join(out)

    def flush(self) -> str:
        """流结束：残留候选缓冲按普通文本原样放行。"""
        pending, self._pending = self._pending, ""
        return pending

    def reset(self) -> None:
        """丢弃缓冲状态（仅测试/异常恢复用；正常路径以 flush 收尾）。"""
        self._pending = ""
