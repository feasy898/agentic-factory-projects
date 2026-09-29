# M2 运行时桥 spec（engine-bridge）

> 状态：frozen。对照 `packages/engine-bridge/src/{index,channels,events,audio,types}.ts` 逐行核验于 2026-09-28；
> 2026-09-29 C2 盲评修正同步：§2.4 第 4 级 defaultLocale 的空串语义改为如实描述（`??` 只挡 nullish）。
> 目标读者：只凭本页 + eval 重建本模块的新 agent。TS 实现，零 npm 运行时依赖；
> 模板/打包器直接以 esbuild 打包 `src/*.ts`，Node 22+ 亦可原生加载。

---

## 1. 职责与边界

**做**：挂载 `window.PF` 全局（幂等）；派发 5 个 `pf:*` DOM 事件；按渠道识别 + 就绪等待 + 退出接口路由
（缺失回退 `window.open`）；执行首交互前强制静音、平台音量跟随、音频管理器。

**不做**：不渲染（模板职责）；不提供 `window.__PF_QC__`（QC 钩子属模板交付物；桥只暴露 `phase()/setState()`
供模板复用同一相位机）；不做渠道 SDK 的运行时硬依赖（只按全局对象探测协议形）。

## 2. 对外契约

### 2.1 window.PF 成员表（冻结）

| 成员 | 签名 | 语义 |
|---|---|---|
| `channel` | `ChannelId`（只读） | 解析后的渠道 id（7 值：6 渠道 + preview） |
| `locale` | string（只读） | 五级解析结果（§2.4） |
| `version` | string | `PF_VERSION = "0.1.0"` |
| `ready` | `Promise<void>` | 渠道就绪后 resolve，并**派发 `pf:ready`**；预览/缺 stub 环境立即 resolve |
| `isMuted()` | → boolean | 首个 first-interaction 前恒 true；平台音量 0 时恒 true（§2.6） |
| `phase()` | → `loading\|tutorial\|playing\|end` | 相位机（QC `state()` 应直读它） |
| `setState(p)` | void | 模板驱动相位（如进教程） |
| `open(url)` | void | **`pf:cta {url}` 每次点击都派发**；渠道退出外呼仅第一次（exitCalled 单次锁） |
| `start()` | void | 相位 → playing + `pf:start` |
| `end(win)` | void | 相位 → end + `pf:end {win}` |
| `audio` | `PFAudioManager` | `create(src)→HTMLAudioElement`；`getContext()→AudioContext\|null`（懒创建单例） |

`initBridge(options)` 幂等：已有 `window.PF` 直接返回实例。`BridgeOptions = { channel?, locale?,
defaultLocale?, readyTimeoutMs? }`。

### 2.2 事件 detail 字段表（冻结——规划缺失部分的补全）

| 事件 | detail | 时机 |
|---|---|---|
| `pf:ready` | 无 | 渠道就绪后恰一次（不改变相位，仍在 loading） |
| `pf:start` | 无 | 模板调 `PF.start()` |
| `pf:first-interaction` | `{ type: "pointerdown" \| "touchstart" \| "mousedown" \| "keydown" }` | 任一交互事件**首次**到达（捕获阶段监听，once 语义，先到者上报类型并解除全部监听） |
| `pf:end` | `{ win: boolean }` | 模板调 `PF.end(win)` |
| `pf:cta` | `{ url: string }` | 每次 `PF.open(url)`（与外呼单次锁无关） |

实现细节：`CustomEvent`，`bubbles=true, cancelable=false`，直接派发到 `document`。

### 2.3 渠道识别（优先级从高到低）

1. `initBridge({ channel })` 显式传入；
2. `window.PF_CHANNEL`（打包器注入）；
3. 全局探测：`FbPlayableAd` → meta；`ExitApi` → google；`openAppStore` 为函数 → tiktok；
   `mraid` → applovin（mraid 形三渠道无法区分，按 applovin 路由，退出调用一致）；
4. 兜底 `preview`。
`normalizeChannel("pangle") = "tiktok"`；非法显式 id 落 preview。`initBridge({channel})` 缺省即走此探测。

### 2.4 locale 五级优先级（冻结）

