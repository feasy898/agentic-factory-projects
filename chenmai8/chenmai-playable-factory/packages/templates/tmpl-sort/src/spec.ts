// PlayableSpec（schema v1）→ 模板内部规范化视图（sort 子 schema，§4.1 冻结）。
// params：rods(4) / layersPerRod(4) / colors(4) / screwMode(bool 拧螺丝变体) /
// moveLimit（步数预算；冻结表未给默认值，模板默认 0=不限步——排序类可玩广告
// 不设败局，提供时严格生效，耗尽即败）。colors ≤ rods 的可解性归 M1 不变式
// I2 强制，这里只做宽容归一（LLM 只填偏差项也能跑）。
// 校验由 @pf/spec 负责。

export interface SortParams {
  rods: number;
  layersPerRod: number;
  colors: number;
  screwMode: boolean;
  /** 0 = 不限步数（默认）；>0 = 全局倾倒步数预算，耗尽即败。 */
  moveLimit: number;
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
  params: SortParams;
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

  // colors ≤ rods 由 M1 I2 强制；模板侧钳制保证渲染恒良构（防御坏 spec）。
  const rods = int(p.rods, 4, 2, 8);
  const colors = Math.min(int(p.colors, 4, 2, 8), rods);
  const layersPerRod = int(p.layersPerRod, 4, 2, 6);
  const moveLimit = int(p.moveLimit, 0, 0, 200);

  const strings: Record<string, Record<string, string>> = {};
  const rawStrings = (i18n.strings ?? {}) as Record<string, Record<string, string>>;
  for (const [locale, table] of Object.entries(rawStrings)) {
    if (table && typeof table === "object") strings[locale] = { ...table };
  }

  return {
    projectId: str(meta.projectId, "sort"),
    title: str(meta.title, "Sort Puzzle"),
    seed: int(meta.seed, 1, 0, 0x7fffffff),
    params: { rods, layersPerRod, colors, screwMode: bool(p.screwMode, false), moveLimit },
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
