// 拔针救援主场景：spec 驱动渲染 + 教程→游玩→结束页全流程 + attract 参数 +
// window.__PF_QC__ 背书的最优步提示。事件与相位一律经 engine-bridge 的
// window.PF（契约 §4.2），音频一律经 PF.audio（首交互前强制静音）。
//
// 玩法语义（与 @pf/spec 冻结不变式 I1 同源，见 levels.ts）：
//   - 每关恰有一个救援针（拔掉即角色逃出，过关）与一个机关针（先于救援针
//     拔掉 → 角色遇难 → 本关重置重试），其余为中性针（引流，随时可拔）。
//   - 错序（先拔机关针）失败不终局：本关重置重试，pf:end 只由"全部关卡救出"
//     的真实逻辑触达（win 恒为 true——可玩广告不设败局）。
//   - attract.nearWin：最后一关首次拔救援针时"险些失败"一次（针拔出一半、
//     机关涌出逼近角色、针弹回），随后再拔即成——经典"差一点"广告话术；
//     attract.failBait：首次游玩拔针以同样的真实弹回失败一次。
//     （nearWin 行为探针语义，模板资产 spec §7.2 冻结：失败呈现不消耗任何
//     资源，__PF_QC__.hint() 始终返回真实救援针坐标不变，pf:end 仍只由真实
//     通关逻辑触达一次 win=true——QC 的 CHK07 判定依据。）
//   - hint() 恒返回当前关救援针的真实坐标（直接拔救援针必过关——与 M1
//     pullpin_simulate 的判定一致），QC 用真实 pointer 事件点按即可通关。
//
// 坐标约定：画布固定铺满视口（世界坐标 = CSS 像素），hint() 直接给视口坐标。

import * as engine from "./vendor/engine.js";
import type { PFGlobal } from "@pf/engine-bridge";
import { makeT, type NormalizedSpec } from "./spec.ts";
import { effectiveOrders, pullpinLevelRoles, type LevelRoles } from "./levels.ts";
import { createGameAudio, type GameAudio } from "./audio.ts";
import {
  createTextures,
  TEX_HAND,
  TEX_KNOB_HAZARD,
  TEX_KNOB_NEUTRAL,
  TEX_KNOB_RESCUEE,
  TEX_LAVA,
  TEX_RESCUEE,
  TEX_RING,
  TEX_SPIKE,
} from "./textures.ts";
import {
  AUDIT_MAD_MAX,
  decodeToCanvas,
  meanAbsDiff,
  sample16,
  type ReplacedSprite,
} from "./assets.ts";

const STONE = 0x39435f;
const STONE_DARK = 0x2b3450;
const GROUND = 0x232c47;

type PinRole = "rescuee" | "hazard" | "neutral";

interface PinView {
  index: number;
  role: PinRole;
  pulled: boolean;
  animating: boolean;
  knob: any;
  rod: any;
  /** 旋钮当前位置（视口 CSS 像素；拔出后随动画更新）。 */
  knobX: number;
  knobY: number;
  /** 锚点（针塞入洞口的位置）。 */
  anchorX: number;
  anchorY: number;
}

interface Slot {
  knobX: number;
  knobY: number;
  anchorX: number;
  anchorY: number;
}

export class PullpinScene extends engine.Scene {
  private readonly spec: NormalizedSpec;
  private readonly pf: PFGlobal;
  private readonly replacedSprites: ReplacedSprite[];
  /** 已渲染到画布的文案登记表（__PF_QC__.texts()/textStates() 上报）。 */
  private readonly seenTexts = new Map<string, any>();

  private rolesCache: LevelRoles[] = [];
  private orders: number[][] = [];

  private level = 0;
  private score = 0;
  private busy = false;
  private ended = false;
  private endScreenShown = false;
  private tutorialActive = false;
  private tutorialDone = false;
  private tutorialTimer: any = null;
  private tutorialGroup: any = null;
  private demoPinIndex = -1;
  private nearWinUsed = false;
  private baitUsed = false;
  private firstPlayPullDone = false;

  private levelGroup: any = null;
  private terrain: any = null;
  private lavaG: any = null;
  private hazardBall: any = null;
  private character: any = null;
  private door: any = null;
  private pins: PinView[] = [];
  private lavaLevel = 1;
  private overlayLayer: any = null;

  private levelText: any = null;
  private scoreText: any = null;
  private titleText: any = null;
  private dotsG: any = null;
  private t: (key: string) => string;
  private audio: GameAudio | null = null;

  constructor(spec: NormalizedSpec, pf: PFGlobal, replacedSprites: ReplacedSprite[] = []) {
    super("main");
    this.spec = spec;
    this.pf = pf;
    this.replacedSprites = replacedSprites;
    this.t = makeT(spec, pf.locale);
  }

  // ---------------------------------------------------------------- 生命周期

