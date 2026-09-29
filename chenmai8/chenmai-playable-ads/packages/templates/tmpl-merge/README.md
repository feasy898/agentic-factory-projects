# @pf/tmpl-merge

合成玩法模板（M3）。PlayableSpec（schema v1）驱动渲染：
`node build.mjs --spec <spec.json>` 产出单文件 HTML 产物（零外链、零相对资源引用）。

## 玩法模型（冻结）

盘面 cols×rows 恒满；一步 = 从源格向 dir 拖动，相邻**同阶**棋子合成升一阶
（升级弹跳动画），源格清空 → 源列重力下落 → 列顶补 1 个出生棋子
（tier ∈ 1..spawnTierMax）。盘面出现 ≥ goalTier 的棋子即胜（pf:end {win:true}）；
无 move 参数，软上限 = cols×rows×2（真人卡死兜底，最优线远用不到）；
死局自动重排（保留棋子重摆，不耗步）。满阶（maxTier）棋子为终态不再合成。

## SPEC 落实（开发指令 §6-M3 / §4.1）

- **spec 驱动渲染**：§4.1 merge params 全部生效——`cols/rows` 盘面尺寸、
  `maxTier` 棋子阶数与贴图组数、`spawnTierMax` 出生阶上限、`goalTier`
  目标阶（HUD 进度条/进度文本随之变化）、`spriteKeys` 键名参与程序化贴图的
  形状与配色推导（键名变 → 画面变；tier i 用 spriteKeys[(i-1) % len]）。
- **3 秒内 `pf:ready`**：入口先装配 engine-bridge（`window.PF`），渠道就绪即派发
  `pf:ready`；渲染引擎在 `PF.ready` 后启动。
- **教程→游玩→结束页**：`flow.tutorial`（手势引导，`maxSec` 超时自动开玩）→
  `pf:start` → 合成出 goalTier → `pf:end {win}` + 结束页（`showScore`、
  `ctaKey` 本地化文案，点击 CTA → `PF.open(landingUrl)` → `pf:cta`）。
- **attract 参数生效**：`attract.nearWin=true` 时最后一步（将合成出 goalTier 的
  一步）以真实"不可合成回弹"失败一次（不消耗步数），随后再成；`attract.failBait`
  同机制作用于第一步。回弹是真实游戏反馈，hint 始终返回真实最优步坐标。
- **`window.__PF_QC__`**：`hint(): {x,y,type}|null`（type ∈ `swap-up/down/left/right`，
  坐标为源格中心视口 CSS 像素；QC 按方向做 44px 真实拖拽即可推动最优线）；
  `state(): "loading|tutorial|playing|end"`（直读 `PF.phase()`）；
  附加 `endScreenVisible()`、`texts()`、`textStates()`（CHK10 文案上屏自证）、
  `assets()`（替换素材像素对账：渲染贴图 vs 内联用户 PNG，16×16 平均绝对差 ≤8）。
- **静音策略走 engine-bridge**：一切音频经 `PF.audio` 创建（首交互前 muted）。

## 用户 PNG 替换 tier 贴图（最小素材路径）

`spec.assets.sprites` 里**文件真实存在**的键（png/jpg/webp/gif，相对 spec 目录或
仓库根解析）在构建期被读出并以 data URI 内联进 `window.PF_ASSETS`；运行期解码、
contain 等比归一到 96×96 画布后注册为该 tier 的贴图。**声明并嵌入即替换；
未声明/缺失/解码失败即程序化回退**（构建日志告警，不阻塞）。真实嵌入清单写
旁车 `<out>.assets.json`（make 据此给 CHK10 传 `--require-sprite`）。

## 可玩性保证（模板交付物，非 QC 作弊）

盘面生成期用贪心最优线做可玩性模拟（预算 = min(24, 软上限-2)，
同时排除"初始盘面已含 goalTier"的秒胜盘面），64 次重生成内仍不可胜才放行并告警；
死局自动重排（不耗步）。`hint()` 即该贪心求解器在当前盘面上的真实最优步。
随机流调度（第 k 步补位 = `SPAWN_SALT ^ k`，重排 = `RESHUFFLE_SALT ^ k`）
与生成期模拟完全一致，`tests/logic-test.ts` 断言"hint 线 = 模拟线"。

## 引擎 bundle（中性名 vendor 件）

`src/vendor/engine.js` 与 tmpl-match3 同一份中性名单文件构建产物（逐字节相同，
sha256 校验一致；生成与中性化流程见 tmpl-match3/README.md「引擎 bundle」节）。
公开仓零引擎依赖名（package.json 无任何上游依赖）。

## 构建

```bash
node build.mjs --spec specs-eval/golden-merge.json --locale en \
  --out artifacts/preview/golden-merge-en.html
npx tsc --noEmit        # 类型检查
```

验收：`python -m pfcore make --spec specs-eval/golden-merge.json --locales en,zh`
→ 三渠道双语包 + qacore 全绿 + pf:end 触发（模板 eval 同 §6-M3）。
