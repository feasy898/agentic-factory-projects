# 流水线契约（Pipeline Contract）

> 版本：草案 v0.2（2026-09-28）。本页是六件优先级资产的第 1 件：唯一命令名、退出码、
> 模板产物目录形态、渠道包形态、报告 JSON 字段、二维码指向。
> **原则：数字与形态一律对照当前代码如实记录；规划与实现有出入处在文中显式标注"待统一"。**
> 在"待统一"项裁决之前，以本页记录的**实现现状**为准。

---

## 1. 命令名：现状与漂移（待统一）

| 能力 | 规划正文写法 | 实现现状（2026-09-28 代码） | 状态 |
|---|---|---|---|
| 规格校验 | `pfcore validate <spec...>` | **已实现**：`python -m pfcore validate <spec...>`（支持 glob） | frozen |
| 全流水线（校验→构建→打包→质检→汇总） | `pfcore make --spec S --locales en,ar --channels all` | **已实现**（`python/pfcore/make.py`）：`python -m pfcore make --spec S [--locales en,ar] [--channels all] [--out] [--serve-port] [--serve-host] [--no-serve]`。默认渠道=规则库三投放渠道；实现对首个 single-html 渠道跑 qacore `--autoplay`，产出 summary/二维码/计时/demo-prebuilt | frozen（**裁决：`make`，占位 `run` 已删除**） |
| 全渠道打包 | `pfcore pack --spec S --all-channels --locale en` | 占位 `pack`（exit 2）；实际可用的打包入口是 `node packages/packager/bin.mjs build` | 未实现 |
| 单模板构建 | `pfcore build`（占位） | 占位 `build`（exit 2）；**实际能用的构建入口是模板自己的 `node packages/templates/tmpl-match3/build.mjs`**（`make` 内部即调它） | 未实现 |
| 规则库校验 | `pfcore rules-check` | 占位（exit 2）；结构校验实际由 packager 的 `loadRules()` 承担 | 未实现 |
| 演示产物伺服 | —（规划未列，2026-09-29 反馈行动 2 新增） | **已实现**：`python -m pfcore serve [--root DIR] [--port N] [--host IP]`（`python/pfcore/serve.py`）：前台伺服既有目录 + 现场重建汇总页/二维码（§5.1） | frozen |

**裁决记录（2026-09-28 回填）**：全流水线冻结名取 **`make`**（与规划正文一致）；实现前占位名 `run`
已从 argparse、门禁常量（`scripts/gate_phase0.py` PFCORE_SUBCOMMANDS）与本仓全部文档删除。
任何新代码不得引入第三个全流水线命令名。

## 2. 退出码契约（已实现部分，冻结）

| 退出码 | 含义 | 出处（现状） |
|---|---|---|
| 0 | 全部通过 | pfcore validate 全过；qacore 无 fail；packager/模板构建成功；gate 脚本 PASS |
| 1 | 判定为失败：任一校验 issue / 质检任何一项 fail / 打包超规或零外链违规 / gate 有 FAIL 项 | validate、qacore、packager、gates |
| 2 | 用法错误 / 占位子命令未实现 / 产物不存在或非 .html | pfcore 占位命令；qacore 产物检查 |

## 3. 产物目录契约（现状，冻结）

### 3.1 模板产物（两条真实路径——双路径痛点见 CONTRACTS.md §痛点 5）

- **路径 A（当前唯一含真实玩法的产物）**：模板自建单文件
  `node packages/templates/tmpl-match3/build.mjs --spec <spec.json> [--out <file.html>] [--locale <tag>] [--no-minify]`
  → 单个自包含 HTML（spec JSON 经 `window.PF_SPEC` 内联 + `window.PF_LOCALE`，零外链、零相对资源引用；
  默认输出 `artifacts/preview/match3.html`）。
  **最小素材路径（2026-09-29 增）**：`spec.assets.sprites` 中文件真实存在的键（png/jpg/webp/gif，
  相对 spec 目录或仓库根解析）在构建期以 data URI 内联进 `window.PF_ASSETS`，运行期替换同键棋子的
  程序化贴图；缺失/格式不支持的键打警告并回退程序化贴图。真实嵌入清单同步写旁车
  **`<out>.assets.json`**（`{spec, locale, sprites:[{spriteKey,path,bytes}]}`，零嵌入也写出空清单）——
  make 据此给 qacore CHK10 传 `--require-sprite`。