`options.locale` → `window.PF_LOCALE`（打包器/模板注入）→ URL `?locale=` → `options.defaultLocale` → `"en"`。

**空串与缺失的逐级回退（精确语义，冻结）**：前三级逐级取"**非空字符串**"（真值判定），任何一级拿到非空串即停——
- `options.locale` 为 undefined 或 `""` → 跳过（真值判定）；
- `window.PF_LOCALE` 非 string 或 `""` → 跳过；
- URL `?locale=`：无 `location` 环境（如 jsdom 异常）整体 try/catch 跳过；参数缺省或空串 → 跳过；
- `options.defaultLocale`（第 4 级，语义与前三级**不同**）：实现为 `return options.defaultLocale ?? "en"`——
  `??` 只挡 nullish，undefined/null → 跳过落到 `"en"`；**空串 `""` 原样返回、不回落 `"en"`**
  （Node 实测 defaultLocale='' → `''`）。源码对此无注释声明空串为有意设计，判为**已知边界（变更候选）**：
  如需空串同样跳过，须把 `??` 改为真值判定，走契约变更流程；
- 全部跳过 → 兜底 `"en"`。

### 2.5 就绪等待与退出路由

- **就绪**（`whenChannelReady`，默认超时 `readyTimeoutMs = 8000ms`）：
  - mraid 形（applovin/unity/mintegral）：无 mraid 或无 `getState` → 立即放行（console.warn 预览模式）；
    `getState() !== "loading"` → 立即；否则等 mraid `ready` 事件，**超时放行（告警），绝不卡死游戏加载**。
  - 非 mraid 形：对应全局缺失 → 立即放行（warn）；存在 → 立即。
- **退出路由**（`routeExit`，返回 `ExitRoute` 枚举 `"mraid"|"meta"|"google"|"tiktok"|"window-open"`）：

| 渠道 | 调用 | 传 URL |
|---|---|---|
| applovin / unity / mintegral | `mraid.open(url)` | 是 |
| meta | `FbPlayableAd.onComplete()` | 否 |
| google | `ExitApi.exit()` | 否 |
| tiktok（含 pangle） | `window.openAppStore()` | 否 |
| preview / 目标接口缺失 | `window.open(url)` | 是 |

完整渠道适配器表（含规则库对应字段）见 [channel-adapters.md](channel-adapters.md)。

### 2.6 静音策略（MutePolicy + AudioManager，冻结）

- `isMuted() = !interactionSeen || platformVolume === 0`——**首交互前强制静音；平台音量 0 时即使已交互也保持
  静音直到平台放开**。
- `markInteraction()`：仅首次生效并通知变化（返回"是否确为首次"，供事件只派发一次）。
- `setPlatformVolume(v)`：非有限数或同值忽略；仅 mraid 形渠道安装探测（初始 `getAudioVolume()` +
  `audioVolumeChange` 监听）。
- AudioManager：`create(src)` 立即对齐策略（`muted` 同步）并纳入后续同步；`getContext()` 懒创建共享单例，
  创建时若策略为 muted 且 state running 则 `suspend()`；无 AudioContext 环境（jsdom/无头）返回 null。
  策略变化回调：全部已建 `<audio>.muted` 同步 + context suspend/resume 双向。
- **契约**：模板的一切音频必须经 `PF.audio` 创建（静音策略的执行点）；缺 `Audio` 构造器时 `create` 抛错。

### 2.7 时序约束（initBridge 单同步段，冻结——再生试验反推点，特此写明）

`initBridge()` 在**返回前同步完成**以下动作，顺序固定：

```
resolveChannel → new MutePolicy → new AudioManager
→ 组装 bridge 对象（ready = whenChannelReady().then(() => dispatchPFEvent("pf:ready"))，此刻仅登记未执行）
→ window.PF = bridge（挂载）
→ installFirstInteraction(...)（document 捕获阶段，pointerdown/touchstart/mousedown/keydown）
→ installPlatformAudioProbe(...)（仅 mraid 形渠道）
→ return bridge
```

