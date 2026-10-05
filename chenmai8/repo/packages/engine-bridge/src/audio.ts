// 静音策略 + PF 音频管理器（开发指令 §4.2 冻结契约）：
// - 首个 pf:first-interaction 之前强制静音：HTMLAudio muted=true；AudioContext suspended。
// - 渠道平台侧音量（mraid.getAudioVolume / audioVolumeChange）为 0 时视为平台静音，
//   即使用户已交互也保持 muted，直到平台放开音量。
// - 模板的一切音频必须经音频管理器创建（契约），策略变化自动同步到已创建的音频。

/** 计算静音态变化时对外通知（音频管理器据此同步元素与 AudioContext）。 */
export type MuteChangeHandler = (muted: boolean) => void;

export class MutePolicy {
  private interactionSeen = false;
  private platformVolume = 1;
  private lastNotified: boolean | null = null;
  private readonly handlers = new Set<MuteChangeHandler>();

  isMuted(): boolean {
    return !this.interactionSeen || this.platformVolume === 0;
  }

  /** 标记首次交互；返回是否确为首次（供 pf:first-interaction 只派发一次）。 */
  markInteraction(): boolean {
    if (this.interactionSeen) return false;
    this.interactionSeen = true;
    this.notifyIfChanged();
    return true;
  }

  /** 平台侧音量（0 = 平台静音）。变化不改变状态时不重复通知。 */
  setPlatformVolume(volume: number): void {
    if (!Number.isFinite(volume) || volume === this.platformVolume) return;
    this.platformVolume = volume;
    this.notifyIfChanged();
  }

  onChange(handler: MuteChangeHandler): void {
    this.handlers.add(handler);
  }

  private notifyIfChanged(): void {
    const muted = this.isMuted();
    if (muted === this.lastNotified) return;
    this.lastNotified = muted;
    for (const handler of this.handlers) handler(muted);
  }
}

interface AudioContextCtor {
  new (): AudioContext;
}

interface WindowWithAudio extends Window {
  Audio?: new (src?: string) => HTMLAudioElement;
  AudioContext?: AudioContextCtor;
  webkitAudioContext?: AudioContextCtor;
}

export class AudioManager {
  private readonly policy: MutePolicy;
  private readonly elements: HTMLAudioElement[] = [];
  private context: AudioContext | null = null;
  private contextCreated = false;

  // 注意：不用 TS 参数属性（constructor(private ...)）——Node 类型剥离模式
  // 只支持可擦除语法（ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX）。
  constructor(policy: MutePolicy) {
    this.policy = policy;
    policy.onChange(() => this.applyPolicy());
  }

  /** 创建 <audio>；muted 立即对齐策略，并纳入后续策略同步。 */
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

  /** 懒创建共享 AudioContext（单例）。环境不支持（如无头 DOM）返回 null。 */
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

  /** 策略变化 → 同步全部已创建音频与 AudioContext。 */
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
