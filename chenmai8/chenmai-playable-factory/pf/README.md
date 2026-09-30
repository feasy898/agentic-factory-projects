# pf/ — 编排 CLI（M2.3 已落地；assetkit/webui 已接入，见 packages/assetkit 与 webui/）

`validate` / `make` / `serve`：子命令、旗标、退出码、产物树全对齐 oracle pfcore
（规格源 = `docs/specs/orchestrator.md` + `docs/specs/pipeline-contract.md`，字节落位 #40–#41）。
CLI 表面：`node pf/pf.mjs`（`python -m pfcore` 迁移，决策 §2.2）。
保：demo-prebuilt / .demo-serve.json / 8618 顺延 / TCP-only 健康检查 / make 墙钟 + spec mtime
计时口径 / 二维码 LAN IP 段优先级。`build` / `pack` / `rules-check` 维持占位（exit 2，
占位语义本身是契约）。

## 用法

```bash
node pf/pf.mjs validate <spec.json> [more.json ...]     # glob；全过 0 / 有 issue 1
node pf/pf.mjs make --spec specs-eval/golden-match3.json [--locales en,zh]
                     [--channels applovin,meta,mintegral|all] [--out artifacts]
                     [--serve-port 8618] [--serve-host <ip>] [--no-serve] [--no-assetkit]
node pf/pf.mjs serve [--root artifacts/demo-prebuilt] [--port 8618] [--host <ip>]
```

- make：校验 → 模板构建 → 按规则库打包 → 首个 single-html 渠道判官 `--autoplay`
  （质检是裁判：任何 fail → exit 1，不产出二维码与 demo-prebuilt）→ 汇总页双名
  （index.html + summary.html）+ pipeline-report.json + LAN 二维码 + 墙钟双口径
  （make 墙钟 / spec mtime 口径）。
- serve：对既有产物目录起**前台**伺服（Ctrl+C / stdin-EOF 停止，exit 0），启动时现场
  重建汇总页与二维码；目录不存在 → exit 2；端口被占向后顺延（上限 20）。
- 静态伺服分离子进程 = `pf/static-server.mjs`（oracle `python -m http.server` 的宿主移植，
  复用判定三重核实：端口 TCP + PID 映像名 node* + 伺服根一致）。

## 宿主适配登记（语义冻结、宿主移植）

1. 分离静态伺服：`python -m http.server` → `node pf/static-server.mjs`（detached、
   随父退出仍存活；PID 身份核实映像名 python* → node*）。
2. serve 停机：Windows 无法跨进程投递 SIGINT——管道 stdin EOF 作为等价"被正常停止"
   钩子；真实控制台 Ctrl+C（SIGINT）路径不变。
3. 素材管线：assetkit 已落地并默认接线（`pf/src/make-cmd.ts runAssetkitStep`：validate 后
   对 spec 声明素材跑 `packages/assetkit`，产物落 `<out>/assetkit/`，模板构建经
   `PF_ASSET_OPTMAP` 环境变量接线内联优化产物；`--no-assetkit` 逃生口保留）。
4. 本机 Node 22.23.2 的 `fs.cpSync(recursive:true)` 原生硬崩（静默 exit 127，任意目录
   可复现）——demo-prebuilt 兜底复制走 hand-rolled `copyDirRecursive`（pf/src/util.ts）。

## eval（双交付之二；真实执行 exit 0）

```bash
npm run test:pf        # pf/test/pf.test.mjs（13 件：validate 11 件同判/glob/复用/伺服 handler…）
                       # + pf/test/make-serve.test.mjs（2 件：make 端到端 + serve 真实 HTTP）
node scripts/e2e-matrix.mjs            # 48 包全矩阵（4 golden×{en,zh}×6 渠道）0 FAIL
npm run gate:m2        # 批次 2 出口门（批次1回归 + 四模板logic+autoplay + 48包 ≤1200s + 中性名）
```
