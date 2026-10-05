# M4 打包器 spec（packager）

> 状态：frozen。对照 `packages/packager/{bin.mjs,src/*,test/run.mjs}` 与 README 逐行核验于 2026-09-28；
> 2026-09-29 C2 盲评修正同步：§3.1.1 升 rulesVersion 1.1.0 六渠道冻结表（T2.4）、§3.3 MRAID 检测规则
> 改为实现真实调用形态正则、未知渠道语义改写（google 已在库，负向用例为 `not-a-channel`）。
> 定位：配置驱动（channel-rules 是规则来源，打包器不改渠道知识）；**宁失败不出超规包**。

---

## 1. 职责与边界

**做**：dist 目录 + spec + 规则库 → 渠道包（单 HTML 全内联 / 规则声明的 zip 结构）；HTML 内联引擎、
自研 zip（字节可复现）、外链白名单扫描、MRAID 禁用检测、大小/文件数/结构强制、`pack-manifest.json` 台账。

**不做**：不做完整 spec 校验（那是 M1；这里只轻量取 `meta.projectId` 与 `specVersion`）；不做渲染；
不决定渠道知识（规则库说了算）。

## 2. CLI 契约（冻结）

```
node packages/packager/bin.mjs build --spec <spec.json> --dist <dir> --channel <id>
        [--locale en] [--out artifacts] [--rules channel-rules/channel-rules.json] [--no-minify]
node packages/packager/bin.mjs channels [--rules <path>]     # 列出规则库渠道
```

