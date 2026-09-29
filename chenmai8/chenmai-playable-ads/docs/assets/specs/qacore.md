# M8 质检器 spec（qacore）

> 状态：**雏形 frozen，正在收紧中（另一代理修改 python/qacore）——以 eval 命令为最终真源**。
> 本页对照 `python/qacore/`（cli.py / checks.py / autoplay.py / server.py / __main__.py）逐项核验于 2026-09-28。
> 定位：QC 是全产线唯一裁判——不信任任何构建器，产物过不过 qacore 说了算。

---

## 1. 职责与边界

**做**：对**单个 HTML 产物**本地伺服 → 无头浏览器（手机仿真）打开两趟（竖屏/横屏）→ 拦截并记录全部网络请求
→ 采集事实（探针 + 截屏）→（`--autoplay`）经 `__PF_QC__.hint()` 用真实指针事件驱动到结束页 → 逐项判定 →
写 `report.json` + 截屏；任何 fail → exit 1。

**不做**：不处理 zip（非 .html 后缀直接 exit 2——**已知缺口**：zip 渠道产物暂无法质检）；不注入渠道退出
stub（CHK06 未实装）；不做多语言/RTL 的 locale 轮换仿真（CHK10 只对**本产物内联语言**断言指定文案与
替换素材上屏，切换语言重跑即可覆盖其他 locale）；不做文件数清点（CHK02 未实装）。

## 2. 命令契约（冻结）

```
python -m qacore run <artifact.html> [--channel preview] [--out <report.json>]
                       [--port 0] [--max-load-sec 2.0] [--autoplay] [--autoplay-timeout 45.0]
                       [--require-text <str> ...] [--require-sprite <key> ...]
```

- 报告默认写产物旁 `<产物名>.report.json`；截屏随报告目录（竖屏 `<名>.png`，横屏 `<名>-landscape.png`）。
- 退出码：0 = 无 fail（skip 不算）；1 = 有 fail；2 = 产物不存在或非 .html。
- cwd 约定：在 `python/` 目录或 pfcore/qacore 已 pip 可编辑安装的 venv 内任意目录均可。

## 3. 魔法数字表（冻结——改任何一个都要回填本页并复跑 gate）

| 常量 | 值 | 位置 | 理由 |
|---|---|---|---|
| 竖屏视口 | 390×844 | cli.py `VIEWPORT_PORTRAIT` | 主流手机 CSS 视口基线 |
| 横屏视口 | 844×390 | cli.py `VIEWPORT_LANDSCAPE` | CHK05 双仿真 |
| 设备仿真 | `is_mobile=True, device_scale_factor=2` | cli.py | 真机参数近似 |
| 导航超时 | 15000 ms | `GOTO_TIMEOUT_MS` | `wait_until="load"` 上限 |
| 首帧缓冲 | 400 ms | `SETTLE_MS` | load 后留给首帧渲染 |
| 空白判定 | 64×64 灰度**方差 < 30.0** 判空白 | `VARIANCE_THRESHOLD`；截屏经 Pillow `convert("L").resize((64,64))` | 纯色/空白页方差趋 0；有内容远高于 30 |
| 自动试玩预算 | 45 s（CLI 默认，取自 spec `qc.autoplayTimeoutSec`） | | 规划 §4.2 冻结值；与 `durationBudgetSec.max<=30` 的不一致见 CONTRACTS §痛点 7 |
| 试玩轮询间隔 | 180 ms | autoplay.py 主循环 | |
| 拖拽手势 | 位移 **44 px，分 4 步** mouse.move | `DRAG_DISTANCE=44.0`, steps=4 | 小于最小棋盘格边长，方向由 hint.type 决定 |
| 本地放行 | hostname ∈ {127.0.0.1, localhost} 且端口=伺服端口 | cli.py `_on_route` | 其余请求一律 `route.abort()` 并记入 external |
| 探针注入 | `add_init_script(PROBE_JS)` 每页面**一次** | cli.py `_wire` | 重复注入会二次包装 AudioContext 导致计数失真 |
| 加载计时 | 只取**竖屏趟** load 耗时 | cli.py | 与 spec `qc.maxLoadSec` 对齐 |

