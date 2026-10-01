# @pf/tmpl-pullpin

拔针救援玩法模板（M3）。PlayableSpec（schema v1）驱动渲染：
`node build.mjs --spec <spec.json>` 产出单文件 HTML 产物（零外链、零相对资源引用）。
规格源 = 模板资产 spec（docs/specs/templates.md §2/§3/§7.2）；本包为模式 M 全新实现
（决策 §2.1 M3 行），玩法行为对照 oracle 冻结 spec 移植。

## SPEC 落实（模板资产 spec §7.2 pullpin 小节）

- **spec 驱动渲染**：§7.2 pullpin params 全部生效——`levels` 关数（HUD 关卡点
  与关卡推进）、`pinsPerLevel` 每关针数（3-5：救援针 + 机关针 + 引流中性针）、
  `hazard`（"lava" 熔岩储备腔 / "spike" 悬挂刺球，机关贴图与涌出动画随之不同）、
  `rescuee`（角色，程序化小圆人）、`orderSolution`（每关拔针顺序，教程演示针取
  其首针；M1 已验证可解，形状坏时运行期回退规范解，见 `levels.ts.effectiveOrders`）。
- **可解性单一真源（决策 §2.1 P1）**：每关角色由 `meta.seed` 经 32 位 LCG 确定性
  生成、拔针模拟判定，唯一实现 = `@pf/spec`（src/invariants.ts；oracle 的
  "Python 权威 + JS 镜像"双实现废除，冻结数值向量由 `tests/logic-test.ts` 锁定）。
  每关恰一个救援针（拔掉即角色逃出、过关）与一个机关针（先于救援针拔掉则角色
  遇难），其余为中性针（引流，随时可拔，熔岩面下降 +20 分）。救援 +100 分。
- **教程→游玩→结束页**：`flow.tutorial`（演示针高亮手势引导，`maxSec` 超时或
  点中演示针即开玩）→ `pf:start` → 逐关救援 → 全部救出 → `pf:end {win:true}` +
  结束页（`showScore`、`ctaKey` 本地化文案，点击 CTA → `PF.open(landingUrl)` →
  `pf:cta`）。**错序失败不终局**：先拔机关针 → 机关涌出角色遇难 → 本关重置重试
  （pf:end 只由真实通关逻辑触达，win 恒 true——可玩广告不设败局，`lose` 文案
  因此无出场机会）。
- **attract 参数生效（nearWin 行为探针语义，§7.2 冻结）**：`attract.nearWin=true`
  时**最后一关首次拔救援针"险些失败"一次**——针拔出一半、机关涌出逼近角色
  （红闪 + 震屏 + 角色惊跳）、针弹回原槽位，随后再拔即成（不消耗任何资源，
  `__PF_QC__.hint()` 保持不变）；`attract.failBait` 同弹回机制作用于首次游玩
  拔针。失败弹回是真实游戏反馈，hint 始终返回真实救援针坐标；pf:end 仍只由
  真实通关逻辑触达一次（QC CHK07 判定依据，不许 hint 造假或直派 pf:end）。
- **3 秒内 `pf:ready`**：入口先装配 engine-bridge（`window.PF`），渠道就绪即派发
  `pf:ready`；渲染引擎在 `PF.ready` 后启动。
- **`window.__PF_QC__`**（qacore §5.1 冻结形状）：`hint(): {x,y,type:"tap"}|null`
  （恒返回当前关救援针——直接拔救援针必过关，与 I1 `pullpinSimulate` 判定一致；
  QC 真实 pointer 点按即可推动最优线）；`state(): "loading|tutorial|playing|end"`
  （直读 `PF.phase()`）；附加 `endScreenVisible()`、`texts()`（已渲染画布文案
  集合，CHK10 取证）、`textStates()`（采样时刻 active+visible 自证）、`assets()`
  （替换素材像素对账）。
- **静音策略走 engine-bridge**：一切音频经 `PF.audio` 创建（首交互前 muted）。

## 用户 PNG 替换贴图（最小素材路径）

`spec.assets.sprites` 固定键 **pin / rescuee / hazard** 对应文件真实存在时
（png/jpg/webp/gif，相对 spec 目录或仓库根解析），构建期读出并以 data URI 内联
进 `window.PF_ASSETS`，运行期 contain 归一 96×96 画布后注册为针/角色/机关贴图
（`createTextures` 对已存在键自动跳过程序化生成）。**声明并嵌入即替换；未声明/
缺失/解码失败即程序化回退**（构建日志告警，不阻塞）。真实嵌入清单写旁车
`<out>.assets.json`（make 据此给 CHK10 传 `--require-sprite`）。

## 引擎 bundle（中性名 vendor 件）

构建时从 `packages/templates/vendor/engine.js` 母本**字节复制**到
`src/vendor/engine.js`（sha256 冻结锚校验，漂移即拒绝构建；包内副本不入库，
见根 .gitignore）。母本已中性化（词表零命中），版本锚 3.88.2，约 1.2MB
（REUSED-ASSETS.md #16）。

## 构建 / 测试

```
npm run build        # 默认 golden spec → artifacts/preview/pullpin.html（+ .assets.json 旁车）
npm run typecheck    # tsc --noEmit（strict；跨包单源经 tsconfig paths 指 @pf/spec）
npm test             # node --experimental-strip-types tests/logic-test.ts（纯逻辑，无 DOM）
```

编排接入（批次 3 的 pf make）：模板 build.mjs 与 match3/merge/sort 同一参数面
（--spec/--out/--locale/--no-minify），产物树与旁车清单同形。
