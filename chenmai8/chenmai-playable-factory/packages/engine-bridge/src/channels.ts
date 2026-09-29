// 渠道识别、就绪等待与退出路由（spec §2.3 / §2.5，frozen）。
//
// 对渠道 SDK 只按全局对象探测协议形，零 npm 运行时依赖。退出接口基线
// 与 channel-rules（rulesVersion 1.1.0）一致：
//   applovin / unity / mintegral → mraid.open(url)
//   meta            → FbPlayableAd.onComplete()
//   google          → ExitApi.exit()
//   tiktok（含 pangle） → window.openAppStore()
//   preview / 目标接口缺失 → window.open(url)（本地预览/QC 可观察兜底）

import type {
  ChannelId,
  GoogleExitLike,
  MetaPlayableLike,
  MraidLike,
} from "./types.ts";

/** 6 个投放渠道 id（不含 preview）。 */
export const CHANNEL_IDS = [
  "applovin",
  "meta",
  "google",
  "unity",
  "tiktok",
  "mintegral",
] as const;

/** pangle 与 tiktok 同协议归一；合法 id 原样；其余返回 null。 */
export function normalizeChannel(raw: string): ChannelId | null {
  if (raw === "pangle") return "tiktok";
  if ((CHANNEL_IDS as readonly string[]).includes(raw)) return raw as ChannelId;
  return null;
}

/** 使用 mraid 形协议的渠道（就绪等待与平台音量探测都走 mraid）。 */
export function isMraidChannel(channel: ChannelId): boolean {
  return channel === "applovin" || channel === "unity" || channel === "mintegral";
}

/**
 * 渠道解析（spec §2.3 优先级）：显式 id > 打包器注入的 PF_CHANNEL >
 * 全局探测（meta → google → tiktok → mraid 形）> preview。
 * mraid 形三渠道协议上无法区分，探测到时按 applovin 路由（退出调用一致）。
 */
export function resolveChannel(explicit?: ChannelId): ChannelId {
  if (explicit) return normalizeChannel(explicit) ?? "preview";
  const w = window;
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
 * 渠道就绪等待（spec §2.5；默认超时 readyTimeoutMs = 8000ms）。
 * - mraid 形：无 mraid 或无 getState → 立即放行（console.warn 预览模式）；
 *   getState() 抛异常 → 静默按就绪；state !== "loading" → 立即；
 *   否则等 mraid "ready" 事件，超时静默放行——绝不卡死游戏加载。
 * - 非 mraid 形：对应全局缺失 → 立即放行（console.warn 预览模式）；存在 → 立即。
 *
 * 告警文案冻结（spec §2.8，恰两处）；除这两处外一切失败路径静默兜底。
 */
export function whenChannelReady(
  channel: ChannelId,
  readyTimeoutMs = 8000,
): Promise<void> {
  const w = window;
  if (isMraidChannel(channel)) {
    const mraid: MraidLike | undefined = w.mraid;
    if (!mraid || typeof mraid.getState !== "function") {
      console.warn(
        `[PF] channel=${channel}: 未检测到 mraid 全局，按就绪处理（预览模式）`,
      );
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
      const finish = (): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        try {
          mraid.removeEventListener?.("ready", finish);
        } catch {
          /* 渠道实现不完整时忽略（spec §3） */
        }
        resolve();
      };
      const timer = setTimeout(finish, readyTimeoutMs);
      try {
        mraid.addEventListener?.("ready", finish);
      } catch {
        /* 渠道实现不完整时忽略 */
      }
    });
  }
  const present =
    (channel === "meta" && w.FbPlayableAd) ||
    (channel === "google" && w.ExitApi) ||
    (channel === "tiktok" && typeof w.openAppStore === "function") ||
    channel === "preview";
  if (!present) {
    console.warn(
      `[PF] channel=${channel}: 未检测到渠道运行时全局对象，按就绪处理（预览模式）`,
    );
  }
  return Promise.resolve();
}

export type ExitRoute = "mraid" | "meta" | "google" | "tiktok" | "window-open";

/**
 * 退出路由（spec §2.5 表）：按渠道路由一次外呼。
 * mraid 形三渠道走 mraid.open(url)；目标接口缺失一律回退 window.open(url)
 * （不抛错，QC/预览环境 CTA 行为可观察）。
 */
export function routeExit(channel: ChannelId, url: string): ExitRoute {
  const w = window;
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
