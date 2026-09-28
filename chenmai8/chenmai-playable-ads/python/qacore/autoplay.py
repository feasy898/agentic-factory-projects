"""自动试玩驱动（--autoplay）：经 window.__PF_QC__.hint() 用真实 pointer 事件
推动游戏走 教程→游玩→结束页，采集静音/事件/结束页事实。

hint 契约（开发指令 §4.2，冻结）：返回 {x, y, type}|null，坐标为视口 CSS 像素，
type ∈ swap-left|swap-right|swap-up|swap-down|tap（模板自定义方向语义，QC 按方向
做真实拖拽）。state(): loading|tutorial|playing|end。
"""

from __future__ import annotations

import time
from typing import Any

from playwright.sync_api import Page

# 页面装载前注入的探针：记录 pf:* 事件时序（performance.now，相对导航起点）
# 并包装 AudioContext 构造器以观测"存在 running 状态的 AudioContext"。
PROBE_JS = """\
(() => {
  const probe = { ready: null, start: null, end: null, endWin: null, first: null, cta: null,
                  audio: { created: 0, running: 0 } };
  window.__pfprobe = probe;
  const once = (key) => () => { if (probe[key] === null) probe[key] = performance.now(); };
  document.addEventListener('pf:ready', once('ready'));
  document.addEventListener('pf:start', once('start'));
  document.addEventListener('pf:end', (e) => {
    if (probe.end === null) {
      probe.end = performance.now();
      probe.endWin = !!(e && e.detail && e.detail.win);
    }
  });
  document.addEventListener('pf:first-interaction', once('first'));
  document.addEventListener('pf:cta', once('cta'));
  const running = new Set();
  const wrap = (name) => {
    const Ctor = window[name];
    if (typeof Ctor !== 'function') return;
    const Wrapped = function (...args) {
      const ctx = new Ctor(...args);
      probe.audio.created += 1;
      const upd = () => {
        if (ctx.state === 'running') running.add(ctx); else running.delete(ctx);
        probe.audio.running = running.size;
      };
      try { if (ctx.addEventListener) ctx.addEventListener('statechange', upd); } catch (e) {}
      upd();
      return ctx;
    };
    Wrapped.prototype = Ctor.prototype;
    try { Object.defineProperty(window, name, { value: Wrapped, configurable: true, writable: true }); } catch (e) {}
  };
  wrap('AudioContext');
  wrap('webkitAudioContext');
})();
"""

# 拖拽位移（像素）：小于最小棋盘格边长，方向语义由 hint.type 给出。
DRAG_DISTANCE = 44.0
_SWEEP_VECTORS = {
    "swap-left": (-1.0, 0.0),
    "swap-right": (1.0, 0.0),
    "swap-up": (0.0, -1.0),
    "swap-down": (0.0, 1.0),
    "drag": (1.0, 0.0),
}


def _state(page: Page) -> str:
    try:
        return str(page.evaluate(
            "() => (window.__PF_QC__ && typeof window.__PF_QC__.state === 'function')"
            " ? String(window.__PF_QC__.state()) : 'loading'"
        ))
    except Exception:
        return "loading"


def _hint(page: Page) -> dict[str, Any] | None:
    try:
        hint = page.evaluate(
            "() => { const q = window.__PF_QC__;"
            " if (!q || typeof q.hint !== 'function') return null;"
            " try { return q.hint(); } catch (e) { return null; } }"
        )
    except Exception:
        return None
    if not isinstance(hint, dict):
        return None
    x, y = hint.get("x"), hint.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return {"x": float(x), "y": float(y), "type": str(hint.get("type", "tap"))}


def _pf_muted(page: Page) -> bool | None:
    try:
        v = page.evaluate("() => (window.PF && typeof PF.isMuted === 'function') ? PF.isMuted() : null")
    except Exception:
        return None
    return bool(v) if isinstance(v, bool) else None


pf_muted = _pf_muted  # 供非 autoplay 路径（仅加载）采集首交互前静音态


