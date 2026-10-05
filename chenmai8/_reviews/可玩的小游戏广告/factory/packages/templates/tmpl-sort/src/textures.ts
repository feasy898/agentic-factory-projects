// 程序化贴图：预览构建不依赖外部图片素材，Boot 阶段用 Graphics 生成试管/螺栓、
// 圆盘/螺母、教程手势等贴图。screwMode 分支驱动两套形体：普通=玻璃试管+圆盘，
// 拧螺丝=金属螺栓+六角螺母；形体由 spec.params.screwMode 决定（spec 驱动渲染）。
// 贴图本体以白色/灰阶绘制，运行期经 setTint 着色——同一张贴图服务全部颜色，
// 用户替换素材（构建期内联 PF_ASSETS）注册同名贴图后此处自动跳过。

import * as engine from "./vendor/engine.js";

/** 用户替换素材（spec.assets.sprites 固定键）→ 引擎贴图键。 */
export const USER_TEX_KEYS = {
  rod: "pf-user-rod",
  piece: "pf-user-piece",
} as const;

export const TEX_ROD_TUBE = "pf-rod-tube";
export const TEX_ROD_BOLT = "pf-rod-bolt";
export const TEX_PIECE_DISC = "pf-piece-disc";
export const TEX_PIECE_NUT = "pf-piece-nut";
export const TEX_HAND = "pf-hand";
export const TEX_RING = "pf-ring";

/** 贴图基准尺寸：柱体宽 96×高 384；棋子 96×96（场景按 cell 缩放）。 */
export const ROD_TEX_W = 96;
export const ROD_TEX_H = 384;
export const PIECE_TEX_SIZE = 96;

function shade(color: number, f: number): number {
  const r = Math.min(255, Math.round(((color >> 16) & 0xff) * f));
  const g = Math.min(255, Math.round(((color >> 8) & 0xff) * f));
  const b = Math.min(255, Math.round((color & 0xff) * f));
  return (r << 16) | (g << 8) | b;
}

/** 玻璃试管（普通模式柱体）：半透明管身 + 高光 + 加厚管口/管底。 */
function makeTube(scene: any, texKey: string): void {
  const w = ROD_TEX_W;
  const h = ROD_TEX_H;
  const g = new engine.GameObjects.Graphics(scene);
  g.fillStyle(0xffffff, 0.14);
  g.fillRoundedRect(6, 6, w - 12, h - 12, 20);
  g.fillStyle(0xffffff, 0.1);
  g.fillRoundedRect(14, 14, 14, h - 60, 12); // 左侧高光条
  g.lineStyle(5, 0xffffff, 0.85);
  g.strokeRoundedRect(6, 6, w - 12, h - 12, 20);
  g.fillStyle(0xffffff, 0.4);
  g.fillRoundedRect(2, 2, w - 4, 18, 9); // 管口
  g.fillRoundedRect(2, h - 20, w - 4, 18, 9); // 管底
  g.generateTexture(texKey, w, h);
  g.destroy();
}

/** 金属螺栓（拧螺丝模式柱体）：柱身 + 螺纹横杠 + 上下法兰。 */
function makeBolt(scene: any, texKey: string): void {
  const w = ROD_TEX_W;
  const h = ROD_TEX_H;
  const g = new engine.GameObjects.Graphics(scene);
  g.fillStyle(0xb9c2d8, 1);
  g.fillRoundedRect(24, 4, w - 48, h - 8, 10);
  g.fillStyle(0x8d99ae, 1);
  for (let y = 26; y < h - 24; y += 26) {
    g.fillRoundedRect(24, y, w - 48, 9, 4); // 螺纹
  }
  g.fillStyle(0xdfe6ff, 0.55);
  g.fillRoundedRect(30, 10, 8, h - 24, 4); // 高光
  g.fillStyle(0x8d99ae, 1);
  g.fillRoundedRect(8, h - 26, w - 16, 22, 8); // 底法兰
  g.fillStyle(0xdfe6ff, 0.7);
  g.fillRoundedRect(14, 2, w - 28, 14, 7); // 顶帽
  g.generateTexture(texKey, w, h);
  g.destroy();
}

