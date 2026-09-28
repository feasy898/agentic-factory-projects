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
| 全流水线（校验→构建→打包→质检→汇总） | `pfcore make --spec S --locales en,ar --channels all` | **未实现**。占位子命令名为 `run`（argparse 已注册，执行即回显"尚未实现"并 exit 2） | **命令名漂移，待统一** |
| 全渠道打包 | `pfcore pack --spec S --all-channels --locale en` | 占位 `pack`（exit 2） | 未实现 |
| 单模板构建 | `pfcore build`（占位） | 占位 `build`（exit 2）；**实际能用的构建入口是模板自己的 `node packages/templates/tmpl-match3/build.mjs`** | 未实现 |
| 规则库校验 | `pfcore rules-check` | 占位（exit 2）；结构校验实际由 packager 的 `loadRules()` 承担 | 未实现 |

**裁决建议**（由仓库 owner 定夺后回填本页）：冻结名取 `make`（与规划一致）或 `run`（与占位一致），
二选一后删除另一处提法；在裁决前，任何新代码不得引入第三个全流水线命令名。

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

### 3.3 质检报告（qacore 输出，冻结）

- 默认写到产物旁：`<产物名>.report.json`；截屏 `<产物名>.png`；横屏趟 `<产物名>-landscape.png`。
- `--out` 可指定报告路径（截屏随其目录）。

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
  "screenshot": "x.report.png",              // 相对报告目录
  "requests": [ { "url", "method", "resource_type", "status", "blocked", "failed" } ],
  "facts": {
    "artifact_bytes": 1239038,
    "channel": "preview",
    "channel_max_bytes": 5242880,            // 规则库缺失该渠道时为 null → CHK01 skip
    "external_requests": [],                 // 非本机请求（已 abort）
    "request_count": 2,
    "console_errors": [],                    // console.error + pageerror
    "load_ms": 572,                          // 竖屏趟 load 耗时
    "max_load_sec": 2.0,
    "autoplay_enabled": true,
    "autoplay_timeout_sec": 45,
    "pf_present": true,
    "viewport_shots": { "portrait": {...}, "landscape": {...} },  // has_canvas / variance / 静音事实
    "variance_threshold": 30.0
  }
}
```

- 注意：`facts` 中**不含** autoplay 明细（单独在判定前抽出，不落盘到 facts）——两趟视口与试玩事实的完整采集结构见 [qacore spec](qacore.md)。
- **缺口**：报告尚无正式 JSON Schema（CHK 字段表即本节；schema 化列入 M8 后续）。

## 5. 二维码指向（未实现，规划契约）

- 现状：无任何二维码产出（webui 与编排器均为空壳；`qrcode` 仅在 Python 依赖清单中）。
- 规划契约（冻结为方向，实现前不得偏移）：二维码内容 = **LAN 可达的预览 HTML 的 http URL**
  （必须是局域网 IP，`127.0.0.1` 手机不可扫）；由本机静态伺服该文件；报告页与二维码同源。
- 计时口径（待实现）：墙钟从"spec 修改完成"到"二维码可扫"为止；目标 ≤90s（--quick 口径）。

## 6. 本契约的变更流程

见 [CONTRACTS.md](CONTRACTS.md) §变更流程。本页的每次裁决结果（尤其"待统一"项）必须回填本页并同步
`python/pfcore/__main__.py` 的 argparse 与门禁脚本。
