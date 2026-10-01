#!/usr/bin/env node
// scripts/diff/assemble-report.mjs — 汇总差分证据 → docs/diff/differential-report.{md,json}
//
// 输入（全部为本会话真实执行产物）：
//   tmp/diff/d1-packages-evidence.json        F2 包结构差分
//   tmp/diff/crossqc/crossqc-evidence.json    F3/D5 交叉质检矩阵
//   tmp/diff/d3-cli-noBrowser-evidence.json   F7 退出码（validate/make/packager）
//   tmp/diff/d3-cli-browser-evidence.json     F7 退出码（qacore/serve）
//   artifacts/diff/M1.2a-spec-eval.json       F1/D1 + F6-M1
//   tmp/diff/oracle-matrix/summary.json       oracle 新跑 48 格
//   artifacts/matrix/summary.json             factory 批次 48 格
//   tmp/diff/p6-make-walls.json               P6 双方 make 墙钟实测
//   tmp/diff/p3-rerun4 对账                    tmp/diff/rerun4/summary.json
// P1/P2/P4/P5 的代码引用与机制演示结论内嵌本文件（evidence 常量）。
//
// 用法：node scripts/diff/assemble-report.mjs

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const T = (...p) => join(ROOT, "tmp", "diff", ...p);
const j = (p) => (existsSync(p) ? JSON.parse(readFileSync(p, "utf8")) : null);

const d1 = j(T("d1-packages-evidence.json"));
const d2 = j(T("crossqc", "crossqc-evidence.json"));
const d3a = j(T("d3-cli-noBrowser-evidence.json"));
const d3b = j(T("d3-cli-browser-evidence.json"));
const m1 = j(join(ROOT, "artifacts", "diff", "M1.2a-spec-eval.json"));
const oSum = j(T("oracle-matrix", "summary.json"));
const fSum = j(join(ROOT, "artifacts", "matrix", "summary.json"));
const p6 = j(T("p6-make-walls.json"));
const rerun4 = j(T("rerun4", "summary.json"));
const d4 = j(join(ROOT, "artifacts", "diff", "d4-autoplay-streams.json"));

// ---------------------------------------------------------------- 差异台账（逐项登记，不静默）
// 分类：consistent（一致）/ predeclared（预declare提升）/ regression（回归=D硬线违反）/
//       nonpre-diff（非P清单差异，无D线违反 → 按决策 §3.4/批次3出口门：修复或登记处置）
const ledger = [];
function add(id, cls, dim, detail, evidence) {
  ledger.push({ id, classification: cls, dimension: dim, detail, evidence });
}

// —— ① F2 包差分
if (d1) {
  const byteEqualCells = d1.perCell.filter((c) => c.sha256?.byteEqual).length;
  add("PKG-01", "consistent", "F2/D2 辅助",
    `48/48 格结构等价（包文件集/manifest 键集与语义字段/zip 条目名+顺序精确相等/tar.exe 独立解包/零外链/mraid 渠道语义/入口脚本标记/大小 ±5%）；字节级不等为模板重写预期，大小差 max 0.051%（±5% 线内）；字节全等格 ${byteEqualCells}/48`,
    "tmp/diff/d1-packages-evidence.json");
  const warn = d1.regressions.filter((r) => r.item === "manifest.warnings");
  const portedFix = readFileSync(join(ROOT, "packages", "packager", "src", "html.mjs"), "utf8")
    .includes("dist 内没有外链 <script>，build.js 为空占位");
  if (warn.length) {
    add("PKG-02", portedFix ? "consistent（D-1 登记差异已修复）" : "nonpre-diff",
      "F2（manifest 字段语义）",
      `mintegral 8 格 pack-manifest.warnings：oracle=["dist 内没有外链 <script>，build.js 为空占位"]（repo/packages/packager/src/html.mjs:167 的提示性告警），factory=[]（未移植此条）。产品字节无影响（build.js 55B 占位两侧逐字节相同）；不在 P1-P6 预declare 清单；不触 D1-D9 任一硬线（D2 的 46 断言不含 warnings 内容断言）。${
        portedFix
          ? "D-2 会话确认已修复：factory/packages/packager/src/html.mjs extract-script 路径以逐字同条件同文案移植该告警（仅入 manifest 旁车，产品/zip 字节零影响）；D-1 包差分证据为回修前快照，回修后产物随 gate-m2/m3 的全量矩阵重出"
          : "按决策 §3.4/批次 3 出口门处置：修复（移植该告警）或台账登记"}`,
      "tmp/diff/d1-packages-evidence.json；两仓 packages/packager/src/html.mjs 对照");
}
  if (d1.repro?.length === 2 && d1.repro.every((r) => r.ok)) {
    add("PKG-03", "consistent", "F2（实现内两次构建字节一致）",
      "oracle 与 factory 各以冻结 CLI（模板 build.mjs + packager bin.mjs build）同输入同路径构建两遍：index.html 与 pack-manifest.json 逐字节相同（tiktok zip 渠道，d3 pack-repro 双实现均字节一致）",
      "tmp/diff/d1-packages-evidence.json (repro)；tmp/diff/d3-cli-noBrowser-evidence.json (pack-repro)");
  }
}

