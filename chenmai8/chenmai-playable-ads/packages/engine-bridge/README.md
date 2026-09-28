# engine-bridge（M2）渠道运行时桥

模板与渠道运行时之间的自研桥：按渠道注入退出接口、挂载 `window.PF` 全局、
派发 `pf:*` 事件、执行首交互前强制静音。TS 实现，**零 npm 运行时依赖**
（打包器直接以 esbuild 打包 `src/*.ts`；Node 22+ 可原生加载 TS）。

## 冻结契约（开发指令 §4.2，schema v1 阶段冻结，不得擅改）

- 全局对象 `window.PF`：`PF.open(url)`（按渠道路由退出接口）、`PF.isMuted()`、`PF.locale`
- 事件（DOM CustomEvent，派发到 document 且 `bubbles=true`）：
  `pf:ready` / `pf:start` / `pf:first-interaction` / `pf:end {win}` / `pf:cta {url}`
- 静音策略：一切音频经 `PF.audio` 音频管理器创建；首个 `pf:first-interaction`
  之前强制静音（HTMLAudio `muted=true` / AudioContext `suspended`）
- 质检钩子 `window.__PF_QC__`（`hint()` / `state()`）属模板（M3）交付物；
  桥暴露 `PF.phase()` / `PF.setState()` 供模板实现 `state()` 时复用同一相位机
  （loading / tutorial / playing / end）

## 6 渠道退出接口

| channel | 就绪来源 | 退出接口（PF.open 路由） |
|---|---|---|
| `applovin` | mraid（loading → 等 `ready` 事件） | `mraid.open(url)` |
| `unity` | 同上 | `mraid.open(url)` |
| `mintegral` | 同上 | `mraid.open(url)` |
| `meta` | 全局 `FbPlayableAd` 存在 | `FbPlayableAd.onComplete()` |
| `google` | 全局 `ExitApi` 存在 | `ExitApi.exit()` |
| `tiktok`（含 `pangle` 别名） | 全局 `openAppStore` 存在 | `window.openAppStore()` |
| `preview`（兜底） | 立即 | `window.open(url)` |

- 渠道来源优先级：`initBridge({ channel })` > 打包器注入的 `window.PF_CHANNEL`
  > 全局对象探测（探测到 mraid 无法区分三渠道时归 `applovin`，退出调用一致）
  > `preview`
- 目标接口缺失时回退 `window.open(url)`（预览/质检环境可观察、不抛错）
- mraid 就绪等待超过 `readyTimeoutMs`（默认 8s）放行并告警，绝不卡死加载
- 平台侧静音：mraid `getAudioVolume()===0` 或 `audioVolumeChange(0)` 时视为
  平台静音，即使用户已交互也保持静音，直到平台放开（对齐渠道"首交互前静音"要求）

## 用法

```ts
import { initBridge } from "@pf/engine-bridge";

const PF = initBridge({ channel: "applovin", locale: "en" }); // 幂等
await PF.ready;                                  // → pf:ready
PF.setState("tutorial");
PF.start();                                      // → pf:start（phase → playing）
const tap = PF.audio.create("./audio/tap.ogg");  // 首交互前 muted=true
PF.end(true);                                    // → pf:end {win:true}
ctaButton.onclick = () => PF.open(landingUrl);   // → pf:cta {url} + mraid.open
```

locale 解析优先级：`options.locale` > `window.PF_LOCALE` > URL `?locale=`
> `options.defaultLocale` > `"en"`。

## 评测（在仓库根执行）

```bash
node --test packages/engine-bridge/test/          # 26 用例：6 渠道 ready→事件序 /
                                                  # open→对应接口 / 首交互前 muted，全过 exit 0
node packages/engine-bridge/test/run.mjs          # 等价入口（转发 node --test）
node node_modules/c8/bin/c8.js --include "packages/engine-bridge/src/**" \
  --check-coverage --lines 80 --reporter text node --test packages/engine-bridge/test/
                                                  # 行覆盖率 ≥80% 门（当前 ~98%）
npm --workspace @pf/engine-bridge run typecheck   # tsc --noEmit
```

测试夹具在 `testsupport/fixture.mjs`（jsdom + 各渠道 stub），不放 `test/`
以免被 `node --test` 当作用例收集；`test/index.js` 是目录参数的入口
（Windows 的 Node 22 不展开 `--test` 的目录参数，见文件头注释）。

## 纪律

- 本包不得引入任何 npm 运行时依赖；渠道 SDK 只按全局对象探测（鸭子类型）
- 公开仓内不出现任何上游项目/工具名（法务红线清单见仓库根开发指令 §12）
