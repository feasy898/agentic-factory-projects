// 音效装配：一切音频经 engine-bridge 的 PF 音频管理器创建（契约 §4.2），
// 首交互前自动 muted。预览构建无外部素材文件，这里用代码生成极小的
// 合法 RIFF/WAV 数据 URI（短促提示音），不产生任何网络请求。
// screwMode 分支：普通=倾倒水声（下滑音）；拧螺丝=棘轮双击（两声短促高频）。

/** PF.audio 的结构类型（与 engine-bridge 的 AudioManager 成员一致）。 */
interface PFAudio {
  create(src: string): HTMLAudioElement;
  getContext(): AudioContext | null;
}

function makeBeepDataUri(
  sampleRate: number,
  ms: number,
  freqFrom: number,
  freqTo: number,
  gain: number,
): string {
  const samples = Math.max(1, Math.round((sampleRate * ms) / 1000));
  const dataSize = samples; // 8-bit 单声道
  const bufferSize = 44 + dataSize;
  const bytes = new Uint8Array(bufferSize);
  const view = new DataView(bytes.buffer);
  const writeStr = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, bufferSize - 8, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate, true); // byteRate = rate*1ch*1byte
  view.setUint16(32, 1, true); // block align
  view.setUint16(34, 8, true); // bits
  writeStr(36, "data");
  view.setUint32(40, dataSize, true);
  let quietUntil = Math.round(samples * 0.05); // 起始 5% 淡入，防爆音
  let phase = 0;
  for (let i = 0; i < samples; i++) {
    const t = i / samples;
    const freq = freqFrom + (freqTo - freqFrom) * t;
    phase += (2 * Math.PI * freq) / sampleRate;
    const envelope = i < quietUntil ? i / quietUntil : 1 - t;
    const v = Math.sin(phase) * gain * Math.max(0, envelope);
    view.setUint8(44 + i, Math.round(128 + v * 127));
  }
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return "data:audio/wav;base64," + btoa(binary);
}

/** 模板音效集合（select 选中/点按；pour 倾倒或拧动；win 结算；danger 险情低鸣）。 */
export interface GameAudio {
  select(): void;
  pour(): void;
  win(): void;
  danger(): void;
}

export function createGameAudio(audio: PFAudio, screwMode: boolean): GameAudio {
  const selectEl = audio.create(makeBeepDataUri(11025, 45, 660, 660, 0.4));
  const pourEl = screwMode
    ? audio.create(makeBeepDataUri(11025, 170, 1450, 1450, 0.4)) // 棘轮：短促高频
    : audio.create(makeBeepDataUri(11025, 200, 980, 420, 0.45)); // 倾倒：下滑水声
  const winEl = audio.create(makeBeepDataUri(11025, 350, 1318, 1760, 0.5));
  const dangerEl = audio.create(makeBeepDataUri(11025, 260, 196, 150, 0.55));
  const play = (el: HTMLAudioElement) => {
    try {
      el.currentTime = 0;
    } catch {
      /* 某些环境不可重定位播放头，忽略 */
    }
    const p = el.play();
    if (p && typeof p.catch === "function") p.catch(() => undefined);
  };
  return {
    select: () => play(selectEl),
    pour: () => play(pourEl),
    win: () => play(winEl),
    danger: () => play(dangerEl),
  };
}
