# @pf/tmpl-merge（factory 移植版）

合成玩法模板（M3）。PlayableSpec（schema v1）驱动渲染：
`node build.mjs --spec <spec.json>` 产出单文件 HTML 产物（零外链、零相对资源引用）。

> **移植出处（模式 M）**：按 oracle 规格源 `repo/docs/assets/specs/templates.md`
> §7.1 + 包内 README/`tests/logic-test.ts` 语义全新实现于 factory 仓；oracle 实现
> 代码只作行为参考、未字节复制（vendor bundle 与 logic-test 除外，见下）。冻结验收：
> `tests/logic-test.ts` **字节复用**（10 断言：生成不变式 / 合成结算有效性 /
> hint 线=模拟线含步数得分逐局一致 / 紧参数鲁棒性）+ 构建后 qacore autoplay。

## 玩法模型（冻结，templates.md §7.1）

盘面 cols×rows 恒满；一步 = 从源格向 dir 拖动，相邻**同阶**棋子合成升一阶
（升级弹跳动画），源格清空 → 源列重力下落 → 列顶补 1 个出生棋子
（tier ∈ 1..spawnTierMax）。盘面出现 ≥ goalTier 的棋子即胜（`pf:end {win:true}`）；
无 move 参数，但有硬步数预算：`movesLeft` 初始 = cols×rows×2，每步合成减一，
耗尽即 `pf:end {win:false}` 真实败局（真实收束，不是"卡死兜底"的软上限；最优线远
用不到）；死局自动重排（保留棋子重摆，不耗步）。满阶（maxTier）棋子为终态不再合成。

## SPEC 落实

- **spec 驱动渲染**：§4.1 merge params 全部生效——`cols/rows` 盘面尺寸（3–9，默认 5）、
  `maxTier` 棋子阶数与贴图组数（2–8，默认 5）、`spawnTierMax` 出生阶上限（< maxTier，
  默认 2）、`goalTier` 目标阶（≤ maxTier，默认 4；HUD 进度条/进度文本随之变化）、
  `spriteKeys` 键名参与程序化贴图的形状与配色推导（键名变 → 画面变；tier i 用
  `spriteKeys[(i-1) % len]`；高阶半径随阶增长、tier ≥ 3 中心芯饰）。
- **3 秒内 `pf:ready`**：入口先装配 engine-bridge（`window.PF`），渠道就绪即派发
  `pf:ready`；渲染引擎在 `PF.ready` 后启动。
- **教程→游玩→结束页**：`flow.tutorial`（手势引导，`maxSec` 超时自动开玩，首次合法
  合成结算后提前结束）→ `pf:start` → 合成出 goalTier 或预算耗尽 → `pf:end {win}` +
  结束页（`showScore`、`ctaKey` 本地化文案，点击 CTA → `PF.open(landingUrl)` →
  `pf:cta`）。相位与 pf:end 只由真实游戏逻辑触达。
- **attract 参数生效**：`attract.nearWin=true` 时最后一步（将合成出 goalTier 的一步）
  以真实"不可合成回弹"失败一次（不消耗步数），随后再成；`attract.failBait` 同机制
  作用于第一步。回弹是真实游戏反馈，hint 始终返回真实最优步坐标。
- **随机流（冻结）**：第 k 次合成补位流 `deriveRng(seed, SPAWN_SALT ^ k)`
  （SPAWN_SALT = 0x4c7a11e5，k = movesMade + 1，tryMerge 先捕获盐再计步）；死局重排流
  `deriveRng(seed, RESHUFFLE_SALT ^ k)`（RESHUFFLE_SALT = 0x5117）。游戏侧=模拟侧
  单实现，logic-test 断言"hint 线 = 模拟线"（含步数/得分逐局一致）。
- **QC 钩子全集**：`hint()`（贪心求解器真实最优步，`swap-<dir>` 源格中心坐标）、
  `state()`（直读 PF.phase）、`endScreenVisible()/texts()/textStates()/assets()`。
- **音频**：tap=11025Hz/60ms/880Hz、pop=11025Hz/110ms/1175Hz（升级）、
  win=11025Hz/350ms/1318Hz；一切经 `PF.audio.create()`。

## 用户 PNG 替换 tier 贴图（最小素材路径）

`spec.assets.sprites` 里**文件真实存在**的键（png/jpg/webp/gif，相对 spec 目录或
仓库根解析）在构建期被读出并以 data URI 内联进 `window.PF_ASSETS`；运行期解码、
contain 等比归一到 96×96 画布后注册为该 tier 的贴图。**声明并嵌入即替换；未声明/
缺失/解码失败即程序化回退**（构建日志告警，不阻塞）。真实嵌入清单写旁车
`<out>.assets.json`（make 据此给 CHK10 传 `--require-sprite`；`assets()` 像素对账
阈值 16×16 平均绝对差 ≤8）。

## 可玩性保证（模板交付物，非 QC 作弊）

盘面生成期用贪心最优线做可玩性模拟（预算 = min(24, 步数预算−2)，同时排除"初始盘面
已含 goalTier"的秒胜盘面），64 次重生成内仍不可胜才放行并告警；死局自动重排（不耗
步）。`hint()` 即该贪心求解器在当前盘面上的真实最优步。

## 引擎 bundle（中性名 vendor 件，字节复用）

`src/vendor/engine.js` 从 factory 母本 `packages/templates/vendor/engine.js` **字节
复制**（sha256 `660aa854…`，与 tmpl-match3 同一份；版本锚 3.88.2，~1.2MB，已中性化、
词表扫描零命中）。禁止改动或重新生成；`src/vendor/engine.d.ts` 为 factory 侧手写
类型垫片。

## 构建 / eval

```bash
npm run build        # 默认 golden spec → artifacts/preview/merge.html（~1.2MB 零外链）
npm run logic        # 冻结 logic-test（字节复用 oracle，10 断言）exit 0
npm run typecheck    # tsc --noEmit strict
```

验收门语义（templates.md §6 同形态）：构建 exit 0 + qacore `--autoplay` 无 fail +
pf:end ≤ 45000ms。factory 侧 qacore（M2.2）落地前，以 oracle qacore
（`repo/python/.venv`）对本构建产物做临时验收。
