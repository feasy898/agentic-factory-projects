// M2 用例组 3：首交互前强制静音（契约核心）。
// 断言：初始化即 muted；经音频管理器创建的 <audio> muted=true、AudioContext
// suspended；首个 pf:first-interaction 后解除；平台侧 mraid 音量为 0 时
// 覆盖用户交互保持静音，直到平台放开。

import test from "node:test";
import assert from "node:assert/strict";

import { initBridge } from "../src/index.ts";
import {
  collectEvents,
  fireInteraction,
  installFakeAudioContext,
  makeDom,
  makeStub,
} from "../testsupport/fixture.mjs";

function setup(channel = "applovin", { ready = true } = {}) {
  makeDom();
  const stub = makeStub(channel);
  if (ready && stub.__setReady) stub.__setReady();
  const seen = collectEvents();
  return { stub, seen, PF: initBridge({ channel }) };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test("初始化即静音：PF.isMuted() === true", () => {
  const { PF } = setup();
  assert.equal(PF.isMuted(), true);
});

test("首交互前的音频被强制 muted；交互后自动解除（已建与新建都解除）", () => {
  const { seen, PF } = setup();
  const pre = PF.audio.create("https://assets.example/tap.ogg");
  assert.equal(pre.muted, true, "首交互前创建的音频 muted=true");
  assert.equal(pre.tagName, "AUDIO");

  fireInteraction("pointerdown");

  const firstEvent = seen.find((e) => e.name === "pf:first-interaction");
  assert.ok(firstEvent, "pf:first-interaction 已派发");
  assert.equal(PF.isMuted(), false);
  assert.equal(pre.muted, false, "已创建的音频解除静音");

  const post = PF.audio.create("https://assets.example/win.ogg");
  assert.equal(post.muted, false, "交互后新建音频不再强制静音");
});

test("AudioContext 在首交互前 suspended，交互后 resume", async () => {
  makeDom();
  const instances = installFakeAudioContext();
  makeStub("applovin").__setReady();
  const PF = initBridge({ channel: "applovin" });

  const ctx = PF.audio.getContext();
  assert.ok(ctx, "jsdom 注入替身后应能创建 AudioContext");
  assert.equal(instances.length, 1);
  await tick();
  assert.equal(ctx.state, "suspended", "静音期创建的 context 应被 suspend");

  fireInteraction("pointerdown");
  await tick();
  assert.equal(ctx.state, "running", "首交互后 resume");

  assert.equal(PF.audio.getContext(), ctx, "getContext 单例");
});

test("无 AudioContext 的环境 getContext() 返回 null（不抛错）", () => {
  const { PF } = setup();
  assert.equal(window.AudioContext, undefined);
  assert.equal(PF.audio.getContext(), null);
});

test("平台侧 mraid 音量为 0：交互后仍静音，平台放开后解除，归零再静音", () => {
  makeDom();
  const stub = makeStub("applovin");
  stub.__volume = 0; // 平台静音
  stub.__setReady();
  const PF = initBridge({ channel: "applovin" });

  const clip = PF.audio.create("https://assets.example/tap.ogg");
  assert.equal(PF.isMuted(), true);

  fireInteraction("pointerdown");
  assert.equal(PF.isMuted(), true, "平台静音覆盖用户交互");
  assert.equal(clip.muted, true);

  stub.__volume = 0.8;
  stub.__fire("audioVolumeChange", 0.8);
  assert.equal(PF.isMuted(), false, "平台放开音量后解除");
  assert.equal(clip.muted, false, "音频元素同步解除");

  stub.__fire("audioVolumeChange", 0);
  assert.equal(PF.isMuted(), true, "平台再归零则再静音");
  assert.equal(clip.muted, true);
});

test("mraid 形渠道缺音频接口（无 getAudioVolume）时正常初始化", () => {
  makeDom();
  const stub = makeStub("applovin");
  delete stub.getAudioVolume;
  delete stub.addEventListener;
  stub.__setReady();
  const PF = initBridge({ channel: "applovin" });
  assert.equal(PF.isMuted(), true);
  fireInteraction("pointerdown");
  assert.equal(PF.isMuted(), false);
});

test("环境缺 Audio 构造器：create 抛出明确错误", () => {
  const { PF } = setup();
  const hadAudio = window.Audio;
  delete window.Audio;
  assert.throws(() => PF.audio.create("https://assets.example/x.ogg"), /Audio/);
  window.Audio = hadAudio;
});

test("静音策略与事件解耦：交互解除静音的同时只发一个 first-interaction", () => {
  const { seen, PF } = setup();
  PF.audio.create("https://assets.example/a.ogg");
  fireInteraction("mousedown");
  fireInteraction("mousedown");
  const interactions = seen.filter((e) => e.name === "pf:first-interaction");
  assert.equal(interactions.length, 1);
  assert.equal(PF.isMuted(), false);
});
