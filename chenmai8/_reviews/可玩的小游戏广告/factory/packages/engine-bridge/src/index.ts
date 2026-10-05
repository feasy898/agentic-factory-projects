// engine-bridge（M2）入口：按渠道装配 window.PF 全局、pf:* 事件、
// 退出接口路由与首交互前强制静音。TS 实现，零 npm 运行时依赖；
// 模板/打包器直接 import 源码（esbuild 打包），Node 22+ 亦可原生加载。
//
// 模板侧用法（spec §1/§2.7 规范时序）：
//   import { initBridge } from "@pf/engine-bridge";
//   const PF = initBridge({ channel: "applovin", locale: spec.i18n.defaultLocale });
//   await PF.ready;                        // 渠道就绪（pf:ready 已派发）
//   PF.setState("tutorial");               // 可选教程相位
//   PF.start();                            // → pf:start，相位 playing
//   const sfx = PF.audio.create(tapUrl);   // 首交互前自动 muted
//   PF.end(true);                          // → pf:end {win:true}
//   ctaButton.onclick = () => PF.open(landingUrl);  // → pf:cta + 渠道退出接口
//
// 边界（spec §1）：window.__PF_QC__（hint/state）属模板（M3）交付物；
// 桥暴露 phase()/setState() 供模板实现其 state() 时复用同一相位机。

import { AudioManager, MutePolicy } from "./audio.ts";
import {
  isMraidChannel,
  resolveChannel,
  routeExit,
  whenChannelReady,
} from "./channels.ts";
import { dispatchPFEvent, installFirstInteraction } from "./events.ts";
import type { BridgeOptions, ChannelId, PFGlobal, PFPhase } from "./types.ts";

export const PF_VERSION = "0.1.0";

export { CHANNEL_IDS, normalizeChannel } from "./channels.ts";
export type {
  BridgeOptions,
  ChannelId,
  PFEventName,
  PFGlobal,
  PFPhase,
} from "./types.ts";

/**
 * locale 五级解析（spec §2.4，冻结）：
 * options.locale → window.PF_LOCALE → URL ?locale= → options.defaultLocale → "en"。
 * 前三级取"非空字符串"（真值判定），任何一级拿到非空串即停；
 * 第四级实现为 `options.defaultLocale ?? "en"`——?? 只挡 nullish，
 * 空串 "" 原样返回、不回落 "en"（spec 已声明为已知边界，变更走契约流程）。
 * URL 级整体 try/catch：无 location 的环境静默跳过。
 */
function resolveLocale(options: BridgeOptions): string {
  if (options.locale) return options.locale;
  const w = window as Window & { location?: { search?: string } };
  if (typeof w.PF_LOCALE === "string" && w.PF_LOCALE !== "") return w.PF_LOCALE;
  try {
    const fromQuery = new URLSearchParams(w.location?.search ?? "").get("locale");
    if (fromQuery) return fromQuery;
  } catch {
    /* 无 location 的环境忽略 */
  }
  return options.defaultLocale ?? "en";
}

/**
 * 安装渠道平台侧音量探测（spec §2.6：仅 mraid 形渠道）。
 * 初始读 getAudioVolume()，再挂 audioVolumeChange 监听；数值字符串一律
 * Number() 归一。渠道未实现音频接口时静默忽略（不抛错不告警）。
 */
function installPlatformAudioProbe(
  channel: ChannelId,
  policy: MutePolicy,
): void {
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
 * 初始化运行时桥并挂载 window.PF；重复调用幂等（任何时刻返回同一实例，
 * 不重复安装监听）。返回前同步完成（spec §2.7 顺序，冻结）：
 * resolveChannel → new MutePolicy → new AudioManager → 组装 bridge（此刻
 * ready 仅登记）→ 挂载 window.PF → 装首交互监听 → 装 mraid 音量探测 → 返回。
 * 推论：返回后不存在"交互监听未装"的窗口；pf:ready 在就绪 promise resolve 后
 * 才异步派发；start()/end() 在 ready resolve 前调用同样有效。
 */
export function initBridge(options: BridgeOptions = {}): PFGlobal {
  const w = window as Window & { PF?: PFGlobal };
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
      // pf:cta 每次点击都派发（结算/埋点用）；渠道退出接口单次锁，仅首次外呼。
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
