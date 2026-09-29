/**
 * 自动试玩驱动（--autoplay，qacore spec §5 / oracle autoplay.py 语义移植）：
 * 经 window.__PF_QC__.hint() 用真实 pointer 事件推动 教程→游玩→结束页。
 *
 * 手势语义表（冻结）：swap-left/right/up/down → 定向拖拽（44px×4 步，
 * mouse down→move→up）；drag → 向右拖拽；tap → 单击（未知 type 按 tap 兜底）。
 * hint 坐标 = 视口 CSS 像素。autoplay 只驱动竖屏趟；不许 mock 被测物。
 */
import type { Page } from "playwright";

import { ev } from "./ev.ts";
import { PROBE_JS } from "./probe.ts";

// 拖拽位移（像素）：小于最小棋盘格边长，方向语义由 hint.type 给出。
export const DRAG_DISTANCE = 44.0;

const SWEEP_VECTORS: Record<string, [number, number]> = {
  "swap-left": [-1.0, 0.0],
  "swap-right": [1.0, 0.0],
  "swap-up": [0.0, -1.0],
  "swap-down": [0.0, 1.0],
  "drag": [1.0, 0.0],
};

export async function state(page: Page): Promise<string> {
  try {
    return await ev(page, 
      "() => (window.__PF_QC__ && typeof window.__PF_QC__.state === 'function')"
      + " ? String(window.__PF_QC__.state()) : 'loading'",
    ) as string;
  } catch {
    return "loading";
  }
}

export interface QcHint { x: number; y: number; type: string }

async function hint(page: Page): Promise<QcHint | null> {
  let raw: unknown;
  try {
    raw = await ev(page, 
      "() => { const q = window.__PF_QC__;"
      + " if (!q || typeof q.hint !== 'function') return null;"
      + " try { return q.hint(); } catch (e) { return null; } }",
    );
  } catch {
    return null;
  }
  if (raw === null || typeof raw !== "object") return null;
  const h = raw as Record<string, unknown>;
  const x = h.x, y = h.y;
  if (typeof x !== "number" || typeof y !== "number") return null;
  return { x, y, type: typeof h.type === "string" ? h.type : "tap" };
}

export async function pfMuted(page: Page): Promise<boolean | null> {
  let v: unknown;
  try {
    v = await ev(page, 
      "() => (window.PF && typeof PF.isMuted === 'function') ? PF.isMuted() : null",
    );
  } catch {
    return null;
  }
  return typeof v === "boolean" ? v : null;
}

export async function audioRunning(page: Page): Promise<number | null> {
  try {
    const v = await ev(page, 
      "() => { const p = window.__pfprobe; return p && p.audio ? p.audio.running : null; }",
    ) as unknown;
    return typeof v === "number" ? Math.trunc(v) : null;
  } catch {
    return null;
  }
}

export interface MediaSample {
  unmuted: number; playing: number; playsBeforeFirst: number;
}

export async function mediaSample(page: Page): Promise<MediaSample | null> {
  let v: unknown;
  try {
    v = await ev(page, 
      "() => (window.__pfprobe && typeof window.__pfprobe.sampleMedia === 'function')"
      + " ? window.__pfprobe.sampleMedia() : null",
    );
  } catch {
    return null;
  }
  if (v === null || typeof v !== "object") return null;
  const m = v as Record<string, unknown>;
  return {
    unmuted: Number(m.unmuted) || 0,
    playing: Number(m.playing) || 0,
    playsBeforeFirst: Number(m.playsBeforeFirst) || 0,
  };
}

export async function rtcCount(page: Page): Promise<number | null> {
  try {
    const v = await ev(page, 
      "() => { const p = window.__pfprobe; return p ? (p.rtc | 0) : null; }",
    ) as unknown;
    return typeof v === "number" ? Math.trunc(v) : null;
  } catch {
    return null;
  }
}

export async function probeInstalled(page: Page): Promise<boolean> {
  try {
    return Boolean(await ev(page, "() => !!window.__pfprobe"));
  } catch {
    return false;
  }
}

/** 用真实 pointer 事件执行 hint：swap-* 为定向拖拽，tap 为单击。 */
async function gesture(page: Page, h: QcHint): Promise<void> {
  const x = h.x, y = h.y;
  const vec = SWEEP_VECTORS[h.type];
  await page.mouse.move(x, y);
  await page.mouse.down();
  if (vec) {
    const steps = 4;
    for (let i = 1; i <= steps; i++) {
      await page.mouse.move(x + vec[0] * DRAG_DISTANCE * i / steps, y + vec[1] * DRAG_DISTANCE * i / steps);
    }
  }
  await page.mouse.up();
}