- **路径 B（打包器的输入形态）**：dist 目录 —— 必须含 `index.html`；
  若存在 `<dist>/<locale>/index.html` 则整目录切换到该语言子目录（优先级：语言产物 > 根产物），
  HTML 内相对引用的 css/js/png 均可（由打包器内联）。
  **缺口（如实记录）**：模板 `build.mjs` 目前不输出 dist 目录形态；两条路径谁是唯一内联者待统一（见 CONTRACTS.md 痛点 5）。

### 3.2 渠道包（打包器输出，冻结）

```
<out>/<projectId>/<channel>/<locale>/
  ├─ index.html                    # single-html 渠道（applovin/meta/unity/preview）
  ├─ <projectId>-<locale>.zip      # zip 渠道（mintegral：包内 Template.html + build.js）
  └─ pack-manifest.json            # 元数据旁车：文件清单/字节数/sha256/警告/rulesVersion —— 不随包投放
```

- `<projectId>` 取 spec `meta.projectId`（校验 `/^[A-Za-z0-9][A-Za-z0-9._-]*$/`）。
- `--out` 缺省 = `artifacts`（相对当前工作目录）。

### 3.4 make 全流水线产物（2026-09-28 实现，冻结）

```
<out>/preview/<projectId>-<locale>.html      # 模板构建的真实可玩单文件（§3.1 路径 A）
<out>/<projectId>/dist/<locale>/index.html   # 打包器输入形态（§3.1 路径 B，构建产物的拷贝）
<out>/<projectId>/<channel>/<locale>/        # §3.2 渠道包 + qacore 报告/截图（质检渠道）
<out>/demo-prebuilt/                         # 演示兜底目录（全绿时才产出；每次运行整体重建）
  ├─ index.html                              # 汇总页（计时/渠道表/质检表/链接，零外链、仅相对引用）
  ├─ qr.png                                  # 二维码（内容=§5 的 LAN 预览 URL）
  ├─ pipeline-report.json                    # make 运行报告（计时/包清单/质检 checks/伺服状态）
  ├─ preview/<projectId>-<locale>.html       # 可玩 HTML 拷贝
  └─ channels/<channel>/<locale>/…           # 渠道包整目录拷贝（含 pack-manifest 与质检报告）
<out>/.demo-serve.json                       # 静态伺服状态（port/pid/root；复用判定用，demo-prebuilt 外）
```

- 渠道集合：`--channels` 缺省 `applovin,meta,mintegral`（规则库已冻结的三投放渠道）；
  `all` = 规则库全部渠道（`preview` 为本地渠道不打包）。规则库外渠道 exit 2。
- 质检：首个 single-html 渠道 × 首语言，`qacore run --autoplay`（预算取 spec `qc.*`）；
  报告落在该渠道目录（`index.report.json` + 双视口截图）。
  CHK10 判定输入由 make 自动传入（2026-09-29 增）：首语言的 标题/教程/胜/CTA/分 文案作
  `--require-text`（lose 不要求——自动试玩必胜，无出场机会），构建旁车清单（§3.1 路径 A）
  中真实嵌入的素材键作 `--require-sprite`。
- 任何质检 fail → exit 1，**不产出** 二维码与 demo-prebuilt（质检是裁判）。

### 3.3 质检报告（qacore 输出，冻结）

- 默认写到产物旁：`<产物名>.report.json`；截屏 `<产物名>.png`；横屏趟 `<产物名>-landscape.png`。
- **stem 命名裁决（2026-09-29 回炉定死，消除本页 §3.2/3.4 与 §4 示例的表面矛盾）**：
  `<产物名>` = **产物文件名去扩展名的 stem**。例如 dist 形态产物 `index.html` →
  `index.report.json` + `index.png` + `index-landscape.png`（make 渠道目录即此形态）；
  预览产物 `match3.html` → `match3.report.json`。§4 示例中的 `x.report.png` 泛指
  "产物 stem + `.report.png`"，不是字面文件名。
