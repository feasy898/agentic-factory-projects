# M3 模板插件 spec（templates）

> 状态：tmpl-match3 / tmpl-merge / tmpl-pullpin / tmpl-sort **四模板全部 frozen**（2026-09-29，
> 全部注册于 `python/pfcore/make.py` 的 `TEMPLATE_BUILDERS`，只增不改名）。
> 玩法逻辑见 [match3-rules-card](match3-rules-card.md) 与 §7 各模板小节（本页写构建契约与插件接口；
> 三新模板的逐行玩法细节以其包内 README.md 与 `tests/logic-test.ts` 为准）。

---

## 1. 职责与边界

**做**（每个模板）：PlayableSpec → 可玩广告（教程→游玩→结束页全流程）；attract 剧本；挂载
`window.__PF_QC__`（hint/state/endScreenVisible）；一切事件与音频经 M2 桥；RTL 标记。

**不做**：不做 spec 校验（宽容归一后直接跑，权威在 M1）；不自带渠道对接（桥的职责）；
不内联渠道运行时脚本（打包器按规则注入）。

## 2. 模板插件接口（新模板的统一形态，冻结方向）

1. 入口 `src/main.ts`：`normalizeSpec(window.PF_SPEC ?? {})` → `initBridge({ defaultLocale })` →
   `pf.ready.then(boot)`（DOM loading 时挂 DOMContentLoaded）。
2. RTL：`spec.rtl.includes(PF.locale)` → `document.documentElement.dir = "rtl"`。
3. QC 钩子（M3 交付物，QC 用真实 pointer 事件点击）：
   - `hint(): {x, y, type} | null` —— **真实最优下一步的视口 CSS 像素坐标**（不许造假坐标；type 词汇表
     现状两组：`swap-up/down/left/right`（match3/merge，44px 定向拖拽）与 `tap`（pullpin/sort，单击））；
   - `state(): string` —— 直读 `PF.phase()`（loading/tutorial/playing/end）；
   - `endScreenVisible(): boolean`（可选）；另有 `texts()/textStates()/assets()`（CHK10 取证
     与像素对账，形状见 [qacore §5.1](qacore.md)）。
4. 事件只经桥：开始 `PF.start()`、结束 `PF.end(win)`、CTA `PF.open(landingUrl)`、相位 `PF.setState()`。
5. 音频只经 `PF.audio.create()`。
6. 相位与 `pf:end` 只能由**真实游戏逻辑**触达（QC 的 CHK07 判定依据）。

## 3. tmpl-match3 构建契约（build.mjs，冻结）

```
node packages/templates/tmpl-match3/build.mjs [--spec specs-eval/golden-match3.json]
     [--out artifacts/preview/match3.html] [--locale <tag>] [--no-minify]
```

- esbuild：entry `src/main.ts`，`bundle + format=iife + target es2019 + minify + legalComments none`。
- 产物单 HTML 骨架：`<html lang="<locale>">` + viewport（`maximum-scale=1, user-scalable=no`）+ 内联样式
  （`#app` 全屏、背景 `#141b34`）+ `<div id="app">` + 两个内联 script：
  ① `window.PF_SPEC=<JSON>;window.PF_LOCALE="<tag>";window.PF_ASSETS=<assetMap>;`
  ② bundle IIFE。
- `window.PF_ASSETS`（最小素材路径，commit `d03ac0e` 增）：构建期真实存在的
  `spec.assets.sprites` 键以 data URI 内联成键→dataURI 映射；运行期解码、contain 归一 96×96
  画布后注册为贴图。**声明并嵌入即替换；未声明/缺失/解码失败即程序化回退**（构建日志告警，
  不阻塞）。构建同写旁车 `<out>.assets.json`（`{spec, locale, sprites[]}` 真实嵌入清单，
  **零嵌入也写出空清单**——make 据此给 CHK10 传 `--require-sprite`）。
- **spec JSON 内联必须经 `escapeForInlineScript`**：`<` → `\u003c`、`>` → `\u003e`、U+2028/U+2029 转义
  （防 `</script>` 提前闭合）。
