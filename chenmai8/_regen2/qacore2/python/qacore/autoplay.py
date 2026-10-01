"""自动试玩驱动（spec §5/§5.1）。

纪律（冻结）：不许 mock 被测物——QC 必须以真实浏览器 + 真实指针事件驱动；autoplay 只驱动竖屏趟。
手势语义表：swap-left/right/up/down → 定向拖拽（44px，分 4 步 mouse.move，down→move→up）；
drag → 向右拖拽；tap → 单击；未知 type 按 tap 兜底（最不打扰被测物）。
hint 坐标 = 视口 CSS 像素。试玩轮询间隔 180ms；预算由 CLI --autoplay-timeout（默认 45s）给定。

取证（全部发生在竖屏趟）：
- 首次手势前采集 firstMutedBeforeInteraction（PF.isMuted()）与 audioRunningBeforeInteraction；
  首次手势后采集 mutedAfterFirstGesture（应为 false=解除静音）。
- 结束采集 pfEndFired/pfEndMs/pfEndWin（探针）、reachedState（state()）、
  endScreenVisible（endScreenVisible()，无钩子为 null）、gestures 计数。
- CHK10 取证：驱动前采一次 texts()（教程浮层数秒即消失，必须早采）、结束页再采一次，
  并集为 page_texts；textStates() 循环内随相位 + 驱动前 + 结束页各采一轮，
  everVisible 归属：QC 逐轮采样并集、只置真不清零；模板直接回 {text, everVisible} 亦兼容；
  assets() 为 Promise，evaluate 自动等待。
"""

from __future__ import annotations

import time

POLL_INTERVAL_MS = 180
DRAG_DISTANCE = 44.0
DRAG_STEPS = 4

# 手势语义表（spec §5）：drag 与 tap 之外的未知 type 按 tap 兜底
_SWAP_VECTORS = {
    "swap-left": (-1.0, 0.0),
    "swap-right": (1.0, 0.0),
    "swap-up": (0.0, -1.0),
    "swap-down": (0.0, 1.0),
    "drag": (1.0, 0.0),  # drag → 向右拖拽
}

_JS_HAS_QC_HOOK = "() => !!(window.__PF_QC__ && typeof window.__PF_QC__.hint === 'function')"
_JS_TEXTS_HOOK = "() => !!(window.__PF_QC__ && typeof window.__PF_QC__.texts === 'function')"
_JS_TEXTSTATES_HOOK = (
    "() => !!(window.__PF_QC__ && typeof window.__PF_QC__.textStates === 'function')"
)
_JS_ASSETS_HOOK = "() => !!(window.__PF_QC__ && typeof window.__PF_QC__.assets === 'function')"

_JS_TEXTS = """() => {
  const q = window.__PF_QC__;
  try {
    const v = q.texts();
    if (v == null) return [];
    if (Array.isArray(v)) return v.map((x) => String(x));
    if (typeof v === 'object') return Object.keys(v);  // QC 侧容错：dict 取 keys
    return [String(v)];                                 // QC 侧容错：标量包单元素
  } catch (e) { return []; }
}"""

_JS_TEXTSTATES = """() => {
  try { return window.__PF_QC__.textStates() || []; } catch (e) { return []; }
}"""

_JS_ASSETS = """() => {
  try { return window.__PF_QC__.assets(); } catch (e) { return []; }
}"""

_JS_STATE = """() => {
  const q = window.__PF_QC__;
  try { return q && typeof q.state === 'function' ? q.state() : null; } catch (e) { return null; }
}"""

_JS_END_VISIBLE = """() => {
  const q = window.__PF_QC__;
  try {
    return q && typeof q.endScreenVisible === 'function' ? q.endScreenVisible() : null;
  } catch (e) { return null; }
}"""

_JS_HINT = """() => {
  const q = window.__PF_QC__;
  if (!q || typeof q.hint !== 'function') return null;
  try {
    const h = q.hint();
    if (!h || typeof h !== 'object') return null;
    return { x: h.x, y: h.y, type: h.type == null ? null : String(h.type) };
  } catch (e) { return null; }
}"""

_JS_PROBE_END = """() => {
  const p = window.__pfprobe;
  return p ? { end: p.end, endWin: p.endWin } : { end: null, endWin: null };
}"""

_JS_PROBE_AUDIO_RUNNING = (
    "() => { const p = window.__pfprobe; return p && p.audio ? p.audio.running : null; }"
)

_JS_IS_MUTED = """() => {
  try {
    return window.PF && typeof window.PF.isMuted === 'function' ? !!window.PF.isMuted() : null;
  } catch (e) { return null; }
}"""