## 4. 探针契约（PROBE_JS，注入页面）

- `window.__pfprobe = { ready,start,end,endWin,first,cta, audio:{created,running}, media:{unmuted,playing,playsBeforeFirst}, rtc }`（时刻为 `performance.now()`，相对导航起点）。
- 监听的 5 个 `pf:*` 事件名单（冻结，各取首个时刻；`pf:end` 记录 `detail.win`）：
  `pf:ready`→`ready`、`pf:start`→`start`、`pf:first-interaction`→`first`、`pf:cta`→`cta`、
  `pf:end`→`end`。`probe.first` **只**由 `pf:first-interaction` 事件经 `once('first')` 设置；
  探针另在捕获阶段**只监听 `pointerdown`**（无 touchstart）记首个真实指针时刻，存入独立变量
  `firstGestureAt`，该时刻**仅用于 `playsBeforeFirst` 计数**（判定首交互前的媒体 `play()`），
  不写 `probe.first`——两个时刻各来自各自的源，不存在"先到者占 `first`"。
- **CHK08 的隐含前提（2026-09-29 回炉成文）**：`route.abort()` 拦截外链后，Chromium 会把
  被拦/失败的资源加载写进 DevTools Log（`Log.entryAdded`），Playwright 将其透传为 console
  error（文本形如 **`Failed to load resource: net::ERR_FAILED`**）。CHK08 的判定语义是页内
  `console.error()`/`pageerror`，故**网络源噪声必须过滤**——实现按"console 消息来源 URL ∈
  本次已 abort 记账的 blocked 集合"剔除（cli.py `_on_console`），该违规已由 CHK03 记账、
  不在 CHK08 重复处罚。不过滤则 MUT-01（外链必被 abort）必误伤 CHK08，与 §8"CHK08 不受扰"
  矛盾（试点曾按文本前缀 `Failed to load resource:` 过滤，同义等效；仓库实现以来源 URL
  归属为准，更精确）。
- **包装 `AudioContext`/`webkitAudioContext` 构造器**：跟踪每个实例 state，`running` 集合大小即"正在出声的上下文数"。
- **包装 `HTMLMediaElement.prototype.play`**（覆盖 `<audio>/<video>/new Audio()`）：首次 pointer 事件前的调用计入 `playsBeforeFirst`；`sampleMedia()` 由 Python 侧每轮调用重采样未静音媒体元素（最坏值粘住）。
- **包装 `RTCPeerConnection`/`webkitRTCPeerConnection` 构造器**：`rtc` 计数 >0 → CHK03 fail（WebRTC 不经过 route 拦截）。

## 5. 自动试玩驱动（autoplay.py）

- **autoplay 只驱动竖屏趟**（明说，冻结）：横屏趟以 `autoplay=off` 运行（cli.py `_run_pass`
  第三参传 `False`）。全部试玩取证（pf:end、手势、CHK10 文案/素材采集）都发生在竖屏趟；
  横屏趟只做 CHK05 方差与第二趟网络/控制台记录。
- 手势语义表：`swap-left/right/up/down` → 定向拖拽（44px×4 步，mouse down→move→up）；`drag` → 向右拖拽；
  `tap` → 单击（未知 type 按 tap 兜底，最不打扰被测物）。hint 坐标 = 视口 CSS 像素（模板规则卡 §8）。
- 首次手势前采集 `firstMutedBeforeInteraction`（`PF.isMuted()`）与 `audioRunningBeforeInteraction`；
  首次手势后采集 `mutedAfterFirstGesture`（应为 false=解除静音）。
- 结束采集：`pfEndFired/pfEndMs/pfEndWin`（探针）、`reachedState`（`__PF_QC__.state()`）、
  `endScreenVisible`（`__PF_QC__.endScreenVisible()`，无此钩子时为 null）、`gestures` 计数。
