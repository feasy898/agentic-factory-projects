// pf:* 事件派发（开发指令 §4.2 冻结契约）。
// 事件为 DOM CustomEvent，直接派发到 document 且 bubbles=true（"冒泡到 document"）。
// detail 约定：pf:end → { win: boolean }；pf:cta → { url: string }；
//              pf:first-interaction → { type: string }；pf:ready / pf:start → 无 detail。

import type { PFEventName } from "./types.ts";

function eventCtor(): typeof CustomEvent {
  const w = window as unknown as { CustomEvent?: typeof CustomEvent };
  return w.CustomEvent ?? CustomEvent;
}

export function dispatchPFEvent(name: PFEventName, detail?: unknown): void {
  const event = new (eventCtor())(name, {
    detail,
    bubbles: true,
    cancelable: false,
  });
  document.dispatchEvent(event);
}

/** 首交互监听的事件集合（捕获阶段，任意一个先到即认定首次交互）。 */
export const INTERACTION_EVENT_NAMES = [
  "pointerdown",
  "touchstart",
  "mousedown",
  "keydown",
] as const;

export type InteractionEventName = (typeof INTERACTION_EVENT_NAMES)[number];

/**
 * 安装首交互监听：任一交互事件首次到达即解除全部监听（once 语义），
 * 返回是否为本次会话的首次交互。事件类型随 pf:first-interaction 的 detail.type 上报。
 */
export function installFirstInteraction(
  onFirst: (type: InteractionEventName) => void,
): void {
  const handler = (ev: Event): void => {
    for (const name of INTERACTION_EVENT_NAMES) {
      document.removeEventListener(name, handler as EventListener, true);
    }
    onFirst(ev.type as InteractionEventName);
  };
  for (const name of INTERACTION_EVENT_NAMES) {
    document.addEventListener(name, handler as EventListener, true);
  }
}
