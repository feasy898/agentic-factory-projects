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

# 页面装载前注入的探针：记录 pf:* 事件时序（performance.now，相对导航起点）；
# 包装 AudioContext 构造器以观测"存在 running 状态的 AudioContext"；
# 包装 HTMLMediaElement.play 以覆盖 <audio>/<video>/new Audio() 的出声尝试；
# 统计未静音媒体元素（sampleMedia 每轮由 Python 侧重采样）；
# 统计 RTCPeerConnection 构造次数（WebRTC 不经过网络拦截，只能靠探针计数）。
PROBE_JS = """\
(() => {
  const probe = { ready: null, start: null, end: null, endWin: null, first: null, cta: null,
                  audio: { created: 0, running: 0 },
                  media: { unmuted: 0, playing: 0, playsBeforeFirst: 0 },
                  rtc: 0 };
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

  // 首次 pointer 事件（真实用户与自动试玩的鼠标事件都算）打点：
  // 此前发生的媒体 play() 计入 playsBeforeFirst。
  let firstGestureAt = null;
  document.addEventListener('pointerdown', () => {
    if (firstGestureAt === null) firstGestureAt = performance.now();
  }, true);

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

  // 媒体元素（<audio>/<video>/new Audio()）观测：未静音 = muted=false 且 volume>0。
  probe.sampleMedia = () => {
    let unmuted = 0, playing = 0;
    const list = document.querySelectorAll('audio,video');
    for (let i = 0; i < list.length; i++) {
      const el = list[i];
      if (!el.muted && (el.volume === undefined || el.volume > 0)) {
        unmuted += 1;
        if (!el.paused) playing += 1;
      }
    }
    probe.media.unmuted = unmuted;
    probe.media.playing = playing;
    return probe.media;
  };
  try {
    const proto = HTMLMediaElement.prototype;
    const origPlay = proto.play;
    if (typeof origPlay === 'function') {
      proto.play = function (...args) {
        if (firstGestureAt === null) probe.media.playsBeforeFirst += 1;
        return origPlay.apply(this, args);
      };
    }
  } catch (e) {}

  // WebRTC 探针：RTCPeerConnection 不经过 route 拦截，构造即视为建立点对点通道的尝试。
  const wrapRtc = (name) => {
    const Ctor = window[name];
    if (typeof Ctor !== 'function') return;
    const Wrapped = function (...args) {
      probe.rtc += 1;
      return new Ctor(...args);
    };
    Wrapped.prototype = Ctor.prototype;
    try { Object.defineProperty(window, name, { value: Wrapped, configurable: true, writable: true }); } catch (e) {}
  };
  wrapRtc('RTCPeerConnection');
  wrapRtc('webkitRTCPeerConnection');
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


def media_sample(page: Page) -> dict | None:
    """重采样媒体元素事实：{unmuted, playing, playsBeforeFirst}；探针缺失返回 None。"""
    try:
        v = page.evaluate(
            "() => (window.__pfprobe && typeof window.__pfprobe.sampleMedia === 'function')"
            " ? window.__pfprobe.sampleMedia() : null"
        )
    except Exception:
        return None
    return v if isinstance(v, dict) else None


def rtc_count(page: Page) -> int | None:
    """RTCPeerConnection 构造次数；探针缺失返回 None。"""
    try:
        v = page.evaluate("() => { const p = window.__pfprobe; return p ? (p.rtc | 0) : null; }")
    except Exception:
        return None
    return int(v) if isinstance(v, (int, float)) else None


def probe_installed(page: Page) -> bool:
    try:
        return bool(page.evaluate("() => !!window.__pfprobe"))
    except Exception:
        return False


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


def qc_texts(page: Page) -> list[str]:
    """模板经 __PF_QC__.texts() 上报的已渲染文案集合。

    画布文字不进 DOM（innerText 取不到），由模板侧登记所有真正加入场景的
    Text 内容。无钩子/异常时返回空表（CHK10 据实判缺证，不做假定）。"""
    try:
        v = page.evaluate(
            "() => (window.__PF_QC__ && typeof window.__PF_QC__.texts === 'function')"
            " ? window.__PF_QC__.texts() : []"
        )
    except Exception:
        return []
    if not isinstance(v, list):
        return []
    return [str(x) for x in v if isinstance(x, (str, int, float))]


def qc_text_states(page: Page) -> tuple[bool, list[dict]]:
    """模板经 __PF_QC__.textStates() 上报的文案对象实况采样（CHK10 自证补强）。

    返回 (钩子在位, 采样条目)：每条 {text, active, visible} 由模板在调用瞬间
    读 Text 对象实况——引擎 destroy() 会把 active/visible 置假，退场浮层不再
    虚报"在屏"。texts() 只能证明"字符串登记过"，本采样把证据升级为"登记的
    对象此刻真的 active+visible"。钩子缺失/异常时返回 (False, [])。"""
    try:
        v = page.evaluate(
            "() => (window.__PF_QC__ && typeof window.__PF_QC__.textStates === 'function')"
            " ? window.__PF_QC__.textStates() : null"
        )
    except Exception:
        return False, []
    if not isinstance(v, list):
        return False, []
    entries: list[dict] = []
    for x in v:
        if isinstance(x, dict) and isinstance(x.get("text"), (str, int, float)):
            entries.append({
                "text": str(x["text"]),
                "active": x.get("active") is True,
                "visible": x.get("visible") is True,
            })
    return True, entries


