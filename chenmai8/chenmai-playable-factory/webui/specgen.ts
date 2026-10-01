// webui/specgen.ts — 表单字段 → PlayableSpec v1 组装器（M10；oracle webui/specgen.py 语义移植）。
//
// 职责：把界面表单（选模板 / 填文案 / 上传 PNG 素材 / 少量高级项）组装成一份
// 能通过 pf 校验（schema v1 + 不变式 I1-I5）的 PlayableSpec dict：
// - 文案：每语言内置一组可改缺省（与 specs-eval/golden、demo-zh 的字符串表同源），
//   用户只填偏差项；任意键留空都回退缺省，保证 I5（每语言五键齐全）恒可满足。
// - seed：表单可留空 → 随机取；match3 用 @pf/spec 不变式的规范生成器预检 I3
//   （初始盘面存在可行步），不可行自动换 seed，提交即过校验。
// - pullpin：orderSolution 由 seed 经 pullpinLevelRoles 实算（中性针升序 + 救援针
//   收尾，与 golden-pullpin 约定一致），并用 pullpinSimulate 复核可解（I1）——
//   校验算法只此一份权威实现（packages/spec/src/invariants.ts），本模块不复制。
// - 素材：上传 PNG 按文件名主干匹配模板槽位键（如 piece-0 / tier-2 / pin），
//   未匹配的按槽位顺序顺延填入；路径相对 spec 文件目录（模板构建器同规）。
// - landingUrl：仅接受 http/https（schema pattern 同规）；服务端从不访问该 URL。
//
// 本模块不做任何网络请求（防 SSRF 纪律，与 oracle 同款）。
// 模板入表口径与 oracle 原状一致：match3/merge/pullpin 三模板；sort 未入表
// （oracle README 预留栏原文"待 specgen 注册后开放"，factory 如实登记同缺口）。

import { randomInt } from "node:crypto";

import {
  match3Board,
  match3FindMove,
  pullpinLevelRoles,
  pullpinSimulate,
} from "../packages/spec/src/invariants.ts";

// 与 pf/src/util.ts TEMPLATE_BUILDERS 对齐：只有接了真实构建器的模板才可入表
//（sort 的构建器在 make 层可用，webui 表单未入表——oracle 原状，登记于 README 预留栏）。
export const TEMPLATES = ["match3", "merge", "pullpin"] as const;

export const TEMPLATE_LABELS: Record<string, string> = {
  match3: "三消", merge: "合成", pullpin: "拔针救援",
};
export const TEMPLATE_TITLES: Record<string, string> = {
  match3: "宝石三消（试玩）",
  merge: "合成大冒险（试玩）",
  pullpin: "拔针救援（试玩）",
};
export const TEMPLATE_GESTURE: Record<string, "tap" | "drag"> = {
  match3: "drag", merge: "drag", pullpin: "tap",
};

/** 各模板可上传替换的精灵槽位键（与模板源码的替换键约定一致）。 */
export const SPRITE_SLOTS: Record<string, string[]> = {
  match3: ["piece-0", "piece-1", "piece-2", "piece-3", "piece-4", "jelly"],
  merge: ["tier-1", "tier-2", "tier-3", "tier-4", "tier-5"],
  pullpin: ["pin", "rescuee", "hazard"],
};

export const LOCALES = ["zh", "en", "ja", "ko", "pt-BR", "de", "ar"] as const;
export const RTL_LOCALES = ["ar"] as const;

export const DEFAULT_LANDING_URL = "https://example.com/playable-lp";
export const DEFAULT_CHANNELS = ["applovin", "meta", "mintegral"];

/** I5 必填五键（@pf/spec REQUIRED_STRING_KEYS 的展示顺序）。 */
export const STRING_KEYS = ["cta", "tutorial", "win", "lose", "score"] as const;

// ---------------------------------------------------------------- 文案缺省表

// cta/win/lose/score 的每语言缺省（与 specs-eval golden 字符串表同源，可改）。
const GENERIC_STRINGS: Record<string, Record<string, string>> = {
  zh: { cta: "立即下载", win: "通关啦！", lose: "再试一次！", score: "得分" },
  en: { cta: "Play Now", win: "You Win!", lose: "Try Again!", score: "Score" },
  ja: { cta: "今すぐ遊ぶ", win: "クリア！", lose: "もう一度！", score: "スコア" },
  ko: { cta: "지금 플레이", win: "성공!", lose: "다시 도전!", score: "점수" },
  "pt-BR": { cta: "Jogue Agora", win: "Você Venceu!", lose: "Tente de Novo!", score: "Pontos" },
  de: { cta: "Jetzt Spielen", win: "Gewonnen!", lose: "Nochmal versuchen!", score: "Punkte" },
  ar: { cta: "العب الآن", win: "لقد فزت!", lose: "حاول مجدداً!", score: "النقاط" },
};

