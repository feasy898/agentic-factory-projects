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
| spriteKeys | 恰 5 个 | ≥1 个即可，缺省**恰为 `["piece-0","piece-1","piece-2","piece-3","piece-4"]`**（2026-09-29 钉死键名，spec.ts `spriteKeysRaw.length >= 1 ? … : [同表]`） | 贴图按 `i % spriteKeys.length` 取键 |
| seed | 整数 ≥0 | `int(meta.seed, 1, 0, 0x7fffffff)`——**参数序 (v, default, min, max)，2026-09-29 回炉消歧**：缺省 1、下界 0、上界 0x7fffffff（非整/非有限数取缺省，`Math.round` 后钳制） | |
| difficulty.targetLevel | 0–1 | 0–1 / 缺省 0.5 | **读入后无玩法消费（痛点，见 CONTRACTS §痛点 3）** |
| attract.nearWin | — | **缺省 `false`**（2026-09-29 回炉补位：`bool(attract.nearWin, false)`） | nearWin 剧本见 §6 |
| attract.firstClickSucceed | 默认 true | 归一保留，缺省 true | **读入后无玩法消费** |
| tutorial.gesture | tap\|drag | 非 "tap" 一律 "drag"（大小写敏感） | |
| qc.maxLoadSec | 0.5–10 / 2.0 | **缺省 2**，钳制 1–10（2026-09-29 回炉钉死：`int(qc.maxLoadSec, 2, 1, 10)`） | QC 竖屏趟 load 预算 |
| qc.autoplayTimeoutSec | 5–120 / 45 | **缺省 45**，钳制 5–300（2026-09-29 回炉钉死：`int(qc.autoplayTimeoutSec, 45, 5, 300)`） | 与 schema 上限 120 不一致是**模板更宽**的如实记录 |

文案查找 `makeT`：当前语言 → 默认语言 → `en` → 键名本身（三级回退）。

## 2. 盘面生成（board.ts，确定性）

- 随机源：`mulberry32(meta.seed)`（主流，生成期消耗顺序即下述步骤顺序）。
- **索引→格映射（2026-09-29 回炉钉死）**：内部格索引为扁平 `idx = y*cols + x`（**行优先**，y=行、
  x=列，原点左上）；`place_jelly` 的洗牌序号取模映射即 `(row, col) = (idx // cols, idx % cols)`。
- `fillNoMatches`：行优先逐格取 `floor(rng()*colors)`；若与左侧两格或上方两格同色则重抽（每格至多 32 次尝试，
  超限后**接受最后一次取值**——32 次内概率上必然找到，不做更强保证）。
- `generate`：fillNoMatches 后若无任何可行步则整体重来（guard ≤200 次），然后摆果冻。
- `placeJelly(count)`：Fisher-Yates 洗牌 `[0..cols*rows)`（同一 rng 流），取前 count 格为果冻。
  **方向（2026-09-29 回炉钉死）**：`for i = total-1; i > 0; i--`（**自 n-1 降至 1 降序**），
  `j = floor(rng()*(i+1))`，`swap(order[i], order[j])`；首个抽号来自 i = total-1。
- score 模式果冻数 = `min(cols*rows, max(6, round(cols*rows*0.25)))`（round = JS Math.round，
  .5 向上；clear-jelly 模式 = goalCount）。
- **生成期 64 次重试的流消耗方式（2026-09-29 回炉钉死）**：`mulberry32(meta.seed)` 在
  game.ts `create()` **只构造一次**并持有于 Board——每次重试 `generate()` 的
  fillNoMatches（含逐格重抽）+ hasAnyMove 守卫重盘 + placeJelly **顺序消耗同一主流**，
  不重置、不换流；故各次重试盘面互异且全程确定（重试次数也确定）。
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
- `ResolveResult = { steps[], cleared[], cascades, score, finalGrid }`；**steps[] 元素 schema
  （2026-09-29 回炉钉死，三型交替出现）**——格位置一律扁平索引 `idx = y*cols + x`（行优先）：
  - `{t:"match", cells: number[]}`——本波被清格索引，**升序**；`cleared` 全程**去重**并集
    （按首次清除顺序，非排序）；`cascades = 最后一个成消波的波号 w`，`score += cells.length * 10 * w`；
  - `{t:"fall", moves: Array<{from: number, to: number}>}`——重力位移（每列自底向上压实；
    **falls 为空则该步整个省略**——被清行在顶部时块体贴底不动，位移可以为零）；
  - `{t:"spawn", cells: Array<{index: number, piece: number}>}`——补位格按**扫描顺序**记录：
    **列优先（x 外层）、每列自上而下（y 内层）**，逐格当场 `floor(rng()*colors)` 出子并记录
    （rng 消耗顺序 = 扫描顺序，这是补位流可复现的关键）；
    补位为空则该步同样省略。
  视图层逐步回放 steps 做动画
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

