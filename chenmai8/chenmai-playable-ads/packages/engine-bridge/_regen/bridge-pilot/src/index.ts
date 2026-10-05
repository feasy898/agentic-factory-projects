// M2 运行时桥（engine-bridge）入口：window.PF 全局（SPEC §2.1）。
// initBridge 幂等：已有 window.PF 直接返回既有实例，不重复装监听。

import type {
  BridgeOptions,
  ChannelId,
  PFGlobal,
  PFPhase,
} from "./types.ts";
import { PF_VERSION } from "./types.ts";
import { emitPFEvent, installInteractionListeners } from "./events.ts";
import {
  MutePolicy,
  createAudioManager,
  installPlatformVolumeProbe,
} from "./audio.ts";
import {
  detectChannel,
  isMraidForm,
  performExit,
  whenChannelReady,
} from "./channels.ts";

export const DEFAULT_READY_TIMEOUT_MS = 8000;

/** locale 五级优先级：options.locale → PF_LOCALE → URL ?locale= → defaultLocale → "en"。 */
function resolveLocale(options: BridgeOptions): string {
  if (typeof options.locale === "string") return options.locale;
  if (typeof window.PF_LOCALE === "string") return window.PF_LOCALE;
  try {
    const fromQuery = new URLSearchParams(window.location.search).get("locale");
    if (fromQuery) return fromQuery;
  } catch {
    /* location 不可用时跳过该级 */
  }
  if (typeof options.defaultLocale === "string") return options.defaultLocale;
  return "en";
}

export function initBridge(options: BridgeOptions = {}): PFGlobal {
  const existing = window.PF;
  if (existing) return existing; // 幂等：不重复装监听

  const channel: ChannelId = detectChannel(options.channel);
  const locale = resolveLocale(options);
  const policy = new MutePolicy();
  const audio = createAudioManager(policy);

  let phase: PFPhase = "loading";
  let exitCalled = false; // 渠道退出外呼单次锁（与 pf:cta 的每次派发无关）

  // 首交互监听：initBridge 时即安装（早于渠道就绪），捕获阶段、once 语义。
  installInteractionListeners((type) => {
    if (policy.markInteraction()) {
      emitPFEvent("pf:first-interaction", { type });
    }
  });

  // 平台音量探测仅 mraid 形渠道安装。
  if (isMraidForm(channel)) installPlatformVolumeProbe(policy);

  const ready: Promise<void> = whenChannelReady(
    channel,
    options.readyTimeoutMs ?? DEFAULT_READY_TIMEOUT_MS,
  );
  ready.then(() => {
    emitPFEvent("pf:ready"); // 渠道就绪后恰一次；不改变相位（仍在 loading）
  });

  const PF: PFGlobal = {
    channel,
    locale,
    version: PF_VERSION,
    ready,
    isMuted: () => policy.isMuted(),
    phase: () => phase,
    setState: (p) => {
      phase = p; // 模板驱动相位（如进教程），无事件
    },
    open: (url: string) => {
      emitPFEvent("pf:cta", { url }); // 每次点击都派发，且先于退出接口（同步序）
      if (!exitCalled) {
        exitCalled = true;
        performExit(channel, url); // 渠道退出外呼仅第一次
      }
    },
    start: () => {
      phase = "playing";
      emitPFEvent("pf:start");
    },
    end: (win: boolean) => {
      phase = "end";
      emitPFEvent("pf:end", { win });
    },
    audio,
  };

  window.PF = PF;
  return PF;
}

export type {
  BridgeOptions,
  ChannelId,
  ExitRoute,
  FbPlayableAdLike,
  ExitApiLike,
  InteractionType,
  MraidFormChannel,
  MraidLike,
  PFAudioManager,
  PFEventName,
  PFGlobal,
  PFPhase,
} from "./types.ts";
export { PF_VERSION } from "./types.ts";