  create(): void {
    // 最小素材路径：先注册用户替换贴图（同名键已存在时 createTextures 自动跳过）。
    for (const r of this.replacedSprites) {
      if (!this.textures.exists(r.texKey)) this.textures.addCanvas(r.texKey, r.canvas);
    }
    createTextures(this, this.spec.params.hazard);
    this.audio = createGameAudio(this.pf.audio);

    // 关卡角色：seed 确定性生成（与 @pf/spec 校验器同源），拔针方案优先取 spec 的
    // orderSolution（M1 已验证可解），形状不安全时回退规范解。
    const p = this.spec.params;
    this.rolesCache = pullpinLevelRoles(this.spec.seed, p.levels, p.pinsPerLevel);
    this.orders = effectiveOrders(p.orderSolution, this.rolesCache, p.pinsPerLevel);

    this.overlayLayer = this.add.container(0, 0).setDepth(50);

    this.buildHud();
    this.buildLevel(0);

    this.scale.on("resize", () => {
      if (!this.busy) this.relayout();
    });

    if (this.spec.tutorial.enabled) {
      this.enterTutorial();
    } else {
      this.startPlay();
    }
  }

  // ---------------------------------------------------------------- 布局

  /** 视口相关尺寸基准：短边比例尺 + 关键部位坐标（视口分数）。 */
  private s(): number {
    return Math.max(0.55, Math.min(2, Math.min(this.scale.width / 390, this.scale.height / 700)));
  }

  private slotFor(role: PinRole, neutralOrdinal: number): Slot {
    const w = this.scale.width;
    const h = this.scale.height;
    if (role === "hazard") {
      return { knobX: 0.5 * w, knobY: 0.4 * h, anchorX: 0.5 * w, anchorY: 0.29 * h };
    }
    if (role === "rescuee") {
      return { knobX: 0.735 * w, knobY: 0.66 * h, anchorX: 0.635 * w, anchorY: 0.7 * h };
    }
    const vents: Slot[] = [
      { knobX: 0.13 * w, knobY: 0.25 * h, anchorX: 0.245 * w, anchorY: 0.2 * h },
      { knobX: 0.87 * w, knobY: 0.25 * h, anchorX: 0.755 * w, anchorY: 0.2 * h },
      { knobX: 0.1 * w, knobY: 0.7 * h, anchorX: 0.21 * w, anchorY: 0.66 * h },
    ];
    return vents[Math.min(neutralOrdinal, vents.length - 1)];
  }

  private reservoirRect(): { cx: number; cy: number; rw: number; rh: number } {
    return { cx: 0.5 * this.scale.width, cy: 0.2 * this.scale.height, rw: 0.26 * this.scale.width, rh: 0.088 * this.scale.height };
  }

  private chamberRect(): { cx: number; cy: number; rw: number; rh: number } {
    return { cx: 0.42 * this.scale.width, cy: 0.7 * this.scale.height, rw: 0.215 * this.scale.width, rh: 0.13 * this.scale.height };
  }

  private charPos(): { x: number; y: number } {
    const c = this.chamberRect();
    return { x: c.cx - c.rw * 0.3, y: c.cy + c.rh - 34 * this.s() };
  }

  private pullDistance(): number {
    return Math.min(0.17 * this.scale.width, 110 * this.s());
  }

  // ---------------------------------------------------------------- HUD

  /** 登记已渲染文案（画布文字不进 DOM，质检经 __PF_QC__.texts()/textStates() 读取）。 */
  private track(t: any): void {
    if (t) this.seenTexts.set(String(t.text), t);
  }

  private buildHud(): void {
    const mk = (color: string): any =>
      this.add
        .text(0, 0, "", { fontFamily: "Arial, sans-serif", fontSize: "10px", color, fontStyle: "bold" })
        .setDepth(10);
    this.levelText = mk("#ffffff");
    this.scoreText = mk("#ffe9a8");
    this.titleText = mk("#ffd166").setOrigin(0.5, 0);
    this.dotsG = this.add.graphics().setDepth(10);
    this.relayoutHud();
  }

  private relayoutHud(): void {
    if (!this.levelText) return;
    const w = this.scale.width;
    const h = this.scale.height;
    const pad = Math.max(16, w * 0.05);
    const fontSize = Math.max(24, Math.round(w * 0.065));
    this.levelText.setFontSize(fontSize).setPosition(pad, h * 0.025);
    this.scoreText.setFontSize(fontSize).setPosition(w - pad, h * 0.025).setOrigin(1, 0);
    this.titleText
      .setFontSize(Math.max(14, Math.round(w * 0.042)))
      .setPosition(w / 2, h * 0.02 + 4)
      .setText(this.spec.title);
    this.track(this.titleText);
    this.updateHud();
    this.drawDots();
  }

  private drawDots(): void {
    if (!this.dotsG) return;
    const w = this.scale.width;
    const y = this.titleText.y + this.titleText.height + Math.round(10 * this.s());
    const n = this.spec.params.levels;
    const gap = Math.round(18 * this.s());
    const r = Math.round(5 * this.s());
    const x0 = w / 2 - ((n - 1) * gap) / 2;
    this.dotsG.clear();
    for (let i = 0; i < n; i++) {
      this.dotsG.fillStyle(i < this.level ? 0xffd166 : 0x39435f, 1);
      this.dotsG.fillCircle(x0 + i * gap, y, r);
      this.dotsG.lineStyle(2, 0x8d99ae, 0.8);
      this.dotsG.strokeCircle(x0 + i * gap, y, r);
    }
  }