- CHK10 取证（2026-09-29 增，autoplay.py `qc_texts`/`qc_assets`；同日自证补强加
  `qc_text_states`）：竖屏趟在**驱动试玩前**采一次 `__PF_QC__.texts()`（教程浮层数秒即消失，
  必须早采）、驱动到结束页**后再采一次**并集为 `page_texts`；`__PF_QC__.assets()`（页面内把
  渲染贴图与内联用户 PNG 经同一 contain-fit 管线降采样 16×16 比平均绝对差，≤ 模板侧阈值 8 判
  replaced）结果记 `asset_audit`。画布文字不进 DOM，innerText 取不到——文案取证必须走模板上报钩子。
  **可见性自证（2026-09-29 补强）**：texts() 只能证明"字符串登记过"，登记后即销毁/隐藏的虚报
  无法排除——故自动试玩循环内随相位（含教程期）+ 驱动前 + 结束页各采一轮
  `__PF_QC__.textStates()`（模板侧当场读 Text 对象实况：active + 父容器链 visible 且 alpha>0），
  记 `text_states`（逐文案 everVisible）与 `text_states_hook`。模板不提供该钩子 → CHK10 从严
  fail（可见性无证据）。
- **禁止事项**：不许 mock 被测物——QC 必须以真实浏览器 + 真实 pointer 事件驱动；被测页面必须真实加载
  （本地伺服是真实 HTTP，这不算 mock）。不许把 skip 当 pass 统计。

### 5.1 模板上报钩子形状（`__PF_QC__`，冻结——对照 tmpl-match3 `main.ts` 声明）

| 钩子 | 返回形状 | 无钩子时 QC 行为 |
|---|---|---|
| `hint()` | `{x, y, type} \| null`，type ∈ `swap-up\|swap-down\|swap-left\|swap-right`，坐标 = 视口 CSS 像素整数 | `hasQcHook=false` → CHK07 fail |
| `state()` | `string`（相位：`tutorial\|playing\|end`） | `reachedState=null` |
| `endScreenVisible()` | `boolean`（可选钩子） | `null`（判定按 null=未证明可见） |
| `texts()` | `string[]`（已渲染到画布的文案集合；画布文字不进 DOM） | `textsHook=false`；QC 侧容错：dict 取 keys、标量包单元素 |
| `textStates()` | `Array<{text, active, visible}>`（采样时刻逐条实况；可选钩子） | `text_states_hook=false` → CHK10 对 required_texts 从严 fail |
| `assets()` | `Promise<Array<{texKey, spriteKey, mad: number\|null, replaced: boolean, reason?}>>`（渲染贴图 vs 内联用户 PNG 的 16×16 contain-fit 降采样平均绝对差对账，≤ 模板侧阈值 8 判 replaced；无替换素材时 `[]`） | `assetAuditHook=false`；required_sprites 有输入即 fail |

- `text_states` 的 `everVisible` 归属定义：QC 逐轮采样并集、**只置真不清零**——任一采样时刻
  `active && visible` 为真该文案即 `everVisible=true`（回弹/销毁不追溯撤销）；模板直接回
  `{text, everVisible}` 形状时亦兼容（pilot 同义实现）。

## 6. 检查项判定表（checks.py，现状）

