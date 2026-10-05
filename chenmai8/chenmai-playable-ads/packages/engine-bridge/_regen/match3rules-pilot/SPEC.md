# 三消规则卡（Match3 Rules Card）

> 版本：冻结 v1.0.0（2026-09-28，对照 `packages/templates/tmpl-match3/src/` 逐文件核验）。
> 本页是三消玩法的唯一权威描述：交换、消除、下落、连消、计分、果冻、nearWin 的精确定义、
> 随机流与盐值、hint 坐标系、素材缺失时的行为。**第二条模板开工前，必须有同等精度的一页。**
> 位置：`packages/templates/tmpl-match3/src/{board,rng,solver,game,spec,textures,audio,main}.ts`。

---

## 1. 参数与宽容归一（spec.ts）

校验权威在 M1（schema + 不变式）。模板入口 `normalizeSpec(raw)` 做**宽容归一**（LLM 只填偏差项也能跑），
钳制范围与 schema 范围**不完全一致**（模板更宽，如实记录）：

| 参数 | schema 范围/默认 | 模板归一钳制/默认 | 备注 |
|---|---|---|---|
| cols / rows | 4–9 / 6 | 3–9 / 6 | |
| moves | 3–60 / 15 | 1–60 / 15 | |
| colors | 3–5 / 5 | 2–7 / 5 | |
| goalCount | 1–999 / 30 | 1–400 / 30 | |
| goalType | clear-jelly \| score | 非 "score" 一律 clear-jelly | |
| spriteKeys | 恰 5 个 | ≥1 个即可，缺省 5 个 piece-* | 贴图按 `i % spriteKeys.length` 取键 |
| seed | 整数 ≥0 | int(v, 1, 0, 0x7fffffff) | 缺省 1 |
| difficulty.targetLevel | 0–1 | 0–1 / 缺省 0.5 | **读入后无玩法消费（痛点，见 CONTRACTS §痛点 3）** |
| attract.firstClickSucceed | 默认 true | 归一保留 | **读入后无玩法消费** |
| tutorial.gesture | tap\|drag | 非 "tap" 一律 "drag" | |
| qc.maxLoadSec / autoplayTimeoutSec | 0.5–10 / 5–120 | 1–10 / 5–300 | |

文案查找 `makeT`：当前语言 → 默认语言 → `en` → 键名本身（三级回退）。

## 2. 盘面生成（board.ts，确定性）

- 随机源：`mulberry32(meta.seed)`（主流，生成期消耗顺序即下述步骤顺序）。
- `fillNoMatches`：行优先逐格取 `floor(rng()*colors)`；若与左侧两格或上方两格同色则重抽（每格至多 32 次尝试，
  超限后**接受最后一次取值**——32 次内概率上必然找到，不做更强保证）。
- `generate`：fillNoMatches 后若无任何可行步则整体重来（guard ≤200 次），然后摆果冻。
- `placeJelly(count)`：Fisher-Yates 洗牌 `[0..cols*rows)`（同一 rng 流），取前 count 格为果冻。
- score 模式果冻数 = `min(cols*rows, max(6, round(cols*rows*0.25)))`（clear-jelly 模式 = goalCount）。
- 死局重排 `reshuffle`：保留果冻，重新 fillNoMatches + hasAnyMove 守卫（guard ≤200）。

## 3. 交换（game.ts 输入）

- 两种输入：① pointer 按下后拖拽，位移阈值 `max(18, cell*0.35)` 像素，主轴定方向；
  ② 点选两相邻格（tap-tap）。
- `trySwap`：busy/ended 时忽略；相位非 playing 且非教程时忽略。
- 非法交换（无三连）或剧本失败 → `animateInvalidSwap`：110ms 滑过去再弹回，**不消耗步数**。

## 4. 消除 / 下落 / 补位 / 连消（board.ts `resolve`，单实现两处复用）

- `matchMask`：行、列各扫一遍，同色 run ≥3 即标记（交叉处都算）。
- 波次循环（至多 **64 波**，防死循环上限）：match → 重力 → 补位，无消除即停。
- 重力：每列自底向上压实被清格，记录 `{from,to}` 位移；顶部空位先置 -1。
- 补位：**列优先、每列自上而下**扫描 `-1` 格，逐格 `floor(rng()*colors)` 生成新棋子（rng 消耗顺序 = 扫描顺序，
  这是补位流可复现的关键）。
- `ResolveResult = { steps[], cleared[], cascades, score, finalGrid }`；视图层逐步回放 steps 做动画
  （match 150ms 缩消、fall 160ms、spawn 170ms 下落、波间 delay 170/180/190ms），逻辑立即生效，动画完后 snap 对齐。

## 5. 计分与胜负

- 得分：第 w 波每格 `10*w` 分（连消越深单格越值钱）。
- clear-jelly：进度 = 已清果冻数；score 模式：进度 = score，目标同为 goalCount。
- 胜：结算后 `progress >= goalCount` → `pf.end(true)` + 结束页。
- 负：`movesLeft <= 0` → `pf.end(false)`。
- 死局（无任何可行步）→ 自动重排（不耗步，280ms 后 snap、560ms 解 busy）。

## 6. nearWin / failBait / firstClickSucceed（attract 剧本）

