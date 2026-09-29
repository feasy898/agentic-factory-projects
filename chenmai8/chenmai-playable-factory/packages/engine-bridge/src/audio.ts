// 静音策略 + 音频管理器（spec §2.6，frozen）。
//
// 策略核心：isMuted = 首交互未发生 || 平台音量为 0——首交互前强制静音；
// 平台侧（mraid getAudioVolume / audioVolumeChange）音量为 0 时，即使已交互
// 也保持静音，直到平台放开。模板的一切音频必须经 AudioManager 创建（契约），
// 策略变化自动同步到全部已建 <audio> 与共享 AudioContext。
//
// TS 纪律（factory/AGENTS.md，坑 5）：Node 类型剥离只支持可擦除语法——
// 禁构造器参数属性，一律显式 this.x = x。

/** 静音态变化通知（音频管理器据此同步元素与 AudioContext）。 */
export type MuteChangeHandler = (muted: boolean) => void;

export class MutePolicy {
  private interactionSeen = false;
  private platformVolume = 1;
  private lastNotified: boolean | null = null;
  private readonly handlers = new Set<MuteChangeHandler>();

  isMuted(): boolean {
    return !this.interactionSeen || this.platformVolume === 0;
  }

  /** 记录首次交互；返回是否确为首次（pf:first-interaction 只派发一次的依据）。 */
  markInteraction(): boolean {
    if (this.interactionSeen) return false;
    this.interactionSeen = true;
    this.notifyIfChanged();
    return true;
  }

  /** 平台侧音量（0 = 平台静音）；非有限数或与当前同值时忽略，不重复通知。 */
  setPlatformVolume(volume: number): void {
    if (!Number.isFinite(volume) || volume === this.platformVolume) return;
    this.platformVolume = volume;
    this.notifyIfChanged();
  }

  onChange(handler: MuteChangeHandler): void {
    this.handlers.add(handler);
  }

  /** 仅在静音态真正变化时通知一次（去重）。 */
  private notifyIfChanged(): void {
    const muted = this.isMuted();
    if (muted === this.lastNotified) return;
    this.lastNotified = muted;
    for (const handler of this.handlers) handler(muted);
  }
}

type AudioContextCtor = new () => AudioContext;

type WindowWithAudio = Window & {
  Audio?: new (src?: string) => HTMLAudioElement;
  AudioContext?: AudioContextCtor;
  webkitAudioContext?: AudioContextCtor;
};

export class AudioManager {
  private readonly policy: MutePolicy;
  private readonly elements: HTMLAudioElement[] = [];
  private context: AudioContext | null = null;
  private contextCreated = false;

  constructor(policy: MutePolicy) {
    this.policy = policy;
    policy.onChange(() => this.applyPolicy());
  }

  /** 创建 <audio>：muted 立即对齐当前策略，并纳入后续策略同步。 */
  create(src: string): HTMLAudioElement {
    const w = window as WindowWithAudio;
    if (typeof w.Audio !== "function") {
      throw new Error("[PF] 当前环境缺少 Audio 构造器，无法创建音频");
    }
    const element = new w.Audio(src);
    element.muted = this.policy.isMuted();
    this.elements.push(element);
    return element;
  }

  /** 懒创建共享 AudioContext（单例）；不支持的环境（jsdom/无头）返回 null。 */
  getContext(): AudioContext | null {
    if (this.contextCreated) return this.context;
    this.contextCreated = true;
    const w = window as WindowWithAudio;
    const ctor = w.AudioContext ?? w.webkitAudioContext;
    if (typeof ctor !== "function") return null;
    try {
      const context = new ctor();
      if (this.policy.isMuted() && context.state === "running") {
        void context.suspend();
      }
      this.context = context;
    } catch {
      this.context = null;
    }
    return this.context;
  }

  /** 策略变化 → 同步全部已建音频元素与 AudioContext（suspend/resume 双向）。 */
  private applyPolicy(): void {
    const muted = this.policy.isMuted();
    for (const element of this.elements) element.muted = muted;
    const context = this.context;
    if (!context) return;
    if (muted && context.state === "running") {
      void context.suspend();
    } else if (!muted && context.state === "suspended") {
      void context.resume();
    }
  }
}
