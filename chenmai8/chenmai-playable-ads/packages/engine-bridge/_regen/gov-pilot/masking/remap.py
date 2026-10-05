"""M3 流式还原状态机（masking-placeholder spec §5，一字不差）。

问题：上游把回答切成 SSE 增量块，占位符可能被切进相邻两个 chunk，
逐块整段正则替换必然漏配。``StreamRestorer``（单响应实例，不可跨响应复用；
唯一状态是有一界缓冲 ``_pending``）：

1. 扫描到 ``〔`` 即开始缓冲（候选态），不再放行任何字符；
2. 候选凑成完整形状 ``〔<标签>·<hex8-12>〕``（总长 ≤ ``MAX_PLACEHOLDER_LEN = 32``）
   → 查映射：命中替换为原值发出；未命中**原样发出**（未知形状不放行也不吞掉）；
3. 候选 ``〕`` 到达但形状不完整，或缓冲**超过 32 字符**仍无 ``〕`` → 判定普通文本：
   放行候选首字符 ``〔``，其余重新扫描（内部再遇 ``〔`` 自然开启新候选）；
4. ``flush()``：流结束，残留候选按普通文本放行。

不变式：任意 1..N 字符切块方式下，``feed()*k + flush()`` 的拼接输出恒等于整段
``SessionMapper.restore`` 的结果（evals.m3_masking 以 1–7 字符随机切块 fuzz
500 条钉死，thresholds ``MASK_STREAM_FUZZ_CASES=500``）。

spec 缺口备注：spec 只写明「凑成完整形状」与「超 32 字符仍无 〕」两个出口，未写
``〕`` 先到但形状不完整（如 ``〔a·b·12345678〕``）时如何处置。若让候选继续吞字，
其后紧邻的真占位符会被一并吞进候选、flush 时原样放出，破坏上述不变式；
故本实现把「形状不完整的 〕」与超限同归出口 3（放行首字符 + 重扫描），
使不变式对任意输入成立。
"""
from __future__ import annotations

import re
from typing import Callable

OPEN_MARK = "〔"    # U+3014
CLOSE_MARK = "〕"   # U+3015
LABEL_SEP = "·"     # U+00B7

MAX_PLACEHOLDER_LEN = 32  # 候选总长上界（冻结）

# 完整候选形状（§2.1 同源）：〔 + 非空标签（不含 〔〕·）+ · + hex8-12 + 〕
_SHAPE_RE = re.compile(
    re.escape(OPEN_MARK) + r"([^" + re.escape(OPEN_MARK + CLOSE_MARK + LABEL_SEP) + r"]+)·"
    + r"([0-9a-f]{8,12})" + re.escape(CLOSE_MARK)
)


class StreamRestorer:
    """SSE 文本增量在线还原器：lookup 未命中/未知形状原样保留，命中替换为原值。"""

    def __init__(self, lookup: Callable[[str], str | None]) -> None:
        self._lookup = lookup
        self._pending = ""  # 有界候选缓冲（空串 = 普通放行态）

    @property
    def pending_len(self) -> int:
        """当前候选缓冲长度（恒 ≤ MAX_PLACEHOLDER_LEN）。"""
        return len(self._pending)

    def feed(self, chunk: str) -> str:
        """喂入一个增量块，返回本块可放行的文本（候选消化为原值或原样）。"""
        out: list[str] = []
        text = chunk
        i = 0
        while i < len(text):
            ch = text[i]
            if not self._pending:
                if ch == OPEN_MARK:
                    self._pending = ch  # 候选态开启，不放行
                else:
                    out.append(ch)
                i += 1
                continue

            self._pending += ch
            if ch == CLOSE_MARK and _SHAPE_RE.fullmatch(self._pending):
                # 完整形状：命中替换为原值，未命中原样发出
                hit = self._lookup(self._pending)
                out.append(self._pending if hit is None else hit)
                self._pending = ""
                i += 1
                continue
            if len(self._pending) > MAX_PLACEHOLDER_LEN or (
                ch == CLOSE_MARK  # 〕 先到但形状不完整 → 候选作废
            ):
                # 判定普通文本：放行候选首字符，其余重新扫描
                out.append(self._pending[0])
                text = self._pending[1:] + text[i + 1:]
                self._pending = ""
                i = 0
                continue
            i += 1
        return "".join(out)

    def flush(self) -> str:
        """流结束：残留候选按普通文本放行。"""
        pending, self._pending = self._pending, ""
        return pending


__all__ = ["MAX_PLACEHOLDER_LEN", "StreamRestorer"]
