# M4 打包器 spec（packager）

> 状态：frozen。对照 `packages/packager/{bin.mjs,src/*,test/run.mjs}` 与 README 逐行核验于 2026-09-28。
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
- 退出码：0 成功；1 构建失败（含超规/外链/结构违规——stderr 一行人读原因）；2 参数错误/未知命令。
- 成功时 stdout 末行输出 JSON：`{ok:true, artifact, totalBytes, maxBytes}`。

## 3. 对外契约

### 3.1 输入

- **dist**：必须含 `index.html`；若存在 `<dist>/<locale>/index.html` 则**整目录基准切换**到该子目录
  （语言产物优先）。HTML 内相对引用基准 = 所在目录（CSS 内 url() 相对 CSS 文件），包含性检查针对 dist 根。
- **规则库**（结构由 `validateRules` 强制，违规直接抛错）：
  `rulesVersion`；`channels.<id>{ package{format: "single-html"|"zip", entry, structure?},
  maxBytes>0, maxFiles>0, exit{protocol, call}, runtime{muteBeforeFirstInteraction, injectRelativeScripts?,
  forbidMraid?}, allowedUrlWhitelist? }`。zip 的 `structure` 必须含 entry；实现还要求 zip 恰为
  `[bundle, entry]` 两项（否则抛错）。
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
packageFiles[], files[{path,bytes,sha256,role}], warnings[]`。role ∈ `package|entry-in-zip|bundle-in-zip`；
`totalBytes` 只累计 role=package。

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
- **MRAID 禁用**：`forbidMraid` 渠道（meta）产物中出现 `\bmraid\b[^;]{0,40}` 全词命中即失败（启发式）。

### 3.4 自研 zip（zip.mjs，冻结）

- 写：deflate level 9（收益不足即回退 store）；**固定 DOS 时间戳 2026-01-01**（同输入字节可复现）；
  UTF-8 文件名 flag 0x0800；重名拒绝；条目名含目录须用 `/`。
- 读：`readZip` 仅供自验收（central directory + inflateRaw；仅支持 method 0/8、无 data descriptor、无 zip64）。

## 4. 行为规格（失败路径）

- spec 缺 `meta.projectId`（正则 `/^[A-Za-z0-9][A-Za-z0-9._-]*$/`）或 `specVersion` → 失败。
- locale 校验 `/^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$/`；projectId/locale 用于路径拼接，禁路径符号。
- dist 缺入口 / 内联资源缺失（带引用来源的报错）/ 白名单外外链 / MRAID / 超上限 / 超文件数 → 全部**构建失败
  而非告警**（zip 收益取舍：零外链与结构是红线）。
- 未知渠道 → 抛错列出现有渠道（拼错渠道名不静默通过）。

## 5. eval：精确命令与通过线

```bash
node packages/packager/test/run.mjs     # 全部断言过 exit 0
```

自验收断言（夹具 `test/fixture/match3-dist`，纯 Node 生成 PNG，`gen-pngs.mjs`）：
applovin 单 HTML（存在 / ≤5MB / 白名单外零外链 / `mraid.js` 已注入 / data URI 内联 / 重复构建字节一致）；
meta（≤3MB——规则 + spec override 生效 / 零外链 / 无 MRAID）；mintegral zip（结构恰 `[Template.html, build.js]`
/ Template.html 相对引用 build.js / 条目内零外链 / **python zipfile 交叉验证**）；负向：dist 混外链 → 拒、
meta 产物混 MRAID → 拒、未知渠道（google）→ 拒。

- 门禁复验：`scripts/gate_phase1.py` 门项 3（对三渠道产物独立断言大小/结构/零外链/注入/禁用；
  `pack-manifest.json` 不计入包内文件）。
- **禁止事项**：不许为过验收放宽外链正则或把失败降级为警告。

## 6. 重生成注意事项（实测坑）

- esbuild 是根工作区 devDependency（0.28.2 钉版）；本包自身零第三方运行时依赖。
- zip 时间戳固定是实现可复现断言的前提——改 `zip.mjs` 时间字段会破坏"重复构建字节一致"。
- HTML 解析是**严格正则**（不用 DOM 库）：dist 产物的标签写法须规整；异常即失败是设计行为。
- `type=module` 外链脚本会触发告警（合并为经典脚本后 import/export 不可用）——dist 必须是自包含 bundle。
- 与模板构建产物如何对接（谁产出 dist 目录形态）见 [pipeline-contract](pipeline-contract.md) §3.1 的双路径缺口。
- 变更史：commit `6cad6a4`（M4 + 规则库三渠道基线）。
