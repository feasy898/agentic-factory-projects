// M2 用例组 2：5 个 pf:* 事件的存在、顺序、detail 与冒泡语义。
// 契约（§4.2）：事件为 DOM CustomEvent，冒泡到 document；
//   pf:ready / pf:start / pf:first-interaction / pf:end {win} / pf:cta。

import test from "node:test";
import assert from "node:assert/strict";

import { initBridge } from "../src/index.ts";
import {
  LANDING_URL,
  collectEvents,
  fireInteraction,
  makeDom,
  makeStub,
} from "../testsupport/fixture.mjs";

function setup(channel = "applovin") {
  makeDom();
  const stub = makeStub(channel);
  if (stub.__setReady) stub.__setReady();
  return { stub, seen: collectEvents() };
}

test("事件序：ready → start → end，phase 相位机同步推进", async () => {
  const { seen } = setup();
  const PF = initBridge({ channel: "applovin" });

  assert.equal(PF.phase(), "loading");
  await PF.ready;
  assert.equal(PF.phase(), "loading", "pf:ready 不改变相位（loading 由模板推进）");

  PF.setState("tutorial");
  assert.equal(PF.phase(), "tutorial");
  PF.start();
  assert.equal(PF.phase(), "playing");
  PF.end(true);
  assert.equal(PF.phase(), "end");

  assert.deepEqual(
    seen.map((e) => e.name),
    ["pf:ready", "pf:start", "pf:end"],
  );
});

test("pf:end detail 为 {win: boolean}，false 亦然", async () => {
  const { seen } = setup();
  const PF = initBridge({ channel: "meta" });
  await PF.ready;
  PF.end(false);
  const endEvent = seen.find((e) => e.name === "pf:end");
  assert.deepEqual(endEvent.detail, { win: false });
});

test("事件冒泡到 document（bubbles=true，CustomEvent 实例）", async () => {
  const { seen } = setup();
  const PF = initBridge({ channel: "google" });
  await PF.ready;
  PF.start();
  const startEvent = seen.find((e) => e.name === "pf:start");
  assert.equal(startEvent.event.constructor.name, "CustomEvent");
  assert.equal(startEvent.bubbles, true);
});

test("pf:first-interaction 只派发一次，detail.type 记录事件类型", () => {
  const { seen } = setup();
  const PF = initBridge({ channel: "applovin" });

  fireInteraction("pointerdown");
  fireInteraction("pointerdown");
  fireInteraction("touchstart");

  const interactions = seen.filter((e) => e.name === "pf:first-interaction");
  assert.equal(interactions.length, 1);
  assert.deepEqual(interactions[0].detail, { type: "pointerdown" });
  assert.equal(PF.isMuted(), false);
});

test("四类交互事件（pointerdown/touchstart/mousedown/keydown）都算首交互", () => {
  for (const type of ["pointerdown", "touchstart", "mousedown", "keydown"]) {
    const { seen } = setup();
    initBridge({ channel: "applovin" });
    fireInteraction(type);
    const interactions = seen.filter((e) => e.name === "pf:first-interaction");
    assert.equal(interactions.length, 1, `${type}: 恰好一次`);
    assert.deepEqual(interactions[0].detail, { type }, `${type}: detail.type`);
  }
});

test("pf:cta 携带 {url} detail，且先于退出接口调用", async () => {
  const { stub, seen } = setup("applovin");
  const PF = initBridge({ channel: "applovin" });
  await PF.ready;

  const order = [];
  document.addEventListener("pf:cta", (ev) => order.push(`pf:cta:${ev.detail.url}`));
  const rawOpen = stub.open.bind(stub);
  stub.open = (url) => {
    order.push("mraid.open");
    rawOpen(url);
  };
  PF.open(LANDING_URL);

  assert.deepEqual(order, [`pf:cta:${LANDING_URL}`, "mraid.open"]);
  const cta = seen.find((e) => e.name === "pf:cta");
  assert.deepEqual(cta.detail, { url: LANDING_URL });
});

test("典型可玩广告生命周期事件序：ready → start → first-interaction → cta → end", async () => {
  const { seen } = setup();
  const PF = initBridge({ channel: "applovin" });
  await PF.ready;
  PF.start();
  fireInteraction("pointerdown");
  PF.open(LANDING_URL);
  PF.end(true);

  assert.deepEqual(seen.map((e) => e.name), [
    "pf:ready",
    "pf:start",
    "pf:first-interaction",
    "pf:cta",
    "pf:end",
  ]);
});