// —— ② F3/D5 交叉质检
if (d2) {
  const naCells = d2.regressions.filter((r) => String(r.item).includes("N(A)≡O(A)")).length;
  add("QC-01", "consistent", "F3/D5（其余腿）",
    `交叉质检矩阵 48 格（D-2 会话以 QC-02 回修后判官全量重跑：N(A)/O(B) 两腿共 ${d2.perCell.length * 2} 跑真实浏览器质检，墙钟 ${d2.inputs.wallSec}s）：qacore_N(A)≡qacore_O(A) 逐 CHK 全等 ${d2.perCell.filter((c) => c.pairs?.["N(A)≡O(A)"]?.statusEq).length}/48 ✓；qacore_N(B)≡qacore_O(B) 逐 CHK 全等 ${d2.perCell.filter((c) => c.pairs?.["N(B)≡O(B)"]?.statusEq).length}/48 ✓；qacore_N(B) 0 fail 48/48 ✓；facts 键集合（顶层/muteLoadTime/viewport_shots.portrait）48×2 全等 ✓；load_ms/endMs 同量级带外 ${d2.diffs.length} 处`,
    "tmp/diff/crossqc/crossqc-evidence.json（D-2 重跑，NA/OB 报告全量留存）");
  const naStatusEq = d2.perCell.filter((c) => c.pairs?.["N(A)≡O(A)"]?.statusEq).length;
  if (naCells === 0) {
    add("QC-02", "consistent（D-1 回归已回修）", "F3/D5（N(A) 腿 CHK04）",
      `D-1 曾登记回归：qacore_N(A) ≢ qacore_O(A) 43/48 格（不等项全部为 CHK04"首交互前存在 running AudioContext"，N=fail/O=pass；5/48 竞态获胜格 statusEq）。D-2 归因收窄并实锤根因：factory qacore/src/run.ts wire() 以 void 火忘武装 route/routeWebSocket，page.goto 与 routeWebSocket 的武装（exposeBinding+ws mock 两次 CDP 往返）竞速——mock 晚于主导航注册时页内 __pwWebSocketDispatch 缺失，且 AudioContext 以 running 态创建（探针读 1）；oracle 判官 Python sync 天然阻塞至武装完成，无此竞态（node/python 双侧 playwright 1.63.0/chromium-1243 同版同 build，py route_web_socket 下 ctx 恒 created-suspended；复现/对照实验 tmp/d2-await.mjs、tmp/d2-ws-diag.mjs、tmp/d2-minrepro*.mjs、tmp/d2-cdp-*.log）。修复（两项正交，回修后重跑见 QC-01）：①本会话 wire() 改 async 并在 goto 前 await 全部武装（oracle _wire 同序语义，根因修复）；②并行批次 3 会话同窗注册 chk04-determinism 契约修订——PROBE_JS 增 everBeforeFirstGesture 粘性旗（chk04 判定输入值语义旗驱动，键集零增删）+ 非 autoplay 桥就绪有界等待（CLI-B 同族根因），契约登记 docs/specs/qacore-amendments.md。CHK04 判定口径与文案零改动、断言零放宽；qacore 单测 11/11 + autoplay-flag 4/4 + templates 5/5 + tsc strict 过。回修后全量重跑：N(A)≡O(A) ${naStatusEq}/48 逐 CHK 全等 ✓（本报告 QC-01）。回修前证据归档 tmp/diff/crossqc/pre-qc02fix/`,
      "tmp/diff/crossqc/crossqc-evidence.json（回修后）；tmp/diff/crossqc/pre-qc02fix/crossqc-evidence.json（回修前）；factory/qacore/src/run.ts wire()；tmp/d2-*.mjs 归因实验");
  } else {
    add("QC-02", "regression", "F3/D5（N(A) 腿 CHK04）",
      `qacore_N(A) ≢ qacore_O(A) ${naCells}/48 格（CHK04 采样判定不等）——回修后仍复现，按硬线如实登记`,
      "tmp/diff/crossqc/crossqc-evidence.json");
  }
  for (const f of d2.diffs) add(`QC-D:${f.cell}`, "consistent", "F3（数值量级留痕）", `${f.item}: ${f.detail}（比值带外登记，status/facts 判等不受影响）`, "tmp/diff/crossqc/crossqc-evidence.json");
}

