// M2 engine-bridge 类型与常量（SPEC §2 对外契约的类型面）。
// 运行时零依赖；只使用可擦除 TS 语法（Node ≥22 原生类型剥离）。

export const PF_VERSION = "0.1.0";

/** 7 值：6 渠道 + preview。 */
export type ChannelId =
  | "applovin"
  | "unity"
  | "mintegral"
  | "meta"
  | "google"
  | "tiktok"
  | "preview";

/** mraid 形渠道（协议同形，退出调用一致）。 */
export type MraidFormChannel = "applovin" | "unity" | "mintegral";

/** 相位机（QC 的 state() 应直读 PF.phase()）。 */
export type PFPhase = "loading" | "tutorial" | "playing" | "end";

export type PFEventName =
  | "pf:ready"
  | "pf:start"
  | "pf:first-interaction"
  | "pf:end"
  | "pf:cta";

export type InteractionType =
  | "pointerdown"
  | "touchstart"
  | "mousedown"
  | "keydown";

export type ExitRoute = "mraid" | "meta" | "google" | "tiktok" | "window-open";

export interface BridgeOptions {
  /** 显式渠道 id（pangle 会归一为 tiktok；非法 id 落 preview）。 */
  channel?: string;
  /** 显式 locale（最高优先级）。 */
  locale?: string;
  /** 兜底 locale（位于 URL query 之后、"en" 之前）。 */
  defaultLocale?: string;
  /** 渠道就绪等待超时（默认 8000ms，超时放行不卡死加载）。 */
  readyTimeoutMs?: number;
}

export interface PFAudioManager {
  /**
   * 创建 <audio>：立即对齐静音策略并纳入后续策略同步。
   * 契约：模板的一切音频必须经此创建；缺 Audio 构造器时抛错。
   */
  create(src: string): HTMLAudioElement;
  /** 懒创建共享 AudioContext 单例；无 AudioContext 环境（jsdom/无头）返回 null。 */
  getContext(): AudioContext | null;
}

export interface PFGlobal {
  readonly channel: ChannelId;
  readonly locale: string;
  readonly version: string;
  /** 渠道就绪后 resolve 并派发 pf:ready；预览/缺 stub 环境立即 resolve。 */
  readonly ready: Promise<void>;
  isMuted(): boolean;
  phase(): PFPhase;
  setState(phase: PFPhase): void;
  open(url: string): void;
  start(): void;
  end(win: boolean): void;
  readonly audio: PFAudioManager;
}

/** mraid 运行时协议形（桥只探测全局对象的形，不做硬依赖）。 */
export interface MraidLike {
  getState?: () => string;
  open?: (url: string) => void;
  getAudioVolume?: () => number;
  addEventListener?: (name: string, cb: (value: number) => void) => void;
  removeEventListener?: (name: string, cb: (value: number) => void) => void;
}

export interface FbPlayableAdLike {
  onComplete?: () => void;
}

export interface ExitApiLike {
  exit?: () => void;
}

declare global {
  interface Window {
    PF?: PFGlobal;
    PF_CHANNEL?: string;
    PF_LOCALE?: string;
    mraid?: MraidLike;
    FbPlayableAd?: FbPlayableAdLike;
    ExitApi?: ExitApiLike;
    openAppStore?: () => void;
  }
}
