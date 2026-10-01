# @pf/tmpl-match3

三消/叠叠消玩法模板（M3，首个模板）。PlayableSpec（schema v1）驱动渲染：
`node build.mjs --spec <spec.json>` 产出单文件 HTML 产物（零外链、零相对资源引用）。

## SPEC 落实（开发指令 §6-M3）

- **spec 驱动渲染**：§4.1 match3 params 全部生效——`cols/rows` 盘面尺寸、
  `moves` 步数、`colors` 棋子种类数（取 `spriteKeys` 前 N 个键）、
  `goalType`（clear-jelly 果冻进度 / score 累分）、`goalCount` 目标、
  `spriteKeys` 键名参与程序化贴图的形状与配色推导（键名变 → 画面变）。
- **3 秒内 `pf:ready`**：入口先装配 engine-bridge（`window.PF`），渠道就绪即派发
  `pf:ready`；渲染引擎在 `PF.ready` 后启动。
- **教程→游玩→结束页**：`flow.tutorial`（手势引导，`maxSec` 超时自动开玩）→
  `pf:start` → 目标达成或步数用尽 → `pf:end {win}` + 结束页（`showScore`、
  `ctaKey` 本地化文案，点击 CTA → `PF.open(landingUrl)` → `pf:cta`）。
- **attract 参数生效**：`attract.nearWin=true` 时最后一步（将达成目标的一步）
  以真实"非法交换回弹"失败一次（不消耗步数），随后再成——广告素材经典的
  "差一点"话术；`attract.failBait` 同机制作用于第一步。失败回弹是真实
  游戏反馈，hint 始终返回真实最优步坐标。
- **`window.__PF_QC__`**：`hint(): {x,y,type}|null`（type ∈ `swap-up/down/left/right`，
  坐标为视口 CSS 像素；QC 用真实 pointer 事件拖拽即可推动最优线）；
  `state(): "loading|tutorial|playing|end"`（直读 `PF.phase()`）；
  附加 `endScreenVisible()`（非契约成员，仅 QC 结束页可见性断言用）、
  `texts()`（已渲染到画布的文案集合——画布文字不进 DOM，CHK10 文案取证走本钩子）、
  `assets()`（替换素材像素对账：渲染贴图 vs 内联用户 PNG，16×16 平均绝对差 ≤8 判 replaced）。
- **静音策略走 engine-bridge**：一切音频经 `PF.audio` 创建（首交互前 muted）。

## 用户 PNG 替换棋子（最小素材路径，反馈行动 3-③）

`spec.assets.sprites` 里**文件真实存在**的键（png/jpg/webp/gif，相对 spec 目录或仓库根解析）
在构建期被读出并以 data URI 内联进 `window.PF_ASSETS`；运行期解码、contain 等比归一到
96×96 画布后注册为该棋子色号的贴图（`createTextures` 对已存在的贴图键自动跳过程序化生成）。
**声明并嵌入即替换；未声明/缺失/解码失败即程序化回退**（构建日志告警，不阻塞）。
真实嵌入清单写旁车 `<out>.assets.json`（make 据此给 CHK10 传 `--require-sprite`，
QC 在页面内做像素对账——`assets()` 上报 `mad/replaced`）。压图/图集/字体子集仍属 assetkit。

## 可玩性保证（模板交付物，非 QC 作弊）

盘面生成期用贪心最优线做可玩性模拟（预留教程一步的步数预算），
64 次重生成内仍不可胜才放行并告警；死局自动重排（不耗步）。
`hint()` 即该贪心求解器在当前盘面上的真实最优步。

## 引擎 bundle（中性名 vendor 件）

`src/vendor/engine.js` 是渲染引擎的单文件构建产物（约 1.2MB，已压缩、
内部标识与字符串已中性化，法律 grep 零命中）。它由本机离线流程生成：

1. 在**仓库外**（本机 `tmp/`，gitignore 覆盖）安装引擎源包（版本按模板骨架
   仓锁定的 3.x 系，记录在 `_vendor/NOTES.md`，不入库）；
2. `esbuild --bundle --minify --format=esm --legal-comments=none` 打成单文件 ESM；
3. 对压缩产物做**纯 token 改名的全局替换**（内部标识/GLSL 宏名/字符串字面量
   同步更名，语义等价），直至大小写不敏感 grep 零命中；
4. 以中性名 `engine.js` 拷入本包提交。

公开仓因此**零引擎依赖名**（package.json 无任何上游依赖），引擎版本与来源
只记录在本地 `_vendor/NOTES.md`。引擎升级 = 重跑 1-4 并回归 QC。

## 构建

```
npm run build        # 默认 golden spec → artifacts/preview/match3.html
npm run typecheck
```

预览产物自包含：未替换的贴图运行时程序化生成，被 `spec.assets.sprites` 命中的棋子在构建期
内联用户 PNG（见上节），音效为内置 WAV data URI，字体用系统字体（M5 assetkit 字体子集
接入后替换）。
