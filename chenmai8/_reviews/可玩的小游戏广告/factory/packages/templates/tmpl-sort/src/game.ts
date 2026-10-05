// 排序/拧螺丝主场景：spec 驱动渲染 + 教程→游玩→结束页全流程 + attract 参数 +
// window.__PF_QC__ 背书的最优步提示。事件与相位一律经 engine-bridge 的
// window.PF（契约 §4.2），音频一律经 PF.audio（首交互前强制静音）。
//
// 玩法语义（与 @pf/spec 冻结走法同源，见 board.ts/deal.ts/solver.ts）：
//   - 倾倒：点选一根柱（顶部同色段抬起）→ 再点目标柱，顶部同色段整段倒过去
//     （k = min(段长, 空位)，目标柱须空或顶同色）；每根柱"空或单色满柱"即胜。
//   - screwMode=true 拧螺丝分支：柱体=金属螺栓、棋子=六角螺母、交互配棘轮音效
//     与旋入动画；走法/可解性与普通模式完全一致（交互与表现分支，规则不分叉）。
//   - 败局仅在 moveLimit>0 且步数耗尽时出现（pf:end {win:false}）；moveLimit=0
//     （默认）不设败局——可玩广告不设败局，与 match3/pullpin 的 lose 语义同源。
//   - attract.nearWin：将胜的一倒先"险些失败"一次（倒到半空+红闪+震屏后倒回），
//     随后同一最优步再倒即成；attract.failBait：首次游玩倾倒以真实弹回失败一次；
//     attract.firstClickSucceed：开局第一击点到空柱/成品柱时自动改选最优解源柱。
//     （nearWin 行为探针语义，模板资产 spec §7.3 冻结：失败呈现不消耗步数，
//     __PF_QC__.hint() 始终返回真实最优步坐标——制胜目标柱被点两次、pf:end 恰
//     一次 win=true，pf:end 仍只由真实结算逻辑触达——QC 的 CHK07 判定依据。）
//   - hint() 两拍节奏：未选中时返回最优解源柱坐标（tap=点选），已选中该源柱时
//     返回目标柱坐标（tap=倾倒）——QC 连续两次点按推进一步，与真人交互一致。
//
// 坐标约定：画布固定铺满视口（世界坐标 = CSS 像素），hint() 直接给视口坐标。

import * as engine from "./vendor/engine.js";
import type { PFGlobal } from "@pf/engine-bridge";
import { makeT, type NormalizedSpec } from "./spec.ts";
import {
  applyMove,
  cloneBoard,
  completedColors,
  isSolved,
  legalMoves,
  topRun,
  type Board,
  type SortMove,
} from "./board.ts";
import { greedyMove, SolutionCache } from "./solver.ts";
import { dealInitialBoard } from "./deal.ts";
import { createGameAudio, type GameAudio } from "./audio.ts";
import {
  createTextures,
  PALETTE,
  PIECE_TEX_SIZE,
  pieceTexture,
  rodTexture,
  TEX_HAND,
  TEX_RING,
  USER_TEX_KEYS,
} from "./textures.ts";
import {
  AUDIT_MAD_MAX,
  decodeToCanvas,
  meanAbsDiff,
  sample16,
  type ReplacedSprite,
} from "./assets.ts";

const PANEL = 0x1b2440;

export class SortScene extends engine.Scene {
  private readonly spec: NormalizedSpec;
  private readonly pf: PFGlobal;
  /** 用户替换贴图（最小素材路径）：create() 先注册，createTextures 自动跳过程序化键。 */
  private readonly replacedSprites: ReplacedSprite[];
  /** 已渲染到画布的文案登记表（__PF_QC__.texts()/textStates() 上报）。 */
  private readonly seenTexts = new Map<string, any>();

  private board!: Board;
  /** 每根柱的棋子图片栈（自底向上），与 board 槽位一一对应（画面=逻辑）。 */
  private stacks: any[][] = [];
  private rodG: any[] = [];
  private readonly solutions = new SolutionCache();