/** 圆盘（普通模式棋子）：白色基调 + 环沿/高光（运行期 setTint 着色）。 */
function makeDisc(scene: any, texKey: string): void {
  const s = PIECE_TEX_SIZE;
  const c = s / 2;
  const g = new engine.GameObjects.Graphics(scene);
  g.fillStyle(shade(0xffffff, 0.62), 1);
  g.fillEllipse(c, c + 6, s - 10, s - 22); // 底沿阴影
  g.fillStyle(0xffffff, 1);
  g.fillEllipse(c, c, s - 10, s - 26);
  g.fillStyle(shade(0xffffff, 0.82), 1);
  g.fillEllipse(c, c + 2, s - 22, s - 40); // 内环
  g.fillStyle(0xffffff, 1);
  g.fillEllipse(c - 10, c - 10, 22, 10); // 高光
  g.generateTexture(texKey, s, s);
  g.destroy();
}

/** 六角螺母（拧螺丝模式棋子）：六角白坯 + 深色内孔 + 高光。 */
function makeNut(scene: any, texKey: string): void {
  const s = PIECE_TEX_SIZE;
  const c = s / 2;
  const rOuter = c - 8;
  const g = new engine.GameObjects.Graphics(scene);
  // 六角坯：中心扇三角拼合
  g.fillStyle(0xffffff, 1);
  for (let k = 0; k < 6; k++) {
    const a1 = (Math.PI / 3) * k - Math.PI / 2;
    const a2 = (Math.PI / 3) * (k + 1) - Math.PI / 2;
    g.fillTriangle(
      c, c,
      c + Math.cos(a1) * rOuter, c + Math.sin(a1) * rOuter,
      c + Math.cos(a2) * rOuter, c + Math.sin(a2) * rOuter,
    );
  }
  // 立体感：上半亮、下半暗（两块半区再描一次）
  g.fillStyle(shade(0xffffff, 0.86), 1);
  for (let k = 0; k < 6; k++) {
    const a1 = (Math.PI / 3) * k - Math.PI / 2;
    const a2 = (Math.PI / 3) * (k + 1) - Math.PI / 2;
    g.fillTriangle(
      c, c,
      c + Math.cos(a1) * rOuter * 0.78, c + Math.sin(a1) * rOuter * 0.78,
      c + Math.cos(a2) * rOuter * 0.78, c + Math.sin(a2) * rOuter * 0.78,
    );
  }
  g.fillStyle(0x2a3350, 1);
  g.fillCircle(c, c, rOuter * 0.42); // 内孔
  g.fillStyle(0x141b34, 1);
  g.fillCircle(c, c, rOuter * 0.3);
  g.fillStyle(0xffffff, 0.85);
  g.fillCircle(c - rOuter * 0.45, c - rOuter * 0.5, 6); // 高光
  g.generateTexture(texKey, s, s);
  g.destroy();
}

function makeHand(scene: any): void {
  if (scene.textures.exists(TEX_HAND)) return;
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

function makeRing(scene: any): void {
  if (scene.textures.exists(TEX_RING)) return;
  const g = new engine.GameObjects.Graphics(scene);
  g.lineStyle(6, 0xffffff, 0.95);
  g.strokeCircle(48, 48, 40);
  g.generateTexture(TEX_RING, 96, 96);
  g.destroy();
}

/** 生成全部贴图（已存在的键自动跳过——用户替换素材先注册即生效）。
 *  screwMode=true 生成螺栓+螺母，false 生成试管+圆盘。 */
export function createTextures(scene: any, screwMode: boolean): void {
  if (screwMode) {
    if (!scene.textures.exists(TEX_ROD_BOLT)) makeBolt(scene, TEX_ROD_BOLT);
    if (!scene.textures.exists(TEX_PIECE_NUT)) makeNut(scene, TEX_PIECE_NUT);
  } else {
    if (!scene.textures.exists(TEX_ROD_TUBE)) makeTube(scene, TEX_ROD_TUBE);
    if (!scene.textures.exists(TEX_PIECE_DISC)) makeDisc(scene, TEX_PIECE_DISC);
  }
  makeHand(scene);
  makeRing(scene);
}

/** 当前模式的柱体贴图键。 */
export function rodTexture(screwMode: boolean): string {
  return screwMode ? TEX_ROD_BOLT : TEX_ROD_TUBE;
}

/** 当前模式的棋子贴图键。 */
export function pieceTexture(screwMode: boolean): string {
  return screwMode ? TEX_PIECE_NUT : TEX_PIECE_DISC;
}

/** 8 色调色板（colors 上限 8；运行期 setTint 着色到棋子白坯上）。 */
export const PALETTE: number[] = [
  0xef476f, 0x06d6a0, 0x118ab2, 0xffd166,
  0x9b5de5, 0xf4840a, 0x4cc9f0, 0xc0eb6a,
];