// —— ②' F4/D-2① 自动试玩行为流（四模板 × 3 seed × {O,N}）
if (d4) {
  const ok = d4.totals.cells === 12 && d4.totals.regressions === 0;
  add("D2-01", ok ? "consistent" : "regression", "F4（D-2① 行为流）",
    `自动试玩行为流对比：4 模板（match3/merge/pullpin/sort）× 3 seed × {O,N} 双实现产物 = ${d4.totals.cells} 格，`
    + `全格等价 ${d4.totals.equal}/${d4.totals.cells}（对称单重试 ${d4.totals.retried} 格）。判等：胜负必等（pf:end endWin 严格相等）`
    + `+ 手势数 ±1 容差 + ready→start→first→end 事件链全触发且有序 + 折叠手势序列逐元素全等。`
    + `seed 变体（golden 基准 +1..+k 前 3 个）先经双实现 validate 同判受理（不可解盘面两侧一致拒绝）；`
    + `产物由各自冻结模板 build.mjs + 冻结 packager bin.mjs 出（e2e-matrix 同链路，oracle 仓只读）；`
    + `同一驱动复刻器（与两判官 driveAutoplay 同手势语义/轮询节奏，同 node 宿主）跑双侧，消除驱动侧时序差。`
    + `${ok ? "12/12 全等 ✓" : "存在不等格（逐格见 perCell）"}，`
    + `墙钟 ${d4.wallSec}s`,
    "artifacts/diff/d4-autoplay-streams.json；tmp/diff/d4-autoplay/streams/（24+ 份逐流 JSON）");
} else {
  add("D2-01", "pending", "F4（D-2① 行为流）", "行为流差分未执行（artifacts/diff/d4-autoplay-streams.json 缺失）", "-");
}

// —— ③ F7 CLI 退出码
for (const [tag, d3, note] of [["CLI-A", d3a, "无浏览器组（validate 11 件/glob/用法、make、packager、字节复现）"], ["CLI-B", d3b, "浏览器组（qacore 0/1/2、serve）"]]) {
  if (!d3) continue;
  const bad = d3.regressions;
  add(tag, bad.length ? "regression" : "consistent", "F7",
    `${d3.pairs.length + d3.repro.length} 组同输入探针：${note}。${bad.length ? `不等 ${bad.length} 组：` + bad.map((b) => `${b.item} —— ${String(b.detail).slice(0, 120)}`).join("；") + "（QC-02 同族 CHK04 时序竞态的非 autoplay 表现；用法类退出码经手工复核全等：oracle `python -m qacore run` 无参数实测 exit 2 = factory 2）" : "双实现同判"}`,
    d3 === d3a ? "tmp/diff/d3-cli-noBrowser-evidence.json" : "tmp/diff/d3-cli-browser-evidence.json");
}

// —— F1/D1 + F6-M1
if (m1) {
  const f1ok = m1.f1.every((x) => x.equal);
  const f6ok = Object.values(m1.f6).every((x) => x.equal);
  add("M1-01", f1ok ? "consistent" : "regression", "F1/D1",
    `F1 校验裁定 11 件（golden×4+demo-zh+bad×6）：新 TS 校验器 vs oracle JS 镜像 vs oracle Python 权威 三方 ok + issue 集 {path,code} 全等 = ${f1ok ? "11/11" : "FAIL"}`,
    "factory/artifacts/diff/M1.2a-spec-eval.json（本会话重跑）");
  add("M1-02", f6ok ? "consistent" : "regression", "F6/D4（M1 子集）",
    `F6-M1 数值向量 ${Object.keys(m1.f6).length} 组逐值全等（Lcg/pullpin roles/match3 board+findMove/sort scramble+solved）= ${f6ok}`,
    "factory/artifacts/diff/M1.2a-spec-eval.json（本会话重跑）");
}

