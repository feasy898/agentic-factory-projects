// M2 用例组 1：6 渠道的就绪（ready → pf:ready）与退出路由（open → 对应接口）。
// 对应自验收三项断言中的前两项：
//   - ready → 事件序（pf:ready 时机正确：mraid ready 之后才派发）
//   - open  → 对应接口记录（mraid.open / FbPlayableAd.onComplete /
//              ExitApi.exit / openAppStore，applovin/unity/mintegral 走 mraid.open）

import test from "node:test";
import assert from "node:assert/strict";

import { initBridge } from "../src/index.ts";
import {
  ALL_CHANNELS,
  LANDING_URL,
  collectEvents,
  fireInteraction,
  makeDom,
  makeStub,
  spyWindowOpen,
} from "../testsupport/fixture.mjs";

const MRAID_CHANNELS = ["applovin", "unity", "mintegral"];
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function setup(channel, { ready = true } = {}) {
  makeDom();
  const stub = makeStub(channel);
  if (ready && MRAID_CHANNELS.includes(channel)) stub.__setReady();
  const seen = collectEvents();
  return { stub, seen };
}

test("6 渠道各自：就绪后 pf:ready，PF.open 调用对应退出接口一次", async () => {
  for (const channel of ALL_CHANNELS) {
    const { stub, seen } = setup(channel);
    const PF = initBridge({ channel });
    await PF.ready;

    assert.equal(PF.channel, channel, `${channel}: channel 字段`);
    assert.ok(
      seen.some((e) => e.name === "pf:ready"),
      `${channel}: pf:ready 应已派发`,
    );

    PF.open(LANDING_URL);
    if (MRAID_CHANNELS.includes(channel)) {
      assert.deepEqual(
        stub.__calls.open,
        [LANDING_URL],
        `${channel}: mraid.open 应收到 landingUrl`,
      );
    } else if (channel === "meta") {
      assert.equal(stub.__calls.onComplete, 1, `${channel}: onComplete 次数`);
    } else if (channel === "google") {
      assert.equal(stub.__calls.exit, 1, `${channel}: ExitApi.exit 次数`);
    } else if (channel === "tiktok") {
      assert.equal(stub.__calls.openAppStore, 1, `${channel}: openAppStore 次数`);
    }
  }
});

test("mraid 形渠道：getState=loading 时 pf:ready 推迟到 mraid ready 事件之后", async () => {
  for (const channel of MRAID_CHANNELS) {
    const { stub, seen } = setup(channel, { ready: false });
    const PF = initBridge({ channel });
    await tick();
    assert.ok(
      !seen.some((e) => e.name === "pf:ready"),
      `${channel}: loading 期不应派发 pf:ready`,
    );
    stub.__setReady();
    await PF.ready;
    assert.ok(seen.some((e) => e.name === "pf:ready"), `${channel}: ready 后应派发`);
  }
});

test("mraid 形渠道：就绪等待超时也放行（不卡死加载）", async () => {
  makeDom();
  const stub = makeStub("applovin");
  stub.__state = "loading";
  const PF = initBridge({ channel: "applovin", readyTimeoutMs: 30 });
  const startedAt = Date.now();
  await PF.ready;
  assert.ok(Date.now() - startedAt < 5000, "超时兜底应远小于 5s");
  assert.ok(true, "PF.ready 已 resolve");
});

test("mraid getState 抛错时按就绪处理（不阻塞）", async () => {
  makeDom();
  const stub = makeStub("applovin");
  stub.getState = () => {
    throw new Error("stub boom");
  };
  const seen = collectEvents(["pf:ready"]);
  const PF = initBridge({ channel: "applovin" });
  await PF.ready;
  assert.ok(seen.some((e) => e.name === "pf:ready"));
});

