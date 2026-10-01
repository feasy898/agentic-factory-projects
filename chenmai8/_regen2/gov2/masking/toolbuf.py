"""工具调用参数的缓冲还原（gov2 盲实现，依据 masking-placeholder spec §6）。

- 流式：tool_call.arguments 增量累积、finish 前不发（feed 恒返回 None）；
  finish 时整体还原后每个工具作为单个 delta 发出；
- 非流式：restore_arguments 直接整体还原。

与流式文本还原（masking/remap.py）的分工：文本流必须在线放行（状态机缓冲候选）；
参数流允许整段 hold 到 finish——拼接视角逐字相等，整段 restore 与「逐块还原」
严格等价，而后者正是占位符被切进两个 arguments 增量时漏配的根源。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from masking.mapper import SessionMapper

log = logging.getLogger(__name__)

#: 单个工具调用槽位的 arguments 缓冲上限（字符）——hold-to-finish 是流式路径上
#: 唯一无上界增长的显式缓冲点，设安全阀；语义为绊线：追加后检查、超限抛
#: ToolArgumentsOverflowError，缓冲状态原样保留（含触发块）——绝不静默截断
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
    """非流式直接整体还原：arguments 串内占位符 → 原值（normalized）。

    还原是纯串级替换（占位符形状不含任何 JSON 结构字符）；还原改变串且原串可
    JSON 解析、还原后不可解析 → 记结构化告警但保留还原结果（占位符→原值是正确
    语义，不回退）。纯文本非 JSON 照常替换；无占位符原样返回。
    """
    restored = mapper.restore(arguments)
    if restored != arguments and _parses_as_json(arguments) and not _parses_as_json(restored):
        log.warning("toolbuf.restore_broke_json", extra={"chars": len(arguments)})
    return restored


class ToolCallBuffer:
    """流式 tool_calls 增量缓冲：arguments 按 index 累积，finish 前不发出。

    - 同一调用的 id/function.name 可能只在首个增量出现（也可能重复）——按槽位
      保留首见非空值；其余 delta 字段（扩展字段）存 extra 并在 finalize 时并入；
    - 无 index 的增量按 index=0 归槽；非 dict 元素跳过不炸；
    - feed 只吞不吐（恒返回 None）；finalize 按槽位升序每工具一个完整 delta，
      返回后清空（重复 finalize 返回空表，幂等收尾）；
    - 实例不可跨响应复用（与 StreamRestorer 同纪律）。
    """

    __slots__ = ("_calls", "_max_arguments_chars", "held_events")

    def __init__(self, *, max_arguments_chars: int = MAX_ARGUMENTS_CHARS) -> None:
        if max_arguments_chars < 1:
            raise ValueError("max_arguments_chars must be >= 1")
        self._max_arguments_chars = max_arguments_chars
        # index → {"id","name","args":[片段...],"extra":{}}；held_events 只增不清（观测口）
        self._calls: dict[int, dict] = {}
        self.held_events = 0

    def feed(self, tool_calls: list | None) -> None:
        """吞下 delta.tool_calls 增量（恒返回 None——finish 前不发）。"""
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
        """当前槽位已缓冲的 arguments 拼接（观测口；不还原）。"""
        slot = self._calls.get(index)
        return "".join(slot["args"]) if slot else ""

    def finalize(self, mapper: SessionMapper) -> list[dict]:
        """finish 时整体还原，按 index 升序返回每工具一个完整 delta；返回后清空。"""
        deltas: list[dict] = []
        for index in sorted(self._calls):
            slot = self._calls[index]
            arguments = restore_arguments(mapper, "".join(slot["args"]))
            call: dict = {"index": index, "type": "function",
                          "id": slot["id"],
                          "function": {"name": slot["name"], "arguments": arguments}}
            call.update(slot["extra"])
            deltas.append(call)
        self._calls.clear()
        return deltas

    def __bool__(self) -> bool:
        return bool(self._calls)
