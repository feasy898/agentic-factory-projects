// M2 测试夹具：每个用例一份独立 jsdom + 渠道 stub，注入 Node 全局。
// 放在 testsupport/（而非 test/）以免被 `node --test` 当作用例文件收集。
//
// 渠道 stub 与真实渠道运行时的对接面一致（全局对象 + 方法签名），
// 由打包器按 channel-rules 注入；这里手工注入以便断言"open → 对应接口"。

import { JSDOM } from "jsdom";

export const LANDING_URL = "https://landing.example.com/app?src=pf";

export const PF_EVENT_NAMES = [
  "pf:ready",
  "pf:start",
  "pf:first-interaction",
  "pf:end",
  "pf:cta",
];

export const ALL_CHANNELS = [
  "applovin",
  "unity",
  "mintegral",
  "meta",
  "google",
  "tiktok",
];

const MRAID_CHANNELS = new Set(["applovin", "unity", "mintegral"]);

/** 新建独立 DOM 并注入 Node 全局（window/document/CustomEvent/Event）。 */
export function makeDom({ url = "https://ad.example/pf.html?locale=ja" } = {}) {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", { url });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.CustomEvent = dom.window.CustomEvent;
  globalThis.Event = dom.window.Event;
  return dom;
}

/**
 * 注入渠道 stub 并返回记录器：
 * - mraid 形（applovin/unity/mintegral）：`stub.__calls.open` 数组；
 *   `stub.__setReady()` 模拟 mraid ready；`stub.__fire("audioVolumeChange", v)`。
 * - meta：`stub.__calls.onComplete` 计数。
 * - google：`stub.__calls.exit` 计数。
 * - tiktok：`stub.__calls.openAppStore` 计数。
 */
export function makeStub(channel) {
  if (MRAID_CHANNELS.has(channel)) {
    const listeners = new Map();
    const stub = {
      __calls: { open: [] },
      __state: "loading",
      __volume: 1,
      getState() {
        return stub.__state;
      },
      open(url) {
        stub.__calls.open.push(url);
      },
      getAudioVolume() {
        return stub.__volume;
      },
      addEventListener(name, cb) {
        if (!listeners.has(name)) listeners.set(name, []);
        listeners.get(name).push(cb);
      },
      removeEventListener(name, cb) {
        listeners.set(name, (listeners.get(name) ?? []).filter((f) => f !== cb));
      },
      __fire(name, ...args) {
        for (const cb of listeners.get(name) ?? []) cb(...args);
      },
      __setReady() {
        stub.__state = "ready";
        stub.__fire("ready");
      },
    };
    window.mraid = stub;
    return stub;
  }
  if (channel === "meta") {
    const stub = { __calls: { onComplete: 0 }, onComplete() { stub.__calls.onComplete += 1; } };
    window.FbPlayableAd = stub;
    return stub;
  }
  if (channel === "google") {
    const stub = { __calls: { exit: 0 }, exit() { stub.__calls.exit += 1; } };
    window.ExitApi = stub;
    return stub;
  }
  if (channel === "tiktok") {
    const stub = { __calls: { openAppStore: 0 } };
    window.openAppStore = () => { stub.__calls.openAppStore += 1; };
    return stub;
  }
  throw new Error(`makeStub: 未知渠道 ${channel}`);
}

/** 在 document 上收集指定 pf:* 事件（含 detail 与原始事件对象）。 */
export function collectEvents(names = PF_EVENT_NAMES) {
  const seen = [];
  for (const name of names) {
    document.addEventListener(name, (ev) => {
      seen.push({ name, detail: ev.detail, bubbles: ev.bubbles, event: ev });
    });
  }
  return seen;
}

/** 记录 window.open 调用（预览/QC 兜底路径断言用），返回记录数组。 */
export function spyWindowOpen() {
  const opened = [];
  window.open = (url) => {
    opened.push(url);
    return null;
  };
  return opened;
}

/** 派发一次交互事件（默认 pointerdown）。 */
export function fireInteraction(type = "pointerdown") {
  document.dispatchEvent(new window.Event(type));
}

/** 注入可计数的 AudioContext 替身（jsdom 无 AudioContext）。 */
export function installFakeAudioContext() {
  const instances = [];
  class FakeAudioContext {
    constructor() {
      this.state = "running";
      instances.push(this);
    }
    async suspend() { this.state = "suspended"; }
    async resume() { this.state = "running"; }
  }
  window.AudioContext = FakeAudioContext;
  return instances;
}
