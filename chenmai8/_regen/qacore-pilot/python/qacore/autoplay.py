"""自动试玩驱动（SPEC qacore.md §5）。

铁律：不许 mock 被测物——QC 必须以真实浏览器 + 真实指针事件驱动。
取证项：pfEndFired/pfEndMs/pfEndWin（探针）、reachedState、endScreenVisible、gestures；
静音链路 firstMutedBeforeInteraction / audioRunningBeforeInteraction / mutedAfterFirstGesture；
CHK10 取证 qc_texts（驱动前+结束页并集 page_texts）、textStates 随相位采样（text_states 逐文案
everVisible + text_states_hook）、assets() 像素对账（asset_audit）。
"""

import time

POLL_INTERVAL_MS = 180  # 试玩轮询间隔（SPEC §3 魔法数字表）
DRAG_DISTANCE = 44.0    # 拖拽位移 px（小于最小棋盘格边长）
DRAG_STEPS = 4          # mouse.move 步数

_SWAP_VECTORS = {
    "swap-left": (-DRAG_DISTANCE, 0.0),
    "swap-right": (DRAG_DISTANCE, 0.0),
    "swap-up": (0.0, -DRAG_DISTANCE),
    "swap-down": (0.0, DRAG_DISTANCE),
}

_JS_HAS_QC = "!!(window.__PF_QC__ && typeof window.__PF_QC__.hint === 'function')"
_JS_IS_MUTED = "(window.PF && typeof window.PF.isMuted === 'function') ? !!window.PF.isMuted() : null"
_JS_AUDIO_RUNNING = "window.__pfprobe ? window.__pfprobe.audio.running : null"
_JS_SAMPLE_MEDIA = "window.__pfprobe && window.__pfprobe.sampleMedia ? window.__pfprobe.sampleMedia() : null"
_JS_HINT = "(window.__PF_QC__ && typeof window.__PF_QC__.hint === 'function') ? window.__PF_QC__.hint() : null"
_JS_STATE = "(window.__PF_QC__ && typeof window.__PF_QC__.state === 'function') ? String(window.__PF_QC__.state()) : null"
_JS_END_VISIBLE = "(window.__PF_QC__ && typeof window.__PF_QC__.endScreenVisible === 'function') ? !!window.__PF_QC__.endScreenVisible() : null"
_JS_TEXTS = "(window.__PF_QC__ && typeof window.__PF_QC__.texts === 'function') ? window.__PF_QC__.texts() : null"
_JS_TEXT_STATES = "(window.__PF_QC__ && typeof window.__PF_QC__.textStates === 'function') ? window.__PF_QC__.textStates() : null"
_JS_ASSETS = "(window.__PF_QC__ && typeof window.__PF_QC__.assets === 'function') ? window.__PF_QC__.assets() : null"
_JS_END_REACHED = ("(window.__pfprobe && window.__pfprobe.end != null) || "
                   "(window.__PF_QC__ && typeof window.__PF_QC__.state === 'function' && window.__PF_QC__.state() === 'end')")
_JS_SNAPSHOT = "window.__pfprobe ? JSON.parse(JSON.stringify(window.__pfprobe)) : null"


def _perform_gesture(page, hint) -> None:
    """手势语义表（SPEC §5）：swap-* 定向拖拽 44px×4 步；drag 向右拖拽；tap 单击。
    hint 坐标 = 视口 CSS 像素。未知类型按 tap 兜底（最不打扰被测物）。"""
    x = float(hint.get("x") or 0.0)
    y = float(hint.get("y") or 0.0)
    gtype = str(hint.get("type") or "tap")
    if gtype in _SWAP_VECTORS:
        dx, dy = _SWAP_VECTORS[gtype]
    elif gtype == "drag":
        dx, dy = DRAG_DISTANCE, 0.0
    else:
        page.mouse.click(x, y)
        return
    page.mouse.move(x, y)
    page.mouse.down()
    for i in range(1, DRAG_STEPS + 1):
        page.mouse.move(x + dx * i / DRAG_STEPS, y + dy * i / DRAG_STEPS)
    page.mouse.up()


def _poll_media(page, ev, record_pre_interaction: bool) -> None:
    """每轮重采样未静音媒体元素（最坏值粘住）。CHK04 只看首交互前窗口。"""
    r = page.evaluate(_JS_SAMPLE_MEDIA)
    if not r:
        return
    unmuted = int(r.get("unmuted") or 0)
    ev["mediaUnmutedMax"] = max(ev.get("mediaUnmutedMax") or 0, unmuted)
    ev["mediaPlayingMax"] = max(ev.get("mediaPlayingMax") or 0, int(r.get("playing") or 0))
    if record_pre_interaction:
        ev["mediaUnmutedBeforeMax"] = max(ev.get("mediaUnmutedBeforeMax") or 0, unmuted)
        ev["mediaPlayingBeforeMax"] = max(ev.get("mediaPlayingBeforeMax") or 0, int(r.get("playing") or 0))