| 检查项 | 状态 | 判定语义 |
|---|---|---|
| CHK01 包体大小 | 实装 | `artifact_bytes <= 规则库 maxBytes`；规则库无该渠道 → **skip**（不假定） |
| CHK02 文件数 | skip | 未实装（当前输入为单文件） |
| CHK03 零外网 | 实装 | 两趟合并：HTTP 由 route abort 记账；WebSocket 由 `route_web_socket("**/*")` 阻断并记账（条目前缀 `websocket:`，实测处理器内 `ws.close()` 会挂死 load 事件，故只记账不 close——未 `connect_to` 的 socket 不会真实连接）；Service Worker 整体禁注册（`service_workers="block"`，实测 SW 无法借道发外链）；RTCPeerConnection 构造计数 >0 → fail（WebRTC 不经过网络层拦截） |
| CHK04 首交互前静音 | 实装 | 渠道要求静音（channel-rules `muteBeforeFirstInteraction`，默认 true）时：无 window.PF 或探针未装 → **fail**（无法证明静音合规即违规，不再 skip）；有桥：首交互前 isMuted 必须 true、无 running AudioContext、无未静音媒体元素（`<audio>/<video>` 每轮重采样）、无首交互前媒体 `play()`；autoplay 时还要求首手势后 isMuted=false。渠道未强制静音且无桥 → skip |
| CHK05 横竖屏 | 实装 | 无 canvas → skip；有 canvas：两趟方差均 ≥ 阈值 30 |
| CHK06 退出接口 | skip | 未实装（stub 注入属后续）；**期望值与真实 API 冲突，修正候选见 channel-adapters §3** |
| CHK07 自动试玩到结束页 | 实装 | 无 `__PF_QC__` → fail；需 pf:end 已触发且 ≤45s、终态=end、结束页可见，三者齐备 |
| CHK08 控制台零错误 | 实装 | 两趟合并：console.error 或 pageerror 任一 → fail；**网络源日志噪声不计入**（来源 URL ∈ 本次 route.abort 记账的 blocked 集合的 console error 剔除——Chromium 对被拦资源必透传 "Failed to load resource" 类 DevTools 日志，该违规归 CHK03，见 §4 隐含前提） |
| CHK09 本地加载 | 实装 | 竖屏 load_ms ≤ max_load_sec×1000 |
| CHK10 多语言文案与素材上屏 | 实装（2026-09-29，扩展自"多语言/RTL"；同日自证补强） | `--require-text`（可重复）每条须在 `page_texts` 中子串命中，**且**在 `text_states` 中有"曾在采样时刻 active+visible"证据（模板无 `__PF_QC__.textStates()` → **fail**：可见性无证据，从严）；`--require-sprite`（可重复）每键须 `asset_audit` 中 `replaced=true`（像素对账）。两者都未提供 → **skip**（无判定对象不算通过）。make 自动传入：首语言 标题/教程/胜/CTA/分 文案 + 构建旁车清单里的真实嵌入素材键；lose 不要求（自动试玩必胜，无出场机会）。自动 pass ≠ 人眼复核：演示上场前须对照报告截图人眼过一遍（docs/demo-checklist.md） |

- 状态机取值 `pass|fail|skip`；**skip 是显式声明"未测"，报告中保留 skip 字样，严禁标成 pass**。

### 6.1 规则库判定输入的具体数值（CHK01/CHK04 消费，2026-09-29 回炉成文）

- 真源 = `channel-rules/channel-rules.json`（结构对齐 CONTRACTS §C4；数值与
  [channel-adapters §1](channel-adapters.md) 适配器总表一致）：`preview`/`applovin`/`mintegral`
  **maxBytes = 5242880**（5MB）、`meta` **maxBytes = 3145728**（3MB）。规则库无该渠道 →
  `facts.channel_max_bytes = null` → CHK01 **skip**（不假定）。
- `muteBeforeFirstInteraction` **缺省 true**（规则库 `defaults`，渠道 `runtime` 同名键可覆盖；
  qacore 取值次序：渠道 runtime > defaults > **true**——规则库不可读时也从严取 true，cli.py
  `load_channel_mute_required`）。
- `runtime_stubs` 机制（2026-09-28 增）：渠道 `runtime.injectRelativeScripts` 声明的容器运行时
  相对脚本（`applovin`/`mintegral` 注 `mraid.js`），且**产物目录内不存在同名文件**时，qacore 以
  空 JS 桩 200 应答（`route.fulfill(status=200, content_type="application/javascript",
  body=CONTAINER_STUB_JS)`，桩体为注释 `/* pf-qacore: 渠道容器运行时脚本本地桩（投放时由渠道
  容器提供，非包体内容） */`），模拟容器注入、保产物可跑；产物自带的同名文件照常透传（不喧宾夺主）。
  记账：请求条目加 `stub=true`，请求 URL 追加进 `facts.runtime_stubs`。