- **mulberry32 函数体（2026-09-29 回炉内联成文，消除"规范公版 vs 变体"分歧——以模板
  `rng.ts` 原文为准，bryc 规范公版）**：

  ```js
  function mulberry32(seed) {
    let a = seed >>> 0;                       // 状态 uint32
    return () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);   // 注意第二乘数是 t|61，非常数 61
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function deriveRng(seed, salt) {            // 派生流
    return mulberry32((seed ^ Math.imul(salt, 0x9e3779b9)) >>> 0);
  }
  ```

  **变体风险实录（本卡第三波再生实测）**：mulberry32 存在流传变体，第二乘数 `t|61`
  与常数 `61` 两者**不同流**。实现者自建对照 oracle 时若转写成 `* 61` 即偏离本模板
  （首个输出 mulberry32(1)：本模板 = **0.6270739405881613**，`*61` 变体 = 0.428673…）。
  **算例（真源=模板 rng.ts，Node 22 实测）**：mulberry32(1) 首 5 抽 =
  `0.627074, 0.002736, 0.527447, 0.981051, 0.968378`；mulberry32(42) 首 5 抽 =
  `0.601104, 0.448291, 0.852466, 0.669734, 0.174814`；deriveRng 的混合不经过 t|61 线、
  两变体一致：deriveSeed(42, SPAWN_SALT^1) = `0xdafaf010`、deriveSeed(9, 0x5117^1) = `0x2647feef`。
- k 的计算（trySwap 先捕获盐再扣步数，保证预估/结算/hint 三者同一 k）：
  **第 k 次玩家交换与第 k 步死局重排的 k 统一 = `moves − movesLeft + 1`**（重排发生时的
  k = 即将进行的玩家交换序号；simulatePlay 中第 k 步死局用 `0x5117 ^ k`，重排不耗步、
  同一 k 在重排后仍用于下一步补位流）。
- **推论（生成期可玩性保证）**：hint 用与真实游玩完全相同的流与贪心策略，所以"生成期 64 次重试找到
  simulatePlay 可胜盘面" ⇔ "QC 按 hint 引导必然可胜"。64 次仍不可胜则告警并按最后盘面放行（概率上不会发生）。

## 8. 求解器与 hint（solver.ts）

- `bestMove`：枚举全部可行交换（`allMoves`：只扫 right/down 两个方向去重），每个候选用**同一补位流**
  完整模拟连消，评价值 = clear-jelly：`果冻×1000 + score×2 + cascades×15`；score 模式：`score×10 + cascades×15`。
  **并列取优规则（2026-09-29 回炉钉死）**：`ev.value > best.value` **严格更大才替换**——并列时取
  `allMoves` 序靠前（扫描序 = 行优先 y 外层、x 内层，dir 内层 right→down）；每个候选各自从
  `deriveRng(seed, SPAWN_SALT ^ k)` 新建流（候选间同流、逐候选重置，保证可比）。