test("pf:cta 先于渠道退出接口（同步序），且每次点击都派发、外呼仅一次", async () => {
  const { stub, seen } = setup("applovin");
  const PF = initBridge({ channel: "applovin" });
  await PF.ready;

  const order = [];
  document.addEventListener("pf:cta", () => order.push("pf:cta"));
  const rawOpen = stub.open.bind(stub);
  stub.open = (url) => {
    order.push("mraid.open");
    rawOpen(url);
  };

  PF.open(LANDING_URL);
  PF.open(LANDING_URL);

  assert.deepEqual(
    order,
    ["pf:cta", "mraid.open", "pf:cta"],
    "每次点击都先派发 cta；接口只在首次真正外呼",
  );
  assert.equal(stub.__calls.open.length, 1, "mraid.open 只真正外呼一次");
  const ctaEvents = seen.filter((e) => e.name === "pf:cta");
  assert.equal(ctaEvents.length, 2, "pf:cta 每次点击都派发");
  assert.deepEqual(ctaEvents[0].detail, { url: LANDING_URL });
});

test("渠道 stub 缺失时回退 window.open(url)（预览/QC 兜底）", async () => {
  for (const channel of ALL_CHANNELS) {
    makeDom();
    const opened = spyWindowOpen();
    const PF = initBridge({ channel });
    PF.open(LANDING_URL);
    assert.deepEqual(opened, [LANDING_URL], `${channel}: 回退 window.open`);
  }
});

test("pangle 与 tiktok 同协议，归一到 tiktok 路由", async () => {
  const { stub } = setup("tiktok");
  const PF = initBridge({ channel: "pangle" });
  assert.equal(PF.channel, "tiktok");
  PF.open(LANDING_URL);
  assert.equal(stub.__calls.openAppStore, 1);
});

test("渠道识别：PF_CHANNEL 注入 > 全局探测 > preview", () => {
  makeDom();
  window.PF_CHANNEL = "google";
  makeStub("google");
  assert.equal(initBridge({}).channel, "google");

  makeDom();
  window.PF_CHANNEL = "unknown-thing";
  assert.equal(initBridge({}).channel, "preview");

  makeDom();
  makeStub("meta");
  assert.equal(initBridge({}).channel, "meta", "探测 FbPlayableAd");

  makeDom();
  makeStub("applovin").__setReady();
  assert.equal(initBridge({}).channel, "applovin", "探测 mraid（默认归 applovin）");

  makeDom();
  assert.equal(initBridge({}).channel, "preview", "无任何全局 → preview");
});

test("initBridge 幂等：重复调用返回同一 window.PF", () => {
  makeDom();
  makeStub("applovin").__setReady();
  const first = initBridge({ channel: "applovin" });
  const second = initBridge({ channel: "meta" });
  assert.equal(first, second);
  assert.equal(window.PF, first);
});

test("locale 解析：显式 > PF_LOCALE > URL ?locale= > defaultLocale > en", () => {
  makeDom(); // 默认 url 带 ?locale=ja
  makeStub("applovin").__setReady();
  assert.equal(initBridge({ locale: "pt-BR" }).locale, "pt-BR");
  assert.equal(initBridge({}).locale, "pt-BR", "幂等返回已有实例");

  makeDom();
  window.PF_LOCALE = "ko";
  makeStub("applovin").__setReady();
  assert.equal(initBridge({}).locale, "ko", "PF_LOCALE 优先于 query");

  makeDom();
  makeStub("applovin").__setReady();
  assert.equal(initBridge({}).locale, "ja", "URL query");

  makeDom({ url: "https://ad.example/pf.html" });
  makeStub("applovin").__setReady();
  assert.equal(initBridge({ defaultLocale: "de" }).locale, "de");

  makeDom({ url: "https://ad.example/pf.html" });
  makeStub("applovin").__setReady();
  assert.equal(initBridge({}).locale, "en");
});

test("首交互与退出都允许发生在 pf:ready 之前（不阻塞玩家操作）", async () => {
  const { stub, seen } = setup("applovin", { ready: false });
  const PF = initBridge({ channel: "applovin" });

  fireInteraction("pointerdown");
  PF.open(LANDING_URL);

  assert.equal(stub.__calls.open.length, 1, "就绪前 open 依然路由退出接口");
  assert.equal(PF.isMuted(), false, "就绪前交互即解除静音");
  assert.ok(
    seen.some((e) => e.name === "pf:first-interaction"),
    "首交互事件已派发",
  );

  stub.__setReady();
  await PF.ready;
  const names = seen.map((e) => e.name);
  assert.ok(
    names.indexOf("pf:first-interaction") < names.indexOf("pf:ready"),
    "事件序：first-interaction → ready",
  );
});
