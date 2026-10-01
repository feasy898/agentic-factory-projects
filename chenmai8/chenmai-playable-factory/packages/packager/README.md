# @pf/packager — M4 打包器（模式 M 全新实现）

配置驱动的多渠道打包器：dist 目录 + PlayableSpec + channel-rules 规则库 → 渠道包
（单 HTML 全内联 / 规则声明 zip）+ `pack-manifest.json` 台账。
定位：**配置驱动**（channel-rules 是规则来源，打包器不改渠道知识）；**宁失败不出超规包**。

## 规格与交付物（双交付）

- **资产 spec**：`docs/specs/packager.md`（自 oracle `docs/assets/specs/packager.md` 字节复制，
  登记于 REUSED-ASSETS.md #25；spec packager.md 是本模块唯一行为权威）。
- **冻结 eval**：`test/run.mjs`——oracle 冻结自验收原样复用（45/46 断言逐字节一致），
  唯一移植点 = P5 预declare：python zipfile 交叉验证 → 系统 bsdtar
  （条目名/入口引用/CRC 语义保持，SKIP 分支删除，断言总数恒定 **46**）。
  本机事实：`where tar` 首位是 Git 的 GNU tar（不能读 zip），故按绝对路径定位
  `C:\Windows\System32\tar.exe`（bsdtar 3.8.4 / libarchive；CRC 损坏经 `-xf` 非零退出拦截，
  已实证单字节翻转 → exit 1 "Damaged Zip archive"）。
- **移植 eval（新增验收面）**：`test/structure.test.mjs`——七渠道（六投放渠道 + preview）
  产物结构断言：目录形状、manifest 字段集/角色序列/packageFiles、zip 条目 = structure 顺序、
  maxBytes=min(规则,override) 对账、CLI totalBytes 对账、退出码契约（未知渠道=1、未知子命令=2）。

## 运行

```bash
node packages/packager/test/run.mjs           # 冻结 46 断言，全过 exit 0
node packages/packager/test/structure.test.mjs
```

## 环境前置（spec §6，冻结契约）

`test/run.mjs` 从自身位置反推仓库根（`REPO_ROOT = <run.mjs>/../../..`），要求：
`<root>/channel-rules/channel-rules.json`、`<root>/specs-eval/golden-match3.json`、
`<root>/packages/packager/{bin.mjs,src/*.mjs,test/…}`、`<root>/package.json + node_modules`
（esbuild 从根解析——本包**零第三方运行时依赖**，esbuild 仅为根工作区 devDependency）。
瞬时失败先查路径假设与 node_modules，再查实现。

## 实现

| 文件 | 职责 |
|---|---|
| `bin.mjs` | CLI（build/channels；退出码 0/1/2 统一裁定） |
| `src/rules.mjs` | 规则库加载/结构校验/单渠道取用/effectiveMaxBytes=min(规则,override) |
| `src/assets.mjs` | dist 引用解析（scheme//根相对/逃逸 快速失败）+ data URI |
| `src/html.mjs` | HTML 内联引擎（§3.3 识别写法精确清单）+ 外链扫描 + MRAID 调用形态正则 |
| `src/zip.mjs` | 自研 zip（deflate 9→store 回退、固定 DOS 时间 2026-01-01、UTF-8 flag、重名拒绝）+ readZip |
| `src/extras.mjs` | package.generated 生成器（tiktok-config / js-sdk-stub） |
| `src/build.mjs` | 打包编排 + manifest 台账 + 红线强制（超规/外链/MRAID/结构→失败） |

## 注意（spec §7 实测坑承袭）

- zip 时间戳固定是"重复构建字节一致"断言的前提，勿改 `zip.mjs` 时间字段。
- HTML 解析是严格正则：dist 产物标签写法须规整，异常即失败是设计行为。
- `type=module` 外链脚本触发告警（合并为经典脚本后 import/export 不可用）。
- `test/fixture/gen-pngs.mjs` 依赖本包 `src/zip.mjs` 的 `crc32` 导出；PNG 为确定性
  纯色生成（重跑同字节），仅改夹具时重跑。