def _sample_texts(page, ev, union: bool = False) -> None:
    """qc_texts：教程浮层数秒即消失必须早采；驱动前 + 结束页各采一次并集为 page_texts。"""
    r = page.evaluate(_JS_TEXTS)
    if r is None:
        ev["textsHook"] = False
        return
    ev["textsHook"] = True
    if isinstance(r, list):
        items = [str(t) for t in r]
    elif isinstance(r, dict):
        items = [str(k) for k in r.keys()]
    else:
        items = [str(r)]
    out = ev.setdefault("page_texts", [])
    for t in items:
        if t not in out:
            out.append(t)


def _sample_text_states(page, ev) -> None:
    """可见性自证：textStates() 模板侧当场读 Text 对象实况；QC 逐轮并集出 everVisible。
    模板不提供该钩子 → text_states_hook=False（CHK10 对 required_texts 从严 fail）。"""
    r = page.evaluate(_JS_TEXT_STATES)
    if r is None:
        ev["textStatesHook"] = False
        return
    ev["textStatesHook"] = True
    merged = {d.get("text"): d for d in ev.setdefault("text_states", [])}
    entries = r if isinstance(r, list) else ([r] if isinstance(r, dict) else [])
    for item in entries:
        if isinstance(item, dict):
            text = str(item.get("text"))
            if "everVisible" in item:
                ever = bool(item.get("everVisible"))
            else:
                ever = bool(item.get("active", True)) and bool(item.get("visible", True))
        else:
            text, ever = str(item), True
        prev = merged.get(text)
        if prev is None:
            merged[text] = {"text": text, "everVisible": ever}
        elif ever:
            prev["everVisible"] = True
    ev["text_states"] = list(merged.values())


def _snapshot_end(page, ev) -> None:
    probe = page.evaluate(_JS_SNAPSHOT) or {}
    ev["probe"] = probe
    ev["pfEndFired"] = probe.get("end") is not None
    ev["pfEndMs"] = probe.get("end")
    ev["pfEndWin"] = probe.get("endWin")
    ev["reachedState"] = page.evaluate(_JS_STATE)
    ev["endScreenVisible"] = page.evaluate(_JS_END_VISIBLE)


def drive(page, timeout_sec: float, ev: dict) -> None:
    """竖屏趟自动试玩：真实指针事件驱动到结束页，把取证写入 ev。"""
    ev["hasQcHook"] = bool(page.evaluate(_JS_HAS_QC))
    ev["gestures"] = 0
    ev["firstMutedBeforeInteraction"] = page.evaluate(_JS_IS_MUTED)
    ev["audioRunningBeforeInteraction"] = page.evaluate(_JS_AUDIO_RUNNING)
    ev["mediaUnmutedBeforeMax"] = 0
    ev["mediaPlayingBeforeMax"] = 0
    ev["mediaUnmutedMax"] = 0
    ev["mediaPlayingMax"] = 0
    ev["textsHook"] = False
    ev["textStatesHook"] = False
    ev["assetAuditHook"] = False
    ev["page_texts"] = []
    ev["text_states"] = []
    ev.setdefault("mutedAfterFirstGesture", None)
    if not ev["hasQcHook"]:
        _snapshot_end(page, ev)  # 无 __PF_QC__：CHK07 由 checks 判 fail
        return

    _sample_texts(page, ev)          # 驱动前必采（教程浮层转瞬即逝）
    _sample_text_states(page, ev)    # 驱动前一轮可见性自证
    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    first_gesture_done = False
    while True:
        _poll_media(page, ev, record_pre_interaction=not first_gesture_done)
        _sample_text_states(page, ev)
        if page.evaluate(_JS_END_REACHED):
            break
        if time.monotonic() >= deadline:
            ev["budgetExhausted"] = True
            break
        hint = page.evaluate(_JS_HINT)
        if hint:
            _perform_gesture(page, hint)
            ev["gestures"] += 1
            if not first_gesture_done:
                first_gesture_done = True
                ev["mutedAfterFirstGesture"] = page.evaluate(_JS_IS_MUTED)  # 应为 false=解除静音
        page.wait_for_timeout(POLL_INTERVAL_MS)

    _sample_texts(page, ev, union=True)   # 结束页后再采一次并集
    _sample_text_states(page, ev)         # 结束页一轮可见性自证
    assets = page.evaluate(_JS_ASSETS)
    if assets is None:
        ev["assetAuditHook"] = False
    else:
        ev["assetAuditHook"] = True
        ev["asset_audit"] = assets if isinstance(assets, list) else [assets]
    _snapshot_end(page, ev)
