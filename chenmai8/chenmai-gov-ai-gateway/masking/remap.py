"""流式还原状态机（masking/remap，开发指令 §6 M3「流式还原」条目）。

问题：上游把回答切成 SSE 增量块时，占位符 ``〔人名·7f3a2b1c〕`` 可能被切进
相邻两个 chunk，逐块做整段正则替换必然漏配/错配。

状态机（spec 一字不差）：
- 一旦扫描到 ``〔`` 即开始**缓冲**（进入候选态），不再放行任何字符；
- 候选凑成完整形状 ``〔<标签>·<hex8-12>〕``（总长 ≤ :data:`MAX_PLACEHOLDER_LEN`）
  → 查会话映射表，命中则**替换为原值后发出**，未命中原样发出（未知形状不放行也不吞掉）；
- 缓冲**超过** 32 字符仍无 ``〕`` → 判定为普通文本：放行候选首字符 ``〔``，
  其余内容重新扫描（内部若再出现 ``〔`` 自然开启新候选）；
- 流结束（:meth:`StreamRestorer.flush`）：残留候选按普通文本放行。

因此任意 1..N 字符切块方式下，``feed()*k + flush()`` 的拼接输出
恒等于整段 :meth:`SessionMapper.restore` 的结果（evals 里 fuzz 断言）。

用法（gateway/sse.py 组合管线）::

    restorer = StreamRestorer(mapper.lookup)
    for delta_text in upstream_text_deltas:
        emit(restorer.feed(delta_text))
    emit(restorer.flush())
"""
from __future__ import annotations

from collections.abc import Callable

from masking.mapper import PLACEHOLDER_OPEN, RESTORE_PATTERN

#: 占位符缓冲上限（字符）：``〔`` + 标签 + ``·`` + hex(8–12) + ``〕`` ≤ 32；
#: 超过仍无闭合 ``〕`` 即判定普通文本放行（spec：缓冲超 32 字符仍无 〕 判定为普通文本）
MAX_PLACEHOLDER_LEN = 32

#: 还原查找函数形状：占位符 → 原值；未知形状返回 None（原样放行）
LookupFn = Callable[[str], str | None]


class StreamRestorer:
    """SSE 文本增量流的占位符还原状态机（单响应实例，不可跨响应复用）。

    状态只有一项：:attr:`_pending` —— 以 ``〔`` 开头、尚未能判定完整/废弃的
    候选缓冲（长度恒 ≤ :data:`MAX_PLACEHOLDER_LEN`，有界即安全）。
    """

    __slots__ = ("_lookup", "_pending")

    def __init__(self, lookup: LookupFn) -> None:
        if not callable(lookup):
            raise TypeError("lookup must be callable(placeholder) -> str | None")
        self._lookup = lookup
        self._pending = ""

    @property
    def pending_len(self) -> int:
        """当前缓冲长度（观测/测试用；恒 ≤ MAX_PLACEHOLDER_LEN）。"""
        return len(self._pending)

    def feed(self, text: str) -> str:
        """喂入一个上游文本增量，返回**本块可安全发出**的还原文本（可能为空串）。"""
        if not text:
            return ""
        data = self._pending + text
        self._pending = ""
        out: list[str] = []
        i = 0
        n = len(data)
        while i < n:
            open_at = data.find(PLACEHOLDER_OPEN, i)
            if open_at < 0:  # 其后不再有 〔 → 全部普通文本
                out.append(data[i:])
                break
            if open_at > i:  # 候选前的普通文本直接放行
                out.append(data[i:open_at])
            match = RESTORE_PATTERN.match(data, open_at)  # 锚定候选起点整匹
            if match is not None:
                replaced = self._lookup(match.group(0))
                out.append(replaced if replaced is not None else match.group(0))
                i = match.end()
                continue
            candidate = data[open_at:]
            if len(candidate) <= MAX_PLACEHOLDER_LEN:
                # 仍可能是被切块的占位符前缀 → 缓冲等待下一增量（有界，不会滞留正文）
                self._pending = candidate
                break
            # 超 32 字符仍非完整形状 → 普通文本：放行 〔 本身，其余重扫
            out.append(PLACEHOLDER_OPEN)
            i = open_at + 1
        return "".join(out)

    def flush(self) -> str:
        """流结束：把残留候选缓冲按普通文本放行（未凑整的 ``〔…`` 原样发出）。"""
        pending, self._pending = self._pending, ""
        return pending

    def reset(self) -> None:
        """丢弃缓冲状态（仅测试/异常恢复用；正常路径以 flush 收尾）。"""
        self._pending = ""
