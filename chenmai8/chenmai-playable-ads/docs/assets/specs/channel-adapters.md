# 渠道适配器表（Channel Adapter Table）

> 版本：v1.0.0（2026-09-28）。本页是渠道知识的**单一真源**：每渠道一行——包形态、体积上限、
> 退出调用是否传 URL、调用名、就绪条件。规则 JSON（`channel-rules/channel-rules.json`）与
> 桥的路由（`packages/engine-bridge/src/channels.ts`）都应以本表为准对齐。
> 现状如实记录：两处是分别维护的，对齐由本页仲裁；分歧见 §4。

---

## 1. 适配器总表

| 渠道 | 包形态 | 体积上限 | 文件数上限 | 包内结构 | 退出调用名 | 是否传 URL | 就绪条件 | 运行时注入 | 禁用项 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|
| `applovin` | 单 HTML 全内联 | 5,242,880 B（5MB） | 1 | 入口 `index.html` | `mraid.open(url)` | **传 URL** | mraid 存在且 `getState() !== "loading"`；为 loading 时等 `ready` 事件，超时 8s 放行（告警） | `<head>` 注入 `<script src="mraid.js">`（相对引用，渠道容器投放时提供） | — | frozen |
| `meta` | 单 HTML 全内联 | 3,145,728 B（3MB，内部从严；官方建议 ~2MB） | 1 | 入口 `index.html` | `FbPlayableAd.onComplete()` | **不传 URL** | 全局 `FbPlayableAd` 存在即就绪（缺失也放行并告警=预览模式） | 无 | **禁 MRAID**（产物出现 `\bmraid\b` 全词即构建失败） | frozen |
| `mintegral` | zip | 5,242,880 B | 100 | **`Template.html`（入口壳）+ `build.js`（合并脚本）**——Phase 0 对照工程实测结构，勿按"单 HTML"假设 | `mraid.open(url)`（在 Template.html 内生效） | **传 URL** | 同 mraid 形（8s 超时放行） | 注入 `mraid.js` | — | frozen |
| `preview` | 单 HTML 全内联 | 5,242,880 B | 1 | 入口 `index.html` | `window.open(url)`（兜底） | 传 URL | 立即就绪 | 无 | — | frozen（本地预览/QC 专用，非投放渠道） |
| `unity` | 单 HTML 全内联（Phase 0 对照实测确认） | 5MB（规划基线） | 1 | 入口 `index.html` | mraid 形：`mraid.open(url)`（桥按 applovin 同协议路由） | 传 URL（mraid 形） | 同 applovin | 规划注入 `mraid.js` | — | **planned：规则库缺席**（打包器对未知渠道直接拒绝） |
| `google` | zip（Phase 0 对照实测：zip 内仅 `index.html`） | 5MB | ≤512（内部目标 ≤200） | 入口 `index.html` | `ExitApi.exit()` | **不传 URL** | 全局 `ExitApi` 存在即就绪 | 无 | — | planned：规则库缺席 |
| `tiktok`（含 `pangle` 别名，桥归一到 tiktok） | zip + `config.json` + sdk js（规划；Phase 0 对照实测 zip 为 `index.html`+`config.json`） | 5MB | ≤100 | 规划：`index.html` + `config.json` + sdk js | `window.openAppStore()` | **不传 URL** | 全局 `openAppStore` 为函数即就绪 | 规划注入 sdk js | — | planned：规则库缺席 |

补充约定：

- 渠道识别优先级（桥，冻结）：`initBridge({channel})` 显式 > 打包器注入的 `window.PF_CHANNEL` > 全局对象探测
  （`FbPlayableAd`→meta、`ExitApi`→google、`openAppStore` 函数→tiktok、`mraid`→applovin；mraid 形三渠道
  无法从全局区分，按 applovin 路由——三者退出调用一致）> `preview`。
- 退出接口目标缺失时一律回退 `window.open(url)`（预览/QC 环境可观察、不抛错）。
- 平台侧静音：仅 mraid 形渠道启用音量探测（`getAudioVolume()` 初始值 + `audioVolumeChange` 监听）；
  平台音量 0 时即使已交互也保持静音。
- 6 渠道共同红线（来自规则库 defaults，冻结）：`externalUrlPolicy: "forbid"`；允许 scheme 仅 `data:`/`blob:`
  （相对引用的运行时脚本如 `mraid.js` 无 scheme，不算外链）；首交互前静音。

## 2. 桥的路由实现映射（channels.ts，冻结）

| ExitRoute 返回值 | 触发条件 |
|---|---|
| `"mraid"` | 渠道 ∈ {applovin, unity, mintegral} 且 `mraid.open` 为函数 |
| `"meta"` | 渠道 meta 且 `FbPlayableAd.onComplete` 为函数 |
| `"google"` | 渠道 google 且 `ExitApi.exit` 为函数 |
| `"tiktok"` | 渠道 tiktok 且 `window.openAppStore` 为函数 |
| `"window-open"` | 以上皆不满足（兜底） |

`PF.open(url)` 语义：`pf:cta {url}` **每次点击都派发**；渠道退出外呼**仅第一次**真正调用（exitCalled 单次锁）。

## 3. CHK06 验收与真实 API 的冲突（契约修正候选，重要）

规划正文 CHK06 原文要求"退出接口被调用**且参数=landingUrl**"。按本表"是否传 URL"列核查：

- 兼容：applovin / unity / mintegral（`mraid.open(url)` 传 URL）、preview（`window.open(url)`）。
- **不兼容**：meta `onComplete()`、google `ExitApi.exit()`、tiktok `openAppStore()` 均**不接收 URL**——
  该验收按字面实现会永远失败。

**修正候选（待 owner 批准后改规划与 M8 spec）**：CHK06 按本表分型断言——
传 URL 渠道断言"调用一次且参数 === landingUrl"；不传 URL 渠道断言"调用恰一次 + 触发时机 = 结束页 CTA 点击"。
桥的测试夹具（`testsupport/fixture.mjs`）已按此分型记录各 stub 调用（`__calls.open` 数组 / 计数器）。

## 4. 单一真源的对齐缺口（如实记录）

- 规则 JSON 的 `exit.call` 是**人读字符串**，不是可执行适配器；新增渠道至少改两处：
  `channel-rules.json` + 桥 `channels.ts`（路由与就绪逻辑是代码）。"渠道规范变化只改配置"的承诺在
  退出路由上不成立（详见 CONTRACTS §痛点 6）。
- 当前缺席：unity/google/tiktok 三渠道不在规则库（打包器对未知渠道抛错拒绝——宁失败不出包是正确行为）。
- 扩渠道流程：先在本页加行 → 补规则 JSON（照 validateRules 结构）→ 桥 `channels.ts` 补路由与就绪分支 →
  桥测试夹具补 stub → packager 自验收补断言 → gate_phase1 门项 3 扩渠道。