// 教程文案按模板区分（zh/en 全量，其余语言回退 en——表单可改）。
const TUTORIALS: Record<string, Record<string, string>> = {
  match3: {
    zh: "拖动宝石，三个同色连成一线！", en: "Drag to match 3 gems!",
    ja: "ドラッグして3つ揃えよう！", ko: "드래그해서 3개를 맞춰요!",
    "pt-BR": "Arraste para juntar 3!", de: "Ziehe und kombiniere 3!",
    ar: "اسحب لمطابقة 3 جواهر!",
  },
  merge: {
    zh: "拖动同类物品，合成升级！", en: "Drag to merge and upgrade!",
  },
  pullpin: {
    zh: "点击拔出别针，救出小伙伴！", en: "Tap to pull the pin and rescue!",
  },
};

export function localeDefaults(template: string, locale: string): Record<string, string> {
  const generic = GENERIC_STRINGS[locale] ?? GENERIC_STRINGS["en"]!;
  const tutorials = TUTORIALS[template] ?? TUTORIALS["match3"]!;
  const tutorial = tutorials[locale] ?? tutorials["en"]!;
  return { ...generic, tutorial };
}

/** 全量缺省表 {template: {locale: {title + 5 键}}}（/api/meta 一次下发）。 */
export function defaultsTable(): Record<string, Record<string, Record<string, string>>> {
  const out: Record<string, Record<string, Record<string, string>>> = {};
  for (const t of TEMPLATES) {
    out[t] = {};
    for (const loc of LOCALES) {
      out[t]![loc] = { title: TEMPLATE_TITLES[t]!, ...localeDefaults(t, loc) };
    }
  }
  return out;
}

// ---------------------------------------------------------------- 组装

/** 表单不合法：message 列表面向界面直接展示。 */
export class SpecBuildError extends Error {
  messages: string[];
  constructor(messages: string[]) {
    super(messages.join("；"));
    this.messages = messages;
  }
}

export function sanitizeProjectId(raw: string, template: string): string {
  const fallback = `webui-${template}`;
  const cleaned = (raw ?? "")
    .trim().toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-{2,}/g, "-")
    .slice(0, 64);
  if (!cleaned || !/^[a-z0-9]/.test(cleaned)) return fallback;
  return cleaned;
}

function normalizeLandingUrl(raw: string): string {
  const url = (raw ?? "").trim();
  if (!url) return DEFAULT_LANDING_URL;
  if (url.length > 512 || /\s/.test(url) || !/^https?:\/\/\S+$/.test(url)) {
    throw new SpecBuildError([`landingUrl 须为 http/https 绝对地址且不含空白：${JSON.stringify(url)}`]);
  }
  return url;
}

/** 取一个满足 I3（初始盘面存在可行步）的 seed；指定 seed 不合规则报错。 */
function match3Seed(rows: number, cols: number, colors: number, want: number | null): number {
  if (want !== null) {
    if (match3FindMove(match3Board(want, rows, cols, colors)) === null) {
      throw new SpecBuildError(
        [`seed=${want} 生成的 match3 初始盘面无可行步（不变式 I3），请换 seed 或留空随机`]);
    }
    return want;
  }
  for (let i = 0; i < 100; i++) {
    const seed = randomInt(0, 2 ** 31);
    if (match3FindMove(match3Board(seed, rows, cols, colors)) !== null) return seed;
  }
  throw new SpecBuildError(["随机 seed 100 次均无可行步（不应发生，请手填 seed）"]);
}

/** 由 seed 实算每关拔针顺序：中性针升序在前、救援针收尾（golden 同约定），
 *  并用模拟复核可解（I1）。 */
function pullpinOrder(seed: number, levels: number, pins: number): number[][] {
  const order: number[][] = [];
  for (const [rescuee, hazard] of pullpinLevelRoles(seed, levels, pins)) {
    const levelOrder = [] as number[];
    for (let p = 0; p < pins; p++) {
      if (p !== rescuee && p !== hazard) levelOrder.push(p);
    }
    levelOrder.push(rescuee);
    const [solved, reason] = pullpinSimulate(levelOrder, rescuee, hazard);
    if (!solved) {
      // 实算 + 复核双保险（不应发生；发生即组装 bug，宁可失败不可假绿）
      throw new SpecBuildError([`pullpin orderSolution 复核不可解：${reason}`]);
    }
    order.push(levelOrder);
  }
  return order;
}

export interface AssembleSpecOptions {
  projectId?: string;
  title?: string;
  locale?: string;
  texts?: Record<string, string> | null;
  seed?: number | null;
  landingUrl?: string;
  nearWin?: boolean;
  spriteSlots?: Record<string, string> | null;
}

