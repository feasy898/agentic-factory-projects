# M3 模板插件 spec（templates）

> 状态：tmpl-match3 **frozen**；tmpl-merge / tmpl-pullpin / tmpl-sort **planned（仅 package.json 占位）**。
> 对照 `packages/templates/tmpl-match3/` 核验于 2026-09-28。玩法逻辑见
> [match3-rules-card](match3-rules-card.md)（本页只写构建契约与插件接口）。

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
     现状只有 `swap-*` 与 `tap`——拧螺丝/拔针等手势词汇是第二个模板开工时必须先定义的契约缺口）；
   - `state(): string` —— 直读 `PF.phase()`（loading/tutorial/playing/end）；
   - `endScreenVisible(): boolean`（可选）。
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
  ① `window.PF_SPEC=<JSON>;window.PF_LOCALE="<tag>";` ② bundle IIFE。
- **spec JSON 内联必须经 `escapeForInlineScript`**：`<` → `\u003c`、`>` → `\u003e`、U+2028/U+2029 转义
  （防 `</script>` 提前闭合）。
- locale 缺省 = spec `i18n.defaultLocale`；title 缺省 = `meta.title`。
- 产物自包含：贴图程序化生成、音效为内置 WAV data URI（规则卡 §10–§11），零外链零相对资源引用。

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

## 7. 未开工模板（planned，开工前置）

| 模板 | 占位 | 开工前置 |
|---|---|---|
| tmpl-merge | `packages/templates/tmpl-merge/package.json` | 先写该模板规则卡（同 match3 卡精度：盘面/合成/胜负/随机流/hint 手势词汇） |
| tmpl-pullpin | 同上 | 同上（含 I1 可解性在模板侧的实现与 `check(spec)` 导出形态） |
| tmpl-sort | 同上 | 同上（含 I2 栈可逆生成的运行时复刻） |

三个模板复用 M2 桥、同一 build 形态与同一 QC 钩子；**不许**自造第二套事件/静音/退出对接。
建议排期：主路径（编排器 + 扫码）彩排稳定后只开一个。
- 变更史：commit `df014e3`（三消冻结）。