- locale 缺省 = spec `i18n.defaultLocale`；title 缺省 = `meta.title`。
- 产物自包含：贴图程序化生成、音效为内置 WAV data URI（规则卡 §10–§11），零外链零相对资源引用。
- tmpl-merge / tmpl-pullpin / tmpl-sort 的 `build.mjs` 为**同一构建形态**（同参数面、同
  `escapeForInlineScript`、同 PF_SPEC/PF_LOCALE/PF_ASSETS 三变量内联与 `.assets.json` 旁车）。

## 4. 渲染引擎 vendor bundle 契约（src/vendor/engine.js，冻结）

- **版本锚点：3.88.2**（模板锁定的大版本；`engine.d.ts` 为手写类型面）。
- 来源与流程（中性表述）：引擎 ESM 发行文件 → esbuild `--bundle --minify --format=esm --legal-comments=none
  --target=es2019` → 纯 token 级全局改名（语义等价替换，字符串与标识符同步）→ 提交为 `engine.js`（约 1.2MB）。
- 硬性门：公开仓对引擎原名做大小写不敏感 grep 必须**零命中**。
- 升级引擎 = 用新版本重跑上述流程 + qacore 自动试玩回归。
- 已知限制：jsdom 无 2D/WebGL 上下文——引擎在 jsdom 只能"加载执行至画布探测"冒烟；**真实验证 =
  qacore --autoplay**（真实 Chromium）。

## 5. 行为规格（关键默认与容差，摘自规则卡）

- 参数宽容归一表、随机流与盐值表、生成期 64 次可玩性重试、死局自动重排、attract 单次触发——
  全部见 [match3-rules-card](match3-rules-card.md)（该卡与本页共同构成三消 spec）。
- 素材路径不参与渲染（程序化贴图），缺失不报错——契约缺口声明见 CONTRACTS §痛点 4。

## 6. eval：精确命令与通过线

```bash
node packages/templates/tmpl-match3/build.mjs --spec specs-eval/golden-match3.json --out artifacts/preview/match3.html
python/.venv/Scripts/python.exe -m qacore run artifacts/preview/match3.html --channel preview --autoplay
# → 构建 exit 0（约 1.24MB）；qacore exit 0 无 fail（CHK02/06/10 skip 允许）；pf:end ≤ 45000ms（实测 ≈26.6s）
npm run typecheck -w @pf/tmpl-match3    # tsc --noEmit strict
```

- 门禁固化：`scripts/gate_phase1.py` 门项 4。
- 已知验收缺口（如实）：nearWin 剧本、素材使用、`difficulty`/`firstClickSucceed` 消费均无断言。
- **禁止事项**：`__PF_QC__.hint()` 不许返回假坐标或直接派发 `pf:end`（结束只能由真实逻辑触达）；
  自动试玩依赖 hint 是"回归测试"语义，不是广告平台认可。

## 7. 新增模板（merge / pullpin / sort，均 frozen）

三模板复用 M2 桥、§3 同一 build 形态与同一 QC 钩子全集（hint/state/endScreenVisible/texts/
textStates/assets）；引擎 vendor 件为同一中性名 bundle（sha256 一致）；**不许**自造第二套
事件/静音/退出对接。玩法细节以各包 README.md 与 `tests/logic-test.ts`（跨语言同余断言 +
Python 权威侧实算回填期望）为准，本节如实概括：

### 7.1 tmpl-merge（合成，commit `53bd40d`）

- **玩法**：盘面 cols×rows 恒满；一步 = 源格向 dir 拖动，相邻**同阶**棋子合成升一阶（升级弹跳），
  源格清空 → 源列重力下落 → 列顶补出生棋子（tier ∈ 1..spawnTierMax）；出现 ≥ goalTier 即胜
  （`pf:end {win:true}`）。无 move 上限参数，但有**硬步数预算**：`movesLeft` 初始 =
  cols×rows×2，每步合成减一，**耗尽时 `pf:end {win:false}` 真实败局**（句式同 §7.3 sort
  moveLimit——它是真实收束，不是"卡死兜底"的软上限；最优线远用不到）；死局自动重排
  （保留棋子重摆，不耗步）；满阶棋子为终态不再合成。§4.1 merge params 全生效（cols/rows/maxTier/
  spawnTierMax/goalTier/spriteKeys 驱动程序化贴图形状配色）。生成期贪心最优线模拟做可玩性校验
  （排除"初始盘面已含 goalTier"的秒胜盘面，≤64 次重试）。
