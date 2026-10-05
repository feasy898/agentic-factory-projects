// 静音策略（MutePolicy）+ 音频管理器（SPEC §2.6）。
// isMuted() = !interactionSeen || platformVolume === 0：
//   首交互前强制静音；平台音量 0 时即使已交互也保持静音直到平台放开。

import type { PFAudioManager } from "./types.ts";

type MuteListener = (muted: boolean) => void;

export class MutePolicy {
  private interactionSeen = false;
  /** null = 未安装平台探测（非 mraid 形渠道）；0 = 平台静音。 */
  private platformVolume: number | null = null;
  private readonly listeners: MuteListener[] = [];

  isMuted(): boolean {
    return !this.interactionSeen || this.platformVolume === 0;
  }

  /** 仅首次生效并通知变化；返回"是否确为首次"（供事件只派发一次）。 */
  markInteraction(): boolean {
    if (this.interactionSeen) return false;
    this.interactionSeen = true;
    this.notify();
    return true;
  }

  /** 非有限数或同值忽略。 */
  setPlatformVolume(volume: number): void {
    if (!Number.isFinite(volume)) return;
    if (volume === this.platformVolume) return;
    this.platformVolume = volume;
    this.notify();
  }

  onChange(listener: MuteListener): void {
    this.listeners.push(listener);
  }

  private notify(): void {
    const muted = this.isMuted();
    for (const listener of this.listeners) listener(muted);
  }
}

/**
 * 安装平台音量探测（仅 mraid 形渠道调用）：
 * 初始读 getAudioVolume()，并监听 audioVolumeChange。
 * 渠道缺音频接口或 API 抛错时静默跳过（渠道实现不完整时不阻塞）。
 */
export function installPlatformVolumeProbe(policy: MutePolicy): void {
  const mraid = window.mraid;
  if (!mraid) return;
  if (typeof mraid.getAudioVolume === "function") {
    try {
      const initial = mraid.getAudioVolume();
      if (typeof initial === "number") policy.setPlatformVolume(initial);
    } catch {
      /* 渠道实现不完整 —— 跳过初始读数 */
    }
  }
  if (typeof mraid.addEventListener === "function") {
    try {
      mraid.addEventListener("audioVolumeChange", (value: number) => {
        if (typeof value === "number") policy.setPlatformVolume(value);
      });
    } catch {
      /* 渠道实现不完整 —— 跳过监听 */
    }
  }
}

export function createAudioManager(policy: MutePolicy): PFAudioManager {
  const elements = new Set<HTMLAudioElement>();
  let sharedContext: AudioContext | null = null;

  // 策略变化回调：全部已建 <audio>.muted 同步 + context suspend/resume 双向。
  const applyMute = (muted: boolean): void => {
    for (const el of elements) {
      try {
        el.muted = muted;
      } catch {
        /* 单个元素异常不阻断其余同步 */
      }
    }
    if (sharedContext) {
      if (muted) {
        if (sharedContext.state === "running") void sharedContext.suspend();
      } else {
        void sharedContext.resume();
      }
    }
  };
  policy.onChange(applyMute);

  return {
    create(src: string): HTMLAudioElement {
      const audioCtor = (
        window as unknown as { Audio?: new (src?: string) => HTMLAudioElement }
      ).Audio;
      if (typeof audioCtor !== "function") {
        throw new Error(
          "PF.audio.create: 环境缺少 Audio 构造器，无法创建音频元素",
        );
      }
      const el = new audioCtor(src);
      el.muted = policy.isMuted(); // 立即对齐策略，并纳入后续同步
      elements.add(el);
      return el;
    },

    getContext(): AudioContext | null {
      if (sharedContext) return sharedContext;
      const contextCtor = (
        window as unknown as { AudioContext?: new () => AudioContext }
      ).AudioContext;
      if (typeof contextCtor !== "function") return null; // jsdom/无头环境
      sharedContext = new contextCtor();
      if (policy.isMuted() && sharedContext.state === "running") {
        void sharedContext.suspend();
      }
      return sharedContext;
    },
  };
}
