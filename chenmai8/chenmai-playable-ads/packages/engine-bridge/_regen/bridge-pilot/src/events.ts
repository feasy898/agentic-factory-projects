// pf:* 事件派发与首交互监听（SPEC §2.2）。
// 事件为 CustomEvent，bubbles=true, cancelable=false，直接派发到 document。

import type { InteractionType, PFEventName } from "./types.ts";

export const INTERACTION_TYPES: readonly InteractionType[] = [
  "pointerdown",
  "touchstart",
  "mousedown",
  "keydown",
];

/** 派发一个 pf:* CustomEvent 到 document（bubbles=true, cancelable=false）。 */
export function emitPFEvent(name: PFEventName, detail?: unknown): void {
  const event = new CustomEvent(name, {
    detail,
    bubbles: true,
    cancelable: false,
  });
  document.dispatchEvent(event);
}

/**
 * 安装首交互监听：四类交互事件（捕获阶段）任一首次到达即上报类型并解除全部监听
 * （once 语义，先到者上报）。initBridge 时即安装，早于渠道就绪（不阻塞玩家操作）。
 */
export function installInteractionListeners(
  onFirst: (type: InteractionType) => void,
): void {
  let seen = false;
  const handler = (ev: Event): void => {
    if (seen) return;
    seen = true;
    for (const type of INTERACTION_TYPES) {
      document.removeEventListener(type, handler, true);
    }
    onFirst(ev.type as InteractionType);
  };
  for (const type of INTERACTION_TYPES) {
    document.addEventListener(type, handler, true);
  }
}