  private updateHud(): void {
    if (!this.levelText) return;
    this.levelText.setText(`${this.level + 1}/${this.spec.params.levels}`);
    this.scoreText.setText(`${this.t("score")} ${this.score}`);
    this.track(this.levelText);
    this.track(this.scoreText);
    this.drawDots();
  }

  // ---------------------------------------------------------------- 关卡搭建

  private buildLevel(li: number): void {
    this.level = li;
    this.lavaLevel = 1;
    this.pins = [];
    if (this.levelGroup) this.levelGroup.destroy();
    this.levelGroup = this.add.container(0, 0).setDepth(2);

    // 地面
    const ground = this.add
      .rectangle(this.scale.width / 2, this.scale.height * 0.94, this.scale.width, this.scale.height * 0.12, GROUND)
      .setDepth(0);
    this.levelGroup.add(ground);

    this.drawTerrain();

    // 角色
    const cp = this.charPos();
    this.character = this.add.image(cp.x, cp.y, TEX_RESCUEE).setScale(1.15 * this.s()).setDepth(4);
    this.levelGroup.add(this.character);

    // 机关球（spike 变体：储备腔内悬挂刺球；lava 变体用熔岩面）
    if (this.spec.params.hazard === "spike") {
      const r = this.reservoirRect();
      this.hazardBall = this.add.image(r.cx, r.cy, TEX_SPIKE).setScale((r.rh * 1.5) / 96).setDepth(3);
      this.levelGroup.add(this.hazardBall);
    } else {
      this.hazardBall = null;
    }

    this.drawLava();

    // 针：角色 = 救援针在门外、机关针在储备腔闸口、其余中性针依次占引流孔位
    const roles = this.rolesCache[li];
    let neutralOrdinal = 0;
    for (let i = 0; i < this.spec.params.pinsPerLevel; i++) {
      const role: PinRole = i === roles.rescuee ? "rescuee" : i === roles.hazard ? "hazard" : "neutral";
      const ordinal = role === "neutral" ? neutralOrdinal++ : 0;
      const slot = this.slotFor(role, ordinal);
      const tex =
        role === "rescuee" ? TEX_KNOB_RESCUEE : role === "hazard" ? TEX_KNOB_HAZARD : TEX_KNOB_NEUTRAL;
      const rod = this.makeRod(slot);
      const knob = this.add
        .image(slot.knobX, slot.knobY, tex)
        .setScale(1.05 * this.s())
        .setDepth(6)
        .setInteractive({ useHandCursor: true });
      knob.on("pointerdown", () => this.tryPull(i));
      knob.on("pointerup", () => this.tryPull(i, true));
      this.levelGroup.add([rod, knob]);
      this.pins.push({
        index: i, role, pulled: false, animating: false,
        knob, rod,
        knobX: slot.knobX, knobY: slot.knobY,
        anchorX: slot.anchorX, anchorY: slot.anchorY,
      });
    }

    this.updateHud();
  }

  private makeRod(slot: Slot): any {
    const g = this.add.graphics().setDepth(5);
    const dx = slot.knobX - slot.anchorX;
    const dy = slot.knobY - slot.anchorY;
    const len = Math.hypot(dx, dy);
    const thickness = Math.max(8, 13 * this.s());
    g.lineStyle(thickness, 0xc9d3ea, 1);
    g.beginPath();
    g.moveTo(slot.anchorX, slot.anchorY);
    g.lineTo(slot.knobX, slot.knobY);
    g.strokePath();
    // 针杆端头法兰（塞在洞口的垫片）
    const nx = -dy / len;
    const ny = dx / len;
    g.lineStyle(thickness * 0.7, 0x8d99ae, 1);
    g.beginPath();
    g.moveTo(slot.anchorX + nx * thickness, slot.anchorY + ny * thickness);
    g.lineTo(slot.anchorX - nx * thickness, slot.anchorY - ny * thickness);
    g.strokePath();
    return g;
  }