- `--out` 可指定报告路径（截屏随其目录且跟随**报告路径的 stem**：`<out>.png` /
  `<out>-landscape.png`；缺省时报告 stem = 产物 stem，三者同 stem）。

## 4. 报告 JSON 字段（qacore report，现状全字段，冻结）

```jsonc
{
  "channel": "applovin",                    // CLI 传入
  "url": "http://127.0.0.1:<port>/x.html",  // 本地伺服地址
  "autoplay": true,                          // 是否开启自动试玩
  "pf": {
    "present": true,     // window.PF 是否存在
    "readyMs": 229,      // pf:ready 时刻（performance.now，相对导航起点；无 autoplay 时为 null）
    "endMs": 26600,      // 首个 pf:end 时刻
    "endWin": true       // pf:end detail.win
  },
  "checks": [ { "id": "CHK01", "name": "包体大小 ≤ 渠道上限", "status": "pass|fail|skip", "detail": "人读说明" } ],
  "screenshot": "x.report.png",              // 相对报告目录；文件名 = 报告路径 stem + ".png"
                                             // （§3.3 stem 命名裁决：缺省时 stem = 产物 stem，
                                             //  "x" 泛指该 stem 而非字面文件名）
  "requests": [ { "url", "method", "resource_type", "status", "blocked", "failed" } ],
  "facts": {
    "artifact_bytes": 1239038,
    "channel": "preview",
    "channel_max_bytes": 5242880,            // 规则库缺失该渠道时为 null → CHK01 skip
    "external_requests": [],                 // 非本机请求（已 abort）
    "runtime_stubs": [],                     // 渠道容器运行时脚本本地桩（如 mraid.js；声明于
                                             // channel-rules runtime.injectRelativeScripts 且
                                             // 本地缺失时以空 JS 桩应答，模拟容器注入——2026-09-28 增）
    "request_count": 2,
    "console_errors": [],                    // console.error + pageerror
    "load_ms": 572,                          // 竖屏趟 load 耗时
    "max_load_sec": 2.0,
    "autoplay_enabled": true,
    "autoplay_timeout_sec": 45,
    "pf_present": true,
    "viewport_shots": { "portrait": {...}, "landscape": {...} },  // has_canvas / variance / 静音事实
    "variance_threshold": 30.0,
    "required_texts": ["宝石消消乐（试玩演示）", ...],  // CHK10 输入：要求的渲染文案（CLI --require-text）
    "required_sprites": ["piece-0"],                    // CHK10 输入：要求的替换素材键（CLI --require-sprite）
    "page_texts": ["..."],                              // 模板 __PF_QC__.texts() 上报的已渲染文案（竖屏趟，
                                                        //   驱动前+循环各相位+结束后并集；画布文字不进 DOM）
    "text_states": [ { "text": "...", "everVisible": true } ],  // CHK10 可见性自证（2026-09-29 增）：
                                                        //   采样时刻 __PF_QC__.textStates() 逐文案
                                                        //   active+visible 核验的"曾见"并集
    "text_states_hook": true,                           // 模板是否提供 __PF_QC__.textStates（缺失时
                                                        //   CHK10 对 required_texts 从严 fail）
    "asset_audit": [ { "texKey": "gem-0", "spriteKey": "piece-0",
                       "mad": 0, "replaced": true } ]   // 替换素材像素对账（渲染贴图 vs 内联用户 PNG）
  }
}
```

- 注意：`facts` 中**不含** autoplay 明细（单独在判定前抽出，不落盘到 facts）——两趟视口与试玩事实的完整采集结构见 [qacore spec](qacore.md)。
- CHK10（多语言文案与素材上屏）2026-09-29 实装：required_* 全缺 → skip（同旧"未实装"形态）；
  文案子串命中 + **text_states 中每条文案曾有 active+visible 采样证据**（模板无
  `__PF_QC__.textStates` 时无证据即 fail，从严）+ 素材对账 replaced 全真 → pass；任一缺口 → fail。
  自动 pass ≠ 人眼复核：演示上场前须对照报告截图人眼过一遍（docs/demo-checklist.md §3）。
