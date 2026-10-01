// 契约类型（开发指令 §4.2 运行时契约，schema v1 阶段冻结，不得擅改）：
// - 全局对象 window.PF：PF.open(url) / PF.isMuted() / PF.locale
// - 事件（DOM CustomEvent，冒泡到 document）：pf:ready / pf:start /
//   pf:first-interaction / pf:end {win} / pf:cta
// - 静音策略：所有音频经 PF 音频管理器创建；首个 pf:first-interaction 前强制静音
//   （HTMLAudio muted=true / AudioContext suspended）
// 说明：window.__PF_QC__（hint/state）是模板（M3）交付物，桥不代装。

export type ChannelId =
  | "applovin"
  | "meta"
  | "google"
  | "unity"
  | "tiktok"
  | "mintegral"
  | "preview";

/** QC 状态机的相位；loading/tutorial/playing/end 与质检钩子约定一致。 */
export type PFPhase = "loading" | "tutorial" | "playing" | "end";

export type PFEventName =
  | "pf:ready"
  | "pf:start"
  | "pf:first-interaction"
  | "pf:end"
  | "pf:cta";

/** 渠道运行时可能暴露的 mraid 形接口（按协议探测，不做运行时硬依赖）。 */
export interface MraidLike {
  getState?: () => string;
  open?: (url: string) => void;
  getAudioVolume?: () => number;
  addEventListener?: (name: string, listener: (...args: unknown[]) => void) => void;
  removeEventListener?: (name: string, listener: (...args: unknown[]) => void) => void;
}

/** Meta 渠道可玩广告全局对象（仅需退出回调）。 */
export interface MetaPlayableLike {
  onComplete?: () => void;
}

/** Google 渠道退出接口。 */
export interface GoogleExitLike {
  exit?: () => void;
}

/** 音频管理器：模板的一切音频都必须经此创建（静音策略的执行点）。 */
export interface PFAudioManager {
  /** 创建 <audio> 元素；首交互前 muted=true，之后随策略自动解除。 */
  create(src: string): HTMLAudioElement;
  /** 懒创建共享 AudioContext；首交互前 suspended。环境不支持时返回 null。 */
  getContext(): AudioContext | null;
}

/** 挂到 window.PF 的全局对象（契约成员见 §4.2；其余为模板驱动事件的便捷入口）。 */
export interface PFGlobal {
  readonly channel: ChannelId;
  readonly locale: string;
  readonly version: string;
  /** 渠道就绪（与 pf:ready 同步 resolve；预览/缺 stub 环境立即 resolve）。 */
  readonly ready: Promise<void>;
  /** 首个 pf:first-interaction 之前恒为 true。 */
  isMuted(): boolean;
  /** 当前相位（loading/tutorial/playing/end），供模板实现质检钩子 state()。 */
  phase(): PFPhase;
  /** 模板驱动相位（如进入教程时 setState("tutorial")）。 */
  setState(phase: PFPhase): void;
  /** CTA 退出：派发 pf:cta {url} 并按渠道路由到退出接口（仅首次真正外呼）。 */
  open(url: string): void;
  /** 玩法开始：派发 pf:start，相位 → playing。 */
  start(): void;
  /** 结束：派发 pf:end {win}，相位 → end。 */
  end(win: boolean): void;
  readonly audio: PFAudioManager;
}

/** initBridge 入参。 */
export interface BridgeOptions {
  /** 显式渠道（打包器注入的首选方式）；缺省时按 PF_CHANNEL / 全局探测。 */
  channel?: ChannelId;
  /** 显式 locale；缺省时按 PF_LOCALE → URL ?locale= → defaultLocale → "en"。 */
  locale?: string;
  /** 无任何 locale 来源时的兜底。 */
  defaultLocale?: string;
  /** 渠道就绪等待上限（毫秒），超时放行以免卡死加载。默认 8000。 */
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