  /** 地形：储备腔（机关槽）、闸口、引流腔壁、角色舱与门、导流虚线。 */
  private drawTerrain(): void {
    if (this.terrain) this.terrain.destroy();
    const g = this.add.graphics().setDepth(1);
    this.terrain = g;
    const r = this.reservoirRect();
    const c = this.chamberRect();
    const s = this.s();

    // 储备腔外壳
    g.fillStyle(STONE_DARK, 1);
    g.fillRoundedRect(r.cx - r.rw, r.cy - r.rh, r.rw * 2, r.rh * 2, 16 * s);
    g.lineStyle(4, STONE, 1);
    g.strokeRoundedRect(r.cx - r.rw, r.cy - r.rh, r.rw * 2, r.rh * 2, 16 * s);
    // 闸口（机关针的塞口）
    g.fillStyle(0x141b34, 1);
    g.fillRoundedRect(r.cx - 16 * s, r.cy + r.rh - 8 * s, 32 * s, 22 * s, 6 * s);
    // 引流孔（中性针的塞口：左右壁 + 舱壁）
    for (const vx of [r.cx - r.rw, r.cx + r.rw]) {
      g.fillStyle(0x141b34, 1);
      g.fillRoundedRect(vx - 10 * s, r.cy - 10 * s, 20 * s, 20 * s, 5 * s);
    }
    const v2 = this.slotFor("neutral", 2);
    g.fillStyle(0x141b34, 1);
    g.fillRoundedRect(v2.anchorX - 10 * s, v2.anchorY - 10 * s, 20 * s, 20 * s, 5 * s);

    // 导流虚线：闸口 → 角色舱（提示机关涌出路径）
    g.lineStyle(3, 0x8d99ae, 0.35);
    for (let t = 0; t <= 10; t++) {
      const x = r.cx + (c.cx + c.rw * 0.4 - r.cx) * (t / 10);
      const y = r.cy + r.rh + (c.cy - c.rh - r.cy - r.rh) * (t / 10);
      if (t % 2 === 0) g.fillCircle(x, y, 2.5 * s);
    }

    // 角色舱（右壁开口 = 门洞）
    g.fillStyle(STONE_DARK, 1);
    g.fillRoundedRect(c.cx - c.rw, c.cy - c.rh, c.rw * 2, c.rh * 2, 14 * s);
    g.fillStyle(0x141b34, 1);
    g.fillRoundedRect(c.cx - c.rw + 6 * s, c.cy - c.rh + 6 * s, c.rw * 2 - 12 * s, c.rh * 2 - 12 * s, 10 * s);
    g.lineStyle(4, STONE, 1);
    g.strokeRoundedRect(c.cx - c.rw, c.cy - c.rh, c.rw * 2, c.rh * 2, 14 * s);
    // 门（救援针拔出后上滑打开）
    this.door = this.add.rectangle(c.cx + c.rw - 3 * s, c.cy, 14 * s, c.rh * 1.4, 0xc9d3ea).setDepth(3);
    this.levelGroup.add(this.door);
  }

  /** 熔岩面（lava 变体）：高度随 lavaLevel（引流后下降）。 */
  private drawLava(): void {
    if (this.spec.params.hazard !== "lava") return;
    if (this.lavaG) this.lavaG.destroy();
    const r = this.reservoirRect();
    const s = this.s();
    const g = this.add.graphics().setDepth(2);
    this.lavaG = g;
    const h = r.rh * 2 * Math.max(0.12, this.lavaLevel) - 8 * s;
    g.fillStyle(0xd93a1f, 1);
    g.fillRoundedRect(r.cx - r.rw + 6 * s, r.cy + r.rh - 6 * s - h, r.rw * 2 - 12 * s, h, 8 * s);
    g.fillStyle(0xff8f3c, 1);
    g.fillEllipse(r.cx - r.rw * 0.4, r.cy + r.rh - 10 * s - h, 30 * s, 10 * s);
    g.fillEllipse(r.cx + r.rw * 0.35, r.cy + r.rh - 12 * s - h, 24 * s, 8 * s);
    g.fillStyle(0xffc145, 0.9);
    g.fillEllipse(r.cx + 4 * s, r.cy + r.rh - 9 * s - h, 14 * s, 6 * s);
  }

  /** 尺寸变化后的整体重排（不重置状态）：地形重画 + 针按槽位重摆。 */
  private relayout(): void {
    if (!this.levelGroup) return;
    const li = this.level;
    const pinsState = this.pins.map((p) => ({ pulled: p.pulled, index: p.index }));
    this.buildLevel(li);
    for (const st of pinsState) {
      const pin = this.pins.find((p) => p.index === st.index);
      if (pin && st.pulled) {
        pin.pulled = true;
        pin.knob.setAlpha(0.3);
      }
    }
    this.relayoutHud();
  }

  // ---------------------------------------------------------------- 教程

  private enterTutorial(): void {
    this.tutorialActive = true;
    this.tutorialDone = false;
    this.pf.setState("tutorial");
    // 教程演示针：spec orderSolution 首针（M1 保证安全），否则回退救援针。
    const first = this.orders[0];
    const roles = this.rolesCache[0];
    this.demoPinIndex =
      Array.isArray(first) && first.length > 0 && first[0] !== roles.hazard ? first[0] : roles.rescuee;

    const w = this.scale.width;
    const h = this.scale.height;
    this.tutorialGroup = this.add.container(0, 0).setDepth(40);
    const dim = this.add.rectangle(w / 2, h / 2, w, h, 0x000000, 0.5);
    const fontSize = Math.max(22, Math.round(w * 0.055));
    const label = this.add
      .text(w / 2, h * 0.5, this.t("tutorial"), {
        fontFamily: "Arial, sans-serif",
        fontSize: `${fontSize}px`,
        color: "#ffffff",
        align: "center",
        wordWrap: { width: w * 0.8 },
      })
      .setOrigin(0.5);
    this.track(label);
    this.tutorialGroup.add([dim, label]);
    this.showTutorialMarker();

    this.tutorialTimer = this.time.delayedCall(this.spec.tutorial.maxSec * 1000, () =>
      this.finishTutorial(),
    );
  }