- Node ≥22；`--out` 缺省 = `<cwd>/artifacts`；rules 缺省 = 仓库根 `channel-rules/channel-rules.json`。
- 退出码（**统一裁定，消除歧义**）：**0** 成功；**1** 构建失败——含超规/外链/结构违规/**未知或未冻结渠道**
  （`channelRule` 抛错、被 main 的 catch 统一接住，stderr 输出 `[packager] 失败: <原因>` 并列出现有渠道）；
  **2** 仅限 CLI 用法层：未知子命令、多余位置参数、参数解析错误。渠道拼写错误**不是** exit 2。
- 成功时 stdout 末行输出 JSON：`{ok:true, artifact, totalBytes, maxBytes}`。

## 3. 对外契约

### 3.1 输入

- **dist**：必须含 `index.html`；若存在 `<dist>/<locale>/index.html` 则**整目录基准切换**到该子目录
  （语言产物优先）。HTML 内相对引用基准 = 所在目录（CSS 内 url() 相对 CSS 文件），包含性检查针对 dist 根。
- **规则库**（结构由 `validateRules` 强制，违规直接抛错）：
  `rulesVersion`；`channels.<id>{ package{format: "single-html"|"zip", entry, structure?},
  maxBytes>0, maxFiles>0, exit{protocol, call}, runtime{muteBeforeFirstInteraction, injectRelativeScripts?,
  forbidMraid?}, allowedUrlWhitelist? }`。zip 的 `structure` 必须含 entry；实现还要求非入口且非
  generated 的合并脚本至多 1 个（否则抛错）——故 structure 项数随渠道面变（如 mintegral
  `[build.js, Template.html]`、google `[index.html]`、tiktok `[index.html, config.json, js-sdk.js]`）。

### 3.1.1 规则库当前内容全量（rulesVersion 1.1.0，再生时逐字节对照 `channel-rules/channel-rules.json`）

公共 `defaults`：`externalUrlPolicy: "forbid"`；`allowedUrlSchemes: ["data:", "blob:"]`；
`allowedTextUrls: ["https://pf.io", "http://www.w3.org/1999/xhtml", "http://www.w3.org/2000/svg"]`
（外链文本扫描全局白名单，只收惰性字符串而非请求目标：引擎品牌串与 XML 命名空间标识符）；
`muteBeforeFirstInteraction: true`；`allowRelativeRuntimeScripts: true`。库级 `updated: "2026-09-29"`。

**T2.4（2026-09-29）起六条投放渠道全部冻结**：applovin / meta / mintegral / google / unity / tiktok
（pangle 与 tiktok 同协议，桥归一为 tiktok，规则库不单列）；另有 `preview`（本地预览/QC 渠道，
非投放渠道）共 **7 渠道在库**。

| 字段 | `applovin` | `meta` | `mintegral` | `google` | `unity` | `tiktok` | `preview` |
|---|---|---|---|---|---|---|---|
| package.format | `single-html` | `single-html` | `zip` | `zip` | `zip` | `zip` | `single-html` |
| package.entry | `index.html` | `index.html` | `Template.html` | `index.html` | `index.html` | `index.html` | `index.html` |
| package.structure | —（无此键） | — | **`["build.js", "Template.html"]`** | `["index.html"]` | `["index.html"]` | **`["index.html", "config.json", "js-sdk.js"]`** | — |
| package.generated | — | — | — | — | — | `{config.json: tiktok-config, js-sdk.js: js-sdk-stub}`（打包器按 spec 生成的附加文件） | — |
| maxBytes | **5242880**（5MB） | **3145728**（3MB 内部从严） | **5242880** | **5242880** | **5242880** | **5242880** | **5242880** |
| maxFiles | 1 | 1 | **100** | **512**（规划基线，内部目标 ≤200） | **512**（暂同 google 内部线） | **100** | 1 |
| exit.protocol / call | `mraid` / `mraid.open(url)` | `fb-playable` / `FbPlayableAd.onComplete()` | `mraid` / `mraid.open(url)` | `exit-api` / `ExitApi.exit()` | `mraid` / `mraid.open(url)` | `js-sdk` / `window.openAppStore()` | `window-open` / `window.open(url)` |
| exit.waitReadyBeforeRender | `true` | `false` | `true` | `false` | `true` | `false` | `false` |
| runtime.injectRelativeScripts | **`["mraid.js"]`** | `[]` | **`["mraid.js"]`** | `[]` | **`["mraid.js"]`** | **`["js-sdk.js"]`** | `[]` |
| runtime.forbidMraid | `false` | **`true`** | `false` | `false` | `false` | `false` | `false` |
| allowedUrlWhitelist | `[]` | `[]` | `[]` | `[]` | `[]` | `[]` | `[]` |

**mraid.js 注入片段原文**（`injectRelativeScripts` 命中且 HTML 尚无该引用时，插到 `<head…>` 开标签之后）：

```html
<script src="mraid.js"></script>
```

已存在判定正则：`src\s*=\s*["']mraid.js`（即已引用则不重复注入）。相对引用无 scheme，**不算外链**。
- **有效大小上限** = `min(渠道 maxBytes, spec.channels.overrides.<channel>.maxBytes)`——**override 只许收紧
  不许放宽**。

### 3.2 输出

```
<out>/<projectId>/<channel>/<locale>/
  single-html: index.html（全内联）
  zip:         <projectId>-<locale>.zip（条目 = 规则 structure 顺序）
  pack-manifest.json（旁车，不随包投放）
```

manifest 字段：`packager("@pf/packager"), rulesVersion, channel, locale, project, specPath, dist, maxBytes,
packageFiles[], files[{path,bytes,sha256,role}], warnings[]`。role ∈
`package|entry-in-zip|bundle-in-zip|generated-in-zip`——第四值 `generated-in-zip`（T2.4 增）=
规则库 `package.generated` 声明、打包器按 spec 现生成的附加文件（tiktok 的 `config.json`/`js-sdk.js`
各记一项）；`totalBytes` 只累计 role=package。

**files[] / packageFiles 形状（按通道，冻结）**：

| 通道 | files[] | packageFiles[] |
|---|---|---|
| single-html | `[{path:"index.html", bytes, sha256, role:"package"}]`（1 项） | `["index.html"]` |
| zip | **项数随渠道 structure 变化**（前 2 项恒为 package+entry-in-zip；structure 无合并脚本则不 push bundle-in-zip）：google/unity **2 项**——`[{zip, package}, {index.html, entry-in-zip}]`；mintegral **3 项**——`[{zip, package}, {Template.html, entry-in-zip}, {build.js, bundle-in-zip}]`；tiktok **4 项**——`[{zip, package}, {index.html, entry-in-zip}, {config.json, generated-in-zip}, {js-sdk.js, generated-in-zip}]` | **仅 1 项**：`["<projectId>-<locale>.zip"]`（zip 内条目不进 packageFiles） |

**specVersion 位置**：打包器读的是**顶格** `spec.specVersion`（`loadSpecFields`），不在 `meta` 内；
连同 `meta.projectId`（正则 `/^[A-Za-z0-9][A-Za-z0-9._-]*$/`）是打包器仅取的两个 spec 结构字段。

### 3.3 HTML 内联引擎（识别写法精确清单，冻结）

| 输入写法 | 处理 |
|---|---|
| `<link rel="stylesheet" href="...">` | 内联为 `<style data-pf="<原href>">`；CSS 内 `url(...)` 先转 data URI 再压缩 |
| `<link rel="icon|shortcut icon|apple-touch-icon" href>` | href → data URI（已是 data:/blob: 则跳过） |
| `<img|source|audio|video|track src>` | src → data URI；`srcset` **不支持内联**（告警，要求改单 src） |
| `<style>` 块内 `url(...)` | 相对 **dist 根** 解析转 data URI；整块压缩 |
| `<script src="...">` | inline 模式：就地内联为 `<script type?> data-pf="<原src>">`；extract 模式（zip 渠道）：**第一个**外链脚本位置替换为 `<script src="<bundleName>">`，其余替换为 `<!-- pf-packager: x merged into y -->`，全部脚本按文档顺序 `"\n;\n"` 合并成 bundle |
| `<head>` 缺 charset | 自动补 `<meta charset="utf-8">` |
| 渠道 `injectRelativeScripts`（如 `mraid.js`） | `<head>` 后注入 `<script src="mraid.js"></script>`（无 scheme，外链扫描不算外链；已存在则不重复注入） |

- 压缩：esbuild `transform`（minify、`target es2017`、`legalComments: "none"`）；`--no-minify` 跳过。
- **拒绝**（resolveDistRef 快速失败）：带 scheme 引用（`http(s)://...`）、协议相对 `//`、根相对 `/`、
  逃逸出 dist 根的相对路径。
- **外链扫描**：正则 `\bhttps?://[^\s"'<>\\)\]}]+`（大小写不敏感）；白名单 = spec `flow.endScreen.landingUrl`
  （前缀匹配）+ 规则 `allowedUrlWhitelist`；HTML 与 bundle 文本分别扫描，命中即构建失败。
- **MRAID 禁用**：`forbidMraid` 渠道（meta）产物命中**调用形态正则**
  `\bmraid(?:\s*\.\s*[A-Za-z_$][\w$]*|(?:\.js)\b)`（`gi`，`findMraidReferences`）——即
  `mraid.<方法>` 的 API 调用形态、或对 `mraid.js` 脚本的引用——命中即失败（启发式）。
  **设计理由（有意收窄，不按全词出现判定）**：含运行时桥的模板产物必然携带 mraid 的
  *探测代码*（`typeof x.mraid`、`x.mraid?"applovin":"preview"` 之类），文本上无法与真依赖
  分开；若按全词出现（早期草案 `\bmraid\b[^;]{0,40}`）判定，一切真实游戏都打不出 meta 包。
  **判定边界（实测）**：`window.mraid`（裸引用）→ 不命中；`Mraid` / `MRAID_TEST` → 不命中
  （`gi` 大小写不敏感，但裸名/下划线接续不构成调用形态）；`mraid.getState()` → 命中
  `mraid.getState`；`src="mraid.js"` → 命中 `mraid.js`。
  **漏检面（启发式固有盲区，非回归）**：别名转手后调用（`var m=window.mraid;m.open()`）
  不落调用形态、不命中；字符串拼接出的 `mraid` 引用同理绕过——本检查只拦"文本可辨的真使用"。
- **maxFiles 语义**：仅 **zip 通道强制**，且按 **zip 内条目数**计数（`entries.length > maxFiles` → 失败）；
  single-html 渠道打包器不检查 maxFiles（其"恰 1 个包文件"由门禁/使用方对产物目录断言）。

### 3.4 自研 zip（zip.mjs，冻结）

- 写：deflate level 9（收益不足即回退 store）；**固定 DOS 时间戳 2026-01-01**（同输入字节可复现）；
  UTF-8 文件名 flag 0x0800；重名拒绝；条目名含目录须用 `/`。
- 读：`readZip` 仅供自验收（central directory + inflateRaw；仅支持 method 0/8、无 data descriptor、无 zip64）。

### 3.5 评测夹具 golden-match3.json（打包器视角的最小内容集，冻结）

文件：`specs-eval/golden-match3.json`。打包器实际消费的字段只有 4 个，再生评测时缺失任一即失败：

| 字段 | 值 | 用途 |
|---|---|---|
| `specVersion` | `"1.0.0"` | **顶格**（不在 meta 内），仅校验存在且为 string |
| `meta.projectId` | `"golden-match3"` | 产物目录名 + zip 文件名（`golden-match3-en.zip`） |
| `flow.endScreen.landingUrl` | `"https://example.com/playable-lp"` | 外链白名单唯一前缀（自验收 `externalUrls()` 也硬编码此值） |
| `channels.overrides.applovin.maxBytes` | `5242880` | 收紧校验（与规则上限相等，实测 effectiveMaxBytes 取 min 逻辑） |
| `channels.overrides.meta.maxBytes` | `3145728`（+`ctaStyle:"endcard"`，打包器不消费 ctaStyle） | meta 3MB 线来源之一（min(规则, override)） |

其余字段（seed 20260930 / 6 语言含 ar / nearWin 等）为全产线共用，打包器不读。夹具 dist
（`test/fixture/match3-dist/`：index.html + css/style.css + js/game.js + img/*.png）**已入库**，
PNG 为纯色占位（零依赖生成器 `gen-pngs.mjs` 的一次性产物，仅在改夹具时重跑）。

## 4. 行为规格（失败路径）

- spec 缺 `meta.projectId`（正则 `/^[A-Za-z0-9][A-Za-z0-9._-]*$/`）或 `specVersion` → 失败。
- locale 校验 `/^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$/`；projectId/locale 用于路径拼接，禁路径符号。
- dist 缺入口 / 内联资源缺失（带引用来源的报错）/ 白名单外外链 / MRAID / 超上限 / 超文件数 → 全部**构建失败
  而非告警**（zip 收益取舍：零外链与结构是红线）。
- 规则库未收录渠道（拼错或未冻结）→ 抛错列出现有渠道（拼错渠道名不静默通过）。

## 5. eval：精确命令与通过线

```bash
node packages/packager/test/run.mjs     # 全部断言过 exit 0
```

自验收断言（夹具 `test/fixture/match3-dist`，纯 Node 生成 PNG，`gen-pngs.mjs`）：
applovin 单 HTML（存在 / ≤5MB / 白名单外零外链 / `mraid.js` 已注入 / data URI 内联 / 重复构建字节一致）；
meta（≤3MB——规则 + spec override 生效 / 零外链 / 无 MRAID）；mintegral zip（结构恰 `[Template.html, build.js]`
/ Template.html 相对引用 build.js / 条目内零外链 / **python zipfile 交叉验证**）；负向：dist 混外链 → 拒、
meta 产物混 MRAID → 拒、未知渠道（`not-a-channel`）→ 拒——google 自 rulesVersion 1.1.0 起为
冻结投放渠道，其自验收为 **3b 正向断言组**（zip 构建 exit 0、条目恰 `[index.html]`、≤5MB、零外链、
无运行时注入），不再是负向用例。

- 门禁复验：`scripts/gate_phase1.py` 门项 3（对三渠道产物独立断言大小/结构/零外链/注入/禁用；
  `pack-manifest.json` 不计入包内文件）。
- **禁止事项**：不许为过验收放宽外链正则或把失败降级为警告。

## 6. 测试环境前置（冻结 run.mjs 的路径假设与 glue——再生试验瞬时失败的根因区，成文于第二批试验）

自验收 `test/run.mjs` **从自身位置反推仓库根**：`REPO_ROOT = <run.mjs>/../../..`。因此隔离再生目录**必须**
具备以下形状，缺一即瞬时失败（这不是测试的 bug，是冻结契约的一部分——**环境前置由 spec 声明，禁止实现者
自创 junction/venv glue**）：

```
<root>/packages/packager/bin.mjs            # BIN（build 以 cwd=REPO_ROOT 子进程运行）
<root>/packages/packager/src/*.mjs          # 被测实现（html.mjs import "esbuild" → 需 root node_modules）
<root>/packages/packager/test/run.mjs       # 冻结测试（<root> = 此文件的上一级再两级）
<root>/packages/packager/test/fixture/match3-dist/**   # 夹具 dist（已入库，含 PNG）
<root>/specs-eval/golden-match3.json        # SPEC（内容见 §3.5）
<root>/channel-rules/channel-rules.json     # 规则库（bin.mjs 默认路径从自身位置反推同一 <root>）
<root>/package.json + node_modules/         # npm ci 一次（esbuild 0.28.2 从根解析；packager 自身零依赖）
<root>/tmp/packager-selftest/               # OUT（测试开头 rmSync 清空重建）
<root>/python/.venv/Scripts/python.exe      # 可选 glue（见下）
```

- **esbuild**：`packages/packager` 无自己的 node_modules，`src/html.mjs` 的 `import "esbuild"` 沿目录向上解析
  → 必须先在 `<root>` 执行 `npm ci`（或最小化 `npm i -g`/等价方式让 Node 能解析 `esbuild`）。缺它 = 所有
  build 立即失败。
- **python zipfile 交叉验证断言的 venv 依赖与 SKIP 语义**：该断言查
  `<root>/python/.venv/Scripts/python.exe`——
  - venv **存在**：执行内联脚本（testzip CRC + 条目名 + Template.html 引用 build.js），失败 → FAIL exit 1；
  - venv **不存在**：打印 `[SKIP ] mintegral: python zipfile 交叉验证（未找到 venv python）`，**不注册断言**
    （既不计 pass 也不计 fail），整体仍可 exit 0。断言总数随渠道扩容增长（T2.4 六渠道 +
    google 3b 正向断言组后）：无 venv 时 **45 条断言 + 1 SKIP**，有 venv 时 **46 条**
    （2026-09-29 实跑 `node packages/packager/test/run.mjs` = 46 条 [PASS] exit 0）。
    SKIP 是显式声明，不是放行 bug。
- 工作流/CI 门跑此测试前先核对上述形状（瞬时失败先查路径假设与 node_modules，再查实现）。

## 7. 重生成注意事项（实测坑）

- esbuild 是根工作区 devDependency（0.28.2 钉版）；本包自身零第三方运行时依赖。
- zip 时间戳固定是实现可复现断言的前提——改 `zip.mjs` 时间字段会破坏"重复构建字节一致"。
- HTML 解析是**严格正则**（不用 DOM 库）：dist 产物的标签写法须规整；异常即失败是设计行为。
- `type=module` 外链脚本会触发告警（合并为经典脚本后 import/export 不可用）——dist 必须是自包含 bundle。
- 与模板构建产物如何对接（谁产出 dist 目录形态）见 [pipeline-contract](pipeline-contract.md) §3.1 的双路径缺口。
- 变更史：commit `6cad6a4`（M4 + 规则库三渠道基线）。