## 7. eval：精确命令与通过线

```bash
# 金标层（门禁固化于 scripts/gate_phase0.py 门项 5 / gate_phase1.py 门项 4）
python/.venv/Scripts/python.exe -m qacore run python/qacore/tests/fixtures/mini.html --channel preview --autoplay
#   → exit 0，报告含非空 checks 且 0 fail；门禁另断言已实装项（CHK01/03/04/05/07/08/09）
#     零 skip（skip 不算过）、CHK03/08/09 必须 pass
python/.venv/Scripts/python.exe -m qacore run artifacts/preview/match3.html --channel preview --autoplay
#   → exit 0（CHK01/03/04/05/07/08/09 全 pass；CHK02/06/10 skip 允许），pf:end ≤ 45000ms
# CHK10 实装层（2026-09-29，中文演示规格 specs-eval/demo-zh.json，piece-0 为用户替换 PNG）：
python/.venv/Scripts/python.exe -m pfcore make --spec specs-eval/demo-zh.json
#   → exit 0；报告 CHK10 pass：标题/教程/胜/CTA/分 中文文案全命中 + piece-0 像素对账 replaced=true。
#   阴性对照：对无嵌入的 golden 构建 `qacore run ... --require-sprite piece-0` → CHK10 fail、exit 1
#   （"替换素材 piece-0：页面未上报像素对账结果"）——检查非永绿。
# 变异样本（门禁固化于 gate_phase0.py 门项 6）：外链 img→恰 CHK03 / 未静音 audio→恰 CHK04 /
#   超体积→恰 CHK01，各自 qacore exit 1
```

## 8. 变异测试（M8 全量里程碑的验收，第一波 4 个样本）

设计原则：**每个 mutant 必须且只失败在对应检查项，其余检查项不受扰**；防"永远绿灯"假质检。

**样本来源与构造算法（2026-09-29 回炉成文）**：冻结测试目录只有 `python/qacore/tests/fixtures/mini.html`
一个夹具——**没有预置 mutant 文件**；变异样本 = gate 脚本**现场对夹具做最小变异**生成（写
`tmp/` 目录，夹具本身只读、永不被改；门禁**无**夹具哈希自检——试点门禁曾对夹具做 sha256
前后比对，仓库 `scripts/gate_phase0.py` 无此检查，防护实际靠"变异一律写 tmp/、报告存在=本次
真事实、先清旧产物再跑"）。已实装三个 mutant 的构造算法
（固化于 `scripts/gate_phase0.py` 门项 6，冻结）：

| 样本 | 构造算法（对 mini.html 的最小变异） | 必须命中 |
|---|---|---|
| MUT-01 外链资源 | 在夹具 QC 桥接桩锚点（`  <script>\n    // QC 桥接桩`）前注入一行 `<img src="https://cdn.example.com/mut01-external.png" alt="" width="1" height="1">` | CHK03（外网请求被拦截并计入） |
| MUT-02 未静音 | 同锚点注入一行 `<audio autoplay src="data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA="></audio>`（短 WAV data URI，未静音自动播放） | CHK04（媒体探针重采样捕获） |
| MUT-04 超体积 | 把 `</body>` 替换为 `<!--` + `"x"×pad` + `--></body>`，pad 取使总字节 = 渠道 maxBytes+4096（meta 渠道 3MB 压线用例；规则库不可读时内部线 3MB） | CHK01 |

