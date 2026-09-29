# @pf/tmpl-match3（factory 移植版）

三消/叠叠消玩法模板（M3）。PlayableSpec（schema v1）驱动渲染：
`node build.mjs --spec <spec.json>` 产出单文件 HTML 产物（零外链、零相对资源引用）。

> **移植出处（模式 M）**：按 oracle 规格源 `repo/docs/assets/specs/match3-rules-card.md`
> （唯一规则权威）+ `repo/docs/assets/specs/templates.md` §2/§3 全新实现于 factory
> 仓；oracle 实现代码只作行为参考、未字节复制（vendor bundle 与 logic-test 除外，
> 见下）。冻结验收：`tests/logic-test.ts` **字节复用**（6 断言：生成不变式 / 最优步
> 合法 / 生成期 64 次重试全可胜 / hint 线=模拟线）+ 构建后 qacore autoplay。

## SPEC 落实（规则卡 §1–§11）

- **宽容归一（§1）**：`normalizeSpec` 钳制面——cols/rows 3–9（默认 6）、moves 1–60
  （默认 15）、colors 2–7（默认 5）、goalCount 1–400（默认 30）、goalType 非 "score"
  一律 clear-jelly、seed 缺省 1 钳 0–0x7fffffff、`qc.maxLoadSec` 钳 1–10（默认 2）、
  `qc.autoplayTimeoutSec` 钳 5–300（默认 45，比 schema 上限 120 更宽——如实记录）；
  spriteKeys 缺省恰为 `piece-0..piece-4`；`attract.nearWin` 缺省 false；
  `difficulty.targetLevel`/`firstClickSucceed` 归一保留、当前无玩法消费（如实声明）。
- **盘面生成（§2）**：`mulberry32(seed)` 主流只构造一次，64 次生成重试顺序消耗同一
  流；fillNoMatches 行优先逐格（32 次重抽上限）；Fisher-Yates 果冻摆放（n-1 → 1 降序）；
  score 模式果冻数 = min(cols×rows, max(6, round(cols×rows×0.25)))。
- **结算（§4）**：match → 重力 → 补位波次循环（≤64 波）；steps 三型
  match/fall/spawn（fall/spawn 为空整步省略）；补位流 = 列优先自上而下当场出子；
  score = 10×波号×格数。
- **随机流（§7，冻结）**：补位流 `deriveRng(seed, SPAWN_SALT ^ k)`（SPAWN_SALT =
  0x51ed270b，k = moves − movesLeft + 1，trySwap 先捕获盐再扣步数）；死局重排流
  `0x5117 ^ k`；mulberry32 第二乘数为 `t|61`（规则卡 §7 内联块为准）。
- **hint（§8）**：枚举全部可行交换（right/down 去重）逐候选同流模拟，评价值
  clear-jelly = 果冻×1000 + score×2 + cascades×15（score 模式 score×10 + cascades×15），
  严格更大才替换；坐标 = 格中心视口 CSS 像素 Math.round；type ∈ `swap-up/down/left/right`。
- **attract（§6）**：nearWin（将胜的一步回弹一次）/ failBait（教程后首个非胜合法交换
  回弹一次）均以真实"非法交换回弹"呈现、不耗步；`firstClickSucceed` 无实现（如实）。
- **教程→游玩→结束页（§9）**：`setState("tutorial")` → maxSec 定时（或首次合法交换
  结算后）提前结束 → `PF.start()` → 胜/负 `PF.end(win)` → 结束页（遮罩 α0.62 + win/lose
  + showScore + CTA 脉冲热区 1.3×/1.6× → `PF.open(landingUrl)`）。相位与 pf:end 只由
  真实游戏逻辑触达。
- **QC 钩子全集**：`hint()/state()/endScreenVisible()/texts()/textStates()/assets()`
  （textStates 在采样瞬间核验对象 active+visible，已销毁如实上报不可见）。
- **音频（§10）**：一切经 `PF.audio.create()`；tap=11025Hz/60ms/880Hz、
  win=11025Hz/350ms/1318Hz，RIFF/WAV data URI（8bit 单声道，起始 5% 淡入）。
- **素材缺失行为（§11）**：贴图程序化生成（96px）；FNV-1a（2166136261/16777619）→
  形状 5 选 1 + 7 色调色板 `(h+i)%7`；spec.assets 路径缺失不报错不加载。

## 用户 PNG 替换棋子（最小素材路径）

`spec.assets.sprites` 里**文件真实存在**的键（png/jpg/webp/gif，相对 spec 目录或仓库
根解析）在构建期被读出并以 data URI 内联进 `window.PF_ASSETS`；运行期解码、contain
等比归一到 96×96 画布后注册为该棋子色号的贴图。**声明并嵌入即替换；未声明/缺失/
解码失败即程序化回退**（构建日志告警，不阻塞）。真实嵌入清单写旁车
`<out>.assets.json`（make 据此给 CHK10 传 `--require-sprite`，QC 在页面内做像素
对账——`assets()` 上报 mad/replaced，阈值 16×16 平均绝对差 ≤8）。

## 可玩性保证（模板交付物，非 QC 作弊）

盘面生成期用贪心最优线做可玩性模拟（与 hint 同一补位流调度），64 次重生成内仍不可胜
才放行并告警；死局自动重排（不耗步，280ms/560ms 节拍）。`hint()` 即该贪心求解器在
当前盘面上的真实最优步——`tests/logic-test.ts` 断言"hint 驱动线 = 生成期模拟线"。

## 引擎 bundle（中性名 vendor 件，字节复用）

`src/vendor/engine.js` 从 factory 母本 `packages/templates/vendor/engine.js` **字节
复制**（sha256 `660aa854…`，版本锚 3.88.2，~1.2MB，已中性化、词表扫描零命中；
生成与中性化流程见母本 README）。禁止改动或重新生成；`src/vendor/engine.d.ts` 为
factory 侧手写类型垫片（只声明用到的导出面）。

## 构建 / eval

```bash
npm run build        # 默认 golden spec → artifacts/preview/match3.html（~1.2MB 零外链）
npm run logic        # 冻结 logic-test（字节复用 oracle，6 断言）exit 0
npm run typecheck    # tsc --noEmit strict
```

验收门语义（templates.md §6）：构建 exit 0 + qacore `--autoplay` 无 fail +
pf:end ≤ 45000ms。factory 侧 qacore（M2.2）落地前，以 oracle qacore
（`repo/python/.venv`）对本构建产物做临时验收。
