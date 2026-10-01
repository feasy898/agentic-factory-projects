// PlayableSpec（schema v1）→ 模板内部规范化视图（宽容归一，与 tmpl-match3 同纪律）。
// §4.1 merge params 全部带默认值：cols 5 / rows 5 / maxTier 5 / spawnTierMax 2 /
// goalTier 4 / spriteKeys 按 tier 顺序。校验权威在 M1；这里只做宽容归一，
// 并与 schema/invariants 取值范围同向收紧（cols/rows 3-9，maxTier 2-8，
// spawnTierMax < maxTier，goalTier ≤ maxTier）。

export interface MergeParams {
  cols: number;
  rows: number;
  /** 棋子最高阶（含）；tier 取值 1..maxTier。 */
  maxTier: number;
  /** 出生棋子的最高阶（合成补位用），恒 < maxTier。 */
  spawnTierMax: number;
  /** 目标阶：盘面出现该阶棋子即胜。 */
  goalTier: number;
  /** 按 tier 顺序的精灵键（spriteKeys[i] 对应 tier i+1，不足循环取用）。 */
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
  params: MergeParams;
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

/** 缺省键名按 tier 顺序：tier-1..tier-5。 */
const DEFAULT_SPRITE_KEYS = ["tier-1", "tier-2", "tier-3", "tier-4", "tier-5"];

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

  const maxTier = int(p.maxTier, 5, 2, 8);
  // spawnTierMax < maxTier；goalTier ≤ maxTier（与校验器不变式同向收紧）。
  const spawnTierMax = Math.min(int(p.spawnTierMax, 2, 1, 8), maxTier - 1);
  const goalTier = Math.min(int(p.goalTier, 4, 2, 8), maxTier);

  const strings: Record<string, Record<string, string>> = {};
  const rawStrings = (i18n.strings ?? {}) as Record<string, Record<string, string>>;
  for (const [locale, table] of Object.entries(rawStrings)) {
    if (table && typeof table === "object") strings[locale] = { ...table };
  }

  return {
    projectId: str(meta.projectId, "merge"),
    title: str(meta.title, "Merge"),
    seed: int(meta.seed, 1, 0, 0x7fffffff),
    params: {
      cols: int(p.cols, 5, 3, 9),
      rows: int(p.rows, 5, 3, 9),
      maxTier,
      spawnTierMax,
      goalTier,
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