- **QC 钩子**：`hint()` = 贪心求解器当前盘面真实最优步（`swap-<dir>`，源格中心坐标）；随机流
  （`SPAWN_SALT`/`RESHUFFLE_SALT` 派生流）游戏侧=模拟侧单实现，logic-test 断言"hint 线=模拟线"。
- **nearWin 语义**：`attract.nearWin=true` 时最后一步（将合成出 goalTier 的一步）以真实
  "不可合成回弹"失败一次（不耗步），随后再成；`attract.failBait` 同机制作用于第一步。

### 7.2 tmpl-pullpin（拔针救援，commit `75cc23d`）

- **玩法**：每关角色由 seed 经 32 位 LCG 确定性生成（`levels.ts` 与 `python/pfcore/invariants.py`
  pullpin 段逐行镜像）；每关恰一个救援针（拔掉即逃出过关）+ 一个机关针（先于救援针拔则角色遇难、
  **本关重置重试，不终局**）+ 其余中性针（引流，熔岩面下降 +20 分；救援 +100 分）。
  §4.1 pullpin params 全生效（levels/pinsPerLevel 3-5/hazard "lava"|"spike"/rescuee/
  orderSolution——教程演示针取首针，坏形状运行期回退规范解）。`pf:end` 只由全部关卡救出的真实
  逻辑触达，win 恒 true（可玩广告不设败局，lose 文案无出场机会）。
- **QC 钩子**：`hint()` 恒返回当前关救援针真实坐标（`tap`——直拔必过关，与 M1 `pullpin_simulate`
  判定一致）；用户 PNG 替换固定键 pin/rescuee/hazard。
- **nearWin 语义**：`attract.nearWin=true` 时最后一关首次拔救援针"险些失败"一次——针拔出一半、
  机关涌出逼近角色（红闪+震屏+角色惊跳）、针弹回原槽位，随后再拔即成（不耗资源，hint 不变）；
  `attract.failBait` 同弹回机制作用于首次游玩拔针。

### 7.3 tmpl-sort（排序/拧螺丝，commit `1a8e0e9`）

- **玩法**：倾倒归类——点选柱（顶部同色段抬起）→ 点目标柱整段倒过去（k = min(段长, 空位)，
  目标柱空或顶同色）；每柱"空或单色满柱"即胜。`board.ts` 与 `python/pfcore/invariants.py` sort 段
  及 `packages/spec/src/invariants.mjs` 逐行镜像（LCG/合法走法/apply/逆步/规范扰动五重同余）。
  §4.1 sort params 全生效（rods 2-8 单行/layersPerRod 2-6/colors 2-8 八色 setTint+HUD 进度点/
  screwMode/moveLimit）。**screwMode**（拧螺丝变体）只分叉交互与表现（金属螺栓+六角螺母+棘轮音效、
  旋入旋出），走法/可解性与普通模式完全同一套冻结规则。初始盘面 = 冻结规范扰动镜像 + 同流深化
  发牌（deal.ts 如实留档：规范扰动盘面恒为已解态排列，故消费同一 LCG 流延续做确定性洗牌发牌，
  BFS（与冻结走法同源）验收"可解+非开局即胜+最优 ≥2 步+步数 ≤moveLimit"，≤64 次重发，不收敛
  回退规范盘面开局即胜——发牌属模板内部实现，spec 无初始盘面字段）。**moveLimit>0 且耗尽时
  `pf:end {win:false}` 真实败局**（0=不限步为模板默认）。
- **QC 钩子**：`hint()` 两拍节奏（未选中 → 最优解源柱坐标；已选中该源柱 → 目标柱坐标，`tap`），
  BFS 最优解可逐回放至胜（logic-test 断言）；用户 PNG 替换固定键 rod/piece。
- **nearWin 语义**：`attract.nearWin=true` 时将胜的一倒先"险些失败"一次——倒到半空、红闪+震屏后
  倒回原柱，随后同一最优步再倒即成（不耗步，hint 不变）；`attract.failBait` 同弹回机制作用于
  首次游玩倾倒；`attract.firstClickSucceed` 开局第一击点到空柱/成品柱时自动改选最优解源柱。

- 变更史：commit `df014e3`（三消冻结）→ `d03ac0e`（PF_ASSETS 素材路径内联）→
  `53bd40d`/`75cc23d`/`1a8e0e9`（merge/pullpin/sort 三模板）。
