/**
 * 探针契约（qacore spec §4）：页面装载前注入的 PROBE_JS。
 * oracle 仓库 python/qacore/autoplay.py 的 PROBE_JS 字符串**逐字照抄**（探针是
 * 冻结契约——改一个字符都可能让 MUT 判定漂移），仅宿主从 playwright-python
 * add_init_script 换成 playwright-node 同名 API（每页面注入一次，勿重复包装）。
 */
export const PROBE_JS = String.raw`(() => {
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
`;
