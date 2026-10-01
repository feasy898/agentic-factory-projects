/**
 * PlayableSpec v1.0.0 —— TS 类型契约（与 playable-spec.schema.json 一一对应）。
 *
 * 本文件是 packages/spec 公开类型面：模板（M3）、打包器（M4）与 Web UI 等
 * TS 侧消费者一律从这里 import 类型，不自行重复声明。
 * 可选字段 = schema 中带 default 的字段（缺省时由校验器/模板按默认值解析）。
 */

export type SpecVersion = "1.0.0";

export type Template = "match3" | "merge" | "pullpin" | "sort";
export type ChannelId =
  | "applovin"
  | "unity"
  | "google"
  | "meta"
  | "tiktok"
  | "mintegral";
export type Gesture = "tap" | "drag";
export type Orientation = "portrait" | "landscape" | "both";
export type Palette = "A" | "B" | "C";

export interface Meta {
  projectId: string;
  title: string;
  /** 确定性随机种子：盘面/布局由规范生成器（pfcore invariants 与本包
   *  src/invariants.mjs 同源实现）从它导出。 */
  seed: number;
}

// ---------------------------------------------------------------- 模板 params

export interface Match3Params {
  cols?: number;
  rows?: number;
  moves?: number;
  colors?: number;
  goalType?: "clear-jelly" | "score";
  goalCount?: number;
  spriteKeys?: string[];
}

export interface MergeParams {
  cols?: number;
  rows?: number;
  maxTier?: number;
  spawnTierMax?: number;
  goalTier?: number;
  spriteKeys?: string[];
}

export interface PullpinParams {
  levels?: number;
  pinsPerLevel?: number;
  hazard?: "lava" | "spike";
  rescuee?: "character";
  /** 每关拔针顺序（针下标互不重复，值 < pinsPerLevel）；长度须等于 levels。 */
  orderSolution?: number[][];
}

export interface SortParams {
  rods?: number;
  layersPerRod?: number;
  colors?: number;
  screwMode?: boolean;
  moveLimit?: number;
}

export type TemplateParams =
  | Match3Params
  | MergeParams
  | PullpinParams
  | SortParams;

export interface Difficulty {
  targetLevel: number; // 0..1
}

export interface Attract {
  nearWin?: boolean;
  failBait?: boolean;
  firstClickSucceed?: boolean;
}

export interface DurationBudgetSec {
  target: number; // 5..30，默认 20
  max: number; // 5..30，默认 30；不变式 I4：max <= 30
}

// ---------------------------------------------------------------- game / flow

export interface GameSpec {
  template: Template;
  params: TemplateParams;
  difficulty?: Difficulty;
  attract?: Attract;
  durationBudgetSec: DurationBudgetSec;
}

/** 按 template 收窄的判别联合（模板侧实现用）。 */
export type Match3Game = GameSpec & { template: "match3"; params: Match3Params };
export type MergeGame = GameSpec & { template: "merge"; params: MergeParams };
export type PullpinGame = GameSpec & { template: "pullpin"; params: PullpinParams };
export type SortGame = GameSpec & { template: "sort"; params: SortParams };
export type TypedGame = Match3Game | MergeGame | PullpinGame | SortGame;

export interface Tutorial {
  enabled: boolean;
  gesture?: Gesture;
  maxSec?: number;
}

export interface EndScreen {
  showScore?: boolean;
  /** CTA 文案的 i18n 键（每语言 strings 须含它）。 */
  ctaKey: string;
  /** 落地页 URL；打包产物内唯一允许出现的外链。 */
  landingUrl: string;
}

export interface Flow {
  tutorial: Tutorial;
  endScreen: EndScreen;
}

// ---------------------------------------------------------------- assets

export interface AudioAssets {
  tap?: string | null;
  win?: string | null;
}

export interface Assets {
  background: string;
  sprites: Record<string, string>;
  audio: AudioAssets;
  fontSubset?: string;
}

// ---------------------------------------------------------------- i18n

export interface LocaleStrings {
  cta: string;
  tutorial: string;
  win: string;
  lose: string;
  score: string;
  /** 允许业务自定义扩展键（值为非空字符串）。 */
  [extra: string]: string;
}

export interface I18n {
  defaultLocale: string;
  locales: string[];
  strings: Record<string, LocaleStrings>;
  rtl?: string[];
}

// ---------------------------------------------------------------- channels / qc

export interface ChannelOverride {
  maxBytes?: number;
  ctaStyle?: string;
}

export interface ChannelsSpec {
  targets: ChannelId[];
  orientation: Orientation;
  overrides?: Record<string, ChannelOverride>;
}

export interface Variant {
  id: string;
  /** 变体覆盖 meta.seed（打包期生效）。 */
  seed?: number;
  palette?: Palette;
}

export interface QC {
  maxLoadSec: number; // 默认 2.0
  autoplayTimeoutSec: number; // 默认 45
}

// ---------------------------------------------------------------- 根对象

export interface PlayableSpec {
  specVersion: SpecVersion;
  meta: Meta;
  game: GameSpec;
  flow: Flow;
  assets: Assets;
  i18n: I18n;
  channels: ChannelsSpec;
  variants?: Variant[];
  qc: QC;
}

// ---------------------------------------------------------------- 校验结果

/** 校验问题：path 为 json-path 风格字段路径（如 "$.game.params.orderSolution[0]"）。 */
export interface SpecError {
  path: string;
  message: string;
  code: string;
}

export interface ValidateResult {
  ok: boolean;
  errors: SpecError[];
}