- 通用纪律：样本写 `tmp/gate-phase0/mutations/`（先清旧产物再跑，报告存在=本次真事实）；
  qacore 以 `--out` 指定报告路径、子进程注入 `PYTHONUTF8=1`；**恰命中断言** = exit 1 且
  fail 集合恰为 `{期望 CHK}`（多 fail/少 fail 都算门禁失败）。
- MUT-03/结页不可达标注属 M8 后续（`__PF_QC__.hint()` 恒返回 null 且无死局重排；与
  `mutation-test` 独立子命令同列）。

| 样本 | 设计意图（实装构造算法见上表） | 必须命中 | 必须不受扰 |
|---|---|---|---|
| MUT-01 外链资源 | 引入一个指向 `https://cdn.example/…` 的外链资源请求 | CHK03（外网请求被拦截并计入） | CHK05/07/08 不受扰（拦截后游戏仍可玩；CHK08 靠 §4 网络噪声过滤） |
| MUT-02 未静音 | 令首交互前存在未静音出声源（桥静音策略失效或未静音 audio 直接出声） | CHK04 | CHK07 不受扰 |
| MUT-03 结束页不可达 | `__PF_QC__.hint()` 恒返回 null，且无死局重排（步数耗尽即卡死） | CHK07（pf:end 未触发/超预算） | CHK03/04/05 不受扰 |
| MUT-04 超体积 | 在产物尾部注入垃圾字节使包体 > 渠道 maxBytes | CHK01 | 其余全部不受扰 |

- 后续第二波（对齐规划 §6-M8）：console error 注入（→CHK08）、退出接口缺失（→CHK06 实装后）等。
- 验收通过线（与门禁实装对齐）：**门禁实装 3/3 mutant（MUT-01/02/04）各自精确命中；金标层保持
  全 pass**。MUT-03 结束页不可达的构造算法已在案（`__PF_QC__.hint()` 恒返回 null 且无死局重排，
  见下表设计意图），其实装列 M8 全量里程碑，落地后通过线升 4/4。
- 实装状态：**MUT-01/02/04 已实装**（2026-09-28 收紧，固化于 `scripts/gate_phase0.py` 门项 6：
  对 mini.html 夹具的最小变异，断言 qacore exit 1 且恰好命中对应 CHK；MUT-03 结束页不可达与
  `mutation-test` 独立子命令仍列 M8 全量里程碑）。

## 9. 重生成注意事项

- **依赖最小集（2026-09-29 回炉成文）**：qacore 运行只需 **playwright 1.63.0 + pillow 12.3.0**
  两个第三方包（再加 `playwright install chromium` 的浏览器）；仓库全量清单
  `python/requirements.txt`（fastapi/uvicorn/httpx/pydantic/jsonschema/fonttools/qrcode 等）
  是**其余模块**的依赖，单独再生 qacore 时不必需。
- **报告 JSON 全字段的单一来源 = [pipeline-contract.md §4](pipeline-contract.md)**（报告顶层
  字段 + `facts` 逐键；本页不再重复列字段表，避免两处漂移——2026-09-29 前 §9 曾误写"§4 字段表"
  指向本页 §4 探针契约，已修正为显式交叉引用）。报告 schema 尚未 JSON Schema 化，收紧期间以
  gate 脚本断言为准。
- Windows：子进程统一注入 `PYTHONUTF8=1`（GBK 控制台乱码坑）；图像分析若引入 cv2，**中文路径会失败**
  （本仓库路径含中文），须用 `np.fromfile + cv2.imdecode` 或沿用 Pillow——qacore 现用 Pillow 规避此坑。
- 已知坑：页面 `add_init_script` 只注入一次（重复包装探针会让 audio.running 失真）；
  两趟视口各建新 context（隔离静音态与请求记录）。
- 变更史：commit `49b1f1f`（雏形）→ 后续收紧提交见 git log python/qacore；2026-09-29 第三波
  试点回炉（§4 事件名单与 CHK08 前提、§5 竖屏明说、§5.1 钩子形状、§6.1 规则库数值、§8 变异
  构造算法、§9 交叉引用与依赖最小集）。