export async function hasPf(page: Page): Promise<boolean> {
  try {
    return Boolean(await ev(page, 
      "() => !!(window.PF && typeof PF.isMuted === 'function')"));
  } catch {
    return false;
  }
}

/** 模板经 __PF_QC__.texts() 上报的已渲染文案集合（画布文字不进 DOM）。 */
export async function qcTexts(page: Page): Promise<string[]> {
  let v: unknown;
  try {
    v = await ev(page, 
      "() => (window.__PF_QC__ && typeof window.__PF_QC__.texts === 'function')"
      + " ? window.__PF_QC__.texts() : []",
    );
  } catch {
    return [];
  }
  if (!Array.isArray(v)) return [];
  return v.filter((x): x is string | number => typeof x === "string" || typeof x === "number")
    .map((x) => String(x));
}

export interface TextStateEntry { text: string; active: boolean; visible: boolean }

/** __PF_QC__.textStates() 实况采样；返回 [钩子在位, 条目]。 */
export async function qcTextStates(page: Page): Promise<[boolean, TextStateEntry[]]> {
  let v: unknown;
  try {
    v = await ev(page, 
      "() => (window.__PF_QC__ && typeof window.__PF_QC__.textStates === 'function')"
      + " ? window.__PF_QC__.textStates() : null",
    );
  } catch {
    return [false, []];
  }
  if (!Array.isArray(v)) return [false, []];
  const entries: TextStateEntry[] = [];
  for (const x of v) {
    if (x !== null && typeof x === "object"
      && (typeof (x as Record<string, unknown>).text === "string"
        || typeof (x as Record<string, unknown>).text === "number")) {
      const e = x as Record<string, unknown>;
      entries.push({
        text: String(e.text),
        active: e.active === true,
        visible: e.visible === true,
      });
    }
  }
  return [true, entries];
}

export interface AssetAuditEntry {
  texKey?: unknown; spriteKey?: unknown; mad?: unknown; replaced?: unknown; reason?: unknown;
  [k: string]: unknown;
}

/** __PF_QC__.assets() 替换素材像素对账结果（对账在页面内完成）。 */
export async function qcAssets(page: Page): Promise<AssetAuditEntry[]> {
  let v: unknown;
  try {
    v = await ev(page, 
      "() => (window.__PF_QC__ && typeof window.__PF_QC__.assets === 'function')"
      + " ? window.__PF_QC__.assets() : []",
    );
  } catch {
    return [];
  }
  if (!Array.isArray(v)) return [];
  return v.filter((x): x is Record<string, unknown> => x !== null && typeof x === "object");
}

export async function hasQcHooks(page: Page): Promise<boolean> {
  try {
    return Boolean(await ev(page, 
      "() => !!(window.__PF_QC__ && typeof window.__PF_QC__.hint === 'function'"
      + " && typeof window.__PF_QC__.state === 'function')"));
  } catch {
    return false;
  }
}

export interface AutoplayFacts {
  enabled: boolean;
  timeoutSec: number;
  reachedState: string;
  gestures: number;
  firstMutedBeforeInteraction: boolean | null;
  audioRunningBeforeInteraction: number | null;
  mediaUnmutedBeforeInteraction: number | null;
  mediaPlaysBeforeInteraction: number | null;
  mutedAfterFirstGesture: boolean | null;
  pfEndFired: boolean;
  pfEndMs: number | null;
  pfEndWin: boolean | null;
  pfReadyMs: number | null;
  endScreenVisible: boolean | null;
  qcHooksPresent: boolean;
  probeInstalled: boolean;
  textStatesHook: boolean;
  qcTexts: string[];
  qcVisibleTexts: string[];
  page_texts?: string[];
  text_states?: TextStateEntry[];
  text_states_hook?: boolean;
  asset_audit?: AssetAuditEntry[];
  [k: string]: unknown;
}

interface ProbeSnapshot {
  ready?: number | null;
  end?: number | null;
  endWin?: boolean | null;
  audio?: { running?: number | null };
}

async function readProbe(page: Page): Promise<ProbeSnapshot> {
  try {
    return (await ev(page, "() => window.__pfprobe || null") as ProbeSnapshot | null) ?? {};
  } catch {
    return {};
  }
}

/**
 * 自动试玩主循环；返回采集到的事实（不判定 PASS/FAIL，判定在 checks）。
 * 首交互前静音事实每轮重采样并"最坏值粘住"；循环内随相位采样 textStates
 * （教程浮层退场即销毁，错过相位就再无证据）。
 */
