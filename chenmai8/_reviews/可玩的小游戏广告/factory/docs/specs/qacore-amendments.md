# qacore spec 修订附录（factory 侧 contract-change 台账）

> **地位与边界**：`docs/specs/qacore.md` 是 oracle `repo/docs/assets/specs/qacore.md`
> 的**字节冻结副本**（REUSED-ASSETS.md 登记册 A 节 #38，sha256
> `924515fa…`，`npm run verify:assets` 逐字节校验）。oracle 已封存只读，故其字节
> 不再可改——本仓对 qacore spec 的**一切后续修订以本附录登记**，逐条注明修订点、
> 依据与影响面；正文（qacore.md）与 oracle 的字节一致性由登记册持续担保。
>
> | 修订 | 日期 | 影响正文位置 | 状态 |
> |---|---|---|---|
> | chk04-determinism（探针旗 + 快速质检等桥） | 2026-09-30 | §4 探针契约、§5 首交互前采集 | 已生效（qacore src 同步落地） |

---

## chk04-determinism（2026-09-30，contract-change）

**背景**：模式 M 批次 3 差分终审（factory commit a4cbef7，`docs/diff/differential-report.md`
QC-02 / CLI-B 同族）判 FAIL 的两根支柱之一：oracle 产物 A 上新 TS 判官 CHK04（首交互前
静音）43/48 格 fail 而 oracle Python 判官 pass。归因实证：oracle 产物保留引擎真实
AudioContext，其 running 态在亚秒窗翻转（vendor engine.js `onGameVisible`
`setTimeout(…,100)` suspend→resume + BOOT unlock）；瞬时采样下 Python 同步链早读到 0
（假阴性）、Node 异步链晚几十毫秒读到 1，两侧判定纯竞态（`tmp/diff/e3a*-n-*.json` vs
`e3b-o-solo.json`；本机另证翻转本身随机器/会话状态抖动，见
`tmp/diff/probe-contract/`）。

**修订内容（仅 factory 侧，oracle 探针冻结不动）**：

1. **PROBE_JS 新增粘性旗 `audio.everBeforeFirstGesture`**（qacore.md §4 包装
   AudioContext 条目的修订）：`upd()` 内 `ctx.state==='running'` 且
   `firstGestureAt===null` 时置真、**置真不复位**——构造时初次 `upd()` 覆盖"构造即
   running"，既有 `statechange` 监听覆盖其后 resume，事件驱动消除采样竞态。旗只存
   页面 `__pfprobe` 对象，**不新增报告 facts 键**。修订后 factory PROBE_JS 3397 字符
   （oracle 冻结版 3119 字符；新旧 diff 存档 `tmp/diff/probe-contract/`，逐字节一致性
   证据自此失效、以本条登记为准）。
2. **`audioRunningBeforeInteraction` 值语义改旗驱动**（qacore.md §5 首次手势前采集
   条目的修订；判定输入键名不变）：旗真 → 1 粘住；旗假维持原瞬时采样 max 粘住语义
   （旗假 ⇒ 同一 `upd()` 同步记账下采样必为 0，两口径严格一致）。CHK04 判定输入与
   fail/pass 文案逐字不变（checks 零改动，含 qacore.md §6/oracle checks.py:106 同文案
   「首交互前存在 running AudioContext（n）」）。
3. **非 autoplay 快速质检桥就绪有界等待**（qacore.md §5/cli `_run_pass` 非 autoplay
   分支的修订）：直读 `PF.isMuted()` 前先 `page.waitForFunction(() => !!(window.PF &&
   typeof window.PF.isMuted === "function"), {timeout:5000})`（**必须传真函数**——
   playwright-node 把字符串页函数按表达式求值，`"() => …"` 得到恒真函数对象、等待
   立即放行），超时兜底照旧直读，缺桥/慢桥 **None→fail 从严语义不变**；横屏趟一致性
   同改；autoplay 趟 pfMuted 循环采样不动。
4. **快速质检 facts 读取口径对齐 oracle Python `or` 语义**：oracle checks.py:82
   `facts.get("autoplay") or facts.get("muteLoadTime") or {}`——空 dict 为 falsy 时回落
   muteLoadTime；JS `??` 对 `{}` 不回落（移植偏差，曾致快速质检 CHK04 恒读空 →
   isMuted=None 假阴性）。实现为 run.ts facts 组装处 `autoplay: autoplayEnabled ?
   autoplayFacts : null`；报告 facts 本就过滤 `autoplay` 键，报告 JSON 字段签名零变化。

**影响面与证据**：报告 JSON 字段签名零增删（facts 顶层/muteLoadTime/
viewport_shots.portrait 键集 + CHK01–CHK10 键集不变，P4 distinct signatures=1 保持）；
回归面 `qacore/tests/autoplay-flag.test.mjs`（探针旗契约页级真实 WebAudio 向量 +
B-like 阴性 ×5 + 慢桥 ×3）与 `qacore/tests/unit.test.mjs` CHK04 旗驱动值 1 判定向量。
机器层竞态取证（旗必要性）：`tmp/diff/probe-contract/probe_oracle_timeline.mjs`
（oracle A 产物 12 采样全程 running=0）、`probe_cli_sequence.mjs`（无手势 resume 3/3
永不落定）、`probe_unlock_strategies.mjs`、`probe_raciness.mjs`。
