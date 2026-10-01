"""虚拟时钟：测试/eval 的确定性仿真时钟（ns）。

MockArm / SafetyEnvelope 的 ``clock`` 参数接受任何提供 ``now_ns()`` 的
对象；生产缺省为墙钟（``time.perf_counter_ns``），测试注入本时钟以
精确推进仿真时间（急停时延、看门狗超时等判定不依赖真实睡眠）。
"""

from __future__ import annotations

__all__ = ["VirtualClock"]


class VirtualClock:
    """手动推进的单调虚拟时钟（起步 0 ns，只进不退）。"""

    def __init__(self, start_ns: int = 0) -> None:
        self._now_ns = int(start_ns)

    def now_ns(self) -> int:
        return self._now_ns

    def advance_s(self, dt_s: float) -> int:
        """推进 dt_s 秒，返回推进后的 now_ns（负增量被忽略）。"""
        if dt_s > 0.0:
            self._now_ns += int(round(dt_s * 1e9))
        return self._now_ns

    def advance_ns(self, dt_ns: int) -> int:
        """推进 dt_ns 纳秒，返回推进后的 now_ns（负增量被忽略）。"""
        if dt_ns > 0:
            self._now_ns += int(dt_ns)
        return self._now_ns

    @property
    def s(self) -> float:
        """当前时刻（秒，浮点）。"""
        return self._now_ns / 1e9