export async function driveAutoplay(page: Page, timeoutSec: number): Promise<AutoplayFacts> {
  const facts: AutoplayFacts = {
    enabled: true,
    timeoutSec,
    reachedState: "loading",
    gestures: 0,
    firstMutedBeforeInteraction: null,
    audioRunningBeforeInteraction: null,
    mediaUnmutedBeforeInteraction: null,
    mediaPlaysBeforeInteraction: null,
    mutedAfterFirstGesture: null,
    pfEndFired: false,
    pfEndMs: null,
    pfEndWin: null,
    pfReadyMs: null,
    endScreenVisible: null,
    qcHooksPresent: await hasQcHooks(page),
    probeInstalled: await probeInstalled(page),
    textStatesHook: false,
    qcTexts: [],
    qcVisibleTexts: [],
  };
  const seenTexts = new Set<string>();
  const visibleTexts = new Set<string>();
  const deadline = Date.now() + Math.max(1.0, timeoutSec) * 1000;
  while (Date.now() < deadline) {
    const st = await state(page);
    facts.reachedState = st;

    // 文案对象实况采样（含教程期）。
    const [hook, states] = await qcTextStates(page);
    if (hook) facts.textStatesHook = true;
    for (const s of states) {
      seenTexts.add(s.text);
      if (s.active && s.visible) visibleTexts.add(s.text);
    }

    const probe = await readProbe(page);
    if (facts.pfReadyMs === null && probe.ready !== null && probe.ready !== undefined) {
      facts.pfReadyMs = probe.ready;
    }

    // 首交互前事实：任何鼠标事件发生前 PF 必须 muted、无 running AudioContext、
    // 不存在未静音媒体元素。采样取"最坏值粘住"。
    if (facts.gestures === 0) {
      const m = await pfMuted(page);
      if (m === false) {
        facts.firstMutedBeforeInteraction = false;
      } else if (facts.firstMutedBeforeInteraction === null) {
        facts.firstMutedBeforeInteraction = m;
      }
      const run = Number(probe.audio?.running) || 0;
      facts.audioRunningBeforeInteraction =
        Math.max(facts.audioRunningBeforeInteraction ?? 0, Math.trunc(run));
      const ms = (await mediaSample(page)) ?? { unmuted: 0, playing: 0, playsBeforeFirst: 0 };
      facts.mediaUnmutedBeforeInteraction = Math.max(
        facts.mediaUnmutedBeforeInteraction ?? 0, Math.trunc(ms.unmuted));
      facts.mediaPlaysBeforeInteraction = Math.max(
        facts.mediaPlaysBeforeInteraction ?? 0, Math.trunc(ms.playsBeforeFirst));
    }

    if (st === "end") break;

    const h = await hint(page);
    if (h !== null) {
      await gesture(page, h);
      facts.gestures += 1;
      if (facts.mutedAfterFirstGesture === null) {
        facts.mutedAfterFirstGesture = await pfMuted(page);
      }
    }

    await page.waitForTimeout(180);
  }

  const probe = await readProbe(page);
  facts.pfEndFired = probe.end !== null && probe.end !== undefined;
  facts.pfEndMs = probe.end ?? null;
  facts.pfEndWin = probe.endWin ?? null;
  if (facts.pfReadyMs === null) facts.pfReadyMs = probe.ready ?? null;
  // 结束后再补采一轮媒体事实（覆盖"最后一轮之后才出声"的边角）。
  const ms = (await mediaSample(page)) ?? { unmuted: 0, playing: 0, playsBeforeFirst: 0 };
  if (facts.gestures === 0) {
    facts.mediaUnmutedBeforeInteraction = Math.max(
      facts.mediaUnmutedBeforeInteraction ?? 0, Math.trunc(ms.unmuted));
    facts.mediaPlaysBeforeInteraction = Math.max(
      facts.mediaPlaysBeforeInteraction ?? 0, Math.trunc(ms.playsBeforeFirst));
  }
  if (facts.reachedState !== "end") facts.reachedState = await state(page);
  // 结束页补采一轮文案实况。
  const [hookFinal, statesFinal] = await qcTextStates(page);
  if (hookFinal) facts.textStatesHook = true;
  for (const s of statesFinal) {
    seenTexts.add(s.text);
    if (s.active && s.visible) visibleTexts.add(s.text);
  }
  facts.qcTexts = [...seenTexts].sort();
  facts.qcVisibleTexts = [...visibleTexts].sort();
  try {
    const v = await ev(page, 
      "() => (window.__PF_QC__ && typeof window.__PF_QC__.endScreenVisible === 'function')"
      + " ? !!window.__PF_QC__.endScreenVisible() : null",
    ) as unknown;
    facts.endScreenVisible = Boolean(v);
  } catch {
    facts.endScreenVisible = null;
  }
  return facts;
}

export { PROBE_JS };