- **nearWin 精确定义**：某次合法交换若将胜（用与真实结算**同一补位流**预估），且 `attract.nearWin=true`
  且未触发过 → 该次交换按非法交换回弹呈现（不耗步），只触发**一次**；下次同样交换将真实结算获胜。
- **failBait**：教程结束后的第一个"非胜"合法交换回弹一次（不耗步），只一次。
- 两者都用 `animateInvalidSwap`（回弹即"失败以真实非法交换呈现"，不是假动画）。
- `firstClickSucceed`：schema 归一保留但当前无实现（如实在此声明）。

## 7. 随机流与盐值（跨生成/模拟/真实游玩一致性的核心，冻结）

| 流 | 派生式 | 用途 |
|---|---|---|
| 主流 | `mulberry32(meta.seed)` | 盘面生成、果冻摆放 |
| 补位流（第 k 次玩家交换，k 从 1 起） | `deriveRng(seed, SPAWN_SALT ^ k)`，`SPAWN_SALT = 0x51ed270b` | 真实结算、nearWin 预估、hint 投影、生成期 simulatePlay —— 四者同流 |
| 死局重排流（第 k 步） | `deriveRng(seed, 0x5117 ^ k)` | doReshuffle 与 simulatePlay 重排 |
| deriveRng | `mulberry32((seed ^ imul(salt, 0x9e3779b9)) >>> 0)` | — |

- k 的计算：`moves - movesLeft + 1`（trySwap 先捕获盐再扣步数，保证预估/结算/hint 三者同一 k）。
- **推论（生成期可玩性保证）**：hint 用与真实游玩完全相同的流与贪心策略，所以"生成期 64 次重试找到
  simulatePlay 可胜盘面" ⇔ "QC 按 hint 引导必然可胜"。64 次仍不可胜则告警并按最后盘面放行（概率上不会发生）。

## 8. 求解器与 hint（solver.ts）

- `bestMove`：枚举全部可行交换（`allMoves`：只扫 right/down 两个方向去重），每个候选用**同一补位流**
  完整模拟连消，评价值 = clear-jelly：`果冻×1000 + score×2 + cascades×15`；score 模式：`score×10 + cascades×15`。
- `__PF_QC__.hint()` 坐标系：**视口 CSS 像素**（画布铺满视口，世界坐标 = CSS 像素；cellCenter 四舍五入取整）；
  返回 `{x, y, type}`，type ∈ `swap-up|swap-down|swap-left|swap-right`（语义 = 从 (x,y) 格向该方向与邻格交换）。
- 返回 null 的情形：教程相位无 demo；busy / ended；playing 无步（此时会触发 doReshuffle）。
- 教程相位 hint 返回 `tutorialDemo` 坐标（= bestMove，无最优步时取 allMoves[0]）。

## 9. 流程与相位（main.ts / game.ts / 桥契约 §4.2）

- 启动：DOM ready → `PF.ready` → new Match3Scene → 引擎 Game（RESIZE 缩放、60fps、背景 0x141b34）。
- 相位机唯一真源 = 桥 `PF.phase()/setState()`：教程 `setState("tutorial")` → `maxSec*1000` 定时器自动结束教程
  （或首次合法交换结算后提前结束）→ `PF.start()`（playing）→ 结束 `PF.end(win)`（end）。
- 结束页：半透明遮罩(α0.62) + 面板 + win/lose 文案 + （showScore）分数 + CTA 按钮（脉冲动画，热区 1.3×/1.6×）
  → 点击调 `PF.open(landingUrl)`（pf:cta + 渠道退出路由）。
- RTL：`spec.rtl` 含当前 locale 时 `document.documentElement.dir = "rtl"`。

## 10. 音频（audio.ts）

- 一切音频经 `PF.audio.create(dataURI)` 创建（首交互前自动 muted，契约见桥 spec）。
- 预览构建无外部素材文件：代码生成合法 RIFF/WAV data URI（8bit 单声道）：
  tap = 11025Hz / 60ms / 880Hz / gain 0.5；win = 11025Hz / 350ms / 1318Hz / gain 0.5；起始 5% 淡入防爆音。

## 11. 素材缺失行为（重要边界）

**spec.assets 里的 background/sprites/audio 路径当前完全不参与渲染**：贴图在 Boot 阶段程序化生成
（96px，`Graphics.generateTexture`）；素材路径缺失**不报错、不加载**。
- 贴图外观由 `spriteKeys` 键名驱动：FNV-1a 哈希（2166136261/16777619）→ 形状 5 选 1（圆/菱/方/三角/六边）
  + 调色板 7 色 `(h+i) % 7`；colors 决定实际使用的键数量。
- 评委改素材路径看不到画面变化是**已知缺口**（CONTRACTS §痛点 4）；改标题/文案/seed 立即可见。

## 12. 验收断言（现状 + 缺口）

- 已固化：`scripts/gate_phase1.py` 门项 4 = 构建 + qacore --autoplay 全过 + pf:end ≤45s（实测 pf:end ≈26.6s）。
- 已知验收缺口（如实记录，未实装）：nearWin 剧本无断言；素材使用率无断言；`difficulty`/`firstClickSucceed`
  无断言（因无消费方）。第二条模板开工时按本卡同等精度补齐。