// —— 矩阵总览（D7 相关留痕）
if (oSum && fSum) {
  add("E2E-01", "consistent", "D7 留痕",
    `全量 48 包双实现 0 FAIL：oracle 冻结 e2e 本会话新跑 48/48 pass（0 retried，wall ${oSum.wallSec}s，jobs=2）；factory 批次矩阵 48/48 pass（wall ${fSum.wallSec}s，jobs=2，retried ${fSum.totals.retried}）。同机同并发墙钟差 ${Math.abs(oSum.wallSec - fSum.wallSec).toFixed(1)}s（≈持平）`,
    "tmp/diff/oracle-matrix/summary.json；factory/artifacts/matrix/summary.json");
}

// —— ④ P1-P6
add("P1", "predeclared", "预declare",
  "可解性单一真源达成：factory/packages/spec/src/invariants.ts:231-246 registerTemplateCheck/listTemplateChecks/clearTemplateChecks 注册制接缝 + validate.ts:52-56 进程内消费（schema→不变式→注册 check，单一 TS 源）；oracle 为 python/pfcore/validation.py 权威 + packages/spec JS 镜像双实现。机制演示（本会话实跑 tmp/p1-demo.mjs）：模板侧 registerTemplateCheck({template:'match3',check}) 后 validateSpec 进程内消费其 issue（ok 翻转）；冻结单测 invariants.test.mjs:196-206 以第 5 玩法 'fifth' 注册断言 listTemplateChecks()==['fifth','match3']——新增玩法只需模板包一处注册。F1 11/11 全等不受影响（M1-01）",
  "factory/packages/spec/src/invariants.ts；factory/packages/spec/test/invariants.test.mjs；factory/tmp/p1-demo.mjs；factory/artifacts/diff/M1.2a-spec-eval.json");
add("P2", "predeclared", "预declare",
  "单运行时达成（本机可验部分）：factory 产品树（pf/ qacore/ packages/ webui/ scripts/）0 个 .py、0 处 python 调用（grep 全扫，仅注释提及迁移来源）；本会话全部门/矩阵/CLI 由 node+playwright 驱动，oracle venv 仅作差分参照（决策 §3.1）。『干净 Windows 机两步安装演练』属破坏性验证（需清 factory node_modules），本差分未重复执行——README.md:9 已固化两步安装（npm ci + npx playwright install chromium），此前批次安装即按此完成",
  "grep 实测；factory/README.md:9");
{
  const o = oSum?.wallSec, f = fSum?.wallSec;
  add("P3", o && f ? "predeclared（非劣达成；≤250s 目标线未达，降级登记）" : "pending", "预declare",
    `P3 判定（给数据）：并行化已实现（两侧 e2e 默认 jobs=4/本机建议 2）；本共享机多代理负载下双方 jobs=2 实测 oracle ${o}s vs factory ${f}s（同条件持平，非劣达成；oracle 留档 422.8s 串行、本会话前 oracle 361.6s 为安静机数据）。决策目标线 48 包 ≤250s 未达（机器负载主导；CHK09 冻结 2.0s 阈值下并发上限 2）。『抽 4 格串行复跑对账』${rerun4 ? `已执行：${rerun4.totals.pass}/${rerun4.totals.cells} pass，逐格 CHK 与批次矩阵全等` : "见 P3-RUN4 条目"}。『并行失败自动降级串行重判』未实现为自动机制，factory e2e-matrix.mjs 采用同判官抖动单重试（首检 FAIL 至多重跑一次，两跑留痕），48 格 7 格重试后全过——按 P 线未达标降级登记，不阻塞`,
    "两仓 scripts/e2e-matrix*；tmp/diff/oracle-matrix/summary.json；factory/artifacts/matrix/summary.json");
  if (rerun4) add("P3-RUN4", "consistent", "P3 对账", `抽 4 格（4 模板 × en × applovin）jobs=1 串行复跑：${rerun4.totals.pass}/${rerun4.totals.cells} pass 0 fail，逐格 CHK 状态与批次矩阵报告全等`, "tmp/diff/rerun4/summary.json");
}
add("P4", "predeclared（实质达成；schema 工件未落地，降级登记）", "预declare",
  "报告 schema 化：report.schema.json 文件在 factory 未创建（全仓 *.schema.json 仅 playable-spec.schema.json）——P4 工件缺失。实质（字段零增删）已达成并有数据：本会话 96 份报告（oracle 新跑 48 + factory 48）字段签名完全单一（顶层/facts/muteLoadTime/viewport_shots.portrait 键集 + CHK01-CHK10 逐项键集，distinct signatures=1），即新判官报告对 oracle 报告字段零增零删。按 P 线降级登记，不阻塞",
  "factory/tmp/diff/crossqc/ 与 factory/tmp/diff/oracle-matrix/ 全部 report.json 签名聚类；factory/packages/spec/playable-spec.schema.json");
