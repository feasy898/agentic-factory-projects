// pf/test/make-serve.test.mjs — pf 编排 CLI eval（真实浏览器链路）：
//   1) pf make 端到端（真实构建→打包→判官 --autoplay→兜底目录→二维码），产物树/报告/
//      汇总页零外链/二维码 PNG 魔数逐项断言（--no-serve 保持 eval 无残留进程）；
//   2) pf serve 前台伺服（真实 HTTP 拉取：汇总页/二维码/预览/报告链接逐个 200 + 零外链；
//      停止后 exit 0——契约 §5.1）。
// 先清后跑，产物落 tmp/（不污染 artifacts/）。运行：node --test pf/test/make-serve.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");
const PF = join(ROOT, "pf", "pf.mjs");
const TMP = join(ROOT, "tmp", "pf-eval-make");
const OUT = join(TMP, "out");

function pfSync(args, timeoutMs = 240_000) {
  const proc = spawnSync(process.execPath, [PF, ...args], {
    cwd: ROOT, encoding: "utf8", timeout: timeoutMs, windowsHide: true,
    maxBuffer: 64 * 1024 * 1024,
  });
  return { code: proc.status, stdout: proc.stdout ?? "", stderr: proc.stderr ?? "" };
}

test("pf make 端到端：构建→打包(preview 渠道)→判官 --autoplay→demo-prebuilt（质检是裁判）", () => {
  rmSync(TMP, { recursive: true, force: true });
  mkdirSync(TMP, { recursive: true });
  const r = pfSync(["make", "--spec", "specs-eval/golden-match3.json",
    "--channels", "preview", "--out", OUT, "--no-serve"]);
  assert.equal(r.code, 0, `stdout 尾部=${r.stdout.split(/\r?\n/).slice(-6).join(" | ")}\nstderr=${r.stderr}`);

  // 产物树（pipeline-contract §3.4 形态）
  const project = "golden-match3";
  const preview = join(OUT, "preview", `${project}-en.html`);
  assert.ok(existsSync(preview), "preview/<project>-<locale>.html 在位");
  assert.ok(existsSync(join(OUT, project, "dist", "en", "index.html")), "打包器输入形态 dist/<locale>/index.html 在位");
  const pkgDir = join(OUT, project, "preview", "en");
  assert.ok(existsSync(join(pkgDir, "index.html")), "渠道包 index.html 在位");
  assert.ok(existsSync(join(pkgDir, "pack-manifest.json")), "pack-manifest.json 旁车在位");
  assert.ok(existsSync(join(pkgDir, "index.report.json")), "判官报告在渠道目录（质检是裁判）");
  assert.ok(existsSync(join(pkgDir, "index.report.png")), "竖屏截图在位");
  assert.ok(existsSync(join(pkgDir, "index.report-landscape.png")), "横屏截图在位");

  // demo-prebuilt 兜底
  const demo = join(OUT, "demo-prebuilt");
  for (const f of ["index.html", "summary.html", "pipeline-report.json", "qr.png",
    `preview/${project}-en.html`, "channels/preview/en/index.html", "channels/preview/en/index.report.json"]) {
    assert.ok(existsSync(join(demo, ...f.split("/"))), `demo-prebuilt/${f} 在位`);
  }
  assert.ok(existsSync(join(OUT, ".demo-serve.json")) === false, "--no-serve 不写伺服状态");

  // 报告语义：0 fail + 自动试玩事实（pf:end ≤ 45s、win=true）
  const report = JSON.parse(readFileSync(join(pkgDir, "index.report.json"), "utf8"));
  assert.equal(report.checks.filter((c) => c.status === "fail").length, 0,
    JSON.stringify(report.checks.filter((c) => c.status !== "pass")));
  assert.equal(report.autoplay, true);
  assert.ok(report.pf.endWin === true, "自动试玩必胜（pf:end win=true）");
  assert.ok(typeof report.pf.endMs === "number" && report.pf.endMs <= 45_000, "pf:end ≤ 45s 预算");
  assert.ok(report.facts.pf_present === true);

  // pipeline-report 计时口径（make 墙钟 + spec mtime 口径，契约 §5）
  const pipeline = JSON.parse(readFileSync(join(demo, "pipeline-report.json"), "utf8"));
  assert.equal(pipeline.command, "pf make");
  assert.ok(pipeline.timings.makeWallSec > 0 && pipeline.timings.makeWallSec <= 90,
    `make 墙钟 ${pipeline.timings.makeWallSec}s（演示口径 ≤90s）`);
  assert.ok(pipeline.timings.specModifiedToQrScannableSec >= 0);
  assert.deepEqual(pipeline.channels, ["preview"]);
  assert.equal(pipeline.qa.channel, "preview");

  // 汇总页：双名同内容 + 零外链（全部 href 相对——契约"本页与二维码同源，零外链"）
  const indexHtml = readFileSync(join(demo, "index.html"), "utf8");
  const summaryHtml = readFileSync(join(demo, "summary.html"), "utf8");
  assert.equal(indexHtml, summaryHtml, "index.html 与 summary.html 同内容（双名落盘）");
  const hrefs = [...indexHtml.matchAll(/href="([^"]*)"/g)].map((m) => m[1]);
  assert.ok(hrefs.length > 0, "汇总页有链接");
  for (const h of hrefs) {
    assert.ok(!/^(https?:)?\/\//i.test(h) && !/^[a-z]+:/i.test(h), `href 零外链：${h}`);
  }
  const srcs = [...indexHtml.matchAll(/src="([^"]*)"/g)].map((m) => m[1]);
  for (const s of srcs) assert.ok(!/^https?:/i.test(s), `src 零外链：${s}`);

  // 二维码：真 PNG（魔数 + 非空体量；内容规则由 make 内部生成 LAN URL——文本在汇总页可核）
  const qr = readFileSync(join(demo, "qr.png"));
  assert.deepEqual([...qr.subarray(0, 8)], [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a], "qr.png 是 PNG");
  assert.ok(qr.length > 200, `qr.png 体量 ${qr.length}B`);
  assert.match(indexHtml, /http:\/\/(?!127\.0\.0\.1)\d+\.\d+\.\d+\.\d+:\d+\/preview\//,
    "二维码内容 = LAN IP 预览 URL（汇总页可见，非 127.0.0.1）");

  // 质检不过就没有二维码/兜底（负向：直接人为构造质检必败的 make 不可廉价构造——
  // 负向由 gate-m2 的全矩阵 + MUT 层覆盖；此处断言正向红线：质检 0 fail 才有兜底目录）。
  assert.ok(existsSync(demo), "质检全过 → 兜底目录产出（宁绿不假绿的另一半由判官 0 fail 保证）");
});

test("pf serve：前台伺服 demo-prebuilt——逐链接 200 + 零外链 + 停止后 exit 0（契约 §5.1）", async () => {
  const demo = join(OUT, "demo-prebuilt");
  assert.ok(existsSync(demo), "前置：make eval 已产出 demo-prebuilt");
  // 现场重建两件东西：index.html + qr.png（serve 启动时覆盖写）
  const beforeIndex = statSync(join(demo, "index.html")).mtimeMs;

  const port = 8723;
  const child = spawn(process.execPath, [PF, "serve", "--root", demo, "--port", String(port)], {
    cwd: ROOT, windowsHide: true,
  });
  let serveOut = "";
  child.stdout.on("data", (d) => { serveOut += d; });
  child.stderr.on("data", (d) => { serveOut += d; });

  const { portListening } = await import("../src/util.ts");
  let up = false;
  for (let i = 0; i < 60; i++) {
    if (await portListening(port)) { up = true; break; }
    await new Promise((res) => setTimeout(res, 250));
  }
  try {
    assert.ok(up, `伺服端口 ${port} 在 15s 内进入监听\n${serveOut}`);
    // serve 启动即重建汇总页（现场解析报告），mtime 前移
    assert.ok(statSync(join(demo, "index.html")).mtimeMs >= beforeIndex - 1, "index.html 现场重建");
    assert.ok(existsSync(join(demo, "qr.png")), "qr.png 在位");

    const base = `http://127.0.0.1:${port}`;
    const get = async (p) => fetch(base + p);
    const page = await get("/");
    assert.equal(page.status, 200);
    const html = await page.text();
    assert.match(html, /演示伺服/, "伺服版汇总页（现场重建，非 make 版残留）");
    assert.match(html, /渠道包下载/, "渠道包下载表在位");
    assert.match(html, /质检报告 · 渠道 preview/, "质检报告区块现场解析在位");

    // 页面引用逐个 200：预览/渠道包/清单/报告/双视口截图/二维码
    const links = [...html.matchAll(/href="([^"]+)"/g)].map((m) => m[1])
      .filter((h) => !h.startsWith("#"));
    for (const h of links) {
      assert.ok(!/^(https?:)?\/\//i.test(h), `零外链：${h}`);
      const res = await get(`/${h}`);
      assert.equal(res.status, 200, `链接 200：${h}`);
    }
    assert.ok(links.some((h) => h.includes("index.report.json")), "报告链接在页面引用集中");
    const qrRes = await get("/qr.png");
    assert.equal(qrRes.status, 200);
    assert.deepEqual([...new Uint8Array((await qrRes.arrayBuffer()).slice(0, 8))],
      [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a], "伺服版二维码 PNG");

    // SERVE 结构化行（供现场脚本消费，oracle 同款日志）
    assert.match(serveOut, new RegExp(`SERVE port=${port} landing_url=`), "SERVE 行在位");
  } finally {
    // 前台伺服：优雅停止（Windows 宿主适配：管道 stdin EOF = 被正常停止，SIGINT 语义等价）
    child.stdin?.end();
    const code = await new Promise((res) => {
      const t = setTimeout(() => res(null), 15_000);
      child.on("exit", (c) => { clearTimeout(t); res(c); });
    });
    assert.equal(code, 0, `serve 被正常停止 → exit 0（实际 ${code}）\n${serveOut.slice(-400)}`);
    let released = false;
    for (let i = 0; i < 20; i++) {
      if (!(await portListening(port))) { released = true; break; }
      await new Promise((res) => setTimeout(res, 250));
    }
    assert.ok(released, "停止后端口即释放");
  }
});
