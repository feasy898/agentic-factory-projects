// 三消主场景：spec 驱动渲染 + 教程→游玩→结束页全流程 + attract 剧本 +
// window.__PF_QC__ 背书的最优步提示。事件与相位一律经 engine-bridge 的
// window.PF（契约 §4.2），音频一律经 PF.audio（首交互前强制静音）。
// pf:end 只能由真实游戏逻辑触达（禁假坐标/禁直接派发结束——templates.md §6）。
//
// 布局/渲染约定（规则卡 §8 冻结）：
// - 画布铺满视口，世界坐标 = CSS 像素，hint() 直接给视口坐标（Math.round 取整）；
// - sprites[i] 与 board.grid[i] 槽位一一对应，交换/下落/补位同步搬槽位，
//   结束后 snapSpritesToGrid() 兜底对齐，保证"画面=逻辑"。

import * as engine from "./vendor/engine.js";
import type { PFGlobal } from "@pf/engine-bridge";
import { Board, DIR_DELTAS, type Dir, type Move } from "./board.ts";
import { makeT, type NormalizedSpec } from "./spec.ts";
import { mulberry32, deriveRng } from "./rng.ts";
import {
  bestMove,
  simulatePlay,
  SPAWN_SALT,
  type SolverContext,
} from "./solver.ts";
import { createGameAudio, type GameAudio } from "./audio.ts";
import {
  createTextures,
  GEM_TEX_PREFIX,
  TEX_ARROW,
  TEX_HAND,
  TEX_JELLY,
} from "./textures.ts";
import {
  AUDIT_MAD_MAX,
  decodeToCanvas,
  meanAbsDiff,
  sample16,
  type ReplacedSprite,
} from "./assets.ts";

interface CellSprites {
  piece: any;
  jelly: any;
}

export class Match3Scene extends engine.Scene {
  private readonly spec: NormalizedSpec;
  private readonly pf: PFGlobal;
  /** 用户替换贴图（最小素材路径）：create() 先注册，程序化生成自动跳过已存在键。 */
  private readonly replacedSprites: ReplacedSprite[];
  /** 已渲染到画布的文案登记表（画布文字不进 DOM；texts()/textStates() 上报）。 */
  private readonly seenTexts = new Map<string, any>();

  private board!: Board;
  private texKeys: string[] = [];
  private sprites: CellSprites[] = [];
  private overlayLayer: any = null;

  private cell = 0;
  private originX = 0;
  private originY = 0;

  private movesLeft = 0;
  private progress = 0; // clear-jelly：已清果冻数；score：当前分
  private score = 0;
  private busy = false;
  private ended = false;
  private tutorialActive = false;
  private tutorialDone = false;
  private tutorialDemo: Move | null = null;
  private tutorialTimer: any = null;
  private tutorialGroup: any = null;
  private nearWinUsed = false;
  private baitUsed = false;
  private firstPlayerMoveDone = false;
  private endScreenShown = false;
  /** 本次交换的补位流盐（trySwap 捕获，playResolve 消费——同一流）。 */
  private pendingSalt = 0;

  private selectedCell: { x: number; y: number } | null = null;
  private selectionRing: any = null;
  private dragging: { x: number; y: number; cx: number; cy: number } | null = null;

  private movesText: any = null;
  private progressText: any = null;
  private progressBar: any = null;
  private titleText: any = null;
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
    const p = this.spec.params;
    // 最小素材路径：先注册用户替换贴图（已存在的键不程序化覆盖）。
    for (const r of this.replacedSprites) {
      if (!this.textures.exists(r.texKey)) this.textures.addCanvas(r.texKey, r.canvas);
    }
    this.texKeys = createTextures(this, p);
    this.audio = createGameAudio(this.pf.audio);

    // 主流只构造一次并持有于 Board——64 次生成重试顺序消耗同一主流（规则卡 §2）。
    const rng = mulberry32(this.spec.seed);
    const jellyCount =
      p.goalType === "clear-jelly"
        ? p.goalCount
        : Math.min(p.cols * p.rows, Math.max(6, Math.round(p.cols * p.rows * 0.25)));
    this.board = new Board(p.cols, p.rows, p.colors, rng);
    this.movesLeft = p.moves;
    this.progress = 0;
    this.score = 0;

