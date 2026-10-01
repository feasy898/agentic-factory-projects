"""M3 工具调用参数还原（masking-placeholder spec §6，一字不差）。

- **流式**：``tool_call.arguments`` 增量累积、**finish 前不发**（明示行为变化：
  客户端在 finish 前收不到任何 tool_calls 增量）；finish 时整体还原后作为
  **单个 delta** 发出——按 index 分槽累积、finish 收尾幂等、缓冲有界
  ``MAX_ARGUMENTS_CHARS`` 安全阀（超限响亮失败 ``ToolArgumentsOverflowError``
  而非静默截断；阀为绊线：抛错时缓冲状态原样保留供上层诊断）。
- **非流式**：``restore_arguments`` 直接整体还原。
- 与流式文本还原的分工：文本流必须在线放行（remap 状态机缓冲）；参数流允许整段
  hold 到 finish，拼接视角逐字相等，整段 restore 与「逐块还原」严格等价。

spec 缺口备注：``MAX_ARGUMENTS_CHARS`` 的默认数值 spec 未钉死（仅要求有界且
响亮失败）；本实现取 1_000_000（冻结测试仅约束 ≥ 1000，见 evals.m3_masking
step_tool_edges）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_ARGUMENTS_CHARS = 1_000_000  # 缓冲安全阀默认值（spec 未钉死数值，见模块文档）

DEFAULT_TOOL_TYPE = "function"


class ToolArgumentsOverflowError(RuntimeError):
    """工具参数缓冲超过安全阀（响亮失败，不静默截断）。"""


@dataclass
class _ToolSlot:
    """单个 index 槽位：id/name 仅首见，arguments 分片按序累积。"""

    call_id: str | None = None
    name: str | None = None
    chunks: list[str] = field(default_factory=list)
    length: int = 0

    def append(self, fragment: str) -> None:
        self.chunks.append(fragment)
        self.length += len(fragment)

    def raw(self) -> str:
        return "".join(self.chunks)


class ToolCallBuffer:
    """流式 tool_calls 增量缓冲器：hold-to-finish，finalize 时整体还原。"""

    def __init__(self, max_arguments_chars: int = MAX_ARGUMENTS_CHARS) -> None:
        self._cap = max_arguments_chars
        self._slots: dict[int, _ToolSlot] = {}
        self._held_events = 0

    # ── 观测 ────────────────────────────────────────────────────────
    @property
    def held_events(self) -> int:
        """已 hold 的增量事件数（非 dict 元素不计）。"""
        return self._held_events

    def held_arguments(self, index: int) -> str:
        """该槽位已累积的原始 arguments 拼接（分片顺序连接）。"""
        slot = self._slots.get(index)
        return "" if slot is None else slot.raw()

    def __len__(self) -> int:
        return self._held_events

    def __bool__(self) -> bool:
        return self._held_events > 0

    # ── 喂入（finish 前零发出）─────────────────────────────────────
    def feed(self, deltas: list[Any]) -> None:
        """累积一个增量批次；恒返回 None（finish 前不发任何事件）。"""
        for item in deltas:
            if not isinstance(item, dict):
                continue  # 非 dict 元素跳过不炸
            index = item.get("index", 0)
            slot = self._slots.setdefault(index, _ToolSlot())
            self._held_events += 1
            if slot.call_id is None and item.get("id") is not None:
                slot.call_id = item["id"]
            fn = item.get("function")
            if isinstance(fn, dict):
                if slot.name is None and fn.get("name") is not None:
                    slot.name = fn["name"]
                fragment = fn.get("arguments")
                if fragment:
                    slot.append(fragment)
                    if slot.length > self._cap:  # 追加后检查（绊线：状态原样保留）
                        raise ToolArgumentsOverflowError(
                            f"tool arguments exceeded {self._cap} chars at index={index} "
                            f"(held {slot.length}); aborting loudly, buffer intact for diagnostics"
                        )

    # ── 收尾（幂等）────────────────────────────────────────────────
    def finalize(self, mapper: Any) -> list[dict[str, Any]]:
        """finish：各槽位整体还原为**单个 delta**，按 index 升序；随后清空（幂等）。"""
        out: list[dict[str, Any]] = []
        for index in sorted(self._slots):
            slot = self._slots[index]
            out.append({
                "index": index,
                "type": DEFAULT_TOOL_TYPE,
                "id": slot.call_id,
                "function": {
                    "name": slot.name,
                    "arguments": mapper.restore(slot.raw()),
                },
            })
        self._slots.clear()
        self._held_events = 0
        return out


def restore_arguments(mapper: Any, text: str) -> str:
    """非流式直接整体还原（与 mapper.restore 严格等价）。"""
    return mapper.restore(text)


__all__ = [
    "MAX_ARGUMENTS_CHARS",
    "ToolArgumentsOverflowError",
    "ToolCallBuffer",
    "restore_arguments",
]
