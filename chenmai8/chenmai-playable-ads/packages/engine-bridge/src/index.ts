// engine-bridge（M2）入口：按渠道装配 window.PF 全局、pf:* 事件、
// 退出接口路由与首交互前强制静音。TS 实现，零 npm 运行时依赖；
// 模板/打包器直接 import 源码（esbuild 打包），Node 22+ 亦可原生加载。
//
// 用法（模板侧）：
//   import { initBridge } from "@pf/engine-bridge";
//   const PF = initBridge({ channel: "applovin", locale: spec.i18n.defaultLocale });
//   await PF.ready;                 // 渠道就绪（pf:ready 已派发）
//   PF.start();                     // → pf:start
//   const sfx = PF.audio.create(tapUrl);   // 首交互前自动 muted
//   PF.end(true);                   // → pf:end {win:true}
//   CTA 按钮 onclick = () => PF.open(landingUrl);  // → pf:cta + 渠道退出接口
//
// 说明：window.__PF_QC__（hint/state）属模板（M3）交付物；桥暴露 phase()/setState()
// 供模板实现其 state() 时复用同一相位机。

import { AudioManager, MutePolicy } from "./audio.ts";
import {
  isMraidChannel,
  resolveChannel,
  routeExit,
  whenChannelReady,
} from "./channels.ts";
import { dispatchPFEvent, installFirstInteraction } from "./events.ts";
import type { BridgeOptions, PFGlobal, PFPhase } from "./types.ts";

export const PF_VERSION = "0.1.0";

export { CHANNEL_IDS, normalizeChannel } from "./channels.ts";
export type {
  BridgeOptions,
  ChannelId,
  PFEventName,
  PFGlobal,
  PFPhase,
} from "./types.ts";

function resolveLocale(options: BridgeOptions): string {
  if (options.locale) return options.locale;
  const w = window as { PF_LOCALE?: string; location?: { search?: string } };
  if (typeof w.PF_LOCALE === "string" && w.PF_LOCALE !== "") return w.PF_LOCALE;
  try {
    const fromQuery = new URLSearchParams(w.location?.search ?? "").get("locale");
    if (fromQuery) return fromQuery;
  } catch {
    /* 无 location 的环境忽略 */
  }
  return options.defaultLocale ?? "en";
}

/** 安装渠道平台侧音量探测（仅 mraid 形渠道）：平台音量为 0 时强制静音。 */
function installPlatformAudioProbe(channel: PFGlobal["channel"], policy: MutePolicy): void {
  if (!isMraidChannel(channel)) return;
  const mraid = window.mraid;
  if (!mraid) return;
  try {
    if (typeof mraid.getAudioVolume === "function") {
      policy.setPlatformVolume(mraid.getAudioVolume());
    }
    mraid.addEventListener?.("audioVolumeChange", (volume) => {
      policy.setPlatformVolume(typeof volume === "number" ? volume : Number(volume));
    });
  } catch {
    /* 渠道未实现音频接口时忽略 */
  }
}

/**
 * 初始化运行时桥并挂载 window.PF；重复调用幂等（返回已有实例）。
 * pf:ready 在渠道就绪后派发；首交互监听与平台音量探测在挂载时同步安装。
 */
export function initBridge(options: BridgeOptions = {}): PFGlobal {
  const w = window as unknown as { PF?: PFGlobal };
  if (w.PF) return w.PF;

  const channel = resolveChannel(options.channel);
  const policy = new MutePolicy();
  const audio = new AudioManager(policy);
  let phase: PFPhase = "loading";
  let exitCalled = false;

  const bridge: PFGlobal = {
    channel,
    locale: resolveLocale(options),
    version: PF_VERSION,
    ready: whenChannelReady(channel, options.readyTimeoutMs).then(() => {
      dispatchPFEvent("pf:ready");
    }),
    isMuted: () => policy.isMuted(),
    phase: () => phase,
    setState: (next) => {
      phase = next;
    },
    open: (url: string) => {
      // pf:cta 每次点击都派发（结算/埋点用）；渠道退出接口只真正外呼一次。
      dispatchPFEvent("pf:cta", { url });
      if (exitCalled) return;
      exitCalled = true;
      routeExit(channel, url);
    },
    start: () => {
      phase = "playing";
      dispatchPFEvent("pf:start");
    },
    end: (win: boolean) => {
      phase = "end";
      dispatchPFEvent("pf:end", { win });
    },
    audio,
  };

  w.PF = bridge;
  installFirstInteraction((type) => {
    if (policy.markInteraction()) dispatchPFEvent("pf:first-interaction", { type });
  });
  installPlatformAudioProbe(channel, policy);
  return bridge;
}