def audio_running(page: Page) -> int | None:
    try:
        v = page.evaluate("() => { const p = window.__pfprobe; return p && p.audio ? p.audio.running : null; }")
    except Exception:
        return None
    return int(v) if isinstance(v, (int, float)) else None


def _gesture(page: Page, hint: dict[str, Any]) -> None:
    """用真实 pointer 事件执行 hint：swap-* 为定向拖拽，tap 为单击。"""
    x, y = hint["x"], hint["y"]
    vec = _SWEEP_VECTORS.get(hint["type"])
    page.mouse.move(x, y)
    page.mouse.down()
    if vec:
        steps = 4
        for i in range(1, steps + 1):
            page.mouse.move(x + vec[0] * DRAG_DISTANCE * i / steps,
                            y + vec[1] * DRAG_DISTANCE * i / steps)
    page.mouse.up()


def has_pf(page: Page) -> bool:
    try:
        return bool(page.evaluate("() => !!(window.PF && typeof PF.isMuted === 'function')"))
    except Exception:
        return False


def has_qc_hooks(page: Page) -> bool:
    try:
        return bool(page.evaluate(
            "() => !!(window.__PF_QC__ && typeof window.__PF_QC__.hint === 'function'"
            " && typeof window.__PF_QC__.state === 'function')"
        ))
    except Exception:
        return False


def drive_autoplay(page: Page, timeout_sec: float) -> dict[str, Any]:
    """自动试玩主循环；返回采集到的事实（不判定 PASS/FAIL，判定在 checks）。"""
    facts: dict[str, Any] = {
        "enabled": True,
        "timeoutSec": timeout_sec,
        "reachedState": "loading",
        "gestures": 0,
        "firstMutedBeforeInteraction": None,
        "audioRunningBeforeInteraction": None,
        "mutedAfterFirstGesture": None,
        "pfEndFired": False,
        "pfEndWin": None,
        "pfEndMs": None,
        "pfReadyMs": None,
        "endScreenVisible": None,
        "qcHooksPresent": has_qc_hooks(page),
    }
    deadline = time.monotonic() + max(1.0, timeout_sec)
    while time.monotonic() < deadline:
        state = _state(page)
        facts["reachedState"] = state

        probe = page.evaluate("() => window.__pfprobe || null") or {}
        if facts["pfReadyMs"] is None and probe.get("ready") is not None:
            facts["pfReadyMs"] = probe.get("ready")

        # 首交互前事实：任何鼠标事件发生前 PF 必须 muted 且无 running AudioContext
        if facts["gestures"] == 0:
            if facts["firstMutedBeforeInteraction"] is None:
                facts["firstMutedBeforeInteraction"] = _pf_muted(page)
            if facts["audioRunningBeforeInteraction"] is None:
                facts["audioRunningBeforeInteraction"] = (probe.get("audio") or {}).get("running")

        if state == "end":
            break

        hint = _hint(page)
        if hint is not None:
            _gesture(page, hint)
            facts["gestures"] += 1
            if facts["mutedAfterFirstGesture"] is None:
                facts["mutedAfterFirstGesture"] = _pf_muted(page)

        page.wait_for_timeout(180)

    probe = page.evaluate("() => window.__pfprobe || null") or {}
    facts["pfEndFired"] = probe.get("end") is not None
    facts["pfEndMs"] = probe.get("end")
    facts["pfEndWin"] = probe.get("endWin")
    if facts["pfReadyMs"] is None:
        facts["pfReadyMs"] = probe.get("ready")
    if facts["reachedState"] != "end":
        facts["reachedState"] = _state(page)
    try:
        facts["endScreenVisible"] = bool(page.evaluate(
            "() => (window.__PF_QC__ && typeof window.__PF_QC__.endScreenVisible === 'function')"
            " ? !!window.__PF_QC__.endScreenVisible() : null"
        ))
    except Exception:
        facts["endScreenVisible"] = None
    return facts
