// PlayableSpec（schema v1）→ 模板内部规范化视图（pullpin 子 schema，§4.1 冻结）。
// params：levels(3) / pinsPerLevel(3-5) / hazard("lava"|"spike") / rescuee("character") /
// orderSolution（每关拔针顺序数组，可解性由 M1 pfcore 不变式 I1 强制，这里只宽容归一）。
// 校验由 @pf/spec 负责；这里只做宽容归一（LLM 只填偏差项也能跑）。

export type HazardKind = "lava" | "spike";

export interface PullpinParams {
  levels: number;
  pinsPerLevel: number;
  hazard: HazardKind;
  rescuee: "character";
  /** 每关拔针顺序（针下标数组）；缺失/不完整时模板回退"先拔救援针"的规范解。 */
  orderSolution: number[][];
}

export interface AttractParams {
  nearWin: boolean;
  failBait: boolean;
  firstClickSucceed: boolean;
}

export interface TutorialParams {
  enabled: boolean;
  gesture: "tap" | "drag";
  maxSec: number;
}

export interface EndScreenParams {
  showScore: boolean;
  ctaKey: string;
  landingUrl: string;
}

export interface NormalizedSpec {
  projectId: string;
  title: string;
  seed: number;
  params: PullpinParams;
  difficultyTargetLevel: number;
  attract: AttractParams;
  tutorial: TutorialParams;
  endScreen: EndScreenParams;
  locales: string[];
  defaultLocale: string;
  rtl: string[];
  strings: Record<string, Record<string, string>>;
  autoplayTimeoutSec: number;
  maxLoadSec: number;
}

function int(v: unknown, dflt: number, lo: number, hi: number): number {
  const n = typeof v === "number" && Number.isFinite(v) ? Math.round(v) : dflt;
  return Math.max(lo, Math.min(hi, n));
}

function bool(v: unknown, dflt: boolean): boolean {
  return typeof v === "boolean" ? v : dflt;
}

function str(v: unknown, dflt: string): string {
  return typeof v === "string" && v.length > 0 ? v : dflt;
}

export function normalizeSpec(raw: any): NormalizedSpec {
  const game = raw?.game ?? {};
  const p = game.params ?? {};
  const flow = raw?.flow ?? {};
  const tutorial = flow.tutorial ?? {};
  const endScreen = flow.endScreen ?? {};
  const i18n = raw?.i18n ?? {};
  const qc = raw?.qc ?? {};
  const meta = raw?.meta ?? {};

  const hazard: HazardKind = p.hazard === "spike" ? "spike" : "lava";
  const levels = int(p.levels, 3, 1, 10);
  const pinsPerLevel = int(p.pinsPerLevel, 3, 3, 5);
  // orderSolution：只保留"每关非空整数数组"的形状（可解性归 M1 不变式）；
  // 关数不足时缺的关回退规范解（见 levels.ts.canonicalOrder）。
  const orderRaw = Array.isArray(p.orderSolution) ? p.orderSolution : [];
  const orderSolution: number[][] = [];
  for (let i = 0; i < levels; i++) {
    const entry = Array.isArray(orderRaw[i]) ? orderRaw[i].map((x: unknown) => Math.round(Number(x))) : [];
    orderSolution.push(entry.filter((x: number) => Number.isFinite(x)));
  }

  const strings: Record<string, Record<string, string>> = {};
  const rawStrings = (i18n.strings ?? {}) as Record<string, Record<string, string>>;
  for (const [locale, table] of Object.entries(rawStrings)) {
    if (table && typeof table === "object") strings[locale] = { ...table };
  }

  return {
    projectId: str(meta.projectId, "pullpin"),
    title: str(meta.title, "Pin Rescue"),
    seed: int(meta.seed, 1, 0, 0x7fffffff),
    params: { levels, pinsPerLevel, hazard, rescuee: "character", orderSolution },
    difficultyTargetLevel: typeof game.difficulty?.targetLevel === "number"
      ? Math.max(0, Math.min(1, game.difficulty.targetLevel))
      : 0.5,
    attract: {
      nearWin: bool(game.attract?.nearWin, false),
      failBait: bool(game.attract?.failBait, false),
      firstClickSucceed: bool(game.attract?.firstClickSucceed, true),
    },
    tutorial: {
      enabled: bool(tutorial.enabled, true),
      gesture: tutorial.gesture === "drag" ? "drag" : "tap",
      maxSec: int(tutorial.maxSec, 3, 1, 10),
    },
    endScreen: {
      showScore: bool(endScreen.showScore, true),
      ctaKey: str(endScreen.ctaKey, "cta"),
      landingUrl: str(endScreen.landingUrl, "https://example.com/playable-lp"),
    },
    locales: Array.isArray(i18n.locales) && i18n.locales.length ? i18n.locales.map(String) : ["en"],
    defaultLocale: str(i18n.defaultLocale, "en"),
    rtl: Array.isArray(i18n.rtl) ? i18n.rtl.map(String) : [],
    strings,
    autoplayTimeoutSec: int(qc.autoplayTimeoutSec, 45, 5, 300),
    maxLoadSec: int(qc.maxLoadSec, 2, 1, 10),
  };
}

/** 取当前语言的字符串，缺语言回退默认语言，再回退键名本身。 */
export function makeT(spec: NormalizedSpec, locale: string): (key: string) => string {
  const table = spec.strings[locale] ?? spec.strings[spec.defaultLocale] ?? spec.strings.en ?? {};
  return (key: string) => table[key] ?? spec.strings[spec.defaultLocale]?.[key] ?? key;
}
