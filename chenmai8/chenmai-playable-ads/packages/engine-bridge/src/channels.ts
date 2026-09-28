// 渠道识别、就绪等待与退出接口路由（自研实现，渠道 SDK 仅按全局对象探测，
// 不做任何 npm 运行时依赖）。6 渠道退出接口基线与 channel-rules 一致：
//   applovin / unity / mintegral → mraid.open(url)
//   meta            → FbPlayableAd.onComplete()
//   google          → ExitApi.exit()
//   tiktok(pangle)  → window.openAppStore()
//   preview         → window.open(url)（本地预览/QC 兜底）

import type {
  ChannelId,
  GoogleExitLike,
  MetaPlayableLike,
  MraidLike,
} from "./types.ts";

export const CHANNEL_IDS = [
  "applovin",
  "meta",
  "google",
  "unity",
  "tiktok",
  "mintegral",
] as const;

/** tiktok 与 pangle 同协议，统一归一到 "tiktok"。 */
export function normalizeChannel(raw: string): ChannelId | null {
  if (raw === "pangle") return "tiktok";
  if ((CHANNEL_IDS as readonly string[]).includes(raw)) return raw as ChannelId;
  return null;
}

/** 使用 mraid 形协议的渠道（就绪等待与音频音量探测走 mraid）。 */
export function isMraidChannel(channel: ChannelId): boolean {
  return channel === "applovin" || channel === "unity" || channel === "mintegral";
}

function globals(): Window {
  return window;
}

/**
 * 渠道探测：显式 id 优先，其次打包器注入的 PF_CHANNEL，最后按全局对象探测。
 * mraid 形全局无法区分 applovin/unity/mintegral，探测到时按 applovin 路由
 * （三者退出调用一致）；什么都没有 → "preview"（本地预览/QC）。
 */
export function resolveChannel(explicit?: ChannelId): ChannelId {
  if (explicit) return normalizeChannel(explicit) ?? "preview";
  const w = globals();
  const injected = w.PF_CHANNEL;
  if (typeof injected === "string" && injected !== "") {
    const normalized = normalizeChannel(injected);
    if (normalized) return normalized;
  }
  if (w.FbPlayableAd) return "meta";
  if (w.ExitApi) return "google";
  if (typeof w.openAppStore === "function") return "tiktok";
  if (w.mraid) return "applovin";
  return "preview";
}

/**
 * 等待渠道就绪（pf:ready 之前）：
 * - mraid 形渠道：getState()==="loading" 时等 mraid 的 ready 事件；
 *   超过 readyTimeoutMs 放行（告警），绝不卡死游戏加载。
 * - 其余渠道：存在对应全局即就绪；缺失时也放行（预览/QC 环境），仅告警。
 */
export function whenChannelReady(channel: ChannelId, readyTimeoutMs = 8000): Promise<void> {
  const w = globals();
  if (isMraidChannel(channel)) {
    const mraid: MraidLike | undefined = w.mraid;
    if (!mraid || typeof mraid.getState !== "function") {
      console.warn(`[PF] channel=${channel}: 未检测到 mraid 全局，按就绪处理（预览模式）`);
      return Promise.resolve();
    }
    let state: string;
    try {
      state = mraid.getState();
    } catch {
      return Promise.resolve();
    }
    if (state !== "loading") return Promise.resolve();
    return new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        try {
          mraid.removeEventListener?.("ready", finish);
        } catch {
          /* 渠道实现不完整时忽略 */
        }
        resolve();
      };
      const timer = setTimeout(finish, readyTimeoutMs);
      mraid.addEventListener?.("ready", finish);
    });
  }
  const present =
    (channel === "meta" && w.FbPlayableAd) ||
    (channel === "google" && w.ExitApi) ||
    (channel === "tiktok" && typeof w.openAppStore === "function") ||
    channel === "preview";
  if (!present) {
    console.warn(`[PF] channel=${channel}: 未检测到渠道运行时全局对象，按就绪处理（预览模式）`);
  }
  return Promise.resolve();
}

export type ExitRoute = "mraid" | "meta" | "google" | "tiktok" | "window-open";

/**
 * 按渠道路由一次退出调用。目标接口缺失时回退 window.open(url)，
 * 保证预览/QC 环境下 CTA 行为可观察、不抛错。
 */
export function routeExit(channel: ChannelId, url: string): ExitRoute {
  const w = globals();
  const mraid = w.mraid as (MraidLike & { open?: (u: string) => void }) | undefined;
  const meta = w.FbPlayableAd as MetaPlayableLike | undefined;
  const google = w.ExitApi as GoogleExitLike | undefined;

  if (isMraidChannel(channel) && typeof mraid?.open === "function") {
    mraid.open(url);
    return "mraid";
  }
  if (channel === "meta" && typeof meta?.onComplete === "function") {
    meta.onComplete();
    return "meta";
  }
  if (channel === "google" && typeof google?.exit === "function") {
    google.exit();
    return "google";
  }
  if (channel === "tiktok" && typeof w.openAppStore === "function") {
    w.openAppStore();
    return "tiktok";
  }
  w.open(url);
  return "window-open";
}
