# @pf/tmpl-pullpin

拔针救援玩法模板（M3 第二个模板）。PlayableSpec（schema v1）驱动渲染：
`node build.mjs --spec <spec.json>` 产出单文件 HTML 产物（零外链、零相对资源引用）。

## SPEC 落实（开发指令 §6-M3 与 §4.1 pullpin 子 schema）

- **spec 驱动渲染**：§4.1 pullpin params 全部生效——`levels` 关数（HUD 关卡点
  与关卡推进）、`pinsPerLevel` 每关针数（3-5：救援针 + 机关针 + 引流中性针）、
  `hazard`（"lava" 熔岩储备腔 / "spike" 悬挂刺球，机关贴图与涌出动画随之不同）、
  `rescuee`（角色，程序化小圆人）、`orderSolution`（每关拔针顺序，教程演示针取
  其首针；M1 已验证可解，形状坏时运行期回退规范解，见 `levels.ts.effectiveOrders`）。
- **玩法语义与 M1 冻结不变式同源**：每关角色由 `meta.seed` 经 32 位 LCG 确定性
  生成（`levels.ts` 是 `python/pfcore/invariants.py` pullpin 段的逐行镜像）——
  每关恰一个救援针（拔掉即角色逃出、过关）与一个机关针（先于救援针拔掉则角色
  遇难），其余为中性针（引流，随时可拔，熔岩面下降 +20 分）。救援 +100 分。
- **教程→游玩→结束页**：`flow.tutorial`（演示针高亮手势引导，`maxSec` 超时或
  点中演示针即开玩）→ `pf:start` → 逐关救援 → 全部救出 → `pf:end {win:true}` +
  结束页（`showScore`、`ctaKey` 本地化文案，点击 CTA → `PF.open(landingUrl)` →
  `pf:cta`）。**错序失败不终局**：先拔机关针 → 机关涌出角色遇难 → 本关重置重试
  （pf:end 只由真实通关逻辑触达，win 恒 true——可玩广告不设败局，`lose` 文案
  因此无出场机会，与 match3 的 lose 同性质）。
- **attract 参数生效**：`attract.nearWin=true` 时**最后一关首次拔救援针"险些
  失败"一次**——针拔出一半、机关涌出逼近角色（红闪 + 震屏 + 角色惊跳）、针弹回
  原槽位，随后再拔即成（不消耗任何资源，hint 保持不变）；`attract.failBait` 同
  弹回机制作用于首次游玩拔针。失败弹回是真实游戏反馈，hint 始终返回真实最优步。
- **3 秒内 `pf:ready`**：入口先装配 engine-bridge（`window.PF`），渠道就绪即派发
  `pf:ready`；渲染引擎在 `PF.ready` 后启动。
- **`window.__PF_QC__`**：`hint(): {x,y,type:"tap"}|null`（恒返回当前关救援针——
  直接拔救援针必过关，与 M1 `pullpin_simulate` 判定一致；QC 真实 pointer 点按
  即可推动最优线）；`state(): "loading|tutorial|playing|end"`（直读 `PF.phase()`）；
  附加 `endScreenVisible()`、`texts()`（已渲染画布文案集合，CHK10 取证）、
  `textStates()`（采样时刻 active+visible 自证）、`assets()`（替换素材像素对账）。
- **静音策略走 engine-bridge**：一切音频经 `PF.audio` 创建（首交互前 muted）。

## 用户 PNG 替换贴图（最小素材路径）

`spec.assets.sprites` 固定键 **pin / rescuee / hazard** 对应文件真实存在时
（png/jpg/webp/gif，相对 spec 目录或仓库根解析），构建期读出并以 data URI 内联
进 `window.PF_ASSETS`，运行期 contain 归一 96×96 画布后注册为针/角色/机关贴图
（`createTextures` 对已存在键自动跳过程序化生成）。**声明并嵌入即替换；未声明/
缺失/解码失败即程序化回退**（构建日志告警，不阻塞）。真实嵌入清单写旁车
`<out>.assets.json`（make 据此给 CHK10 传 `--require-sprite`）。

## 可玩性保证（模板交付物，非 QC 作弊）

针角色由 seed 确定性生成、与 M1 校验器同算法（跨语言同余，`tests/logic-test.ts`
含 Python 侧实算回填的期望值锁定）；`orderSolution` 经 M1 不变式 I1 验证可解，
模板运行期再兜底（坏形状回退规范解"先引流后救援"）。`hint()` 即"当前关救援针
坐标"——该步对任意合法角色必过关，autoplay 据此稳定通关。

## 引擎 bundle（中性名 vendor 件）

`src/vendor/engine.js` 与 tmpl-match3 同一件渲染引擎单文件构建产物（约 1.2MB，
已压缩、内部标识与字符串已中性化，法律 grep 零命中）；生成与升级流程见
tmpl-match3 README（仓库外离线构建 → token 中性化 → 中性名拷入）。

## 构建

```
npm run build        # 默认 golden spec → artifacts/preview/pullpin.html
npm run typecheck
node --experimental-strip-types tests/logic-test.ts   # 纯逻辑自测（无 DOM）
```

接入编排：`python/pfcore/make.py` 的 `TEMPLATE_BUILDERS` 已登记 pullpin，
`python -m pfcore make --spec specs-eval/golden-pullpin.json --locales en,zh`
即走与 match3 相同的三渠道出包 + qacore --autoplay 质检 + 二维码/兜底目录链路。