def _perform(page, hint: dict) -> None:
    """按手势语义表执行真实指针事件。hint 坐标 = 视口 CSS 像素。"""
    try:
        x = float(hint.get("x"))
        y = float(hint.get("y"))
    except (TypeError, ValueError):
        return
    gesture_type = hint.get("type") or ""
    vector = _SWAP_VECTORS.get(gesture_type)
    if vector is None:
        page.mouse.click(x, y)  # tap 与未知 type 一律单击（最不打扰被测物）
        return
    dx, dy = vector
    page.mouse.move(x, y)
    page.mouse.down()
    for step in range(1, DRAG_STEPS + 1):  # 位移 44px，分 4 步 mouse.move
        page.mouse.move(
            x + dx * DRAG_DISTANCE * step / DRAG_STEPS,
            y + dy * DRAG_DISTANCE * step / DRAG_STEPS,
        )
    page.mouse.up()


def drive_autoplay(page, timeout_sec: float, sample_media) -> dict:
    """以真实指针事件驱动竖屏趟到结束页；返回试玩取证 facts（不落盘进 report.facts，
    完整结构随 viewport_shots.portrait 落盘，spec §5/pipeline-contract §4 注）。"""
    facts = {
        "hasQcHook": False,
        "gestures": 0,
        "pfEndFired": False,
        "pfEndMs": None,
        "pfEndWin": None,
        "reachedState": None,
        "endScreenVisible": None,
        "firstMutedBeforeInteraction": None,
        "audioRunningBeforeInteraction": None,
        "mutedAfterFirstGesture": None,
        "textsHook": False,
        "page_texts": [],
        "textStatesHook": False,
        "text_states": [],
        "assetsHook": False,
        "asset_audit": [],
    }

    facts["hasQcHook"] = bool(page.evaluate(_JS_HAS_QC_HOOK))

    ever: dict = {}

    def _sample_text_states() -> None:
        """textStates() 逐轮采样；everVisible 只置真不清零（含模板直回 everVisible 形状）。"""
        if not facts["textStatesHook"] and page.evaluate(_JS_TEXTSTATES_HOOK):
            facts["textStatesHook"] = True
        if not facts["textStatesHook"]:
            return
        for item in page.evaluate(_JS_TEXTSTATES) or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text"))
            if "everVisible" in item:
                seen = bool(item.get("everVisible"))
            else:
                seen = bool(item.get("active")) and bool(item.get("visible"))
            ever[text] = ever.get(text, False) or seen

    def _snapshot_states() -> None:
        facts["text_states"] = [
            {"text": t, "everVisible": v} for t, v in sorted(ever.items())
        ]

    # 驱动前采样：教程浮层数秒即消失，必须早采
    if page.evaluate(_JS_TEXTS_HOOK):
        facts["textsHook"] = True
        facts["page_texts"] = [str(t) for t in (page.evaluate(_JS_TEXTS) or [])]
    sample_media()
    _sample_text_states()
    # 首次手势前采集静音事实——必须在任何 hint() 调用之前：模板的 hint() 本身即可能
    # 触发首交互并解除静音（夹具语义"第一次 hint 即首交互"）
    facts["firstMutedBeforeInteraction"] = page.evaluate(_JS_IS_MUTED)
    facts["audioRunningBeforeInteraction"] = page.evaluate(_JS_PROBE_AUDIO_RUNNING)

    if not facts["hasQcHook"]:
        # 无 __PF_QC__ → 无法驱动；CHK07 由判定层 fail
        _snapshot_states()
        return facts

    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    while True:
        sample_media()          # 每轮重采样未静音媒体（最坏值粘住，探针侧 max）
        _sample_text_states()   # 循环内随相位采样（含教程期）
        ended = page.evaluate(_JS_PROBE_END)
        state = page.evaluate(_JS_STATE)
        if ended.get("end") is not None and state == "end":
            break
        if time.monotonic() >= deadline:
            break
        hint = page.evaluate(_JS_HINT)
        if hint is not None:
            _perform(page, hint)
            facts["gestures"] += 1
            if facts["mutedAfterFirstGesture"] is None:
                facts["mutedAfterFirstGesture"] = page.evaluate(_JS_IS_MUTED)
        page.wait_for_timeout(POLL_INTERVAL_MS)

    # 结束页采样：texts() 再采一次并与驱动前并集；textStates 结束页一轮；assets 对账
    sample_media()
    if facts["textsHook"]:
        tail = [str(t) for t in (page.evaluate(_JS_TEXTS) or [])]
        facts["page_texts"] = list(dict.fromkeys(list(facts["page_texts"]) + tail))
    _sample_text_states()
    _snapshot_states()

    ended = page.evaluate(_JS_PROBE_END)
    facts["pfEndFired"] = ended.get("end") is not None
    facts["pfEndMs"] = ended.get("end")
    facts["pfEndWin"] = ended.get("endWin")
    facts["reachedState"] = page.evaluate(_JS_STATE)
    facts["endScreenVisible"] = page.evaluate(_JS_END_VISIBLE)
    if page.evaluate(_JS_ASSETS_HOOK):
        facts["assetsHook"] = True
        audit = page.evaluate(_JS_ASSETS)
        facts["asset_audit"] = list(audit) if isinstance(audit, list) else []
    return facts