  private showTutorialMarker(): void {
    if (!this.tutorialGroup || this.demoPinIndex < 0) return;
    while (this.tutorialGroup.length > 2) {
      const last = this.tutorialGroup.getAt(this.tutorialGroup.length - 1);
      this.tweens.killTweensOf(last);
      last.destroy();
    }
    const pin = this.pins[this.demoPinIndex];
    if (!pin) return;
    const ring = this.add.image(pin.knobX, pin.knobY, TEX_RING).setScale(0.8 * this.s());
    const hand = this.add.image(pin.knobX, pin.knobY + 6 * this.s(), TEX_HAND).setScale(0.75 * this.s()).setAlpha(0.95);
    this.tweens.add({
      targets: [ring, hand],
      scale: "+=0.12",
      duration: 380,
      yoyo: true,
      repeat: -1,
      ease: "sine.inout",
    });
    this.tutorialGroup.add([ring, hand]);
  }

  private finishTutorial(): void {
    if (this.tutorialDone || this.ended) return;
    this.tutorialDone = true;
    this.tutorialActive = false;
    if (this.tutorialTimer) {
      this.tutorialTimer.remove(false);
      this.tutorialTimer = null;
    }
    if (this.tutorialGroup) {
      this.tutorialGroup.destroy();
      this.tutorialGroup = null;
    }
    this.startPlay();
  }

  private startPlay(): void {
    if (this.ended) return;
    this.pf.start(); // pf:start + 相位 → playing
  }

  // ---------------------------------------------------------------- 拔针与结算

  private tryPull(index: number, fromUp = false): void {
    if (this.busy || this.ended) return;
    if (this.pf.phase() !== "playing" && !this.tutorialActive) return;
    const pin = this.pins[index];
    if (!pin || pin.pulled || pin.animating) return;

    // 教程期只认演示针（手势引导：点对正确针立即入局）
    if (this.tutorialActive && index !== this.demoPinIndex) return;
    if (this.tutorialActive && fromUp) return; // pointerdown 已处理
    if (this.tutorialActive) this.finishTutorial();

    // attract.failBait：首次游玩拔针以真实"弹回"失败一次（不消耗、可重试）
    if (
      !this.firstPlayPullDone &&
      this.tutorialDone &&
      this.spec.attract.failBait &&
      !this.baitUsed
    ) {
      this.baitUsed = true;
      this.firstPlayPullDone = true;
      this.bouncePin(pin);
      return;
    }
    if (!this.tutorialActive) this.firstPlayPullDone = true;

    if (pin.role === "neutral") {
      this.pullNeutral(pin);
    } else if (pin.role === "hazard") {
      this.pullHazard(pin);
    } else {
      const lastLevel = this.level === this.spec.params.levels - 1;
      if (lastLevel && this.spec.attract.nearWin && !this.nearWinUsed) {
        this.nearWinUsed = true;
        this.nearWinAlmost(pin);
        return;
      }
      this.pullRescuee(pin);
    }
  }

  /** 针拔出动画：旋钮沿锚点→旋钮方向滑出，针杆随动（anchor→knob 实时连线）。 */
  private animatePullOut(pin: PinView, ratio: number, duration: number, onComplete: () => void): void {
    pin.animating = true;
    const dist = this.pullDistance() * ratio;
    const len0 = Math.hypot(pin.knobX - pin.anchorX, pin.knobY - pin.anchorY) || 1;
    const ux = (pin.knobX - pin.anchorX) / len0;
    const uy = (pin.knobY - pin.anchorY) / len0;
    const targetX = pin.anchorX + ux * (len0 + dist);
    const targetY = pin.anchorY + uy * (len0 + dist);
    this.tweens.add({
      targets: pin.knob,
      x: targetX,
      y: targetY,
      duration,
      ease: "quad.out",
      onUpdate: () => this.redrawRod(pin),
      onComplete: () => {
        pin.knobX = targetX;
        pin.knobY = targetY;
        onComplete();
      },
    });
  }

  /** 针杆重画：从锚点到旋钮当前实时位置（拔出过程中针杆随之变短）。 */
  private redrawRod(pin: PinView): void {
    pin.rod.clear();
    const thickness = Math.max(8, 13 * this.s());
    pin.rod.lineStyle(thickness, 0xc9d3ea, 1);
    pin.rod.beginPath();
    pin.rod.moveTo(pin.anchorX, pin.anchorY);
    pin.rod.lineTo(pin.knob.x, pin.knob.y);
    pin.rod.strokePath();
  }

  /** 引流（中性针）：安全拔出，熔岩面下降 / 刺球微晃，+20 分。 */
  private pullNeutral(pin: PinView): void {
    this.busy = true;
    this.audio?.tap();
    this.animatePullOut(pin, 1, 240, () => {
      pin.pulled = true;
      pin.animating = false;
      pin.knob.setAlpha(0.35);
      this.lavaLevel = Math.max(0.12, this.lavaLevel - 1 / (this.rolesCache[this.level].neutrals.length + 1));
      this.drawLava();
      if (this.hazardBall) {
        this.tweens.add({ targets: this.hazardBall, angle: "+=14", duration: 200, yoyo: true, ease: "sine.inout" });
      }
      this.score += 20;
      this.updateHud();
      this.busy = false;
    });
  }