    // 生成期可玩性校验：贪心最优线（与 hint 同一补位流调度）必须在步数内可胜。
    // 64 次重生成仍不可胜才放行并告警（概率上不会发生，规则卡 §7 推论）。
    let ok = false;
    for (let attempt = 0; attempt < 64 && !ok; attempt++) {
      this.board.generate(jellyCount);
      const sim = simulatePlay(this.solverCtx(), this.board.grid, this.board.jelly, p.moves);
      ok = sim.win;
    }
    if (!ok) {
      console.warn("[pf/tmpl-match3] 64 次生成后仍无贪心可胜盘面，按最后盘面继续");
    }

    this.overlayLayer = this.add.container(0, 0).setDepth(50);

    this.computeLayout();
    this.buildSprites();
    this.buildHud();
    this.updateHud();

    this.installInput();
    this.scale.on("resize", () => {
      if (!this.busy) {
        this.computeLayout();
        this.repositionAll();
      }
    });

    // 相位：教程或直接开玩（PF 相位是唯一真源，QC state() 直读）。
    if (this.spec.tutorial.enabled) {
      this.enterTutorial();
    } else {
      this.startPlay();
    }
  }

  private solverCtx(): SolverContext {
    const p = this.spec.params;
    return {
      cols: p.cols,
      rows: p.rows,
      colors: p.colors,
      seed: this.spec.seed,
      goalType: p.goalType,
      progress: () => this.progress,
      goal: () => p.goalCount,
      // 下一次玩家交换的 k = moves − movesLeft + 1（trySwap 先捕获盐再扣步数，
      // 对 hint/将胜预估/实际结算三者给出同一个盐——规则卡 §7）。
      salt: () => SPAWN_SALT ^ (p.moves - this.movesLeft + 1),
    };
  }

  // ---------------------------------------------------------------- 布局

  /** 规则卡 §8 冻结数学：hudH/availW/availH/cell/origin 全部由此推出。 */
  private computeLayout(): void {
    const w = this.scale.width;
    const h = this.scale.height;
    const p = this.spec.params;
    const hudH = Math.max(96, h * 0.13);
    const availW = w * 0.94;
    const availH = h - hudH - h * 0.05;
    this.cell = Math.max(24, Math.floor(Math.min(availW / p.cols, availH / p.rows)));
    this.originX = Math.round((w - this.cell * p.cols) / 2);
    this.originY = Math.round(hudH + (availH - this.cell * p.rows) / 2);
  }

  private pieceScale(): number {
    return (this.cell - 6) / 96;
  }

  private cellCenter(x: number, y: number): { x: number; y: number } {
    return {
      x: this.originX + x * this.cell + this.cell / 2,
      y: this.originY + y * this.cell + this.cell / 2,
    };
  }

  private buildSprites(): void {
    const p = this.spec.params;
    this.sprites = new Array(p.cols * p.rows);
    const scale = this.pieceScale();
    for (let i = 0; i < p.cols * p.rows; i++) {
      const x = i % p.cols;
      const y = Math.floor(i / p.cols);
      const c = this.cellCenter(x, y);
      const jellyImg = this.board.jelly[i]
        ? this.add.image(c.x, c.y, TEX_JELLY).setScale(scale).setDepth(1)
        : null;
      const pieceImg = this.add
        .image(c.x, c.y, GEM_TEX_PREFIX + this.board.at(x, y))
        .setScale(scale)
        .setDepth(2);
      this.sprites[i] = { piece: pieceImg, jelly: jellyImg };
    }
  }

  /** 尺寸变化/重排后的整体重摆（不动画）。 */
  private repositionAll(): void {
    const p = this.spec.params;
    const scale = this.pieceScale();
    for (let i = 0; i < this.sprites.length; i++) {
      const s = this.sprites[i];
      const x = i % p.cols;
      const y = Math.floor(i / p.cols);
      const c = this.cellCenter(x, y);
      if (s.jelly) s.jelly.setPosition(c.x, c.y).setScale(scale);
      if (s.piece) {
        s.piece.setPosition(c.x, c.y).setScale(scale);
        s.piece.setTexture(GEM_TEX_PREFIX + this.board.grid[i]);
      }
    }
    this.clearSelectionRing();
    this.selectedCell = null;
    this.buildHudPositions();
    if (this.tutorialGroup && this.tutorialActive) this.showTutorialMarkers();
  }

  /** 连消/交换后兜底：把每个槽位的贴图、位置、透明度对齐逻辑盘面。 */
  private snapSpritesToGrid(): void {
    this.repositionAll();
  }

  // ---------------------------------------------------------------- HUD

  /** 登记已渲染文案（质检经 __PF_QC__.texts()/textStates() 读取）。 */
  private track(t: any): void {
    if (t) this.seenTexts.set(String(t.text), t);
  }

  private buildHud(): void {
    this.movesText = this.add
      .text(0, 0, "", {
        fontFamily: "Arial, sans-serif",
        fontSize: "10px",
        color: "#ffffff",
        fontStyle: "bold",
      })
      .setDepth(10);
    this.progressText = this.add
      .text(0, 0, "", {
        fontFamily: "Arial, sans-serif",
        fontSize: "10px",
        color: "#ffe9a8",
        fontStyle: "bold",
      })
      .setDepth(10);
    this.progressBar = this.add.graphics().setDepth(9);
    // 标题上屏：评委改 spec 标题要看得见。
    this.titleText = this.add
      .text(0, 0, "", {
        fontFamily: "Arial, sans-serif",
        fontSize: "10px",
        color: "#ffd166",
        fontStyle: "bold",
      })
      .setOrigin(0.5, 0)
      .setDepth(10);
    this.buildHudPositions();
  }

  private buildHudPositions(): void {
    if (!this.movesText) return;
    const w = this.scale.width;
    const h = this.scale.height;
    const pad = Math.max(16, w * 0.05);
    const fontSize = Math.max(26, Math.round(w * 0.07));
    this.movesText.setFontSize(fontSize).setPosition(pad, h * 0.03);
    this.progressText.setFontSize(fontSize).setPosition(w - pad, h * 0.03);
    this.titleText
      .setFontSize(Math.max(14, Math.round(w * 0.042)))
      .setPosition(w / 2, h * 0.03 + 6)
      .setText(this.spec.title);
    this.track(this.titleText);
    this.updateHud();
  }

  private updateHud(): void {
    if (!this.movesText) return;
    const p = this.spec.params;
    this.movesText.setText(`×${this.movesLeft}`);
    const shown =
      p.goalType === "clear-jelly"
        ? `${Math.min(this.progress, p.goalCount)}/${p.goalCount}`
        : `${this.score}/${p.goalCount}`;
    this.progressText.setText(shown);
    this.track(this.movesText);
    this.track(this.progressText);
    const w = this.scale.width;
    const pad = Math.max(16, w * 0.05);
    const barW = w - pad * 2;
    const barY = this.movesText.y + this.movesText.height + 12;
    const ratio = Math.max(0, Math.min(1, this.progress / p.goalCount));
    this.progressBar.clear();
    this.progressBar.fillStyle(0x2a3560, 1);
    this.progressBar.fillRoundedRect(pad, barY, barW, 10, 5);
    if (ratio > 0) {
      this.progressBar.fillStyle(0xffd166, 1);
      this.progressBar.fillRoundedRect(pad, barY, Math.max(10, barW * ratio), 10, 5);
    }
  }

  // ---------------------------------------------------------------- 教程

  private enterTutorial(): void {
    this.tutorialActive = true;
    this.tutorialDone = false;
    this.pf.setState("tutorial");
    const best = bestMove(this.solverCtx(), this.board.grid, this.board.jelly);
    const p = this.spec.params;
    this.tutorialDemo =
      best ? best.move : (Board.allMoves(this.board.grid, p.cols, p.rows)[0] ?? null);

    const w = this.scale.width;
    const h = this.scale.height;
    this.tutorialGroup = this.add.container(0, 0).setDepth(40);
    const dim = this.add.rectangle(w / 2, h / 2, w, h, 0x000000, 0.55);
    const fontSize = Math.max(22, Math.round(w * 0.055));
    const label = this.add
      .text(w / 2, h * 0.16, this.t("tutorial"), {
        fontFamily: "Arial, sans-serif",
        fontSize: `${fontSize}px`,
        color: "#ffffff",
        align: "center",
        wordWrap: { width: w * 0.8 },
      })
      .setOrigin(0.5);
    this.track(label);
    this.tutorialGroup.add([dim, label]);
    this.showTutorialMarkers();

    // maxSec 超时自动结束教程（首次合法交换结算后也会提前结束——afterResolve）。
    this.tutorialTimer = this.time.delayedCall(this.spec.tutorial.maxSec * 1000, () =>
      this.finishTutorial(),
    );
  }

  private showTutorialMarkers(): void {
    if (!this.tutorialGroup || !this.tutorialDemo) return;
    // 清掉旧标记（前两个成员是 dim 与 label）。
    while (this.tutorialGroup.length > 2) {
      const last = this.tutorialGroup.getAt(this.tutorialGroup.length - 1);
      this.tweens.killTweensOf(last);
      last.destroy();
    }
    const mv = this.tutorialDemo;
    const from = this.cellCenter(mv.x, mv.y);
    const [dx, dy] = DIR_DELTAS[mv.dir];
    const to = { x: from.x + dx * this.cell * 0.8, y: from.y + dy * this.cell * 0.8 };
    const hand = this.add
      .image(from.x, from.y, TEX_HAND)
      .setScale(this.cell / 110)
      .setAlpha(0.95);
    const arrow = this.add
      .image((from.x + to.x) / 2, (from.y + to.y) / 2, TEX_ARROW)
      .setScale(this.cell / 130)
      .setAngle((Math.atan2(to.y - from.y, to.x - from.x) * 180) / Math.PI);
    this.tweens.add({
      targets: [hand, arrow],
      x: "+=" + (to.x - from.x) * 0.22,
      y: "+=" + (to.y - from.y) * 0.22,
      duration: 380,
      yoyo: true,
      repeat: -1,
      ease: "sine.inout",
    });
    this.tutorialGroup.add([hand, arrow]);
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

  // ---------------------------------------------------------------- 输入

  private installInput(): void {
    // 输入一：按下后拖拽，位移阈值 max(18, cell*0.35) 像素，主轴定方向（规则卡 §3）。
    this.input.on("pointerdown", (pointer: any) => {
      const cell = this.pickCell(pointer.x, pointer.y);
      if (!cell) return;
      this.dragging = { x: pointer.x, y: pointer.y, cx: cell.x, cy: cell.y };
    });

    this.input.on("pointermove", (pointer: any) => {
      if (!this.dragging) return;
      const dx = pointer.x - this.dragging.x;
      const dy = pointer.y - this.dragging.y;
      const dist = Math.hypot(dx, dy);
      if (dist < Math.max(18, this.cell * 0.35)) return;
      const dir: Dir =
        Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : dy > 0 ? "down" : "up";
      const mv: Move = { x: this.dragging.cx, y: this.dragging.cy, dir };
      this.dragging = null;
      this.trySwap(mv);
    });

    // 输入二：点选两相邻格（tap-tap）。
    this.input.on("pointerup", (pointer: any) => {
      const consumed = this.dragging === null;
      this.dragging = null;
      if (consumed) return;
      const cell = this.pickCell(pointer.x, pointer.y);
      if (!cell) return;
      if (this.selectedCell) {
        const dx = cell.x - this.selectedCell.x;
        const dy = cell.y - this.selectedCell.y;
        if (Math.abs(dx) + Math.abs(dy) === 1) {
          const dir: Dir = dy === -1 ? "up" : dy === 1 ? "down" : dx === -1 ? "left" : "right";
          const mv: Move = { x: this.selectedCell.x, y: this.selectedCell.y, dir };
          this.selectedCell = null;
          this.clearSelectionRing();
          this.trySwap(mv);
          return;
        }
      }
      this.selectedCell = cell;
      this.drawSelectionRing(cell);
    });
  }

  private pickCell(px: number, py: number): { x: number; y: number } | null {
    const p = this.spec.params;
    const x = Math.floor((px - this.originX) / this.cell);
    const y = Math.floor((py - this.originY) / this.cell);
    if (x < 0 || y < 0 || x >= p.cols || y >= p.rows) return null;
    return { x, y };
  }

  private drawSelectionRing(cell: { x: number; y: number }): void {
    this.clearSelectionRing();
    const c = this.cellCenter(cell.x, cell.y);
    this.selectionRing = this.add.graphics().setDepth(3);
    this.selectionRing.lineStyle(4, 0xffffff, 0.9);
    this.selectionRing.strokeRoundedRect(
      c.x - this.cell / 2 + 3,
      c.y - this.cell / 2 + 3,
      this.cell - 6,
      this.cell - 6,
      12,
    );
  }

  private clearSelectionRing(): void {
    if (this.selectionRing) {
      this.selectionRing.destroy();
      this.selectionRing = null;
    }
  }

  // ---------------------------------------------------------------- 交换与结算

  private trySwap(mv: Move): void {
    if (this.busy || this.ended) return;
    if (this.pf.phase() !== "playing" && !this.tutorialActive) return;

    const p = this.spec.params;
    const swapped = Board.swap(this.board.grid, p.cols, p.rows, mv);
    if (!swapped) return;
    const mask = Board.matchMask(swapped, p.cols, p.rows);
    const valid = mask.some(Boolean);

    if (valid) {
      // "将胜"预估：与实际结算同一补位随机流（k = moves − movesLeft + 1），
      // 保证 nearWin 触发判定和真实连消一致（规则卡 §6）。
      const simRng = deriveRng(this.spec.seed, SPAWN_SALT ^ (p.moves - this.movesLeft + 1));
      const sim = Board.resolve(swapped, p.cols, p.rows, p.colors, simRng, this.board.jelly);
      let jellyGain = 0;
      for (const i of sim.cleared) if (this.board.jelly[i]) jellyGain++;
      const willWin =
        p.goalType === "clear-jelly"
          ? this.progress + jellyGain >= p.goalCount
          : this.score + sim.score >= p.goalCount;

      // attract 剧本（规则卡 §6）：失败以真实"非法交换回弹"呈现，不消耗步数；
      // hint() 始终返回真实最优步坐标。
      if (willWin && this.spec.attract.nearWin && !this.nearWinUsed) {
        this.nearWinUsed = true;
        this.animateInvalidSwap(mv);
        return;
      }
      if (
        !willWin &&
        !this.firstPlayerMoveDone &&
        this.tutorialDone &&
        this.spec.attract.failBait &&
        !this.baitUsed
      ) {
        this.baitUsed = true;
        this.animateInvalidSwap(mv);
        return;
      }
    }

    if (!valid) {
      this.animateInvalidSwap(mv);
      return;
    }

    this.busy = true;
    this.firstPlayerMoveDone = true;
    this.clearSelectionRing();
    this.selectedCell = null;
    // 先捕获本次交换的补位流盐（第 k 次玩家交换，k 从 1 起），再扣步数。
    this.pendingSalt = SPAWN_SALT ^ (p.moves - this.movesLeft + 1);
    this.movesLeft = Math.max(0, this.movesLeft - 1);
    this.animateSwapThenResolve(mv, swapped);
  }

  /** 非法交换/attract 剧本失败：110ms 滑过去再弹回，不消耗步数。 */
  private animateInvalidSwap(mv: Move): void {
    this.busy = true;
    const [dx, dy] = DIR_DELTAS[mv.dir];
    const sa = this.sprites[this.board.idx(mv.x, mv.y)];
    const sb = this.sprites[this.board.idx(mv.x + dx, mv.y + dy)];
    if (!sa?.piece || !sb?.piece) {
      this.busy = false;
      return;
    }
    const ax = sa.piece.x;
    const ay = sa.piece.y;
    const bx = sb.piece.x;
    const by = sb.piece.y;
    this.tweens.add({
      targets: sa.piece,
      x: bx,
      y: by,
      duration: 110,
      yoyo: true,
      ease: "sine.inout",
      onComplete: () => {
        sa.piece.x = ax;
        sa.piece.y = ay;
        this.busy = false;
      },
    });
    this.tweens.add({
      targets: sb.piece,
      x: ax,
      y: ay,
      duration: 110,
      yoyo: true,
      ease: "sine.inout",
      onComplete: () => {
        sb.piece.x = bx;
        sb.piece.y = by;
      },
    });
  }

  private animateSwapThenResolve(mv: Move, swapped: number[]): void {
    const [dx, dy] = DIR_DELTAS[mv.dir];
    const ia = this.board.idx(mv.x, mv.y);
    const ib = this.board.idx(mv.x + dx, mv.y + dy);
    const sa = this.sprites[ia];
    const sb = this.sprites[ib];
    if (!sa?.piece || !sb?.piece) {
      this.busy = false;
      return;
    }
    this.tweens.add({ targets: sa.piece, x: sb.piece.x, y: sb.piece.y, duration: 120, ease: "sine.inout" });
    this.tweens.add({
      targets: sb.piece,
      x: sa.piece.x,
      y: sa.piece.y,
      duration: 120,
      ease: "sine.inout",
      onComplete: () => {
        // 槽位互换（贴图随槽走），grid 采用交换结果，然后回放连消。
        this.sprites[ia] = sb;
        this.sprites[ib] = sa;
        this.board.grid = swapped;
        this.audio?.tap();
        this.playResolve();
      },
    });
  }

  private playResolve(): void {
    const p = this.spec.params;
    const simRng = deriveRng(this.spec.seed, this.pendingSalt);
    const result = Board.resolve(this.board.grid, p.cols, p.rows, p.colors, simRng, this.board.jelly);

    // 果冻与进度结算（逻辑立即生效，画面动画随后回放）。
    let jellyGain = 0;
    for (const i of result.cleared) {
      if (this.board.jelly[i]) {
        this.board.jelly[i] = false;
        jellyGain++;
      }
    }
    if (p.goalType === "clear-jelly") {
      this.progress += jellyGain;
    }
    this.score += result.score;
    if (p.goalType === "score") this.progress = this.score;
    this.updateHud();

    // 波次动画回放（match 150ms / fall 160ms / spawn 170ms，波间 170/180/190ms）。
    let delay = 0;
    for (const step of result.steps) {
      if (step.t === "match") {
        for (const i of step.cells) {
          const s = this.sprites[i];
          if (!s?.piece) continue;
          const img = s.piece;
          this.sprites[i] = { piece: null, jelly: s.jelly };
          this.tweens.add({
            targets: img,
            scale: 0,
            alpha: 0,
            duration: 150,
            delay,
            ease: "quad.in",
            onComplete: () => img.destroy(),
          });
        }
        delay += 170;
      } else if (step.t === "fall") {
        for (const m of step.moves) {
          const fromSlot = this.sprites[m.from];
          const toSlot = this.sprites[m.to];
          if (!fromSlot?.piece) continue;
          const img = fromSlot.piece;
          this.sprites[m.to] = { piece: img, jelly: toSlot ? toSlot.jelly : null };
          this.sprites[m.from] = { piece: null, jelly: fromSlot.jelly };
          const x = m.to % p.cols;
          const y = Math.floor(m.to / p.cols);
          this.tweens.add({
            targets: img,
            y: this.cellCenter(x, y).y,
            duration: 160,
            delay,
            ease: "quad.in",
          });
        }
        delay += 180;
      } else if (step.t === "spawn") {
        const scale = this.pieceScale();
        for (const c of step.cells) {
          const x = c.index % p.cols;
          const y = Math.floor(c.index / p.cols);
          const pos = this.cellCenter(x, y);
          const img = this.add
            .image(pos.x, pos.y - this.cell * 0.8, GEM_TEX_PREFIX + c.piece)
            .setScale(scale)
            .setDepth(2)
            .setAlpha(0.6);
          this.tweens.add({
            targets: img,
            y: pos.y,
            alpha: 1,
            duration: 170,
            delay,
            ease: "quad.out",
          });
          this.sprites[c.index] = { piece: img, jelly: this.sprites[c.index]?.jelly ?? null };
        }
        delay += 190;
      }
    }

    // 果冻清除动画（board.jelly 已在结算时置 false）。
    for (let i = 0; i < this.sprites.length; i++) {
      const s = this.sprites[i];
      if (s.jelly && !this.board.jelly[i]) {
        const j = s.jelly;
        this.tweens.add({
          targets: j,
          alpha: 0,
          scale: j.scaleX * 1.3,
          duration: 220,
          delay,
          onComplete: () => j.destroy(),
        });
        this.sprites[i] = { piece: s.piece, jelly: null };
      }
    }

    // 动画播完 → 逻辑收尾。
    this.time.delayedCall(delay + 240, () => {
      this.board.grid = result.finalGrid;
      this.snapSpritesToGrid();
      this.afterResolve();
    });
  }

  private afterResolve(): void {
    const p = this.spec.params;
    this.busy = false;
    if (this.progress >= p.goalCount) {
      this.endGame(true);
      return;
    }
    if (this.tutorialActive) {
      // 教程内首次合法交换结算后提前结束教程。
      this.finishTutorial();
      return;
    }
    if (this.movesLeft <= 0) {
      this.endGame(false);
      return;
    }
    if (!Board.hasAnyMove(this.board.grid, p.cols, p.rows)) {
      this.doReshuffle();
    }
  }

  private doReshuffle(): void {
    this.busy = true;
    // 与生成期模拟同一重排流（0x5117 ^ k，k = moves − movesLeft + 1）——
    // 保持"画面=逻辑=模拟线"对齐（规则卡 §7）。
    const p = this.spec.params;
    this.board.setRng(deriveRng(this.spec.seed, 0x5117 ^ (p.moves - this.movesLeft + 1)));
    this.board.reshuffle();
    this.time.delayedCall(280, () => {
      this.snapSpritesToGrid();
    });
    this.time.delayedCall(560, () => {
      this.busy = false;
    });
  }

  // ---------------------------------------------------------------- 结束页

  private endGame(win: boolean): void {
    if (this.ended) return;
    this.ended = true;
    this.clearSelectionRing();
    this.audio?.win();
    this.pf.end(win); // pf:end {win} + 相位 → end（只由真实逻辑触达）
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

    // CTA：点击 → PF.open(landingUrl)（pf:cta + 渠道退出接口路由）；脉冲动画，热区 1.3×/1.6×。
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

  /** __PF_QC__.texts()：已渲染到画布的全部文案集合（画布文字不进 DOM）。 */
  textsSeen(): string[] {
    return Array.from(this.seenTexts.keys());
  }

  /** __PF_QC__.textStates()：采样时刻逐条核验文案对象 active+visible。
   *  active=引擎 update 列表成员；visible=对象自身与父容器链逐级 visible 且 alpha>0。
   *  已销毁对象如实上报为不可见——CHK10 必须在浮层在屏的相位采样到它。 */
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

  /** __PF_QC__.assets()：替换素材像素对账。渲染贴图源与构建期内联的用户 PNG
   *  经同一 contain-fit 管线降采样到 16×16 比平均绝对差（≤ AUDIT_MAD_MAX 判
   *  replaced）；无替换素材的构建返回 []。 */
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

  /** __PF_QC__.hint()：当前最优下一步的真实坐标（视口 CSS 像素，Math.round 取整）。
   *  返回 null 的情形：教程相位无 demo；busy/ended；playing 无步（此时触发重排）。 */
  hint(): { x: number; y: number; type: string } | null {
    const phase = this.pf.phase();
    if (phase === "tutorial") {
      if (!this.tutorialActive || !this.tutorialDemo) return null;
      return this.moveHint(this.tutorialDemo);
    }
    if (phase !== "playing" || this.busy || this.ended) return null;
    const best = bestMove(this.solverCtx(), this.board.grid, this.board.jelly);
    if (!best) {
      if (!this.busy) this.doReshuffle();
      return null;
    }
    return this.moveHint(best.move);
  }

  private moveHint(mv: Move): { x: number; y: number; type: string } {
    const c = this.cellCenter(mv.x, mv.y);
    return { x: Math.round(c.x), y: Math.round(c.y), type: "swap-" + mv.dir };
  }

  endScreenVisible(): boolean {
    return this.endScreenShown && this.pf.phase() === "end";
  }
}
