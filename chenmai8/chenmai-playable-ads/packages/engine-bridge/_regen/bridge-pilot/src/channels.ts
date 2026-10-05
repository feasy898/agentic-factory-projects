// 渠道识别、就绪等待与退出路由（SPEC §2.3–§2.5）。

import type { ChannelId, ExitRoute, MraidFormChannel } from "./types.ts";

export const MRAID_FORM_CHANNELS: readonly MraidFormChannel[] = [
  "applovin",
  "unity",
  "mintegral",
];

const EXPLICIT_CHANNEL_IDS: readonly string[] = [
  "applovin",
  "unity",
  "mintegral",
  "meta",
  "google",
  "tiktok",
  "preview",
];

export function isMraidForm(channel: ChannelId): channel is MraidFormChannel {
  return (MRAID_FORM_CHANNELS as readonly string[]).includes(channel);
}

/**
 * pangle 归一为 tiktok（同协议）；其余合法 id 原样返回；
 * 未知 id 返回 null（调用方落 preview）。
 */
export function normalizeChannel(raw: string): ChannelId | null {
  if ((EXPLICIT_CHANNEL_IDS as readonly string[]).includes(raw)) {
    return raw as ChannelId;
  }
  if (raw === "pangle") return "tiktok";
  return null;
}

/**
 * 渠道识别（优先级从高到低）：
 * 显式传入 → window.PF_CHANNEL → 全局探测（FbPlayableAd → ExitApi →
 * openAppStore 函数 → mraid）→ 兜底 preview。非法显式 id 直接落 preview。
 */
export function detectChannel(explicit?: string): ChannelId {
  if (typeof explicit === "string" && explicit.length > 0) {
    return normalizeChannel(explicit) ?? "preview";
  }
  if (typeof window.PF_CHANNEL === "string" && window.PF_CHANNEL.length > 0) {
    return normalizeChannel(window.PF_CHANNEL) ?? "preview";
  }
  if (window.FbPlayableAd) return "meta";
  if (window.ExitApi) return "google";
  if (typeof window.openAppStore === "function") return "tiktok";
  if (window.mraid) return "applovin"; // mraid 形三渠道无法区分，按 applovin 路由
  return "preview";
}

/** 非 mraid 形渠道的运行时全局是否就位（缺失时按预览模式立即放行）。 */
function probeGlobalPresent(channel: ChannelId): boolean {
  switch (channel) {
    case "meta":
      return !!window.FbPlayableAd;
    case "google":
      return !!window.ExitApi;
    case "tiktok":
      return typeof window.openAppStore === "function";
    default:
      return true; // preview 及 mraid 形不在此判断
  }
}

/** mraid 形渠道就绪等待：loading 时等 ready 事件，超时放行（告警），绝不卡死。 */
function whenMraidReady(timeoutMs: number): Promise<void> {
  return new Promise<void>((resolve) => {
    const mraid = window.mraid;
    if (!mraid || typeof mraid.getState !== "function") {
      console.warn("[PF] mraid 不存在或缺 getState —— 按预览模式立即就绪");
      resolve();
      return;
    }
    let state: string;
    try {
      state = mraid.getState();
    } catch {
      resolve(); // mraid API 抛异常 → 吞掉按就绪处理，不阻塞
      return;
    }
    if (state !== "loading") {
      resolve();
      return;
    }

    let settled = false;
    const finish = (): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      removeReadyListener();
      resolve();
    };
    const onReady = (): void => finish();
    const removeReadyListener = (): void => {
      if (typeof mraid.removeEventListener === "function") {
        try {
          mraid.removeEventListener("ready", onReady);
        } catch {
          /* 忽略 */
        }
      }
    };
    const timer = setTimeout(() => {
      console.warn("[PF] mraid ready 等待超时 —— 放行，不卡死游戏加载");
      finish();
    }, timeoutMs);
    if (typeof mraid.addEventListener === "function") {
      try {
        mraid.addEventListener("ready", onReady);
      } catch {
        finish(); // addEventListener 抛异常 → 按就绪处理
      }
    }
    // 无 addEventListener 时只能等超时兜底
  });
}

/** 非 mraid 形渠道：全局缺失 → 立即放行（warn）；存在 → 立即。 */
function whenGlobalReady(channel: ChannelId): Promise<void> {
  if (!probeGlobalPresent(channel)) {
    console.warn(
      `[PF] 渠道 ${channel} 的运行时全局缺失 —— 按预览模式立即就绪`,
    );
  }
  return Promise.resolve();
}

/** 就绪等待（预览立即；mraid 形等 ready/超时；其余看全局是否就位）。 */
export function whenChannelReady(
  channel: ChannelId,
  timeoutMs: number,
): Promise<void> {
  if (channel === "preview") return Promise.resolve();
  if (isMraidForm(channel)) return whenMraidReady(timeoutMs);
  return whenGlobalReady(channel);
}

/** 解析退出路由（不执行）：目标接口缺失一律 window-open。 */
export function routeExit(channel: ChannelId): ExitRoute {
  if (isMraidForm(channel)) {
    if (typeof window.mraid?.open === "function") return "mraid";
  } else if (channel === "meta") {
    if (typeof window.FbPlayableAd?.onComplete === "function") return "meta";
  } else if (channel === "google") {
    if (typeof window.ExitApi?.exit === "function") return "google";
  } else if (channel === "tiktok") {
    if (typeof window.openAppStore === "function") return "tiktok";
  }
  return "window-open";
}

/** 执行退出外呼；调用抛错或目标缺失时回退 window.open(url)，不抛错。 */
export function performExit(channel: ChannelId, url: string): void {
  const route = routeExit(channel);
  if (route === "mraid") {
    try {
      window.mraid?.open?.(url);
      return;
    } catch {
      /* 落兜底 */
    }
  } else if (route === "meta") {
    try {
      window.FbPlayableAd?.onComplete?.();
      return;
    } catch {
      /* 落兜底 */
    }
  } else if (route === "google") {
    try {
      window.ExitApi?.exit?.();
      return;
    } catch {
      /* 落兜底 */
    }
  } else if (route === "tiktok") {
    try {
      window.openAppStore?.();
      return;
    } catch {
      /* 落兜底 */
    }
  }
  window.open(url);
}