- **缺口**：报告尚无正式 JSON Schema（CHK 字段表即本节；schema 化列入 M8 后续）。

## 5. 二维码指向与计时（2026-09-28 随 `make` 实现，冻结）

- 二维码内容 = **LAN 可达的预览 HTML 的 http URL**（`http://<局域网IP>:<port>/preview/<file>`；
  必须是局域网 IP，`127.0.0.1` 手机不可扫）。IP 探测按段优先级选（192.168 > 10 > 172.16-31 >
  100.64/10 > 其他 > 198.18/15 兜底——默认路由常落在 TUN 虚拟网卡上，不可直接采信），
  `--serve-host` 可显式覆盖。
- 伺服：`make` 以分离子进程启动 `python -m http.server <port> --bind 0.0.0.0 --directory
  <out>/demo-prebuilt`（缺省端口 8618，被未知进程占用时向后顺延；状态记 `<out>/.demo-serve.json`；
  复用前三重核实：记录端口 TCP 可连 + 记录 PID 存在且映像名为 python（tasklist /FI，防 PID
  跨重启被无关进程复用）+ 伺服根与本次一致——任一不满足即清状态文件，验明正身的旧 python
  伺服器杀旧起新（spawn ~0.3s），占用者是未知进程时绝不 taskkill 只换口）。汇总页 `index.html`
  与二维码同源。
- "可扫"判定 = qr.png 落盘 **且** 伺服端口 TCP 监听实测通过（本模块不向 loopback/私网发起
  HTTP 请求，健康检查只做 TCP connect）。
- 计时口径（实测打印两行，并写入 pipeline-report.json）：
  1. **make 墙钟**：编排入口 → 二维码可扫（演示计时器口径，目标 ≤90s；
     留档实测 28.9s：构建+三渠道包+qacore 自动试玩+兜底目录；接通复审复核值，
     旧草案期 41.8s 已被真实链路取代）；
  2. **spec 修改完成 → 二维码可扫**：以 spec 文件 mtime 为"改完 spec"的客观代理。

### 5.1 pfcore serve（2026-09-29 反馈行动 2，冻结）

对**已经生成好的**目录起前台局域网静态伺服器（演示日兜底：扫"今早 make 的预构建产物"
不必重跑流水线）：

```
python -m pfcore serve [--root artifacts/demo-prebuilt] [--port 8618] [--host <ip>]
```

- `--root` 缺省 `artifacts/demo-prebuilt`（相对 CWD）；也接受裸预览目录（如 `artifacts/preview/`）。
  目录不存在 → exit 2。
- 启动时**现场重建**两件东西（都落在被伺服目录内，覆盖写）：`index.html` 汇总页（预览链接 +
  各渠道包下载链接 + 质检报告链接——`*.report.json`/双视口截图/检查项明细现场解析，
  仅相对引用、零外链）与 `qr.png`（内容规则与上面 make 完全同规：LAN 预览 HTML 的 http URL；
  目录内无预览 HTML 时退化指向汇总页并打印警告）。
- **前台进程**（区别于 make 的分离子进程）：Ctrl+C 停止、端口即释放；不写 `.demo-serve.json`
  复用状态；端口被占同样向后顺延（上限 20 个）。退出码：0 = 被正常停止；2 = 用法/环境错误。
- 二维码指向优先级：`preview/*.html` 排序第一个 > 根目录散置 `*.html`（排除 index.html）> 汇总页。
- IP 探测、段优先级、TCP-only 健康检查复用 `make.py` 同一套函数（`_lan_ip`/`_port_listening`），
  本命令同样不发起任何 HTTP 请求。

## 6. 本契约的变更流程

见 [CONTRACTS.md](CONTRACTS.md) §变更流程。本页的每次裁决结果（尤其"待统一"项）必须回填本页并同步
`python/pfcore/__main__.py` 的 argparse 与门禁脚本。