  /** 机关针错序：机关涌出 → 角色遇难 → 本关重置重试（不终局，pf:end 不触发）。 */
  private pullHazard(pin: PinView): void {
    this.busy = true;
    this.audio?.danger();
    this.animatePullOut(pin, 1, 200, () => {
      pin.pulled = true;
      pin.animating = false;
      pin.knob.setAlpha(0.35);
      this.time.delayedCall(160, () => this.floodAndFail());
    });
  }

  /** 机关涌出动画 + 失败重置。 */
  private floodAndFail(): void {
    const r = this.reservoirRect();
    const c = this.chamberRect();
    const cp = this.charPos();
    const shake = this.cameras?.main?.shake;
    if (typeof shake === "function") this.cameras.main.shake(320, 0.012);

    if (this.spec.params.hazard === "lava") {
      // 熔岩柱从闸口砸向角色
      const stream = this.add
        .rectangle(r.cx, (r.cy + r.rh + cp.y) / 2, 26 * this.s(), Math.abs(cp.y - (r.cy + r.rh)), 0xd93a1f)
        .setDepth(7)
        .setAlpha(0);
      this.levelGroup.add(stream);
      this.tweens.add({ targets: stream, alpha: 1, duration: 200, ease: "quad.in" });
      this.tweens.add({ targets: this.character, alpha: 0.15, angle: 70, duration: 380, delay: 220, ease: "quad.in" });
      this.time.delayedCall(720, () => {
        stream.destroy();
        this.resetLevelAfterFail();
      });
    } else {
      // 刺球从储备腔坠落砸向角色
      if (this.hazardBall) {
        this.tweens.add({
          targets: this.hazardBall,
          y: cp.y,
          x: cp.x,
          duration: 420,
          ease: "quad.in",
        });
      }
      this.tweens.add({ targets: this.character, alpha: 0.15, angle: 70, duration: 380, delay: 240, ease: "quad.in" });
      this.time.delayedCall(720, () => this.resetLevelAfterFail());
    }
  }

  private resetLevelAfterFail(): void {
    const shade = this.add
      .rectangle(this.scale.width / 2, this.scale.height / 2, this.scale.width, this.scale.height, 0x000000, 0)
      .setDepth(45);
    this.tweens.add({
      targets: shade,
      alpha: 0.6,
      duration: 220,
      onComplete: () => {
        this.buildLevel(this.level);
        this.character.setAlpha(1);
        this.character.setAngle(0);
        if (this.tutorialGroup && this.tutorialActive) this.showTutorialMarker();
        this.tweens.add({
          targets: shade,
          alpha: 0,
          duration: 260,
          onComplete: () => {
            shade.destroy();
            this.busy = false;
          },
        });
      },
    });
  }

  /** 结束页前的救援动画：开门 → 角色跑出。 */
  private pullRescuee(pin: PinView): void {
    this.busy = true;
    this.audio?.tap();
    this.animatePullOut(pin, 1, 240, () => {
      pin.pulled = true;
      pin.animating = false;
      pin.knob.setAlpha(0.35);
      this.score += 100;
      this.updateHud();
      // 门上滑 + 角色冲出
      if (this.door) {
        this.tweens.add({ targets: this.door, y: this.door.y - this.chamberRect().rh * 1.2, duration: 220, ease: "quad.out" });
      }
      this.tweens.add({
        targets: this.character,
        x: this.scale.width + 60,
        duration: 560,
        delay: 140,
        ease: "quad.in",
      });
      this.time.delayedCall(860, () => {
        const next = this.level + 1;
        if (next >= this.spec.params.levels) {
          this.endGame(true);
        } else {
          const shade = this.add
            .rectangle(this.scale.width / 2, this.scale.height / 2, this.scale.width, this.scale.height, 0x000000, 0)
            .setDepth(45);
          this.tweens.add({
            targets: shade,
            alpha: 0.6,
            duration: 200,
            onComplete: () => {
              this.buildLevel(next);
              this.tweens.add({
                targets: shade,
                alpha: 0,
                duration: 240,
                onComplete: () => {
                  shade.destroy();
                  this.busy = false;
                },
              });
            },
          });
        }
      });
    });
  }

