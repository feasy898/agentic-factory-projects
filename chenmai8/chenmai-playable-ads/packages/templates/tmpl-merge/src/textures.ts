// 程序化贴图：预览构建不依赖外部图片素材，Boot 阶段用 Graphics 生成 tier 棋子/
// 手势/箭头贴图。tier 形状与色相由 spec 的 spriteKeys 键名决定（键名变化 →
// 形状/配色变化），阶数参与配色偏移与尺寸缩放（高阶更大更亮眼），
// 实现 spec 驱动渲染；maxTier 决定实际生成的 tier 数量。

import * as engine from "./vendor/engine.js";
import type { MergeParams } from "./spec.ts";

export const TIER_TEX_PREFIX = "pf-tier-";
export const TEX_HAND = "pf-hand";
export const TEX_ARROW = "pf-arrow";

const PALETTE = [0xff5a5f, 0xffc145, 0x2ec4b6, 0x4d96ff, 0xb388eb, 0xff8fab, 0x9adf5d];
const SHAPES = ["circle", "diamond", "square", "triangle", "hexagon"] as const;

function hashString(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function shade(color: number, f: number): number {
  const r = Math.min(255, Math.round(((color >> 16) & 0xff) * f));
  const g = Math.min(255, Math.round(((color >> 8) & 0xff) * f));
  const b = Math.min(255, Math.round((color & 0xff) * f));
  return (r << 16) | (g << 8) | b;
}

/** tier → 贴图键（tier 从 1 起）。 */
export function tierTexKey(tier: number): string {
  return TIER_TEX_PREFIX + tier;
}

/** 生成全部贴图；返回 tier → 贴图键 的映射（长度 = maxTier）。 */
export function createTextures(scene: any, params: MergeParams): string[] {
  const size = 96;
  const half = size / 2;
  const texKeys: string[] = [];

  for (let tier = 1; tier <= params.maxTier; tier++) {
    const spriteKey = params.spriteKeys[(tier - 1) % params.spriteKeys.length];
    const h = hashString(spriteKey);
    const shape = SHAPES[h % SHAPES.length];
    const base = PALETTE[(h + tier * 3) % PALETTE.length];
    const texKey = tierTexKey(tier);
    // 高阶更大更饱满（半径随阶增长），高阶加中心芯饰以示"进化"
    const r = Math.min(half - 8, 24 + tier * 4);

    if (!scene.textures.exists(texKey)) {
      const g = new engine.GameObjects.Graphics(scene);
      // 底色主体
      g.fillStyle(shade(base, 0.92), 1);
      drawShape(g, shape, half, half, r);
      // 内部高光
      g.fillStyle(0xffffff, 0.28);
      drawShape(g, shape, half - 5, half - 8, r * 0.45);
      // 描边
      g.lineStyle(4, shade(base, 0.6), 1);
      drawShape(g, shape, half, half, r, true);
      // 高阶中心芯饰（tier ≥ 3）：小菱形点亮
      if (tier >= 3) {
        g.fillStyle(0xffffff, 0.85);
        g.fillTriangle(half, half - r * 0.28, half + r * 0.24, half, half, half + r * 0.28);
        g.fillTriangle(half, half - r * 0.28, half - r * 0.24, half, half, half + r * 0.28);
      }
      g.generateTexture(texKey, size, size);
      g.destroy();
    }
    texKeys.push(texKey);
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