  private selected: number | null = null;
  private selRing: any = null;
  private busy = false;
  private ended = false;
  private endScreenShown = false;
  private movesLeft = 0;
  private completed = 0;
  private score = 0;

  private tutorialActive = false;
  private tutorialDone = false;
  private tutorialTimer: any = null;
  private tutorialGroup: any = null;
  private demoRod = -1;
  private nearWinUsed = false;
  private baitUsed = false;
  private firstPlayMoveDone = false;
  private firstTapDone = false;

  // 布局缓存（computeLayout）
  private pitch = 0;
  private rodW = 0;
  private rodH = 0;
  private layerH = 0;
  private originX = 0;
  private baseY = 0;

  private overlayLayer: any = null;
  private chipsG: any = null;
  private movesText: any = null;
  private progressText: any = null;
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
    // 最小素材路径：先注册用户替换贴图（rod/piece），createTextures 自动跳过同名程序化键。
    for (const r of this.replacedSprites) {
      if (!this.textures.exists(r.texKey)) this.textures.addCanvas(r.texKey, r.canvas);
    }
    createTextures(this, p.screwMode);
    this.audio = createGameAudio(this.pf.audio, p.screwMode);

    // 生成期发牌（seed 确定性）：冻结规范扰动镜像 → 同流深化发牌 → BFS 验收
    // （可解 + 非开局即胜 + 最优步数 ≤ moveLimit）。64 次不收敛回退规范盘面。
    const deal = dealInitialBoard(this.spec.seed, {
      rods: p.rods,
      layersPerRod: p.layersPerRod,
      colors: p.colors,
      moveLimit: p.moveLimit,
    });
    this.board = deal.board;
    this.movesLeft = p.moveLimit; // 0 = 不限步（HUD 隐藏计数）
    if (!deal.deepened) {
      console.warn("[pf/tmpl-sort] 深化发牌 64 次未收敛，回退冻结规范盘面（开局即胜）");
    }

    this.overlayLayer = this.add.container(0, 0).setDepth(50);
    this.computeLayout();
    this.buildBoardSprites();
    this.buildHud();
    this.updateHud();

    this.installInput();
    this.scale.on("resize", () => {
      if (!this.busy) {
        this.deselect();
        this.computeLayout();
        this.relayoutAll();
      }
    });