def qc_assets(page: Page) -> list[dict]:
    """模板经 __PF_QC__.assets() 上报的替换素材像素对账结果。

    对账在页面内完成：渲染贴图与构建期内联的用户 PNG 经同一 contain-fit
    管线降采样到 16×16 比平均绝对差。无钩子/无替换素材时返回 []。"""
    try:
        v = page.evaluate(
            "() => (window.__PF_QC__ && typeof window.__PF_QC__.assets === 'function')"
            " ? window.__PF_QC__.assets() : []"
        )
    except Exception:
        return []
    if not isinstance(v, list):
        return []
    return [dict(x) for x in v if isinstance(x, dict)]


def has_qc_hooks(page: Page) -> bool:
    try:
        return bool(page.evaluate(
            "() => !!(window.__PF_QC__ && typeof window.__PF_QC__.hint === 'function'"
            " && typeof window.__PF_QC__.state === 'function')"
        ))
    except Exception:
        return False


def drive_autoplay(page: Page, timeout_sec: float) -> dict[str, Any]:
    """自动试玩主循环；返回采集到的事实（不判定 PASS/FAIL，判定在 checks）。

    每轮随相位采样 __PF_QC__.textStates()（CHK10 自证补强）：退场浮层（教程
    文案在教程结束后即被销毁）只能在它在屏的相位采到 active+visible，故循环
    内逐轮累积"曾见文案/曾见 active+visible 文案"两个并集，随 facts 返回。"""
    facts: dict[str, Any] = {
        "enabled": True,
        "timeoutSec": timeout_sec,
        "reachedState": "loading",
        "gestures": 0,
        "firstMutedBeforeInteraction": None,
        "audioRunningBeforeInteraction": None,
        "mediaUnmutedBeforeInteraction": None,
        "mediaPlaysBeforeInteraction": None,
        "mutedAfterFirstGesture": None,
        "pfEndFired": False,
        "pfEndMs": None,
        "pfEndWin": None,
        "pfReadyMs": None,
        "endScreenVisible": None,
        "qcHooksPresent": has_qc_hooks(page),
        "probeInstalled": probe_installed(page),
        "textStatesHook": False,
        "qcTexts": [],
        "qcVisibleTexts": [],
    }
    seen_texts: set[str] = set()
    visible_texts: set[str] = set()
    deadline = time.monotonic() + max(1.0, timeout_sec)
    while time.monotonic() < deadline:
        state = _state(page)
        facts["reachedState"] = state

        # 文案对象实况采样（含教程期——退场即销毁，错过相位就再无证据）
        hook, states = qc_text_states(page)
        if hook:
            facts["textStatesHook"] = True
        for s in states:
            seen_texts.add(s["text"])
            if s["active"] and s["visible"]:
                visible_texts.add(s["text"])

        probe = page.evaluate("() => window.__pfprobe || null") or {}
        if facts["pfReadyMs"] is None and probe.get("ready") is not None:
            facts["pfReadyMs"] = probe.get("ready")

        # 首交互前事实：任何鼠标事件发生前 PF 必须 muted、无 running AudioContext、
        # 不存在未静音媒体元素。每轮重采样（声音/媒体可能迟到才出现），
        # 采样取"最坏值粘住"：一旦观测到未静音/出声/未静音媒体即不再被后续轮次洗白。
        if facts["gestures"] == 0:
            m = _pf_muted(page)
            if m is False:
                facts["firstMutedBeforeInteraction"] = False
            elif facts["firstMutedBeforeInteraction"] is None:
                facts["firstMutedBeforeInteraction"] = m
            run = (probe.get("audio") or {}).get("running") or 0
            facts["audioRunningBeforeInteraction"] = max(
                facts["audioRunningBeforeInteraction"] or 0, int(run))
            ms = media_sample(page) or {}
            facts["mediaUnmutedBeforeInteraction"] = max(
                facts["mediaUnmutedBeforeInteraction"] or 0, int(ms.get("unmuted") or 0))
            facts["mediaPlaysBeforeInteraction"] = max(
                facts["mediaPlaysBeforeInteraction"] or 0, int(ms.get("playsBeforeFirst") or 0))

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
    # 结束后再补采一轮媒体事实（覆盖"最后一轮之后才出声"的边角）。
    ms = media_sample(page) or {}
    if facts["gestures"] == 0:
        facts["mediaUnmutedBeforeInteraction"] = max(
            facts["mediaUnmutedBeforeInteraction"] or 0, int(ms.get("unmuted") or 0))
        facts["mediaPlaysBeforeInteraction"] = max(
            facts["mediaPlaysBeforeInteraction"] or 0, int(ms.get("playsBeforeFirst") or 0))
    if facts["reachedState"] != "end":
        facts["reachedState"] = _state(page)
    # 结束页补采一轮文案实况（覆盖"最后一轮循环之后才上屏"的结束页文案）。
    hook, states = qc_text_states(page)
    if hook:
        facts["textStatesHook"] = True
    for s in states:
        seen_texts.add(s["text"])
        if s["active"] and s["visible"]:
            visible_texts.add(s["text"])
    facts["qcTexts"] = sorted(seen_texts)
    facts["qcVisibleTexts"] = sorted(visible_texts)
    try:
        facts["endScreenVisible"] = bool(page.evaluate(
            "() => (window.__PF_QC__ && typeof window.__PF_QC__.endScreenVisible === 'function')"
            " ? !!window.__PF_QC__.endScreenVisible() : null"
        ))
    except Exception:
        facts["endScreenVisible"] = None
    return facts
