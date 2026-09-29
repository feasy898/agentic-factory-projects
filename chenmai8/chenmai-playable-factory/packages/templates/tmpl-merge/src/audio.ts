// 音效装配：一切音频经 engine-bridge 的 PF.audio 创建（首交互前自动 muted）。
// 预览构建无外部素材文件——代码生成合法 RIFF/WAV data URI（8bit 单声道，
// 起始 5% 淡入防爆音），零网络请求。合成模板三音：tap=合成点击（880Hz），
// pop=升级（1175Hz），win=结算（1318Hz）。

/** PF.audio 的结构类型（与 engine-bridge 的 PFAudioManager 成员一致）。 */
interface PFAudio {
  create(src: string): HTMLAudioElement;
  getContext(): AudioContext | null;
}

function makeBeepDataUri(sampleRate: number, ms: number, freq: number, gain: number): string {
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
  view.setUint32(28, sampleRate, true); // byteRate = rate × 1ch × 1byte
  view.setUint16(32, 1, true); // block align
  view.setUint16(34, 8, true); // bits
  writeStr(36, "data");
  view.setUint32(40, dataSize, true);
  const quietUntil = Math.round(samples * 0.05); // 起始 5% 淡入
  for (let i = 0; i < samples; i++) {
    const t = i / sampleRate;
    const envelope = i < quietUntil ? i / quietUntil : 1 - i / samples;
    const v = Math.sin(2 * Math.PI * freq * t) * gain * Math.max(0, envelope);
    view.setUint8(44 + i, Math.round(128 + v * 127));
  }
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return "data:audio/wav;base64," + btoa(binary);
}

/** 模板音效集合（tap：合成拖放；pop：升级；win：结算）。 */
export interface GameAudio {
  tap(): void;
  pop(): void;
  win(): void;
}

export function createGameAudio(audio: PFAudio): GameAudio {
  const tapEl = audio.create(makeBeepDataUri(11025, 60, 880, 0.5));
  const popEl = audio.create(makeBeepDataUri(11025, 110, 1175, 0.5));
  const winEl = audio.create(makeBeepDataUri(11025, 350, 1318, 0.5));
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
    tap: () => play(tapEl),
    pop: () => play(popEl),
    win: () => play(winEl),
  };
}
