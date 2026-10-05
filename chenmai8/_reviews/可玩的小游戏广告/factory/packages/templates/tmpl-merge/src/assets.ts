// 最小素材路径（与 tmpl-match3 同一管线）：spec.assets.sprites 声明的用户 PNG 由
// 构建脚本读出内联进 window.PF_ASSETS；运行期在这里解码、contain 等比归一到
// 96×96 画布，由场景经 textures.addCanvas 注册为该 tier 的贴图——createTextures
// 对已存在的贴图键自动跳过程序化生成，因此"声明并嵌入即替换，未声明/缺失/
// 解码失败即程序化回退"。spriteKey → tier 映射与 createTextures 同源：
// tier i 用 spriteKeys[(i-1) % len]。同一 16×16 取样管线兼作
// __PF_QC__.assets() 的像素对账（渲染贴图 vs 用户 PNG）。

import { tierTexKey } from "./textures.ts";
import type { MergeParams } from "./spec.ts";

/** 归一画布边长（= 程序化贴图尺寸，pieceScale() 以 96 为基准缩放）。 */
export const SPRITE_TEX_SIZE = 96;

/** 像素对账阈值：16×16 平均绝对差 ≤ 此值判定"替换生效"。 */
export const AUDIT_MAD_MAX = 8;

export interface ReplacedSprite {
  /** 引擎贴图键（pf-tier-N，N=tier）。 */
  texKey: string;
  /** spec.assets.sprites 键（如 tier-1）。 */
  spriteKey: string;
  /** 归一化后的画布（贴图真源，同时供像素对账取样）。 */
  canvas: HTMLCanvasElement;
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("图片解码失败"));
    img.src = src;
  });
}

/** contain 等比缩放居中画进 size×size 画布（透明补边）。
 *  解码注册与像素对账都走本函数，保证两侧像素管线一致。 */
export function drawFitted(img: CanvasImageSource, size: number): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas 2d 上下文不可用");
  const w = (img as HTMLImageElement).width || size;
  const h = (img as HTMLImageElement).height || size;
  const k = Math.min(size / w, size / h);
  const dw = Math.max(1, Math.round(w * k));
  const dh = Math.max(1, Math.round(h * k));
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, Math.round((size - dw) / 2), Math.round((size - dh) / 2), dw, dh);
  return canvas;
}

/** 解码 window.PF_ASSETS（构建期内联的用户素材），返回要注册的替换贴图。
 *  单个素材解码失败只告警并跳过（回退程序化贴图），不阻塞启动。 */
export async function decodeReplacedSprites(
  assets: Record<string, string> | undefined | null,
  params: MergeParams,
): Promise<ReplacedSprite[]> {
  if (!assets) return [];
  const decoded = new Map<string, HTMLImageElement | null>();
  const out: ReplacedSprite[] = [];
  for (let tier = 1; tier <= params.maxTier; tier++) {
    const spriteKey = params.spriteKeys[(tier - 1) % params.spriteKeys.length];
    const dataUri = assets[spriteKey];
    if (typeof dataUri !== "string" || !dataUri) continue;
    if (!decoded.has(spriteKey)) {
      try {
        decoded.set(spriteKey, await loadImage(dataUri));
      } catch (err) {
        console.warn(`[pf/tmpl-merge] 素材解码失败，回退程序化贴图: ${spriteKey}`, err);
        decoded.set(spriteKey, null);
      }
    }
    const img = decoded.get(spriteKey);
    if (!img) continue;
    out.push({
      texKey: tierTexKey(tier),
      spriteKey,
      canvas: drawFitted(img, SPRITE_TEX_SIZE),
    });
  }
  return out;
}

/** 像素对账取样：任一画布/图片源降采样到 16×16 的 RGB 数组（忽略 alpha）。 */
function sample16(src: CanvasImageSource): number[] {
  const c = document.createElement("canvas");
  c.width = 16;
  c.height = 16;
  const ctx = c.getContext("2d");
  if (!ctx) throw new Error("canvas 2d 上下文不可用");
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(src, 0, 0, 16, 16);
  const data = ctx.getImageData(0, 0, 16, 16).data;
  const px: number[] = [];
  for (let i = 0; i < data.length; i += 4) {
    px.push(data[i], data[i + 1], data[i + 2]);
  }
  return px;
}

/** 平均绝对差（0-255 标度）。 */
export function meanAbsDiff(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  if (n === 0) return 255;
  let sum = 0;
  for (let i = 0; i < n; i++) sum += Math.abs(a[i] - b[i]);
  return sum / n;
}

/** 解码 data URI 并归一到 SPRITE_TEX_SIZE 画布（对账侧与注册侧同管线）。 */
export async function decodeToCanvas(dataUri: string): Promise<HTMLCanvasElement> {
  return drawFitted(await loadImage(dataUri), SPRITE_TEX_SIZE);
}

export { sample16 };
