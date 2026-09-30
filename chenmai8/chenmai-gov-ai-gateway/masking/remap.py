"""流式还原状态机（masking/remap，开发指令 §6 M3「流式还原」条目）。

问题：上游把回答切成 SSE 增量块时，占位符 ``〔人名·7f3a2b1c〕`` 可能被切进
相邻两个 chunk，逐块做整段正则替换必然漏配/错配。

状态机（spec 一字不差，T8.4 增补容错改形面）：
- 一旦扫描到开括号变体（〔【〖［[，T8.4：模型会转写同形括号）即开始**缓冲**
  （进入候选态），不再放行任何字符；
- 候选凑成完整括号对 → 内文经 :func:`masking.mapper.canonical_placeholder`
  **规范化**（T8.4 容错改形：剥除反引号/空白/换行、全半角与大小写归一、
  同形括号·间隔号归一）成规范键 ``〔<标签>·<hex8-12>〕`` → 查会话映射表，
  命中则**替换为原值后发出**，未命中原样放行（未知形状不放行也不吞掉）；
- 窗内（:data:`MAX_PLACEHOLDER_LEN`，T8.4 起 32→48 以容纳改形噪声字符）仍无
  闭合括号 → 判定为普通文本：放行候选首字符（开括号），其余内容重新扫描
  （内部若再出现开括号自然开启新候选）；
- 流结束（:meth:`StreamRestorer.flush`）：残留候选按普通文本放行。

因此任意 1..N 字符切块方式下，``feed()*k + flush()`` 的拼接输出
恒等于整段 :meth:`SessionMapper.restore` 的结果（evals 里 fuzz 断言；
T8.4 起两侧共用 canonical_placeholder 同一判定链）。

用法（gateway/sse.py 组合管线）::

    restorer = StreamRestorer(mapper.lookup)
    for delta_text in upstream_text_deltas:
        emit(restorer.feed(delta_text))
    emit(restorer.flush())
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
#: 规范形状 ≤32，容忍模型改形（反引号/空白/换行噪声）放宽到 48；超过仍无闭合
#: 括号即判定普通文本放行（spec「缓冲超 32 仍无 〕 放行」的 T8.4 容错增补口径）
MAX_PLACEHOLDER_LEN = PLACEHOLDER_TOLERANT_MAX_LEN

#: 还原查找函数形状：占位符 → 原值；未知形状返回 None（原样放行）
LookupFn = Callable[[str], str | None]


class StreamRestorer:
    """SSE 文本增量流的占位符还原状态机（单响应实例，不可跨响应复用）。

    状态只有一项：:attr:`_pending` —— 以开括号变体开头、尚未能判定完整/废弃的
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
            m = _OPEN_VARIANTS_RE.search(data, i)
            if m is None:  # 其后不再有开括号变体 → 全部普通文本
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
                    replaced = self._lookup(key)
                    if replaced is not None:
                        out.append(replaced)
                        i = cm.end()
                        continue
                # 完整括号对但不可还原 → 放行开括号字符本身，其余重扫
                # （内部若再出现开括号自然开启新候选）
                out.append(data[open_at])
                i = open_at + 1
                continue
            if n - open_at < MAX_PLACEHOLDER_LEN - 1:
                # 仍可能是被切块的占位符前缀 → 缓冲等待下一增量（有界，不会滞留正文）
                self._pending = data[open_at:]
                break
            # 超窗仍无闭合 → 普通文本：放行开括号本身，其余重扫
            out.append(data[open_at])
            i = open_at + 1
        return "".join(out)

    def flush(self) -> str:
        """流结束：把残留候选缓冲按普通文本放行（未凑整的 ``〔…`` 原样发出）。"""
        pending, self._pending = self._pending, ""
        return pending

    def reset(self) -> None:
        """丢弃缓冲状态（仅测试/异常恢复用；正常路径以 flush 收尾）。"""
        self._pending = ""