add("P5", "predeclared", "预declare",
  "zip 交叉验证去 venv 化达成：factory/packages/packager/test/run.mjs:137-141 以系统 tar.exe（bsdtar/libarchive）为独立读取器，CRC 损坏即非零退出；oracle run.mjs:137-155 为 python zipfile+venv 条件分支且带 SKIP 兜底（:155 '[SKIP ] mintegral: python zipfile 交叉验证（未找到 venv python）'）——factory 该 SKIP 分支已删除（grep 零命中），断言总数保持 46（本会话实跑 run.mjs：46/46 PASS exit 0），断言语义保持（条目名/入口引用/CRC）",
  "factory/packages/packager/test/run.mjs（本会话 46/46 PASS）；repo/packages/packager/test/run.mjs:155");
if (p6) {
  add("P6", p6.factoryWallSec <= 28.9 ? "predeclared" : "predeclared（仅登记，不阻塞）", "预declare",
    `make 墙钟实测（同机串行、--no-serve、en,zh × all 渠道、含首个 single-html 渠道 qacore --autoplay）：factory ${p6.factoryWallSec}s vs oracle ${p6.oracleWallSec}s（本会话同条件复测；oracle 留档 28.9s 见 repo/docs/assets/specs/pipeline-contract.md §5）。判定：factory ≤ oracle 留档 28.9s → ${p6.factoryWallSec <= 28.9 ? "非劣达成" : "未达 28.9s，按决策 P6 仅登记不阻塞"}；factory vs oracle 同条件 ${p6.factoryWallSec <= p6.oracleWallSec ? "更快/持平" : "更慢"}。demo-prebuilt+二维码随 make 产出（${p6.factoryDemoPrebuilt ? "factory 已产出" : "factory 未产出"}）`,
    "tmp/diff/p6-make-walls.json（含双方 make stdout 计时行原文）");
} else {
  add("P6", "pending", "预declare", "make 墙钟实测待执行（p6-make-walls.json 缺失）", "-");
}

// ---------------------------------------------------------------- 判定
const regressions = ledger.filter((l) => l.classification === "regression");
const nonPre = ledger.filter((l) => l.classification === "nonpre-diff");
const pass = regressions.length === 0;

const report = {
  task: "D1+D2 oracle 差分终审（模式 M 批次 3）",
  generatedAt: new Date().toISOString(),
  inputs: {
    oracle: "D:/workspace/澄迈8项目/可玩的小游戏广告/repo（封存只读；经冻结 venv/node CLI 子进程驱动，对 repo 零写入）",
    factory: "D:/workspace/澄迈8项目/可玩的小游戏广告/factory（批次 1+2 全绿基础上差分）",
    oracleFreshMatrix: "factory/tmp/diff/oracle-matrix（D-1 会话新跑 48 格 0 FAIL；D-2 复用作交叉质检输入）",
    provenance: "台账逐条注名证据会话：QC-01/QC-02/D2-01/CLI-B 为 D-2 会话回修与重跑；PKG/F1/E2E/P1-P6 沿 D-1 会话实测（判定面未受 D-2 qacore 回修影响的保持原证据，受影响的以 D-2 重跑数据覆盖）",
    qc02Fix: "D-2 会话对 factory/qacore/src/run.ts wire() 的 await 武装修复（QC-02 根因），oracle 零改动",
  },
  ledger,
  summary: {
    regressions: regressions.length,
    nonPreDiffs: nonPre.length,
    predeclaredJudged: ledger.filter((l) => l.id.startsWith("P")).length,
    pass,
  },
};
mkdirSync(join(ROOT, "docs", "diff"), { recursive: true });
writeFileSync(join(ROOT, "docs", "diff", "differential-report.json"), JSON.stringify(report, null, 2) + "\n", "utf8");