  /** attract.nearWin：最后一关首次拔救援针"险些失败"——针拔出一半、机关涌出
   *  逼近角色、针弹回；随后再拔即成。不消耗任何资源，hint 保持不变。 */
  private nearWinAlmost(pin: PinView): void {
    this.busy = true;
    this.audio?.danger();
    const shake = this.cameras?.main?.shake;
    if (typeof shake === "function") this.cameras.main.shake(260, 0.008);
    // 危险红闪
    const flash = this.add
      .rectangle(this.scale.width / 2, this.scale.height / 2, this.scale.width, this.scale.height, 0xd93a1f, 0)
      .setDepth(44);
    this.tweens.add({ targets: flash, alpha: 0.22, duration: 200, yoyo: true, hold: 160 });
    // 角色惊跳躲闪
    this.tweens.add({
      targets: this.character,
      y: this.character.y - 22 * this.s(),
      duration: 180,
      yoyo: true,
      ease: "quad.out",
    });
    // 机关涌出一半（熔岩柱/刺球逼到半途即回退）
    let surge: any = null;
    if (this.spec.params.hazard === "lava") {
      const r = this.reservoirRect();
      const cp = this.charPos();
      const fullH = Math.abs(cp.y - (r.cy + r.rh));
      surge = this.add
        .rectangle(r.cx, r.cy + r.rh + fullH * 0.25, 26 * this.s(), fullH * 0.5, 0xd93a1f)
        .setDepth(7)
        .setAlpha(0);
      this.levelGroup.add(surge);
      this.tweens.add({ targets: surge, alpha: 0.95, duration: 240, ease: "quad.out" });
    } else if (this.hazardBall) {
      surge = this.hazardBall;
      this.tweens.add({ targets: surge, y: "+=" + 40 * this.s(), duration: 240, ease: "quad.out" });
    }
    // 针拔出一半再弹回原槽位
    this.animatePullOut(pin, 0.55, 200, () => {
      this.time.delayedCall(240, () => {
        this.tweens.add({
          targets: pin.knob,
          x: pin.knobX,
          y: pin.knobY,
          duration: 180,
          ease: "quad.in",
          onUpdate: () => this.redrawRod(pin),
          onComplete: () => {
            pin.animating = false;
            pin.knob.x = pin.knobX;
            pin.knob.y = pin.knobY;
            this.redrawRod(pin);
            if (surge && surge !== this.hazardBall) {
              this.tweens.add({ targets: surge, alpha: 0, duration: 180, onComplete: () => surge.destroy() });
            } else if (surge === this.hazardBall && surge) {
              this.tweens.add({ targets: surge, y: this.reservoirRect().cy, duration: 200, ease: "quad.in" });
            }
            this.tweens.add({ targets: flash, alpha: 0, duration: 160, onComplete: () => flash.destroy() });
            this.busy = false;
          },
        });
      });
    });
  }

  /** attract.failBait 的真实弹回：滑出一小段再弹回原槽位，不消耗。 */
  private bouncePin(pin: PinView): void {
    this.busy = true;
    this.audio?.tap();
    this.animatePullOut(pin, 0.4, 160, () => {
      this.tweens.add({
        targets: pin.knob,
        x: pin.knobX,
        y: pin.knobY,
        duration: 150,
        ease: "quad.in",
        onUpdate: () => this.redrawRod(pin),
        onComplete: () => {
          pin.animating = false;
          pin.knob.x = pin.knobX;
          pin.knob.y = pin.knobY;
          this.redrawRod(pin);
          this.busy = false;
        },
      });
    });
  }

  // ---------------------------------------------------------------- 结束页

  private endGame(win: boolean): void {
    if (this.ended) return;
    this.ended = true;
    this.audio?.win();
    this.pf.end(win); // pf:end {win} + 相位 → end
    this.showEndScreen(win);
  }

  private showEndScreen(win: boolean): void {
    const w = this.scale.width;
    const h = this.scale.height;
    const dim = this.add.rectangle(w / 2, h / 2, w, h, 0x000000, 0.62).setDepth(50);
    const panelW = Math.min(w * 0.86, 420);
    const panelH = h * 0.46;
    const panelY = h * 0.52;
    const panel = this.add.graphics().setDepth(51);
    panel.fillStyle(0x1b2440, 0.97);
    panel.fillRoundedRect((w - panelW) / 2, panelY - panelH / 2, panelW, panelH, 22);
    panel.lineStyle(3, win ? 0xffd166 : 0x8899bb, 1);
    panel.strokeRoundedRect((w - panelW) / 2, panelY - panelH / 2, panelW, panelH, 22);

    const title = this.add
      .text(w / 2, panelY - panelH * 0.28, this.t(win ? "win" : "lose"), {
        fontFamily: "Arial, sans-serif",
        fontSize: `${Math.round(panelW * 0.12)}px`,
        color: win ? "#ffd166" : "#dfe6ff",
        fontStyle: "bold",
      })
      .setOrigin(0.5)
      .setDepth(52);
    this.track(title);

    const nodes: any[] = [dim, panel, title];
    if (this.spec.endScreen.showScore) {
      const scoreText = this.add
        .text(w / 2, panelY - panelH * 0.04, `${this.t("score")}  ${this.score}`, {
          fontFamily: "Arial, sans-serif",
          fontSize: `${Math.round(panelW * 0.08)}px`,
          color: "#ffffff",
        })
        .setOrigin(0.5)
        .setDepth(52);
      this.track(scoreText);
      nodes.push(scoreText);
    }

    // CTA：点击 → PF.open(landingUrl)（pf:cta + 渠道退出接口路由）
    const ctaW = panelW * 0.72;
    const ctaH = Math.max(56, panelH * 0.2);
    const ctaY = panelY + panelH * 0.26;
    const ctaG = this.add.graphics().setDepth(52);
    ctaG.fillStyle(0xff5a5f, 1);
    ctaG.fillRoundedRect(w / 2 - ctaW / 2, ctaY - ctaH / 2, ctaW, ctaH, ctaH / 2);
    ctaG.lineStyle(3, 0xffffff, 0.85);
    ctaG.strokeRoundedRect(w / 2 - ctaW / 2, ctaY - ctaH / 2, ctaW, ctaH, ctaH / 2);
    const ctaLabel = this.add
      .text(w / 2, ctaY, this.t(this.spec.endScreen.ctaKey), {
        fontFamily: "Arial, sans-serif",
        fontSize: `${Math.round(ctaH * 0.42)}px`,
        color: "#ffffff",
        fontStyle: "bold",
      })
      .setOrigin(0.5)
      .setDepth(53);
    this.track(ctaLabel);
    const ctaZone = this.add
      .zone(w / 2, ctaY, ctaW * 1.3, ctaH * 1.6)
      .setOrigin(0.5)
      .setInteractive()
      .setDepth(54);
    ctaZone.on("pointerup", () => {
      this.pf.open(this.spec.endScreen.landingUrl);
    });
    this.tweens.add({
      targets: ctaG,
      scale: 1.06,
      duration: 450,
      yoyo: true,
      repeat: -1,
      ease: "sine.inout",
    });

    nodes.push(ctaG, ctaLabel, ctaZone);
    this.overlayLayer.add(nodes);
    dim.alpha = 0;
    this.tweens.add({ targets: dim, alpha: 0.62, duration: 220 });
    this.endScreenShown = true;
  }

