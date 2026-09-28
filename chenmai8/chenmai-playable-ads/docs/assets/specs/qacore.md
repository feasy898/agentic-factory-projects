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
- 监听 5 个 `pf:*` 事件（首个时刻；`pf:end` 记录 `detail.win`）。
- **包装 `AudioContext`/`webkitAudioContext` 构造器**：跟踪每个实例 state，`running` 集合大小即"正在出声的上下文数"。
- **包装 `HTMLMediaElement.prototype.play`**（覆盖 `<audio>/<video>/new Audio()`）：首次 pointer 事件前的调用计入 `playsBeforeFirst`；`sampleMedia()` 由 Python 侧每轮调用重采样未静音媒体元素（最坏值粘住）。
- **包装 `RTCPeerConnection`/`webkitRTCPeerConnection` 构造器**：`rtc` 计数 >0 → CHK03 fail（WebRTC 不经过 route 拦截）。

## 5. 自动试玩驱动（autoplay.py）

- 手势语义表：`swap-left/right/up/down` → 定向拖拽（44px×4 步，mouse down→move→up）；`drag` → 向右拖拽；
  `tap` → 单击。hint 坐标 = 视口 CSS 像素（模板规则卡 §8）。
- 首次手势前采集 `firstMutedBeforeInteraction`（`PF.isMuted()`）与 `audioRunningBeforeInteraction`；
  首次手势后采集 `mutedAfterFirstGesture`（应为 false=解除静音）。
- 结束采集：`pfEndFired/pfEndMs/pfEndWin`（探针）、`reachedState`（`__PF_QC__.state()`）、
  `endScreenVisible`（`__PF_QC__.endScreenVisible()`，无此钩子时为 null）、`gestures` 计数。
- CHK10 取证（2026-09-29 增，autoplay.py `qc_texts`/`qc_assets`）：竖屏趟在**驱动试玩前**采一次
  `__PF_QC__.texts()`（教程浮层数秒即消失，必须早采）、驱动到结束页**后再采一次**并集为
  `page_texts`；`__PF_QC__.assets()`（页面内把渲染贴图与内联用户 PNG 经同一 contain-fit 管线
  降采样 16×16 比平均绝对差，≤ 模板侧阈值 8 判 replaced）结果记 `asset_audit`。
  画布文字不进 DOM，innerText 取不到——文案取证必须走模板上报钩子。
- **禁止事项**：不许 mock 被测物——QC 必须以真实浏览器 + 真实 pointer 事件驱动；被测页面必须真实加载
  （本地伺服是真实 HTTP，这不算 mock）。不许把 skip 当 pass 统计。

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
| CHK08 控制台零错误 | 实装 | 两趟合并：console.error 或 pageerror 任一 → fail |
| CHK09 本地加载 | 实装 | 竖屏 load_ms ≤ max_load_sec×1000 |
| CHK10 多语言文案与素材上屏 | 实装（2026-09-29，扩展自"多语言/RTL"） | `--require-text`（可重复）每条须在 `page_texts` 中子串命中；`--require-sprite`（可重复）每键须 `asset_audit` 中 `replaced=true`（像素对账）。两者都未提供 → **skip**（无判定对象不算通过）。make 自动传入：首语言 标题/教程/胜/CTA/分 文案 + 构建旁车清单里的真实嵌入素材键；lose 不要求（自动试玩必胜，无出场机会） |

- 状态机取值 `pass|fail|skip`；**skip 是显式声明"未测"，报告中保留 skip 字样，严禁标成 pass**。

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

| 样本 | 构造方式（对金标产物的最小变异） | 必须命中 | 必须不受扰 |
|---|---|---|---|
| MUT-01 外链资源 | 把一个棋子/背景引用改成 `https://cdn.example/x.png` 外链 `<img>` 或 fetch | CHK03（外网请求被拦截并计入） | CHK05/07/08 不受扰（拦截后游戏仍可玩） |
| MUT-02 未静音 | 移除桥的静音策略（首交互前 `PF.isMuted()=false`，或 AudioContext 直接 running） | CHK04 | CHK07 不受扰 |
| MUT-03 结束页不可达 | `__PF_QC__.hint()` 恒返回 null，且无死局重排（步数耗尽即卡死） | CHK07（pf:end 未触发/超预算） | CHK03/04/05 不受扰 |
| MUT-04 超体积 | 在产物尾部注入垃圾字节使包体 > 渠道 maxBytes | CHK01 | 其余全部不受扰 |

- 后续第二波（对齐规划 §6-M8）：console error 注入（→CHK08）、退出接口缺失（→CHK06 实装后）等。
- 验收通过线：4/4 mutant 各自精确命中；金标层保持全 pass。
- 实装状态：**MUT-01/02/04 已实装**（2026-09-28 收紧，固化于 `scripts/gate_phase0.py` 门项 6：
  对 mini.html 夹具的最小变异，断言 qacore exit 1 且恰好命中对应 CHK；MUT-03 结束页不可达与
  `mutation-test` 独立子命令仍列 M8 全量里程碑）。

## 9. 重生成注意事项

- 依赖钉版：playwright 1.63.0 + `playwright install chromium`；pillow 12.3.0。
- Windows：子进程统一注入 `PYTHONUTF8=1`（GBK 控制台乱码坑）；图像分析若引入 cv2，**中文路径会失败**
  （本仓库路径含中文），须用 `np.fromfile + cv2.imdecode` 或沿用 Pillow——qacore 现用 Pillow 规避此坑。
- 报告 schema 尚未 JSON Schema 化（§4 字段表即现状契约）；收紧期间以 gate 脚本断言为准。
- 已知坑：页面 `add_init_script` 只注入一次（重复包装探针会让 audio.running 失真）；
  两趟视口各建新 context（隔离静音态与请求记录）。
- 变更史：commit `49b1f1f`（雏形）→ 后续收紧提交见 git log python/qacore。
