// 模板入口（templates.md §2 统一形态）：normalizeSpec(window.PF_SPEC ?? {}) →
// initBridge({ defaultLocale }) → pf.ready.then(boot)（DOM loading 时挂
// DOMContentLoaded）。挂载 window.__PF_QC__（hint/state/endScreenVisible/texts/
// textStates/assets）；RTL 标记；事件只经桥、音频只经 PF.audio。
// spec 由构建时内联的 window.PF_SPEC 提供；window.PF_ASSETS 为构建期内联的
// 用户替换素材（可缺省）。

import { initBridge, type PFGlobal } from "@pf/engine-bridge";
import * as engine from "./vendor/engine.js";
import { normalizeSpec } from "./spec.ts";
import { decodeReplacedSprites, type ReplacedSprite } from "./assets.ts";
import { Match3Scene } from "./game.ts";

declare global {
  interface Window {
    PF_SPEC?: unknown;
    /** 构建期内联的用户替换素材（spriteKey → data URI）；无替换时为空对象。 */
    PF_ASSETS?: Record<string, string>;
    __PF_QC__?: {
      hint: () => { x: number; y: number; type: string } | null;
      state: () => string;
      endScreenVisible?: () => boolean;
      /** 已渲染到画布的文案集合（画布文字不进 DOM，innerText 取不到）。 */
      texts?: () => string[];
      /** 采样时刻逐条核验文案对象 active+visible（CHK10 上屏自证）。 */
      textStates?: () => Array<{ text: string; active: boolean; visible: boolean }>;
      /** 替换素材像素对账（渲染贴图 vs 内联用户 PNG），无替换素材时为 []。 */
      assets?: () => Promise<
        Array<{ texKey: string; spriteKey: string; mad: number | null; replaced: boolean; reason?: string }>
      >;
    };
  }
}

const spec = normalizeSpec((window as any).PF_SPEC ?? {});
const pf: PFGlobal = initBridge({ defaultLocale: spec.defaultLocale });

// RTL 语言（如 ar）：文档方向标记（结束页/教程文本排版镜像在模板层处理）。
if (spec.rtl.includes(pf.locale)) {
  document.documentElement.setAttribute("dir", "rtl");
}

let scene: any = null;
(window as any).__PF_QC__ = {
  hint: () => (scene ? scene.hint() : null),
  state: () => pf.phase(),
  endScreenVisible: () => (scene ? scene.endScreenVisible() : false),
  texts: () => (scene && typeof scene.textsSeen === "function" ? scene.textsSeen() : []),
  textStates: () => (scene && typeof scene.textStates === "function" ? scene.textStates() : []),
  assets: () => (scene && typeof scene.assetAudit === "function" ? scene.assetAudit() : Promise.resolve([])),
};

async function boot(): Promise<void> {
  // 最小素材路径：解码构建期内联的用户 PNG（可缺省——纯程序化构建无此对象）。
  const replaced: ReplacedSprite[] = await decodeReplacedSprites(
    (window as any).PF_ASSETS,
    spec.params,
  );
  scene = new Match3Scene(spec, pf, replaced); // 供 __PF_QC__ 闭包引用
  const game = new engine.Game({
    type: engine.AUTO,
    parent: "app",
    backgroundColor: "#141b34",
    banner: false,
    scale: {
      mode: engine.Scale.RESIZE,
      autoCenter: engine.Scale.NO_CENTER,
      width: window.innerWidth,
      height: window.innerHeight,
    },
    fps: { target: 60 },
    // 引擎 WebAudio 关闭（CHK04 合规，M2.2 复验回修）：玩法音效一律经 PF.audio
    // （桥管理的 HTMLAudio 元素，首交互前强制静音）。引擎自带 WebAudio 管理器会在
    // 启动期创建 AudioContext，且无头/真机浏览器授予 autoplay 时可能创建即 running
    // ——形成"首交互前 running AudioContext"的真实违规（channel-rules
    // muteBeforeFirstInteraction）。引擎原生支持 noAudio（NoAudioSoundManager，
    // 不创建任何 AudioContext）；CHK04 的媒体探针（play()/<audio>/<video>）不受影响。
    audio: { noAudio: true },
    scene: [scene],
  });
  void game; // 场景持有全部引用，Game 实例保存在闭包防回收
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => pf.ready.then(boot));
} else {
  pf.ready.then(boot);
}