  // ---------------------------------------------------------------- QC 钩子

  /** __PF_QC__.texts()：已渲染到画布的全部文案集合（CHK10 文案取证走本钩子）。 */
  textsSeen(): string[] {
    return Array.from(this.seenTexts.keys());
  }

  /** __PF_QC__.textStates()：采样时刻逐条核验文案对象 active+visible（CHK10 自证）。 */
  textStates(): Array<{ text: string; active: boolean; visible: boolean }> {
    const out: Array<{ text: string; active: boolean; visible: boolean }> = [];
    this.seenTexts.forEach((obj, text) => {
      let active = false;
      let visible = false;
      try {
        active = !!obj && obj.active === true;
        visible = !!obj;
        for (let n: any = obj; visible && n; n = n.parentContainer ?? null) {
          if (n.visible === false || (typeof n.alpha === "number" && !(n.alpha > 0))) {
            visible = false;
          }
        }
      } catch {
        active = false; // 已销毁引用访问异常 → 如实按不可见上报
        visible = false;
      }
      out.push({ text, active, visible });
    });
    return out;
  }

  /** __PF_QC__.assets()：替换素材像素对账（渲染贴图 vs 内联用户 PNG）。 */
  async assetAudit(): Promise<
    Array<{ texKey: string; spriteKey: string; mad: number | null; replaced: boolean; reason?: string }>
  > {
    const assets = (window as any).PF_ASSETS as Record<string, string> | undefined;
    const out: Array<{
      texKey: string; spriteKey: string; mad: number | null; replaced: boolean; reason?: string;
    }> = [];
    for (const r of this.replacedSprites) {
      const entry: { texKey: string; spriteKey: string; mad: number | null; replaced: boolean; reason?: string } = {
        texKey: r.texKey,
        spriteKey: r.spriteKey,
        mad: null,
        replaced: false,
      };
      try {
        if (!this.textures.exists(r.texKey)) {
          entry.reason = "贴图未注册（引擎纹理管理器无该键）";
        } else if (!assets || typeof assets[r.spriteKey] !== "string") {
          entry.reason = "window.PF_ASSETS 缺该键（非嵌入构建？）";
        } else {
          const src = this.textures.get(r.texKey).getSourceImage() as CanvasImageSource;
          const userCanvas = await decodeToCanvas(assets[r.spriteKey]);
          const mad = meanAbsDiff(sample16(src), sample16(userCanvas));
          entry.mad = Math.round(mad * 10) / 10;
          if (mad <= AUDIT_MAD_MAX) {
            entry.replaced = true;
          } else {
            entry.reason = `渲染贴图与用户 PNG 的 16×16 平均差 ${entry.mad} > 阈值 ${AUDIT_MAD_MAX}（疑似程序化贴图）`;
          }
        }
      } catch (err: any) {
        entry.reason = `对账异常：${err?.message ?? err}`;
      }
      out.push(entry);
    }
    return out;
  }

  /** __PF_QC__.hint()：当前最优下一步的真实坐标（视口 CSS 像素）。
   *  pullpin 的最优步恒为"直接拔当前关的救援针"（与 M1 pullpin_simulate 判定
   *  一致：救援针先于机关针拔出即救出）；教程期为演示针。 */
  hint(): { x: number; y: number; type: string } | null {
    const phase = this.pf.phase();
    if (phase === "tutorial") {
      if (!this.tutorialActive || this.demoPinIndex < 0) return null;
      const pin = this.pins[this.demoPinIndex];
      return pin ? { x: Math.round(pin.knob.x), y: Math.round(pin.knob.y), type: "tap" } : null;
    }
    if (phase !== "playing" || this.busy || this.ended) return null;
    const roles = this.rolesCache[this.level];
    const pin = this.pins[roles?.rescuee ?? -1];
    if (!pin || pin.pulled) return null;
    return { x: Math.round(pin.knob.x), y: Math.round(pin.knob.y), type: "tap" };
  }

  endScreenVisible(): boolean {
    return this.endScreenShown && this.pf.phase() === "end";
  }
}
