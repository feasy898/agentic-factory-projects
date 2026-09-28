"""工具调用参数的缓冲还原（开发指令 §6 M3「工具调用」条目；§4 masking 包职责「工具还原」）。

spec（一字不差）：
- 流式下 ``tool_call.arguments`` **增量累积，finish 前不发**（spec 明示此行为变化：
  客户端在 finish 前收不到任何 tool_calls 增量）；
- finish 时**整体还原**后作为**单个 delta** 发出；
- 非流式直接整体还原（:func:`restore_arguments`）。

与流式文本还原（masking/remap.py）的分工——remap 状态机经验的正反两面：

- 文本流必须**在线放行**（客户端逐字看回答），占位符被上游切进两个 chunk 时靠
  状态机缓冲候选（``〔`` 起、≤32 字符、凑整替换/超限放行）；
- 参数流允许**整段 hold 到 finish**，于是按序拼接出的完整 arguments 与上游拼接
  视角逐字相等，finish 时整段 restore 与"逐块还原"严格等价——而逐块还原在占位
  符被切进两个 arguments 增量时必然漏配/错配，正是 remap 状态机的出发点。故本
  模块把 remap 的工程经验照搬：按 index 分槽累积、finish 收尾幂等、缓冲有界
  （:data:`MAX_ARGUMENTS_CHARS` 安全阀，超限响亮失败而非静默截断）、单响应实例
  不可跨响应复用。

用法（gateway/sse.py 组合管线）::

    tools = ToolCallBuffer()
    for delta_tool_calls in upstream_tool_deltas:
        tools.feed(delta_tool_calls)          # 全部吞下，不产生输出
    for call in tools.finalize(mapper):       # finish 时：整体还原，单个 delta
        emit(format_sse(...delta.tool_calls=[call]...))
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from common.logs import get_logger

if TYPE_CHECKING:
    from masking.mapper import SessionMapper

log = get_logger(__name__)

#: 单个工具调用槽位的 arguments 缓冲上限（字符）。
#: spec 的 hold-to-finish 意味着这是流式路径上唯一无上界增长的显式缓冲点，故设
#: 安全阀：上限取远超真实工具参数量级（网关请求体上限 10MB 的约 1/3 字符量）。
#: 语义为**绊线**：追加后检查，超限抛 :class:`ToolArgumentsOverflowError`，缓冲
#: 状态原样保留（含触发块）供上层诊断——绝不静默截断参数制造还原缺口；网关管线
#: 不捕获该异常，响应流响亮中断。
MAX_ARGUMENTS_CHARS = 1_000_000

RestoreFn = Callable[[str], str]


class ToolArgumentsOverflowError(RuntimeError):
    """单个工具调用的 arguments 缓冲超过安全阀（MAX_ARGUMENTS_CHARS）。"""


def _parses_as_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def restore_arguments(mapper: SessionMapper, arguments: str) -> str:
    """非流式直接整体还原（§6 M3）：arguments 串内占位符 → 原值（normalized）。

    还原是纯串级替换：占位符形状 ``〔标签·hex〕`` 不含 ``"``/``\\`` 等任何 JSON
    结构字符，替换只发生在字符串字面量内部，不会破坏合法 JSON。万一原值本身
    含结构字符导致还原后不再可解析（极端脏数据），保留还原结果（占位符→原值
    是正确语义）并记结构化告警——可观测、不吞错、不回退成占位符版。
    """
    restored = mapper.restore(arguments)
    if restored != arguments and _parses_as_json(arguments) and not _parses_as_json(restored):
        log.warning("toolbuf.restore_broke_json", extra={"chars": len(arguments)})
    return restored


class ToolCallBuffer:
    """流式 tool_calls 增量缓冲：arguments 按 index 累积，finish 前不发出。

    - 同一调用的 ``id``/``function.name`` 可能只在首个增量出现（也可能重复），
      按槽位保留首见非空值；其余 delta 字段（如 OpenAI 兼容扩展字段）原样保留；
    - 无 ``index`` 的增量按 index=0 归槽（单工具调用上游常省略）；
    - :meth:`feed` 只吞不吐（hold-to-finish）；:meth:`finalize` 在 finish 时
      整体还原，每个工具一个完整 delta（``tool_calls`` 数组元素形状）；
    - finalize 后缓冲清空；实例不可跨响应复用（与 StreamRestorer 同纪律）。
    """

    __slots__ = ("_calls", "held_events", "_max_arguments_chars")

    def __init__(self, *, max_arguments_chars: int = MAX_ARGUMENTS_CHARS) -> None:
        if max_arguments_chars < 1:
            raise ValueError("max_arguments_chars must be >= 1")
        self._max_arguments_chars = max_arguments_chars
        # index → {"id","name","args": [片段…], "extra": {}}；held 只增不清（观测用）
        self._calls: dict[int, dict] = {}
        self.held_events = 0  # 观测/测试用：累计吞下的含参增量数

    def feed(self, tool_calls: list | None) -> None:
        """吞下 delta.tool_calls 增量（不产生任何输出；§6 M3 finish 前不发）。"""
        for call in tool_calls or []:
            if not isinstance(call, dict):
                continue
            index = call.get("index")
            key = index if isinstance(index, int) else 0
            slot = self._calls.setdefault(key, {"id": "", "name": "", "args": [], "extra": {}})
            if isinstance(call.get("id"), str) and call["id"]:
                slot["id"] = call["id"]
            fn = call.get("function")
            if isinstance(fn, dict):
                if isinstance(fn.get("name"), str) and fn["name"]:
                    slot["name"] = fn["name"]
                fragment = fn.get("arguments")
                if isinstance(fragment, str) and fragment:
                    slot["args"].append(fragment)
                    self.held_events += 1
                    if sum(len(a) for a in slot["args"]) > self._max_arguments_chars:
                        raise ToolArgumentsOverflowError(
                            f"tool_call[index={key}] arguments exceeded "
                            f"{self._max_arguments_chars} chars")
            for k, v in call.items():
                if k not in ("index", "id", "function"):
                    slot["extra"][k] = v

    def held_arguments(self, index: int) -> str:
        """当前槽位已缓冲的 arguments 拼接（观测/测试用；不还原）。"""
        slot = self._calls.get(index)
        return "".join(slot["args"]) if slot else ""

    def finalize(self, mapper: SessionMapper) -> list[dict]:
        """finish 时整体还原，返回每工具一个的完整 delta（``tool_calls`` 形状）。

        拼接 → :func:`restore_arguments` 整段还原（与"逐块还原"严格等价，
        见模块 docstring）；返回后缓冲清空（重复 finalize 返回空表，幂等收尾）。
        """
        deltas: list[dict] = []
        for index in sorted(self._calls):
            slot = self._calls[index]
            arguments = restore_arguments(mapper, "".join(slot["args"]))
            call: dict = {"index": index, "type": "function",
                          "id": slot["id"], "function": {"name": slot["name"], "arguments": arguments}}
            call.update(slot["extra"])
            deltas.append(call)
        self._calls.clear()
        return deltas

    def __bool__(self) -> bool:
        return bool(self._calls)
