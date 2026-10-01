// packages/assetkit/src/deps.d.ts — 无类型声明文件的两个上游依赖的最小面声明。
//（sharp 自带类型；fontkit 2.x 与 subset-font 均不随包发 types、@types 侧无对位版本。）

declare module "fontkit" {
  export interface FontkitFont {
    hasGlyphForCodePoint(codePoint: number): boolean;
    fonts?: unknown[];
  }
  export function openSync(src: string): FontkitFont;
  export function open(src: string): Promise<FontkitFont>;
}

declare module "subset-font" {
  export interface SubsetFontOptions {
    targetFormat?: "sfnt" | "truetype" | "woff" | "woff2";
    preserveNameIds?: number[];
    variationAxes?: Record<string, number | { min: number; default: number; max: number }>;
  }
  export default function subsetFont(
    font: Buffer | Uint8Array,
    text: string,
    options?: SubsetFontOptions,
  ): Promise<Buffer>;
}