推论（均为契约，测试冻结）：
- **不存在"桥已可取但交互监听未装"的窗口**：`initBridge()` 返回后的任何交互必然被观测；
- **pf:ready 派发时机 = 异步**：渠道就绪 promise resolve 后才派发，可能先于或后于首次交互；
- **静音策略与就绪无关**：首交互发生在 `pf:ready` 之前同样解除静音并派发 `pf:first-interaction`；
- `pf:ready` 不改变相位（派发时相位仍是 loading，由模板经 setState/start 推进）；
- 在 `ready` resolve 前调用 `start()/end()` 仍有效（相位机立即迁移并派发事件），规范顺序仍是
  `await PF.ready → (setState("tutorial")) → start() → end()`；
- 重复 `initBridge()` 在任何时刻返回同一实例（不重复安装监听）。

### 2.8 告警（console.warn）文案规范（冻结——恰两处，前缀 `[PF] `）

| 触发条件 | 精确文案 |
|---|---|
| mraid 形渠道（applovin/unity/mintegral）无 `window.mraid` 或无 `getState` 函数 | `[PF] channel=<id>: 未检测到 mraid 全局，按就绪处理（预览模式）` |
| 非 mraid 形渠道对应全局缺失（meta/google/tiktok） | `[PF] channel=<id>: 未检测到渠道运行时全局对象，按就绪处理（预览模式）` |

- 除以上两处外**一切失败路径静默兜底，不抛错不告警**：`mraid.getState()` 抛异常 → 按就绪；
  `removeEventListener` 抛异常 → 忽略；**就绪超时（readyTimeoutMs）→ 静默 resolve**
  （源码头注释与 README 写"放行（告警）"，实测代码无 warn——以代码为准；如需对齐注释属契约变更流程）。

## 3. 行为规格（边界与失败路径）

- 重复 `initBridge` → 返回既有实例（不重复装监听）。
- `routeExit` 目标缺失 → `window.open(url)` 兜底，不抛错（QC/预览可观察）。
- mraid API 抛异常（getState/addEventListener）→ 吞掉按就绪处理（渠道实现不完整时不阻塞）。
- jsdom 环境无 AudioContext → `getContext()` 返回 null。

## 4. eval：精确命令与通过线

```bash
node packages/engine-bridge/test/run.mjs          # node --test 转发；26 用例全过 exit 0
npm run coverage -w @pf/engine-bridge             # c8 行覆盖 >= 80%（--check-coverage；实测 ≈97.85%）
npm run typecheck -w @pf/engine-bridge            # tsc --noEmit（strict）
```

- **coverage 脚本防"空过"**：`--include` 必须是**包内相对** `src/**`（npm -w 在包目录下执行脚本）。
  2026-09-28 再生试验发现原脚本用 monorepo 根相对路径匹配 0 文件 → 0% 覆盖仍 exit 0，已修；
  验证方法：临时把 `--lines` 提到 100 跑一遍，必须 exit 1 才算真门。

- 测试结构：3 用例组——channels（6 渠道就绪→pf:ready、open→对应接口恰一次）、events（事件序/detail/冒泡/
  相位推进）、mute（初始化即静音、首交互解除、平台音量 0 覆盖交互、AudioContext suspend/resume）。
- 夹具：`testsupport/fixture.mjs` 每例独立 jsdom + 渠道 stub（`__calls` 记录器 / `__setReady()` /
  `__fire("audioVolumeChange", v)` / FakeAudioContext）；stub 与真实渠道运行时对接面一致。
- **禁止事项**：不许 mock 被测物（桥本体永远真实加载，只有渠道 stub 是替身）；不许删 detail 字段断言。

## 5. 重生成注意事项（实测坑）

- Node ≥22（类型剥离原生加载 `.ts`）：**只能用可擦除 TS 语法**——禁构造器参数属性
  （`constructor(private x)` 会报 `ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX`），一律显式赋值。
- import 带 `.ts` 扩展 + tsconfig `allowImportingTsExtensions` + `noEmit`（typecheck 用）。
- Windows Node 22 的 `node --test <dir>` 不展开目录参数 → 需要 `test/index.js` 作进程内装载入口；
  `run.mjs` 用 `NODE_TEST_CONTEXT` 环境变量防被收集时递归自举。
- 引擎 vendor 无关本模块，但桥被模板以 esbuild bundle（`format=iife, target=es2019`）——保持零依赖。
- 变更史：commit `3207e1f`（M2 冻结）。