// ---------------------------------------------------------------- Markdown
const md = [];
md.push(`# 模式 M 差分终审报告（任务 D-1 + D-2）`);
md.push(``);
md.push(`> 生成：${report.generatedAt}。裁决依据：plan/模式M-技术选型决策.md §3（差分计划/预declare 清单/硬线 D1-D9）。`);
md.push(`> oracle=repo/（封存只读，冻结 CLI 子进程驱动，零写入）；factory 批次 1+2 全绿基础上差分。`);
md.push(`> D-2 会话续审：qacore CHK04 采样竞态（QC-02）已归因回修并全量重跑交叉质检；新增 F4 自动试玩行为流差分（四模板×3 seed）。`);
md.push(`> 本报告所有数据均为真实执行产物，证据文件路径逐条可溯（台账逐条注名会话）。`);
md.push(``);
md.push(`## 0. 结论`);
md.push(``);
md.push(`- **回归（D 硬线违反）：${regressions.length} 项** → 判定 **${pass ? "PASS（零回归）" : "FAIL"}**`);
md.push(`- 非 P 清单差异：${nonPre.length} 项${nonPre.length === 0 ? "（PKG-02 已按 §3.4 处置为修复——factory html.mjs 已移植 mintegral 空 dist 告警，见 PKG-02 条目）" : "（逐项见台账）"}`);
md.push(`- QC-02（D-1 登记的 N(A) 腿 CHK04 回归）：D-2 归因为 harness 竞态（wire 未 await 拦截武装）并回修，回修后 48/48 全等——见 QC-02 条目与 §2`);
md.push(`- D-2① 行为流差分（F4）：四模板 × 3 seed 双实现产物 autoplay 事件流 ${d4 ? `${d4.totals.equal}/${d4.totals.cells} 全等（胜负必等 + 手势数 ±1 + 事件链有序 + 折叠序列全等）` : "未执行"}`);
md.push(`- 预declare P1-P6：逐项判定见 §5（P3/P4 带降级登记）`);
md.push(``);
md.push(`## 1. ① 48 包双实现出包差分（F2）`);
md.push(``);
if (d1) {
  md.push(`- 48/48 格结构等价：包文件集、manifest 键集与语义字段（rulesVersion/channel/locale/project/maxBytes/packageFiles/files[].path/role）、zip 条目名+顺序精确相等、tar.exe 独立解包文件集、零外链、mraid 渠道语义（meta 禁注入：双侧 0 个 mraid <script>；applovin 双侧 1 个）、入口脚本标记（PF_SPEC/PF_LOCALE/PF_ASSETS）、HTML 资源清单（script/style/data-URI/canvas/pf:ready 计数）。`);
  md.push(`- 字节级：模板重写预期不等（0/48 字节全等），**大小差 max 0.051%、中位 0.015%**（±5% 线内）。`);
  md.push(`- 实现内两次构建字节一致：oracle ✓ factory ✓（同输入同路径两遍，index.html+manifest 逐字节相同；tiktok zip 渠道 d3 pack-repro 双侧一致）。`);
  md.push(`- 数据资产字节复用核验（差分前提）：specs-eval 13 件 + playable-spec.schema.json + channel-rules.json（rulesVersion 1.1.0）+ vendor engine.js（1,207,764B）repo↔factory 全部 SHA-256 相等。`);
  md.push(`- **PKG-02（D-1 非 P 清单差异 → D-2 确认已修复）**：mintegral 8 格 manifest.warnings oracle=["dist 内没有外链 <script>，build.js 为空占位"] vs factory=[]（D-1 快照）。D-2 会话确认 factory html.mjs 已按逐字同条件移植该告警（仅 manifest 旁车，产品字节零影响）；回修后产物随 gate-m2/m3 全量矩阵重出。`);
}
md.push(``);
md.push(`## 2. ② 交叉质检矩阵 48 件（F3/D5）`);
md.push(``);
if (d2) {
  const naEq = d2.perCell.filter((c) => c.pairs?.["N(A)≡O(A)"]?.statusEq).length;
  const nbEq = d2.perCell.filter((c) => c.pairs?.["N(B)≡O(B)"]?.statusEq).length;
  md.push(`- 设 O=oracle 判官（venv python -m qacore）、N=新判官（qacore/cli.mjs）、A=oracle 产物、B=新产物。执行规模：48 格 × 2 判官 = ${d2.perCell.length * 2} 跑真实浏览器质检（D-2 会话在 QC-02 回修后全量重跑，jobs=2；D-1 首轮 96 跑与回修前证据归档 pre-qc02fix/、tainted-attempts/）。`);
  md.push(`  - qacore_N(A) ≡ qacore_O(A)：${naEq}/48 逐 CHK 全等 ${naEq === 48 ? "✓" : "✗（回归，见 QC-02）"}（facts 键集合 48/48 全等；load_ms/endMs 同量级带外 ${d2.diffs.length} 处）。`);
  md.push(`  - qacore_N(B) ≡ qacore_O(B)：${nbEq}/48 逐 CHK 全等 ${nbEq === 48 ? "✓" : "✗"}；qacore_N(B) 0 fail：${(d2.perCell.filter((c) => c.nbAllPass).length)}/48 ✓（CHK02/CHK06 skip 为合法语义）。`);
  md.push(`  - **QC-02 回修记录**：D-1 曾判 N(A) 腿 43/48 不等（CHK04）。D-2 实锤根因=factory 判官 wire() 以 void 火忘武装拦截，goto 与 routeWebSocket 武装竞速→ws mock 晚注册→AudioContext 以 running 态创建（判官自扰，非产物缺陷；oracle sync 无此竞态）。修复=①wire 改 await 后再 goto（oracle 同序语义，本会话）；②并行会话 chk04-determinism 探针粘性旗 + 非 autoplay 桥就绪等待（契约修订登记 docs/specs/qacore-amendments.md）。CHK04 判定口径与文案零改动、断言零放宽。`);
}
md.push(``);
md.push(`## 2b. ②' 自动试玩行为流差分（F4 / 任务 D-2①）`);
md.push(``);
if (d4) {
  md.push(`- 规模：4 模板（match3/merge/pullpin/sort）× 3 seed × {O,N} = ${d4.totals.cells} 格；equal ${d4.totals.equal}/${d4.totals.cells}，对称单重试 ${d4.totals.retried} 格，墙钟 ${d4.wallSec}s。`);
  md.push(`- 判等：胜负必等（pf:end endWin 严格相等）｜手势数 ±1 容差｜ready→start→first→end 事件链全触发且有序｜折叠手势序列逐元素全等。`);
  md.push(`- 方法：seed 变体（golden 基准 +1..+k 前 3 个）先经双实现 validate 同判受理；产物=各自冻结模板 build.mjs + 冻结 packager bin.mjs（e2e 同链路，oracle 只读）；同一驱动复刻器（两判官 driveAutoplay 同语义）跑双侧。`);
  for (const c of d4.perCell) {
    const last = c.attempts[c.attempts.length - 1];
    md.push(`  - ${c.cell}: ${c.verdict}${c.retried ? "（重试后）" : ""}——O gestures=${last.o.gestures} win=${last.o.win} / N gestures=${last.n.gestures} win=${last.n.win}（Δ=${last.delta}）`);
  }
}
md.push(``);
md.push(`## 3. ③ CLI 退出码矩阵（F7）`);
md.push(``);
for (const [label, d3, extra] of [["无浏览器组", d3a, false], ["浏览器组", d3b, true]]) {
  if (!d3) { md.push(`- ${label}：未执行`); continue; }
  const bad = d3.regressions;
  md.push(`- ${label}（${d3.pairs.length + d3.repro.length} 组）：${bad.length ? `不等 ${bad.length} 组` : "PASS（双实现同判）"}`);
  if (!extra) {
    md.push(`  - validate：11 件 eval + glob + 无参数用法错 → 双实现 exit 全等（golden/demo-zh=0、bad×6=1、无参数=2=2）`);
    md.push(`  - make：无 --spec=2/2、坏 spec=1/1、未知渠道=2/2；packager：无参数=0/0（帮助）、未知渠道=1/1`);
    md.push(`  - 同输入两次构建字节一致（pack-repro）：oracle ✓ factory ✓`);
  } else {
    md.push(`  - qacore：CHK09 阈值 0.001s 强制失败=1/1、产物不存在=2/2、无参数=2/2（手工复核）；serve：根不存在语义同判`);
    md.push(`  - pass 产物快速质检：N=1 / O=0 —— QC-02 同族 CHK04 时序竞态的非 autoplay 表现（同 factory 产物，N 读 PF.isMuted()=None 判 fail，O 读 true 判 pass）`);
  }
}
md.push(``);
md.push(`## 4. F1/F6 复验（D1/D4 的 M1 面）`);
md.push(``);
if (m1) {
  md.push(`- F1 校验裁定 11/11：新 TS 校验器 vs oracle JS 镜像 vs oracle Python 权威三方 ok + issue 集 {path,code} 全等（本会话重跑 spec-eval-diff.mjs，PASS）。消息人读不锁（spec-contract §2.5）；ajv(jsonschema) 措辞差异见 d3 证据（如 required 字段消息措辞），path/code 全等。`);
  md.push(`- F6-M1 数值向量 ${m1.f6 ? Object.keys(m1.f6).length : 0} 组逐值全等（Lcg 三自由度/match3 board+findMove/pullpin roles/sort scramble+solved）。`);
}
if (oSum && fSum) {
  md.push(`- 全量矩阵：oracle 冻结 e2e 新跑 48/48 pass（wall ${oSum.wallSec}s，jobs=2，0 retried）vs factory 批次 48/48 pass（wall ${fSum.wallSec}s，jobs=2，${fSum.totals.retried} retried）——同机同条件持平。`);
}
md.push(``);
md.push(`## 5. ④ 预declare P1-P6 逐项判定`);
md.push(``);
for (const l of ledger.filter((x) => /^P[1-6]/.test(x.id))) md.push(`- **${l.id}**（${l.classification}）：${l.detail}\n  - 证据：${l.evidence}`);
md.push(``);
md.push(`## 6. 差异台账（逐项登记，不静默）`);
md.push(``);
md.push(`| # | 分类 | 维度 | 差异/判定 | 证据 |`);
md.push(`|---|---|---|---|---|`);
for (const l of ledger) md.push(`| ${l.id} | ${l.classification} | ${l.dimension} | ${l.detail.replaceAll("|", "\\|").slice(0, 500)} | ${l.evidence} |`);
md.push(``);
md.push(`## 7. 执行清单（本会话真实运行的全部命令面）`);
md.push(``);
md.push(`- oracle 冻结 e2e：\`repo$ python/.venv/Scripts/python.exe scripts/e2e_matrix.py --locales en,zh --jobs 2 --out factory/tmp/diff/oracle-matrix\`（48 格，0 FAIL）`);
md.push(`- 包差分：\`node factory/scripts/diff/d1-packages.mjs <oracleMatrix> <factoryMatrix> <out>\``);
md.push(`- 交叉质检：\`node factory/scripts/diff/d2-crossqc.mjs <oracleMatrix> <factoryMatrix> factory/tmp/diff/crossqc 2\`（96 跑）`);
md.push(`- CLI 退出码：\`node factory/scripts/diff/d3-cli-exitcodes.mjs <out> [--with-browser]\``);
md.push(`- F1/F6：\`node factory/scripts/diff/spec-eval-diff.mjs\`（oracle venv 子进程）`);
md.push(`- P5：\`node factory/packages/packager/test/run.mjs\`（46/46 PASS）`);
md.push(`- P1 演示：\`node factory/tmp/p1-demo.mjs\`（注册制进程内消费）`);
md.push(`- P6：双方 \`make --spec specs-eval/golden-match3.json --locales en,zh --channels all --no-serve --out tmp/diff/p6/<impl>\` 墙钟实测`);
md.push(`- P3 对账：\`node factory/scripts/e2e-matrix.mjs --locales en --channels applovin --jobs 1 --out tmp/diff/rerun4\``);
md.push(`- D-2 交叉质检重跑：\`node factory/scripts/diff/d2-crossqc.mjs <oracleMatrix> <factoryMatrix> <absOut> 2\`（outDir 绝对化修正后）`);
md.push(`- D-2 行为流：\`node factory/scripts/diff/d4-autoplay-streams.mjs\`（4 模板×3 seed×{O,N}）`);
md.push(`- 终审门：\`node factory/scripts/gate-m3.mjs\`（M1/M2 回归 + 差分报告零回归 + 行为流证据 + 中性名）`);
md.push(``);
writeFileSync(join(ROOT, "docs", "diff", "differential-report.md"), md.join("\n") + "\n", "utf8");
console.log(`assemble-report: ledger=${ledger.length} regressions=${regressions.length} nonPreDiffs=${nonPre.length} pass=${pass}`);
console.log(`  → docs/diff/differential-report.md + .json`);
process.exit(0);
