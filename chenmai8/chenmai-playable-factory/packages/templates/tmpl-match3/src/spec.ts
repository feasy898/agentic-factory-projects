// PlayableSpec（schema v1）→ 模板内部规范化视图（宽容归一）。
// 校验权威在 M1（schema + 不变式）；这里只按规则卡 §1 的钳制表放宽归一，
// 让"LLM 只填偏差项"的 spec 也能直接跑。钳制范围与 schema 不完全一致（模板更宽）。

export interface Match3Params {
  cols: number;
  rows: number;
  moves: number;
  colors: number;
  goalType: "clear-jelly" | "score";
  goalCount: number;
  spriteKeys: string[];
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
  params: Match3Params;
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

/** 参数序 (v, default, min, max)：非数值/非有限取缺省，Math.round 后钳制。 */
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

/** 缺省键名按 2026-09-29 规则卡钉死：恰为 piece-0..piece-4（≥1 个即可覆盖）。 */
const DEFAULT_SPRITE_KEYS = ["piece-0", "piece-1", "piece-2", "piece-3", "piece-4"];

export function normalizeSpec(raw: any): NormalizedSpec {
  const game = raw?.game ?? {};
  const p = game.params ?? {};
  const flow = raw?.flow ?? {};
  const tutorial = flow.tutorial ?? {};
  const endScreen = flow.endScreen ?? {};
  const i18n = raw?.i18n ?? {};
  const qc = raw?.qc ?? {};
  const meta = raw?.meta ?? {};

  const spriteKeysRaw = Array.isArray(p.spriteKeys) ? p.spriteKeys.map(String) : [];
  const spriteKeys = spriteKeysRaw.length >= 1 ? spriteKeysRaw : DEFAULT_SPRITE_KEYS.slice();

  const goalType: "clear-jelly" | "score" = p.goalType === "score" ? "score" : "clear-jelly";

  const strings: Record<string, Record<string, string>> = {};
  const rawStrings = (i18n.strings ?? {}) as Record<string, Record<string, string>>;
  for (const [locale, table] of Object.entries(rawStrings)) {
    if (table && typeof table === "object") strings[locale] = { ...table };
  }

  return {
    projectId: str(meta.projectId, "match3"),
    title: str(meta.title, "Match 3"),
    seed: int(meta.seed, 1, 0, 0x7fffffff),
    params: {
      cols: int(p.cols, 6, 3, 9),
      rows: int(p.rows, 6, 3, 9),
      moves: int(p.moves, 15, 1, 60),
      colors: int(p.colors, 5, 2, 7),
      goalType,
      goalCount: int(p.goalCount, 30, 1, 400),
      spriteKeys,
    },
    difficultyTargetLevel:
      typeof game.difficulty?.targetLevel === "number"
        ? Math.max(0, Math.min(1, game.difficulty.targetLevel))
        : 0.5,
    attract: {
      nearWin: bool(game.attract?.nearWin, false),
      failBait: bool(game.attract?.failBait, false),
      firstClickSucceed: bool(game.attract?.firstClickSucceed, true),
    },
    tutorial: {
      enabled: bool(tutorial.enabled, true),
      gesture: tutorial.gesture === "tap" ? "tap" : "drag",
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

/** 文案三级回退：当前语言 → 默认语言 → en → 键名本身。 */
export function makeT(spec: NormalizedSpec, locale: string): (key: string) => string {
  const table = spec.strings[locale] ?? spec.strings[spec.defaultLocale] ?? spec.strings.en ?? {};
  return (key: string) => table[key] ?? spec.strings[spec.defaultLocale]?.[key] ?? key;
}
