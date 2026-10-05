// pf:* 事件派发（spec §2.2，冻结）。
//
// 事件为 DOM CustomEvent，直接派发到 document，bubbles=true、cancelable=false。
// detail 契约：pf:end → { win: boolean }；pf:cta → { url: string }；
// pf:first-interaction → { type: "pointerdown" | "touchstart" | "mousedown" | "keydown" }；
// pf:ready / pf:start → 无 detail。

import type { PFEventName } from "./types.ts";

// esbuild 打包进页面后 CustomEvent 即全局；这里仍从 window 取用一次，
// 保证打包环境与裸 Node 环境（jsdom 注入）都拿到构造器。
function customEventCtor(): typeof CustomEvent {
  const scope = window as unknown as { CustomEvent?: typeof CustomEvent };
  return scope.CustomEvent ?? CustomEvent;
}

/** 按 detail 契约构造并派发一个 pf:* 事件到 document。 */
export function dispatchPFEvent(name: PFEventName, detail?: unknown): void {
  const event = new (customEventCtor())(name, {
    detail,
    bubbles: true,
    cancelable: false,
  });
  document.dispatchEvent(event);
}

/** 认定"首次交互"的事件集合（spec §2.2：捕获阶段监听，先到者上报类型）。 */
export const INTERACTION_EVENT_NAMES = [
  "pointerdown",
  "touchstart",
  "mousedown",
  "keydown",
] as const;

export type InteractionEventName = (typeof INTERACTION_EVENT_NAMES)[number];

/**
 * 安装首交互监听（spec §2.2 once 语义）：任一交互事件首次到达即解除全部监听，
 * 并以事件类型回调 onFirst（供 pf:first-interaction 的 detail.type）。
 * 捕获阶段监听：任何先于模板逻辑的交互都被观测。
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