/** 组装一份 PlayableSpec v1 dict；表单不合法抛 SpecBuildError。
 *  spriteSlots：{槽位键: 相对 spec 文件的素材路径}（上传文件落盘后由调用方传入）。 */
export function assembleSpec(template: string, opts: AssembleSpecOptions = {}): Record<string, unknown> {
  const {
    projectId = "", title = "", locale = "zh",
    texts = null, seed = null, landingUrl = "",
    nearWin = true, spriteSlots = null,
  } = opts;
  if (!TEMPLATES.includes(template as typeof TEMPLATES[number])) {
    throw new SpecBuildError([`未知模板：${JSON.stringify(template)}（可选：${TEMPLATES.join(", ")}）`]);
  }
  if (!(LOCALES as readonly string[]).includes(locale)) {
    throw new SpecBuildError([`不支持的语言：${JSON.stringify(locale)}（可选：${LOCALES.join(", ")}）`]);
  }
  const cleanTexts: Record<string, string> = {};
  for (const [k, v] of Object.entries(texts ?? {})) {
    const value = (v ?? "").trim();
    if (!STRING_KEYS.includes(k as typeof STRING_KEYS[number])) {
      throw new SpecBuildError([`未知文案键：${JSON.stringify(k)}`]);
    }
    cleanTexts[k] = value;
  }

  const pid = sanitizeProjectId(projectId, template);
  const finalTitle = title.trim() || TEMPLATE_TITLES[template]!;
  if (finalTitle.length > 80) {
    throw new SpecBuildError(["标题超过 80 字符（schema 上限）"]);
  }

  // match3 参数固定走冻结默认（6×6/15 步/5 色/清果冻 30）——界面只做最小表单，
  // 参数级微调走 spec 上传或 pf CLI。
  const rows = 6;
  const cols = 6;
  const colors = 5;
  const finalSeed = template === "match3"
    ? match3Seed(rows, cols, colors, seed)
    : (seed !== null && seed !== undefined ? seed : randomInt(0, 2 ** 31));

  const slots: Record<string, string> = { ...(spriteSlots ?? {}) };
  for (const [key, rel] of Object.entries(slots)) {
    if (typeof rel !== "string" || !rel) {
      throw new SpecBuildError([`素材槽位 ${JSON.stringify(key)} 路径为空`]);
    }
  }
  for (const key of SPRITE_SLOTS[template]!) {
    if (!(key in slots)) slots[key] = `assets/theme-a/${key}.png`; // 缺省指向主题路径（缺失→程序化贴图）
  }

  const strings = { ...localeDefaults(template, locale) };
  for (const [k, v] of Object.entries(cleanTexts)) {
    if (v) strings[k] = v;
  }
  const rtl = RTL_LOCALES.filter((loc) => loc === locale);

  const params: Record<string, unknown> =
    template === "match3"
      ? {
        cols, rows, moves: 15, colors,
        goalType: "clear-jelly", goalCount: 30,
        spriteKeys: SPRITE_SLOTS["match3"]!.slice(0, 5),
      }
      : template === "merge"
        ? { cols: 5, rows: 5, maxTier: 5, spawnTierMax: 2, goalTier: 4, spriteKeys: SPRITE_SLOTS["merge"] }
        : {
          levels: 3, pinsPerLevel: 3, hazard: "lava", rescuee: "character",
          orderSolution: pullpinOrder(finalSeed, 3, 3),
        };

  const spec: Record<string, unknown> = {
    specVersion: "1.0.0",
    meta: { projectId: pid, title: finalTitle, seed: finalSeed },
    game: {
      template,
      params,
      difficulty: { targetLevel: 0.4 },
      attract: { nearWin: Boolean(nearWin), failBait: false, firstClickSucceed: true },
      durationBudgetSec: { target: 20, max: 30 },
    },
    flow: {
      tutorial: { enabled: true, gesture: TEMPLATE_GESTURE[template], maxSec: 3 },
      endScreen: { showScore: true, ctaKey: "cta", landingUrl: normalizeLandingUrl(landingUrl) },
    },
    assets: {
      background: "assets/theme-a/bg-portrait.png",
      sprites: slots,
      audio: { tap: null, win: null },
    },
    i18n: {
      defaultLocale: locale,
      locales: [locale],
      strings: { [locale]: strings },
      rtl,
    },
    channels: {
      targets: [...DEFAULT_CHANNELS],
      orientation: "portrait",
      overrides: {
        applovin: { maxBytes: 5_242_880, ctaStyle: "banner" },
        meta: { maxBytes: 3_145_728, ctaStyle: "endcard" },
      },
    },
    qc: { maxLoadSec: 3.0, autoplayTimeoutSec: 45 },
  };
  return spec;
}