- **hint 布局数学（2026-09-29 回炉成文，game.ts `computeLayout`）**：设视口 w×h（画布铺满视口，
  世界坐标 = CSS 像素）——
  `hudH = max(96, h×0.13)`；`availW = w×0.94`；`availH = h − hudH − h×0.05`；
  `cell = max(24, floor(min(availW/cols, availH/rows)))`；
  `originX = Math.round((w − cell×cols)/2)`；`originY = Math.round(hudH + (availH − cell×rows)/2)`。
  格中心 `cellCenter(x,y) = (originX + x·cell + cell/2, originY + y·cell + cell/2)`，
  hint 出口 `Math.round` 取整。
  **四舍五入 = JS `Math.round`（= floor(x+0.5)，正负数 .5 均向 +∞）**——`Math.round(2.5)=3`、
  `Math.round(0.5)=1`、`Math.round(−2.5)=−2`，与 Python 的银行家舍入（`round(2.5)=2`）**可区分**，
  镜像实现须显式实现 `jsRound` 而不可直接用 Python `round`。
  **参数化算例（Layout(cell, ox, oy) 抽离视口后验证，可离线复算）**：cell=60、ox=oy=0 时
  格 (2,1) 中心 = ((2+0.5)×60, (1+0.5)×60) = (150, 90) → hint `{x:150, y:90, type:"swap-right"}`；
  cell=50 时格 (0,0) → `{x:25, y:25, type:"swap-down"}`；cell=40、ox=4.5 时格 (0,0) 中心 x =
  jsRound(4.5+20) = **25**（Python round(24.5)=24，恰可区分）。
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
- 贴图外观由 `spriteKeys` 键名驱动：FNV-1a 哈希（2166136261/16777619，逐字符 `h ^= c; h = imul(h, 16777619)`，
  最终 `>>> 0`）→ 形状 5 选 1（`h % 5`）+ 调色板 7 色 `PALETTE[(h + i) % 7]`（i = 棋子序号 0 起）；
  colors 决定实际使用的键数量。
  **形状枚举序（2026-09-29 回炉钉死）**：`circle(圆) → diamond(菱) → square(方) → triangle(三角) → hexagon(六边)`。
  **调色板 7 色色值表（2026-09-29 回炉钉死）**：

  | 序 | 色值 | 色 |
  |---|---|---|
  | 0 | `0xff5a5f` | 红 |
  | 1 | `0xffc145` | 琥珀 |
  | 2 | `0x2ec4b6` | 青绿 |
  | 3 | `0x4d96ff` | 蓝 |
  | 4 | `0xb388eb` | 紫 |
  | 5 | `0xff8fab` | 粉 |
  | 6 | `0x9adf5d` | 绿 |

  **算例（默认键名 piece-0..4、colors=5；已过真实 gate）**：FNV 已知向量 `fnv1a("")=2166136261`、
  `fnv1a("a")=0xe40c292c`、`fnv1a("foobar")=0xbf9cf968`；

  | i | 键 | FNV-1a h | h%5 → 形状 | (h+i)%7 → 色值 |
  |---|---|---|---|---|
  | 0 | piece-0 | 1612991320 (0x60244b58) | 圆 | 3 → `0x4d96ff` |
  | 1 | piece-1 | 1629768939 (0x61244ceb) | 六边 | 2 → `0x2ec4b6` |
  | 2 | piece-2 | 1646546558 (0x62244e7e) | 三角 | 1 → `0xffc145` |
  | 3 | piece-3 | 1663324177 (0x63245011) | 方 | 0 → `0xff5a5f` |
  | 4 | piece-4 | 1680101796 (0x642451a4) | 菱 | 6 → `0x9adf5d` |

- 评委改素材路径看不到画面变化是**已知缺口**（CONTRACTS §痛点 4）；改标题/文案/seed 立即可见。
- **范围标注（2026-09-29 回炉）**：相位机/教程定时、结束页 CTA 与热区、RTL 文档方向、音频
  （RIFF/WAV data URI 合成）与程序化贴图绘制**属模板侧**（`game.ts/main.ts/audio.ts/textures.ts`，
  契约见桥 spec §4.2 与 [templates.md](templates.md)）——本卡 §9–§11 只如实记录其行为供验收对照；
  "规则核"的镜像复算（再生成试验的可测面）以 §1–§8 + §11 的**纯派生部分**（FNV/形状/调色板）
  为界，模板侧交互行为不在镜像范围。

## 12. 数值算例（已知答案，冻结——2026-09-29 回炉新增）

> 本节算例是卡面的**可执行验收物**：镜像实现须逐条复算相符。真源 = 模板 TS 源码
> （`board.ts/solver.ts/rng.ts/textures.ts`）在 Node 22 下的实跑输出；出处标注 [frozen] 的
> 盘面构造转写自重生成试点的冻结 eval（`tests/frozen.py`，其断言已被真实 gate 验证）。

