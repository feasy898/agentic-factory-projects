# @pf/packager —— 配置驱动的多渠道打包器（M4）

把**模板构建产物（dist）**按 **channel-rules 规则库** 打包成各渠道可投放的试玩广告包。

## 包形态（本阶段冻结三渠道）

| 渠道 | 包形态 | 大小上限 | 退出接口 | 产物 |
|---|---|---|---|---|
| applovin | 单 HTML 全内联 | 5MB | `mraid.open(url)`（MRAID 2.0，等 ready 再渲染） | `index.html` |
| meta | 单 HTML 全内联 | 3MB（内部从严） | `FbPlayableAd.onComplete()`，禁 MRAID | `index.html` |
| mintegral | zip（包内 `build.js` + `Template.html`） | 5MB / ≤100 文件 | `mraid.open(url)`（Template.html 内） | `<project>-<locale>.zip` |

规则数值与包结构一律来自 `channel-rules/channel-rules.json`（我们的知识资产，D9 官方工具实测后回填）；
unity / google / tiktok 渠道随后继里程碑按同一结构补入规则库即可，打包器不改代码。

## 用法

```bash
# 在仓库根执行（Node ≥22，依赖根工作区 devDependency 里的 esbuild 做压缩）
node packages/packager/bin.mjs build \
  --spec specs-eval/golden-match3.json \
  --dist packages/packager/test/fixture/match3-dist \
  --channel applovin --locale en --out artifacts
```

- `--dist`：模板构建产物目录，需含 `index.html`；若存在 `<dist>/<locale>/index.html` 则优先按语言产物打包。
- 输出目录契约：`<out>/<project>/<channel>/<locale>/`（`<project>` 取 spec 的 `meta.projectId`）。
- `channels` 子命令列出规则库当前渠道；`--no-minify` 跳过压缩（调试）。
- 附带产出 `pack-manifest.json`（非渠道包内容，只是构建台账：文件清单/字节数/sha256/警告）。

## 打包器强制执行的约束（宁失败不出超规包）

1. **零外链**：产物中出现白名单外 `http(s)://` 即构建失败。白名单 = spec 的
   `flow.endScreen.landingUrl`（CTA 参数允许出现在 JS 中）+ 渠道规则 `allowedUrlWhitelist`。
   CSS/JS/图片全部 base64 内联；`mraid.js` 由渠道容器投放时提供，以相对引用注入，不算外链。
2. **大小**：实际字节数 ≤ min(渠道规则上限, `spec.channels.overrides.<channel>.maxBytes`)（override 只许收紧）。
3. **文件数 / 结构**：单 HTML 渠道恰 1 个包文件；zip 渠道条目结构恰为规则声明的 `build.js` + `Template.html`。
4. **渠道禁用项**：`forbidMraid` 渠道（meta）产物中出现 MRAID 引用即失败（全词启发式检测）。

## 自验收

```bash
node packages/packager/test/run.mjs   # 22 断言：三渠道产物 + 可复现性 + 负向（外链/MRAID/未知渠道必须被拒）
```

测试夹具 `test/fixture/match3-dist/` 是最小 match3 占位工程（index.html + css + js + png，
PNG 由 `test/fixture/gen-pngs.mjs` 纯 Node 生成），仅用于打包器验收，不参与正式模板交付。

## 设计说明

- **零第三方运行时依赖**：HTML 内联引擎为受限正则解析（模板 dist 由我们控制，异常快速失败）；
  zip 为自研读写器（`node:zlib` deflate + CRC32，固定时间戳，同输入字节可复现）。
- esbuild 仅用于 JS/CSS 压缩（根工作区 devDependency，依赖解析走根 `node_modules`，
  与 `packages/spec` 使用根 ajv 同一约定），不进本包 dependencies。
