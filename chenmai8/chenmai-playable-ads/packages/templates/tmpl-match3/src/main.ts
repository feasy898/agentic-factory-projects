// 模板入口：装配 engine-bridge 的 window.PF → 等渠道就绪 → 启动渲染引擎 →
// 挂载 window.__PF_QC__（hint/state，契约 §4.2）。spec 由构建时内联的
// window.PF_SPEC 提供（预览/单文件产物），渠道经 PF_CHANNEL / 全局探测识别。

import { initBridge, type PFGlobal } from "@pf/engine-bridge";
import * as engine from "./vendor/engine.js";
import { normalizeSpec } from "./spec.ts";
import { Match3Scene } from "./game.ts";

declare global {
  interface Window {
    PF_SPEC?: unknown;
    __PF_QC__?: {
      hint: () => { x: number; y: number; type: string } | null;
      state: () => string;
      endScreenVisible?: () => boolean;
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
};

function boot(): void {
  scene = new Match3Scene(spec, pf); // 供 __PF_QC__ 闭包引用
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
    scene: [scene],
  });
  void game; // 场景持有全部引用，Game 实例保存在闭包防回收
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => pf.ready.then(boot));
} else {
  pf.ready.then(boot);
}
