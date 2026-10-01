# @pf/tmpl-sort

排序/拧螺丝玩法模板（M3）。PlayableSpec（schema v1）驱动渲染：
`node build.mjs --spec <spec.json>` 产出单文件 HTML 产物（零外链、零相对资源引用）。
规格源 = 模板资产 spec（docs/specs/templates.md §2/§3/§7.3）；本包为模式 M 全新实现
（决策 §2.1 M3 行），玩法行为对照 oracle 冻结 spec 移植。

## SPEC 落实（模板资产 spec §7.3 sort 小节）

- **spec 驱动渲染**：§7.3 sort params 全部生效——`rods` 柱数（2-8，单行布局）、
  `layersPerRod` 柱深（2-6，柱体/棋子尺寸随之缩放）、`colors` 颜色数（2-8，八色
  调色板 setTint 着色 + HUD 进度点）、`screwMode`（拧螺丝变体交互分支，见下）、
  `moveLimit`（0=不限步，模板默认；>0 时 HUD 显示 `×N` 步数预算，耗尽即
  `pf:end {win:false}`）。
- **可解性单一真源（决策 §2.1 P1）**：倾倒走法/apply/逆步判定/规范扰动的唯一
  实现 = `@pf/spec`（src/invariants.ts；oracle 的五重镜像废除，冻结数值向量由
  `tests/logic-test.ts` 锁定）。倾倒 = 顶部同色段整段倒向目标柱（k =
  min(段长, 空位)，目标柱空或顶同色）；每根柱"空或单色满柱"即胜。
- **screwMode 交互分支**：`false`=玻璃试管+圆盘、点选-倾倒水声动画；`true`=金属
  螺栓+六角螺母、棘轮音效、旋入/旋出表现。走法/可解性与普通模式完全一致
  （交互与表现分支，规则不分叉——保证 M1 同一套走法判定覆盖两种变体）。
- **初始盘面 = 冻结规范扰动镜像 + 同流深化发牌**（`deal.ts`，设计依据如实留档）：
  从已解态出发的"逆步合法"扰动只能整柱搬运（顶段=满柱、空位=满柱 ⇒ k 取满），
  单色柱性质保持，故规范扰动盘面恒为"每柱单色"的已解态排列（logic-test 含 40
  seed 的运行期证明）——对它开局即胜。因此模板在消费规范扰动同一 LCG 流的延续
  做确定性洗牌发牌后，用与冻结走法同源的 BFS 求解器验收"可解 + 非开局即胜 +
  最优步数 ≥2 + 步数 ≤ moveLimit"，不合格重发（≤64 次，与 match3 的生成期可玩性
  校验同一先例）；64 次不收敛回退规范盘面（开局即胜的诚实兜底）。发牌算法属
  模板内部实现——M1 I2 约束的是种子扰动过程的良构性，spec 中没有初始盘面字段，
  渲染盘面的可解性由模板自查兜底。
- **教程→游玩→结束页**：`flow.tutorial`（最优解源柱高亮手势引导，`maxSec` 超时或
  点中演示柱即开玩）→ `pf:start` → 逐柱归类 → 全部成柱 → `pf:end {win:true}` +
  结束页（`showScore`、`ctaKey` 本地化文案，点击 CTA → `PF.open(landingUrl)` →
  `pf:cta`）。败局仅在 `moveLimit>0` 且步数耗尽时出现（可玩广告默认不设败局）。
- **attract 参数生效（nearWin 行为探针语义，§7.3 冻结）**：`attract.nearWin=true`
  时**将胜的一倒先"险些失败"一次**——倒到半空、红闪 + 震屏后倒回原柱，随后
  同一最优步再倒即成（不消耗步数，`__PF_QC__.hint()` 保持不变；行为探针实测
  语义：制胜目标柱被点两次、pf:end 恰一次 win=true）；`attract.failBait` 同弹回
  机制作用于首次游玩倾倒；`attract.firstClickSucceed` 开局第一击点到空柱/成品柱
  时自动改选最优解源柱（真实选中，永远有进展）。pf:end 仍只由真实结算逻辑触达
  （QC CHK07 判定依据，不许 hint 造假或直派 pf:end）。
- **3 秒内 `pf:ready`**：入口先装配 engine-bridge（`window.PF`），渠道就绪即派发
  `pf:ready`；渲染引擎在 `PF.ready` 后启动。
- **`window.__PF_QC__`**（qacore §5.1 冻结形状）：`hint(): {x,y,type:"tap"}|null`
  （两拍节奏：未选中 → 最优解源柱坐标；已选中该源柱 → 目标柱坐标；BFS 与 M1
  冻结走法同源，QC 真实 pointer 点按即可沿最优线通关）；`state():
  "loading|tutorial|playing|end"`（直读 `PF.phase()`）；附加 `endScreenVisible()`、
  `texts()`（已渲染画布文案集合，CHK10 取证）、`textStates()`（采样时刻
  active+visible 自证）、`assets()`（替换素材像素对账）。
- **静音策略走 engine-bridge**：一切音频经 `PF.audio` 创建（首交互前 muted）。

## 用户 PNG 替换贴图（最小素材路径）

`spec.assets.sprites` 固定键 **rod / piece** 对应文件真实存在时（png/jpg/webp/gif，
相对 spec 目录或仓库根解析），构建期读出并以 data URI 内联进 `window.PF_ASSETS`，
运行期 contain 归一 96×96 画布后注册为柱体/棋子贴图（`createTextures` 对已存在键
自动跳过程序化生成）。**声明并嵌入即替换；未声明/缺失/解码失败即程序化回退**
（构建日志告警，不阻塞）。柱体素材会被拉伸到柱体比例（建议竖长图）；棋子颜色
由运行期 setTint 施加（建议白/灰基调）。真实嵌入清单写旁车 `<out>.assets.json`
（make 据此给 CHK10 传 `--require-sprite`）。

## 引擎 bundle（中性名 vendor 件）

构建时从 `packages/templates/vendor/engine.js` 母本**字节复制**到
`src/vendor/engine.js`（sha256 冻结锚校验，漂移即拒绝构建；包内副本不入库，
见根 .gitignore）。母本已中性化（词表零命中），版本锚 3.88.2，约 1.2MB
（REUSED-ASSETS.md #16）。

## 构建 / 测试

```
npm run build        # 默认 golden spec → artifacts/preview/sort.html（+ .assets.json 旁车）
npm run typecheck    # tsc --noEmit（strict；跨包单源经 tsconfig paths 指 @pf/spec）
npm test             # node --experimental-strip-types tests/logic-test.ts（纯逻辑，无 DOM）
```

编排接入（批次 3 的 pf make）：模板 build.mjs 与 match3/merge/pullpin 同一参数面
（--spec/--out/--locale/--no-minify），产物树与旁车清单同形。
