// engine-bridge 契约类型（spec：docs/assets/specs/engine-bridge.md §2，frozen）。
//
// 本包是 M2 运行时桥：挂载 window.PF 全局、派发 5 个 pf:* DOM 事件、
// 按渠道做就绪等待与退出路由、执行首交互前强制静音。零 npm 运行时依赖；
// 模板/打包器以 esbuild 直接打包 src/*.ts，Node 22+ 亦可原生加载。
//
// 边界（spec §1）：不渲染（模板职责）；不提供 window.__PF_QC__（QC 钩子属
// 模板交付物，桥只暴露 phase()/setState() 供模板复用同一相位机）；对渠道 SDK
// 只做全局对象协议形探测，不做运行时硬依赖。

/** 渠道 id 全集：6 个投放渠道 + preview（本地预览/QC 兜底）。 */
export type ChannelId =
  | "applovin"
  | "meta"
  | "google"
  | "unity"
  | "tiktok"
  | "mintegral"
  | "preview";

/** 相位机四相位（QC 钩子 state() 直读它）。 */
export type PFPhase = "loading" | "tutorial" | "playing" | "end";

/** 桥派发的 5 个 pf:* 事件名。 */
export type PFEventName =
  | "pf:ready"
  | "pf:start"
  | "pf:first-interaction"
  | "pf:end"
  | "pf:cta";

/** mraid 形接口（applovin/unity/mintegral 共用协议形，按探测使用）。 */
export interface MraidLike {
  getState?: () => string;
  open?: (url: string) => void;
  getAudioVolume?: () => number;
  addEventListener?: (name: string, listener: (...args: unknown[]) => void) => void;
  removeEventListener?: (name: string, listener: (...args: unknown[]) => void) => void;
}

/** Meta 可玩广告全局（仅需退出回调）。 */
export interface MetaPlayableLike {
  onComplete?: () => void;
}

/** Google 渠道退出接口。 */
export interface GoogleExitLike {
  exit?: () => void;
}

/**
 * 音频管理器：模板的一切音频必须经此创建（静音策略的执行点，spec §2.6 契约）。
 */
export interface PFAudioManager {
  /** 创建 <audio>；muted 立即对齐当前策略，并纳入后续策略同步。 */
  create(src: string): HTMLAudioElement;
  /** 懒创建共享 AudioContext 单例；策略静音时 suspended；不支持的环境返回 null。 */
  getContext(): AudioContext | null;
}

/** 挂到 window.PF 的全局对象成员表（spec §2.1，冻结）。 */
export interface PFGlobal {
  readonly channel: ChannelId;
  readonly locale: string;
  readonly version: string;
  /** 渠道就绪后 resolve，并派发 pf:ready；预览/缺 stub 环境立即 resolve。 */
  readonly ready: Promise<void>;
  /** 首次交互前恒 true；平台音量为 0 时即使已交互也恒 true。 */
  isMuted(): boolean;
  /** 当前相位（loading/tutorial/playing/end）。 */
  phase(): PFPhase;
  /** 模板驱动相位（如进教程 setState("tutorial")）。 */
  setState(phase: PFPhase): void;
  /** 每次 open 都派发 pf:cta {url}；渠道退出外呼仅第一次（单次锁）。 */
  open(url: string): void;
  /** 玩法开始：相位 → playing + pf:start。 */
  start(): void;
  /** 结束：相位 → end + pf:end {win}。 */
  end(win: boolean): void;
  readonly audio: PFAudioManager;
}

/** initBridge 入参（全部可选）。 */
export interface BridgeOptions {
  /** 显式渠道；缺省时按 PF_CHANNEL → 全局探测 → preview 解析。 */
  channel?: ChannelId;
  /** 显式 locale；缺省时按 PF_LOCALE → URL ?locale= → defaultLocale → "en"。 */
  locale?: string;
  /** 无任何 locale 来源时的兜底（?? 语义：undefined/null 才回落 "en"）。 */
  defaultLocale?: string;
  /** 渠道就绪等待上限（毫秒），超时静默放行；默认 8000。 */
  readyTimeoutMs?: number;
}

declare global {
  interface Window {
    mraid?: MraidLike;
    FbPlayableAd?: MetaPlayableLike;
    ExitApi?: GoogleExitLike;
    openAppStore?: () => void;
    PF?: PFGlobal;
    PF_CHANNEL?: string;
    PF_LOCALE?: string;
  }
}