    // 相位：教程或直接开玩（PF 相位是唯一真源，QC state() 直读）。
    if (this.spec.tutorial.enabled) {
      this.enterTutorial();
    } else {
      this.startPlay();
    }
  }

  // ---------------------------------------------------------------- 布局

  private computeLayout(): void {
    const w = this.scale.width;
    const h = this.scale.height;
    const p = this.spec.params;
    const hudH = Math.max(96, h * 0.13);
    const bottomPad = h * 0.05;
    const availH = h - hudH - bottomPad;
    this.pitch = Math.min((w * 0.94) / p.rods, 130);
    this.rodW = Math.max(34, Math.min(this.pitch * 0.84, 76));
    this.layerH = Math.min(this.rodW * 0.6, Math.max(22, (availH - 26) / p.layersPerRod));
    this.rodH = this.layerH * p.layersPerRod + 14;
    this.originX = w / 2 - (this.pitch * (p.rods - 1)) / 2;
    const centerY = hudH + availH / 2;
    this.baseY = centerY + this.rodH / 2;
  }

  private rodCenterX(rod: number): number {
    return this.originX + rod * this.pitch;
  }

  /** 第 layer 层（0=底）棋子的中心坐标。 */
  private piecePos(rod: number, layer: number): { x: number; y: number } {
    return { x: this.rodCenterX(rod), y: this.baseY - (layer + 0.5) * this.layerH };
  }

  private pieceScale(): number {
    return (this.rodW * 0.92) / PIECE_TEX_SIZE;
  }

  private pieceTexKey(): string {
    return this.textures.exists(USER_TEX_KEYS.piece) ? USER_TEX_KEYS.piece : pieceTexture(this.spec.params.screwMode);
  }

  private rodTexKey(): string {
    return this.textures.exists(USER_TEX_KEYS.rod) ? USER_TEX_KEYS.rod : rodTexture(this.spec.params.screwMode);
  }

  private buildBoardSprites(): void {
    const p = this.spec.params;
    this.stacks = [];
    this.rodG = [];
    const pieceTex = this.pieceTexKey();
    const scale = this.pieceScale();
    for (let r = 0; r < p.rods; r++) {
      const rodImg = this.add.image(0, 0, this.rodTexKey()).setDepth(1);
      this.rodG.push(rodImg);
      const stack: any[] = [];
      for (let layer = 0; layer < this.board[r].length; layer++) {
        const pos = this.piecePos(r, layer);
        const img = this.add
          .image(pos.x, pos.y, pieceTex)
          .setScale(scale)
          .setTint(PALETTE[this.board[r][layer] % PALETTE.length])
          .setDepth(2);
        stack.push(img);
      }
      this.stacks.push(stack);
    }
    this.repositionRods();
  }

  /** 尺寸变化/重排后的整体重摆（不动画）：柱体与棋子对齐布局缓存。 */
  private repositionRods(): void {
    const p = this.spec.params;
    const rodTex = this.textures.get(this.rodTexKey()).getSourceImage();
    const rodScaleX = (this.rodW + 12) / (rodTex.width || 96);
    const rodScaleY = (this.rodH + 16) / (rodTex.height || rodTex.width || 96);
    const scale = this.pieceScale();
    for (let r = 0; r < p.rods; r++) {
      this.rodG[r]
        .setPosition(this.rodCenterX(r), this.baseY - this.rodH / 2)
        .setScale(rodScaleX, rodScaleY);
      for (let layer = 0; layer < this.stacks[r].length; layer++) {
        const pos = this.piecePos(r, layer);
        this.stacks[r][layer].setPosition(pos.x, pos.y).setScale(scale);
      }
    }
  }

  private relayoutAll(): void {
    this.computeLayout();
    this.repositionRods();
    this.buildHudPositions();
    if (this.tutorialGroup && this.tutorialActive) this.showTutorialMarker();
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
    this.movesText = mk("#ffffff");
    this.progressText = mk("#ffe9a8").setOrigin(1, 0);
    this.titleText = mk("#ffd166").setOrigin(0.5, 0);
    this.chipsG = this.add.graphics().setDepth(10);
    this.buildHudPositions();
  }

  private buildHudPositions(): void {
    if (!this.movesText) return;
    const w = this.scale.width;
    const h = this.scale.height;
    const pad = Math.max(16, w * 0.05);
    const fontSize = Math.max(24, Math.round(w * 0.065));
    this.movesText.setFontSize(fontSize).setPosition(pad, h * 0.025);
    this.progressText.setFontSize(fontSize).setPosition(w - pad, h * 0.025);
    this.titleText
      .setFontSize(Math.max(14, Math.round(w * 0.042)))
      .setPosition(w / 2, h * 0.02 + 4)
      .setText(this.spec.title);
    this.track(this.titleText);
    this.updateHud();
  }

  private updateHud(): void {
    if (!this.movesText) return;
    const p = this.spec.params;
    this.movesText.setText(p.moveLimit > 0 ? `×${this.movesLeft}` : "");
    this.progressText.setText(`${this.completed}/${p.colors}`);
    this.track(this.movesText);
    this.track(this.progressText);
    this.score = this.completed * 100;
    this.drawChips();
  }

  /** 已完成色进度点（标题下方一排小圆点，完成的填色）。 */
  private drawChips(): void {
    if (!this.chipsG) return;
    const p = this.spec.params;
    const w = this.scale.width;
    const s = Math.max(0.55, Math.min(2, Math.min(w / 390, this.scale.height / 700)));
    const gap = Math.round(20 * s);
    const r = Math.round(6 * s);
    const y = this.titleText.y + this.titleText.height + Math.round(12 * s) + r;
    const x0 = w / 2 - ((p.colors - 1) * gap) / 2;
    this.chipsG.clear();
    for (let c = 0; c < p.colors; c++) {
      const done = c < this.completed; // 完成数==已满柱单色数（颜色无关次序，示意足够）
      this.chipsG.fillStyle(done ? PALETTE[c % PALETTE.length] : 0x39435f, 1);
      this.chipsG.fillCircle(x0 + c * gap, y, r);
      this.chipsG.lineStyle(2, 0x8d99ae, 0.8);
      this.chipsG.strokeCircle(x0 + c * gap, y, r);
    }
  }

  // ---------------------------------------------------------------- 教程

  private enterTutorial(): void {
    this.tutorialActive = true;
    this.tutorialDone = false;
    this.pf.setState("tutorial");
    // 教程演示柱：最优解源柱（发牌期已保证最优解存在；退化盘面回退首根可动柱）。
    const sol = this.solutions.solution(this.board, this.spec.params.layersPerRod);
    const best: SortMove | null = sol && sol.length ? sol[0] : greedyMove(this.board, this.spec.params.layersPerRod);
    if (best) {
      this.demoRod = best.src;
    } else {
      this.demoRod = this.board.findIndex((rod) => !!topRun(rod));
    }

    const w = this.scale.width;
    const h = this.scale.height;
    this.tutorialGroup = this.add.container(0, 0).setDepth(40);
    const dim = this.add.rectangle(w / 2, h / 2, w, h, 0x000000, 0.5);
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
    this.showTutorialMarker();

    this.tutorialTimer = this.time.delayedCall(this.spec.tutorial.maxSec * 1000, () =>
      this.finishTutorial(),
    );
  }

  private showTutorialMarker(): void {
    if (!this.tutorialGroup || this.demoRod < 0) return;
    while (this.tutorialGroup.length > 2) {
      const last = this.tutorialGroup.getAt(this.tutorialGroup.length - 1);
      this.tweens.killTweensOf(last);
      last.destroy();
    }
    const x = this.rodCenterX(this.demoRod);
    const y = this.baseY - this.rodH * 0.5;
    const ring = this.add.image(x, y, TEX_RING).setScale((this.rodW * 1.3) / 96);
    const hand = this.add.image(x, y + this.layerH * 0.8, TEX_HAND).setScale(this.rodW / 90).setAlpha(0.95);
    this.tweens.add({
      targets: [ring, hand],
      y: "-=" + this.layerH * 0.35,
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
    // 兜底盘面（深化发牌未收敛）可能开局即胜：进入游玩即由真实逻辑结算。
    if (isSolved(this.board, this.spec.params.layersPerRod)) {
      this.busy = true;
      this.time.delayedCall(120, () => this.endGame(true));
    }
  }

  // ---------------------------------------------------------------- 输入

  private installInput(): void {
    this.input.on("pointerdown", (pointer: any) => {
      this.onTap(pointer.x, pointer.y);
    });
  }

  /** 命中检测：x 就近落柱（半柱距内），y 在柱体上下放宽范围内。 */
  private pickRod(px: number, py: number): number | null {
    const p = this.spec.params;
    if (p.rods === 0) return null;
    const approx = Math.round((px - this.originX) / this.pitch);
    const rod = Math.max(0, Math.min(p.rods - 1, approx));
    if (Math.abs(px - this.rodCenterX(rod)) > this.pitch / 2) return null;
    if (py < this.baseY - this.rodH - this.layerH * 2 || py > this.baseY + 26) return null;
    return rod;
  }

  private onTap(px: number, py: number): void {
    if (this.busy || this.ended) return;
    if (this.pf.phase() !== "playing" && !this.tutorialActive) return;
    const rod = this.pickRod(px, py);
    if (rod === null) return;
    if (this.tutorialActive) {
      // 教程期只认演示柱（点中即入局：结束教程并真正选中该柱）
      if (rod !== this.demoRod) return;
      this.finishTutorial();
      this.trySelect(rod, true);
      return;
    }
    const firstTap = !this.firstTapDone;
    this.firstTapDone = true;
    if (this.selected === null) {
      this.trySelect(rod, firstTap);
    } else if (rod === this.selected) {
      this.deselect();
    } else {
      this.tryPour(this.selected, rod);
    }
  }

  /** 该柱当前是否可被点选（有同色顶段且非已完成的满柱）。 */
  private selectable(rod: number): boolean {
    const p = this.spec.params;
    const stack = this.board[rod];
    const top = topRun(stack);
    if (!top) return false;
    if (stack.length === p.layersPerRod && stack.every((c) => c === top.color)) return false;
    return true;
  }

  private trySelect(rod: number, firstTap: boolean): void {
    if (!this.selectable(rod)) {
      // attract.firstClickSucceed：开局第一击永远"有进展"——点到空柱/成品柱时
      // 自动改选最优解源柱（真实选中，非作弊：只影响选中目标，不代替玩家决策）。
      if (firstTap && this.spec.attract.firstClickSucceed) {
        const mv = this.currentBestMove();
        if (mv && this.selectable(mv.src)) {
          this.doSelect(mv.src);
          return;
        }
      }
      this.shakeRod(rod);
      return;
    }
    this.doSelect(rod);
  }

  private doSelect(rod: number): void {
    this.deselect();
    this.selected = rod;
    this.audio?.select();
    // 顶部同色段抬起（纯视觉，不改逻辑）
    const run = topRun(this.board[rod])!.run;
    const stack = this.stacks[rod];
    for (let i = stack.length - run; i < stack.length; i++) {
      this.tweens.add({
        targets: stack[i],
        y: stack[i].y - this.layerH * 0.4,
        duration: 110,
        ease: "quad.out",
      });
    }
    this.drawSelRing(rod);
  }

  private deselect(): void {
    if (this.selected !== null && !this.ended) {
      // 抬起的段落回（若还在原柱——倾倒动画会接管这些图片）
      const stack = this.board[this.selected];
      const run = topRun(stack)?.run ?? 0;
      const imgs = this.stacks[this.selected];
      for (let i = imgs.length - run; i < imgs.length; i++) {
        const pos = this.piecePos(this.selected, i);
        const img = imgs[i];
        if (img) this.tweens.add({ targets: img, x: pos.x, y: pos.y, duration: 90, ease: "quad.in" });
      }
    }
    this.selected = null;
    this.clearSelRing();
  }

  private drawSelRing(rod: number): void {
    this.clearSelRing();
    this.selRing = this.add.graphics().setDepth(3);
    this.selRing.lineStyle(4, 0xffffff, 0.9);
    this.selRing.strokeRoundedRect(
      this.rodCenterX(rod) - this.rodW / 2 - 6,
      this.baseY - this.rodH - 8,
      this.rodW + 12,
      this.rodH + 16,
      12,
    );
  }

  private clearSelRing(): void {
    if (this.selRing) {
      this.selRing.destroy();
      this.selRing = null;
    }
  }

  private shakeRod(rod: number): void {
    const g = this.rodG[rod];
    if (!g) return;
    this.tweens.add({ targets: g, x: "+=6", duration: 50, yoyo: true, repeat: 3, ease: "sine.inout" });
  }

  // ---------------------------------------------------------------- 倾倒与结算

  private currentBestMove(): SortMove | null {
    const layers = this.spec.params.layersPerRod;
    const sol = this.solutions.solution(this.board, layers);
    if (sol && sol.length) return sol[0];
    return greedyMove(this.board, layers);
  }

  private tryPour(src: number, dst: number): void {
    const p = this.spec.params;
    const mv = legalMoves(this.board, p.layersPerRod).find((m) => m.src === src && m.dst === dst);
    if (!mv) {
      // 非法倾倒：目标柱可选则切换选中（真实反馈：换选），否则摇晃提示
      if (this.selectable(dst)) {
        this.deselect();
        this.doSelect(dst);
      } else {
        this.shakeRod(dst);
      }
      return;
    }

    // "将胜"预估：与实际结算同一走法语义（applyMove + isSolved）
    const trial = cloneBoard(this.board);
    applyMove(trial, mv.src, mv.dst, mv.k);
    const willWin = isSolved(trial, p.layersPerRod);

    // attract 剧本：失败以真实"倒到半空倒回"呈现，不消耗步数；hint 保持不变
    if (willWin && this.spec.attract.nearWin && !this.nearWinUsed) {
      this.nearWinUsed = true;
      this.animateNearWin(mv);
      return;
    }
    if (!willWin && !this.firstPlayMoveDone && this.tutorialDone && this.spec.attract.failBait && !this.baitUsed) {
      this.baitUsed = true;
      this.firstPlayMoveDone = true;
      this.animateBounce(mv);
      return;
    }

    // 真实倾倒：逻辑立即生效（画面=逻辑），动画随后回放。
    // 静默清选中（不做落回补间——抬起的这 k 张图片正好由倾倒动画接管）。
    this.busy = true;
    this.firstPlayMoveDone = true;
    this.selected = null;
    this.clearSelRing();
    if (p.moveLimit > 0) this.movesLeft = Math.max(0, this.movesLeft - 1);
    this.audio?.pour();
    applyMove(this.board, mv.src, mv.dst, mv.k);
    this.animatePour(mv, () => this.afterMove());
  }

  /** 当前柱实际抬起的图片数（= 顶部同色段长）。 */
  private stackRun(rod: number): number {
    return topRun(this.board[rod])?.run ?? 0;
  }

  /** 倾倒动画：把 src 顶部 k 张图片抬升 → 飞向 dst → 逐张落入槽位。 */
  private animatePour(mv: SortMove, onDone: () => void): void {
    const imgs = this.stacks[mv.src].splice(this.stacks[mv.src].length - mv.k);
    this.stacks[mv.dst].push(...imgs);
    const scale = this.pieceScale();
    const liftY = this.baseY - this.rodH - this.layerH * 1.1;
    const dstX = this.rodCenterX(mv.dst);
    let pending = imgs.length;
    if (!pending) {
      onDone();
      return;
    }
    imgs.forEach((img, i) => {
      img.setDepth(8);
      const target = this.piecePos(mv.dst, this.stacks[mv.dst].length - imgs.length + i);
      const flightDelay = i * 55;
      this.tweens.add({ targets: img, y: liftY, duration: 110, delay: flightDelay, ease: "quad.out" });
      this.tweens.add({
        targets: img,
        x: dstX,
        duration: 150,
        delay: flightDelay + 110,
        ease: "sine.inout",
      });
      this.tweens.add({
        targets: img,
        y: target.y,
        scale,
        duration: 120,
        delay: flightDelay + 260,
        ease: "quad.in",
        onComplete: () => {
          img.setDepth(2);
          if (--pending === 0) this.time.delayedCall(60, onDone);
        },
      });
    });
  }

  /** attract.failBait：首次倾倒弹回——抬到半空晃一晃放回，不消耗步数。 */
  private animateBounce(mv: SortMove): void {
    this.busy = true;
    this.audio?.select();
    const run = this.stackRun(mv.src);
    const imgs = this.stacks[mv.src].slice(this.stacks[mv.src].length - run);
    const liftedY = this.baseY - this.rodH - this.layerH * 0.7;
    imgs.forEach((img) => {
      this.tweens.add({ targets: img, y: liftedY, duration: 140, ease: "quad.out" });
      this.tweens.add({ targets: img, x: "+=8", duration: 60, delay: 160, yoyo: true, repeat: 3 });
    });
    this.time.delayedCall(520, () => {
      imgs.forEach((img, i) => {
        const pos = this.piecePos(mv.src, this.stacks[mv.src].length - run + i);
        this.tweens.add({ targets: img, x: pos.x, y: pos.y, duration: 130, ease: "quad.in" });
      });
      this.time.delayedCall(160, () => {
        this.busy = false;
      });
    });
  }

  /** attract.nearWin：将胜的一倒"险些失败"——倒到半空、红闪+震屏、倒回原柱；
   *  随后同一最优步再倒即成。不消耗步数，hint 保持不变。 */
  private animateNearWin(mv: SortMove): void {
    this.busy = true;
    this.audio?.danger();
    const shake = this.cameras?.main?.shake;
    if (typeof shake === "function") this.cameras.main.shake(280, 0.009);
    const w = this.scale.width;
    const h = this.scale.height;
    const flash = this.add.rectangle(w / 2, h / 2, w, h, 0xd93a1f, 0).setDepth(44);
    this.tweens.add({ targets: flash, alpha: 0.2, duration: 180, yoyo: true, hold: 140 });

    const run = this.stackRun(mv.src);
    const imgs = this.stacks[mv.src].slice(this.stacks[mv.src].length - run);
    const liftY = this.baseY - this.rodH - this.layerH * 1.1;
    const midX = (this.rodCenterX(mv.src) + this.rodCenterX(mv.dst)) / 2;
    imgs.forEach((img) => {
      this.tweens.add({ targets: img, y: liftY, duration: 130, ease: "quad.out" });
      this.tweens.add({ targets: img, x: midX, duration: 200, delay: 140, ease: "sine.inout" });
    });
    this.time.delayedCall(480, () => {
      imgs.forEach((img, i) => {
        const pos = this.piecePos(mv.src, this.stacks[mv.src].length - run + i);
        this.tweens.add({ targets: img, x: pos.x, duration: 160, ease: "quad.in" });
        this.tweens.add({
          targets: img,
          y: pos.y,
          duration: 170,
          delay: 140,
          ease: "quad.in",
          onComplete: () => {
            if (i === imgs.length - 1) {
              this.tweens.add({ targets: flash, alpha: 0, duration: 140, onComplete: () => flash.destroy() });
              this.busy = false;
            }
          },
        });
      });
    });
  }

  /** 一倒结算（逻辑已在 applyMove 生效）：完成色/进度 → 胜/负判定。 */
  private afterMove(): void {
    const p = this.spec.params;
    const done = completedColors(this.board, p.layersPerRod);
    if (done > this.completed) {
      // 新完成的满柱轻微弹跳庆祝（targets 为该柱图片数组）
      for (let r = 0; r < this.board.length; r++) {
        const stack = this.board[r];
        if (stack.length === p.layersPerRod && stack.every((c) => c === stack[0])) {
          this.tweens.add({
            targets: this.stacks[r],
            scale: "+=0.05",
            duration: 130,
            yoyo: true,
            ease: "quad.out",
          });
        }
      }
    }
    this.completed = done;
    this.updateHud();
    if (isSolved(this.board, p.layersPerRod)) {
      this.endGame(true);
      return;
    }
    if (p.moveLimit > 0 && this.movesLeft <= 0) {
      this.endGame(false);
      return;
    }
    this.busy = false;
  }

  // ---------------------------------------------------------------- 结束页

  private endGame(win: boolean): void {
    if (this.ended) return;
    this.ended = true;
    this.deselect();
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
    panel.fillStyle(PANEL, 0.97);
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
   *  两拍节奏：未选中 → 最优解源柱（tap=点选）；已选中该源柱 → 目标柱（tap=倾倒）。
   *  教程期为演示柱。全部坐标命中真实柱体热区，QC 用真实 pointer 事件点按即可
   *  沿最优线通关（BFS 与 M1 冻结走法同源，见 solver.ts）。 */
  hint(): { x: number; y: number; type: string } | null {
    const phase = this.pf.phase();
    if (phase === "tutorial") {
      if (!this.tutorialActive || this.demoRod < 0) return null;
      return this.rodTapPos(this.demoRod);
    }
    if (phase !== "playing" || this.busy || this.ended) return null;
    if (isSolved(this.board, this.spec.params.layersPerRod)) return null;
    const mv = this.currentBestMove();
    if (!mv) return null;
    if (this.selected === mv.src) return this.rodTapPos(mv.dst);
    return this.rodTapPos(mv.src);
  }

  private rodTapPos(rod: number): { x: number; y: number; type: string } {
    return { x: Math.round(this.rodCenterX(rod)), y: Math.round(this.baseY - this.rodH * 0.5), type: "tap" };
  }

  endScreenVisible(): boolean {
    return this.endScreenShown && this.pf.phase() === "end";
  }
}
