// 程序化贴图：预览构建不依赖外部图片素材，Boot 阶段用 Graphics 生成救援针/
// 机关针/中性针旋钮、角色、熔岩、刺球、教程手势等贴图。角色/机关的形状与
// 配色由 spec 的 params.hazard 等决定（hazard 变 → 机关贴图变），实现 spec
// 驱动渲染；用户替换素材（构建期内联 PF_ASSETS）注册同名贴图后此处自动跳过。

import * as engine from "./vendor/engine.js";

/** 用户替换素材（spec.assets.sprites 固定键）→ 引擎贴图键。 */
export const USER_TEX_KEYS = {
  pin: "pf-user-pin",
  rescuee: "pf-user-rescuee",
  hazard: "pf-user-hazard",
} as const;

export const TEX_KNOB_NEUTRAL = "pf-knob-neutral";
export const TEX_KNOB_RESCUEE = "pf-knob-rescuee";
export const TEX_KNOB_HAZARD = "pf-knob-hazard";
export const TEX_RESCUEE = "pf-rescuee";
export const TEX_LAVA = "pf-lava";
export const TEX_SPIKE = "pf-spike";
export const TEX_HAND = "pf-hand";
export const TEX_RING = "pf-ring";

const KNOB_SIZE = 56;

function shade(color: number, f: number): number {
  const r = Math.min(255, Math.round(((color >> 16) & 0xff) * f));
  const g = Math.min(255, Math.round(((color >> 8) & 0xff) * f));
  const b = Math.min(255, Math.round((color & 0xff) * f));
  return (r << 16) | (g << 8) | b;
}

function makeKnob(scene: any, texKey: string, base: number, ring: number): void {
  if (scene.textures.exists(texKey)) return;
  const c = KNOB_SIZE / 2;
  const g = new engine.GameObjects.Graphics(scene);
  g.fillStyle(shade(base, 0.55), 1);
  g.fillCircle(c, c, c - 3);
  g.fillStyle(base, 1);
  g.fillCircle(c, c, c - 7);
  g.fillStyle(0xffffff, 0.4);
  g.fillCircle(c - 7, c - 9, 7);
  g.lineStyle(3, ring, 0.95);
  g.strokeCircle(c, c, c - 5);
  g.generateTexture(texKey, KNOB_SIZE, KNOB_SIZE);
  g.destroy();
}

/** 生成全部贴图（已存在的键自动跳过——用户替换素材先注册即生效）。 */
export function createTextures(scene: any, hazard: "lava" | "spike"): void {
  makeKnob(scene, TEX_KNOB_NEUTRAL, 0x8d99ae, 0xdfe6ff);
  makeKnob(scene, TEX_KNOB_RESCUEE, 0x2ec46e, 0xd8ffe8);
  makeKnob(scene, TEX_KNOB_HAZARD, hazard === "lava" ? 0xff5a3c : 0xff8f3c, 0xffe0d0);

  if (!scene.textures.exists(TEX_RESCUEE)) {
    // 小圆人：身体 + 眼睛 + 张开呼救的手
    const g = new engine.GameObjects.Graphics(scene);
    g.fillStyle(0xffd166, 1);
    g.fillCircle(32, 26, 15); // 头
    g.fillStyle(0x4d96ff, 1);
    g.fillRoundedRect(18, 38, 28, 24, 10); // 身体
    g.fillStyle(0x22283a, 1);
    g.fillCircle(27, 24, 2.6);
    g.fillCircle(37, 24, 2.6);
    g.fillStyle(0xffd166, 1);
    g.fillCircle(12, 46, 5); // 手
    g.fillCircle(52, 46, 5);
    g.generateTexture(TEX_RESCUEE, 64, 64);
    g.destroy();
  }

  if (hazard === "lava" && !scene.textures.exists(TEX_LAVA)) {
    // 熔岩块：橙红底 + 亮纹
    const g = new engine.GameObjects.Graphics(scene);
    g.fillStyle(0xd93a1f, 1);
    g.fillRoundedRect(0, 0, 64, 64, 8);
    g.fillStyle(0xff8f3c, 1);
    g.fillEllipse(20, 22, 26, 12);
    g.fillEllipse(46, 42, 22, 10);
    g.fillStyle(0xffc145, 0.9);
    g.fillEllipse(30, 34, 12, 6);
    g.generateTexture(TEX_LAVA, 64, 64);
    g.destroy();
  }

  if (hazard === "spike" && !scene.textures.exists(TEX_SPIKE)) {
    // 刺球：圆 + 一圈尖刺
    const g = new engine.GameObjects.Graphics(scene);
    g.fillStyle(0xb4642a, 1);
    for (let k = 0; k < 10; k++) {
      const a = (Math.PI * 2 * k) / 10;
      const x1 = 48 + Math.cos(a) * 30;
      const y1 = 48 + Math.sin(a) * 30;
      const a2 = a + 0.28;
      const a3 = a - 0.28;
      g.fillTriangle(x1, y1, 48 + Math.cos(a2) * 40, 48 + Math.sin(a2) * 40, 48 + Math.cos(a3) * 40, 48 + Math.sin(a3) * 40);
    }
    g.fillStyle(0x8d5a2b, 1);
    g.fillCircle(48, 48, 30);
    g.fillStyle(0x6e441f, 1);
    g.fillCircle(40, 40, 8);
    g.generateTexture(TEX_SPIKE, 96, 96);
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

  if (!scene.textures.exists(TEX_RING)) {
    const g = new engine.GameObjects.Graphics(scene);
    g.lineStyle(6, 0xffffff, 0.95);
    g.strokeCircle(48, 48, 40);
    g.generateTexture(TEX_RING, 96, 96);
    g.destroy();
  }
}