**算例 A——seed 首 5 抽**：见 §7 mulberry32 内联块（mulberry32(1) / mulberry32(42) 各首 5 抽、
deriveSeed 混合值）。镜像实现先过此条再谈盘面。

**算例 B——恰一合法步盘** [frozen]（3×3，colors=3）：

```
1 0 1
2 1 2
0 0 2
```

12 个候选相邻交换逐一手工验证，`allMoves` 恰为 `[{x:1, y:0, dir:"down"}]`（交换 (0,1)-(1,1)
后 row0 成 `[1,1,1]`）；`hasAnyMove=true`。取果冻 = row0 三格时该步将胜（清 3 果冻 → progress 3）；
果冻改取 (1,0) 时同一步合法但非胜（供 failBait/负局算例）。`bestMove` 该盘返回同一步，
`win=true`、`progress=3`，评价值 `eval_clear(3, score, cascades)`。

**算例 C——死局盘** [frozen]（3×3 拉丁方，colors=3）：

```
0 1 2
1 2 0
2 0 1
```

行列皆三色互异 → 任何相邻交换都不成 run：`allMoves = []`、`hasAnyMove=false`；
playing 相位 `hint()` 返回 `null` 并触发 `doReshuffle`（0x5117 流，k=1）。

**算例 D——两级连消盘波形** [frozen]（5 列×3 行，colors=2，补位流用脚本
`[0,1,1,0,0,1,0,1,0]` 逐抽注入——`floor(rng()*2)` 恰还原脚本值）：

```
0 1 0 1 1
0 1 1 0 1
0 1 0 1 0
```

期望输出（实跑真源模板 `Board.resolve`，扁平 idx=y·cols+x）：

- 补位流恰消耗 **9 次**（波1 六抽 + 波2 三抽）；`cascades = 2`；
  `score = 120`（波1 `6格×10×1=60` + 波2 `3格×10×2=60`）。
- steps 波形 = `match → spawn → match → spawn`（**两波都无 fall 步**：波1 整列被清、
  波2 顶行被清，块体贴底无位移——fall 步在无位移时整个省略，见 §4）。
- 波1 `match.cells = [0,1,5,6,10,11]`（col0+col1 各 run3，升序）；
  波1 `spawn.cells` 顺序 = 列优先自上而下：
  `[{0,p0},{5,p1},{10,p1},{1,p0},{6,p0},{11,p1}]`。
- 波2 `match.cells = [0,1,2]`（row0 成 `[0,0,0]`）；波2 `spawn.cells = [{0,p0},{1,p1},{2,p0}]`；
  波3 补位后无消即停。
- `cleared = [0,1,5,6,10,11,2]`（去重、按首次清除顺序，7 格）；终盘
  `[[0,1,0,1,1],[1,0,1,0,1],[1,1,0,1,0]]`。

**算例 E——重力位移观测盘** [frozen]（3×3，colors=2，补位脚本 `[0,1,0]`）：

```
1 1 0
0 0 0
1 0 1
```

波1 row1 三连清（`match.cells=[3,4,5]`）；重力 `fall.moves =
[{from:0,to:3},{from:1,to:4},{from:2,to:5}]`（row0 三格各下落一格，自底向上压实）；
波1 补位顶部三格后无消即停：`cascades=1`、`score=30`、
`spawn.cells=[{0,p0},{1,p1},{2,p0}]`、终盘 `[[0,1,0],[1,1,0],[1,0,1]]`。

**算例 F——评价值与取整**：`eval_clear(0,30,1)=75`、`eval_clear(1,30,1)=1075`、
`eval_clear(2,45,3)=2135`（=2000+90+45）、`eval_score(30,2)=330`；
`Math.round` 语义：`2.5→3`、`0.5→1`、`−2.5→−2`、`24.5→25`（银行家舍入可区分，见 §8）。

## 13. 验收断言（现状 + 缺口）

- 已固化：`scripts/gate_phase1.py` 门项 4 = 构建 + qacore --autoplay 全过 + pf:end ≤45s（实测 pf:end ≈26.6s）。
- 已知验收缺口（如实记录，未实装）：nearWin 剧本无断言；素材使用率无断言；`difficulty`/`firstClickSucceed`
  无断言（因无消费方）。第二条模板开工时按本卡同等精度补齐。
