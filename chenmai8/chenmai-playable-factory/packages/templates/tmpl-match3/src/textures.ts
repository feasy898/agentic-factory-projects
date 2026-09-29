// 程序化贴图（规则卡 §11）：预览构建零外部素材，Boot 阶段用 Graphics 生成
// 棋子/果冻/手势/箭头贴图。棋子形状与配色由 spec.spriteKeys 键名经 FNV-1a 驱动
// （键名变 → 画面变），colors 决定实际使用的键数量（按 i % len 循环取键）。
//
// 冻结面（2026-09-29 回炉钉死）：FNV-1a 2166136261/16777619；形状枚举序
// circle → diamond → square → triangle → hexagon；调色板 7 色表。

import * as engine from "./vendor/engine.js";
import type { Match3Params } from "./spec.ts";

export const GEM_TEX_PREFIX = "gem-";
export const TEX_JELLY = "pf-jelly";
export const TEX_HAND = "pf-hand";
export const TEX_ARROW = "pf-arrow";

const PALETTE = [0xff5a5f, 0xffc145, 0x2ec4b6, 0x4d96ff, 0xb388eb, 0xff8fab, 0x9adf5d];
const SHAPES = ["circle", "diamond", "square", "triangle", "hexagon"] as const;

/** FNV-1a（逐字符 h ^= c; h = imul(h, 16777619)，最终 >>> 0）。 */
export function hashString(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** 逐通道乘系数后取整回 RGB（高光/描边明暗用）。 */
function shade(color: number, f: number): number {
  const r = Math.min(255, Math.round(((color >> 16) & 0xff) * f));
  const g = Math.min(255, Math.round(((color >> 8) & 0xff) * f));
  const b = Math.min(255, Math.round((color & 0xff) * f));
  return (r << 16) | (g << 8) | b;
}

/** 生成全部贴图；返回棋子贴图键数组（长度 = colors，键名按 i % spriteKeys.length）。 */
export function createTextures(scene: any, params: Match3Params): string[] {
  const size = 96;
  const half = size / 2;
  const texKeys: string[] = [];

  for (let i = 0; i < params.colors; i++) {
    const spriteKey = params.spriteKeys[i % params.spriteKeys.length];
    const h = hashString(spriteKey);
    const shape = SHAPES[h % SHAPES.length];
    const base = PALETTE[(h + i) % PALETTE.length];
    const texKey = GEM_TEX_PREFIX + i;

    if (!scene.textures.exists(texKey)) {
      const g = new engine.GameObjects.Graphics(scene);
      g.fillStyle(shade(base, 0.92), 1); // 底色主体
      drawShape(g, shape, half, half, half - 12);
      g.fillStyle(0xffffff, 0.28); // 内部高光
      drawShape(g, shape, half - 6, half - 10, (half - 12) * 0.45);
      g.lineStyle(4, shade(base, 0.6), 1); // 描边
      drawShape(g, shape, half, half, half - 12, true);
      g.generateTexture(texKey, size, size);
      g.destroy();
    }
    texKeys.push(texKey);
  }

  if (!scene.textures.exists(TEX_JELLY)) {
    const g = new engine.GameObjects.Graphics(scene);
    g.fillStyle(0x9ad7ff, 0.45);
    g.fillRoundedRect(3, 3, size - 6, size - 6, 14);
    g.lineStyle(3, 0xdff3ff, 0.9);
    g.strokeRoundedRect(3, 3, size - 6, size - 6, 14);
    g.generateTexture(TEX_JELLY, size, size);
    g.destroy();
  }

  if (!scene.textures.exists(TEX_HAND)) {
    const g = new engine.GameObjects.Graphics(scene);
    g.fillStyle(0xffffff, 0.95);
    g.fillCircle(32, 32, 22);
    g.fillStyle(0x1b2440, 1);
    g.fillCircle(32, 32, 15);
    g.fillStyle(0xffffff, 0.95);
    g.fillCircle(32, 32, 9);
    g.generateTexture(TEX_HAND, 64, 64);
    g.destroy();
  }

  if (!scene.textures.exists(TEX_ARROW)) {
    const g = new engine.GameObjects.Graphics(scene);
    g.fillStyle(0xffffff, 0.95);
    g.fillTriangle(10, 8, 10, 40, 42, 24);
    g.generateTexture(TEX_ARROW, 48, 48);
    g.destroy();
  }

  return texKeys;
}

function drawShape(
  g: any,
  shape: (typeof SHAPES)[number],
  cx: number,
  cy: number,
  r: number,
  stroke = false,
): void {
  switch (shape) {
    case "circle":
      if (stroke) g.strokeCircle(cx, cy, r);
      else g.fillCircle(cx, cy, r);
      break;
    case "diamond": {
      const pts = [
        [cx, cy - r],
        [cx + r, cy],
        [cx, cy + r],
        [cx - r, cy],
      ];
      pathPoly(g, pts, stroke);
      break;
    }
    case "square": {
      const k = r * 0.82;
      if (stroke) g.strokeRoundedRect(cx - k, cy - k, k * 2, k * 2, 14);
      else g.fillRoundedRect(cx - k, cy - k, k * 2, k * 2, 14);
      break;
    }
    case "triangle": {
      const pts = [
        [cx, cy - r],
        [cx + r * 0.95, cy + r * 0.75],
        [cx - r * 0.95, cy + r * 0.75],
      ];
      pathPoly(g, pts, stroke);
      break;
    }
    case "hexagon": {
      const pts: number[][] = [];
      for (let k = 0; k < 6; k++) {
        const a = (Math.PI / 3) * k - Math.PI / 6;
        pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
      }
      pathPoly(g, pts, stroke);
      break;
    }
  }
}

function pathPoly(g: any, pts: number[][], stroke: boolean): void {
  g.beginPath();
  g.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) g.lineTo(pts[i][0], pts[i][1]);
  g.closePath();
  if (stroke) g.strokePath();
  else g.fillPath();
}
