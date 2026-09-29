/**
 * qacore run 的实现（oracle cli.py 语义移植）：本地伺服 → 无头打开
 * （横竖屏双仿真）→ 记录请求 →（--autoplay 时经 __PF_QC__ 自动试玩）→
 * 截屏 → 写报告。采集结构（facts）由本模块组装，PASS/FAIL 判定统一在
 * checks.evaluate。报告 JSON 全字段单一来源 = pipeline-contract §4。
 *
 * 魔法数字表（qacore spec §3，冻结）：竖屏 390×844 / 横屏 844×390 /
 * isMobile+DPR2 / 导航超时 15000ms / 首帧缓冲 400ms / 空白方差阈值 30.0 /
 * 探针每页面注入一次 / 加载计时只取竖屏趟。
 */
import { readFileSync, statSync, writeFileSync, mkdirSync } from "node:fs";
import { basename, dirname, isAbsolute, relative, resolve } from "node:path";

import { chromium } from "playwright";
import type { ConsoleMessage, Page, Request, Route } from "playwright";

import { driveAutoplay, hasPf, mediaSample, pfMuted, probeInstalled, PROBE_JS,
         qcAssets, qcTextStates, qcTexts, rtcCount, audioRunning } from "./autoplay.ts";
import { evaluate } from "./checks.ts";
import { ev } from "./ev.ts";
import { grayscaleVariance } from "./pngvar.ts";
import { ArtifactServer } from "./server.ts";
import { loadChannelLimit, loadChannelMuteRequired, loadChannelRuntimeScripts } from "./rules.ts";

export interface RunOptions {
  artifact: string;
  channel: string;
  out?: string;
  port: number;
  maxLoadSec: number;
  autoplay: boolean;
  autoplayTimeout: number;
  requireTexts: string[];
  requireSprites: string[];
}

export const VIEWPORT_PORTRAIT = { width: 390, height: 844 } as const;
export const VIEWPORT_LANDSCAPE = { width: 844, height: 390 } as const;
const GOTO_TIMEOUT_MS = 15_000;
const SETTLE_MS = 400;            // load 之后留给首帧渲染的缓冲
export const VARIANCE_THRESHOLD = 30.0; // 64×64 灰度方差低于此值视为空白画面

// 渠道容器运行时脚本的本地桩：投放时由容器提供（如 mraid.js），本地质检时
// 容器不在场。桩不定义任何全局（与真实缺失一致），只消掉 404。
export const CONTAINER_STUB_JS =
  "/* pf-qacore: 渠道容器运行时脚本本地桩（投放时由渠道容器提供，非包体内容） */\n";

interface RequestEntry {
  url: string;
  method: string;
  resource_type: string;
  status: number | null;
  blocked: boolean;
  failed: boolean;
  stub?: boolean;
}

interface PassFacts {
  [k: string]: unknown;
}

/** Python rep(文本) 的人读裁定行（stdout 不锁字节，仅对齐人读格式）。 */
function isLocalFile(p: string): boolean {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
}

/** pathlib.Path.with_suffix 同义：换掉最后一段后缀（stem + 新后缀）。 */
function withSuffix(p: string, sfx: string): string {
  const base = basename(p);
  const dot = base.lastIndexOf(".");
  const stem = dot > 0 ? base.slice(0, dot) : base;
  return resolve(dirname(p), stem + sfx);
}

export async function cmdRun(args: RunOptions): Promise<number> {
  const artifact = resolve(args.artifact);
  if (!isLocalFile(artifact)) {
    process.stderr.write(`qacore: 产物不存在或不是文件：${artifact}\n`);
    return 2;
  }
  if (!artifact.toLowerCase().endsWith(".html")) {
    process.stderr.write(
      `qacore: 当前阶段仅支持单个 HTML 产物，收到：${basename(artifact)}\n`);
    return 2;
  }

  // 报告默认写产物旁 <产物名>.report.json；截屏随报告目录且跟随报告路径的
  // stem（with_suffix 语义）：缺省时 mini.html → mini.report.json + mini.report.png
  // + mini.report-landscape.png（与 oracle 落盘产物同名，见 pipeline-contract §3.3）。
  const outPath = args.out
    ? (isAbsolute(args.out) ? resolve(args.out) : resolve(args.out))
    : withSuffix(artifact, ".report.json");
  mkdirSync(dirname(outPath), { recursive: true });
  const screenshotPath = withSuffix(outPath, ".png");

  const autoplayEnabled = args.autoplay;
  const autoplayTimeout = args.autoplayTimeout;

  const external: string[] = [];
  const consoleErrors: string[] = [];
  const requests: RequestEntry[] = [];
  const entries = new Map<Request, RequestEntry>();
  const blockedUrls = new Set<string>();
  const runtimeScripts = loadChannelRuntimeScripts(args.channel);
  const runtimeStubs: string[] = [];
  let rtcMax = 0;
  let loadMs = -1.0;
  let pfPresent = false;
  let probeOk = false;
  let autoplayFacts: PassFacts = {};
  let muteFacts: PassFacts = {};
  const shots: Record<string, PassFacts> = {};

  const server = new ArtifactServer(dirname(artifact), args.port);
  await server.start();
  try {
    const url = server.url_for(basename(artifact));

    const isLocal = (parsedUrl: URL): boolean =>
      (parsedUrl.hostname === "127.0.0.1" || parsedUrl.hostname === "localhost")
      && parsedUrl.port === String(server.port);

    const onRoute = (route: Route): void => {
      const req = route.request();
      let parsed: URL;
      try {
        parsed = new URL(req.url());
      } catch {
        parsed = new URL("about:blank");
      }
      const entry: RequestEntry = {
        url: req.url(),
        method: req.method(),
        resource_type: req.resourceType(),
        status: null,
        blocked: false,
        failed: false,
      };
      entries.set(req, entry);
      requests.push(entry);
      if (!isLocal(parsed)) {
        entry.blocked = true;
        if (!external.includes(req.url())) external.push(req.url());
        blockedUrls.add(req.url());
        void route.abort();
        return;
      }
      // 渠道容器运行时脚本（如 mraid.js）：本地缺失时以桩应答，模拟容器注入。
      // 只对规则库声明过的相对脚本名生效；包体自身的本地 404 照常透传。
      const parts = parsed.pathname.split("/");
      const name = parts[parts.length - 1]!;
      if (runtimeScripts.includes(name) && !isLocalFile(resolve(dirname(artifact), name))) {
        entry.status = 200;
        entry.stub = true;
        if (!runtimeStubs.includes(req.url())) runtimeStubs.push(req.url());
        void route.fulfill({
          status: 200,
          contentType: "application/javascript",
          body: CONTAINER_STUB_JS,
        });
        return;
      }
      void route.continue();
    };

    const onWs = (ws: { url(): string }): void => {
      // WebSocket 不经过 page.route，必须单独拦截。注册 routeWebSocket 后，
      // 未调用 connectToServer 的 socket 不会向服务器发起真实连接（非本机 WS
      // 记账后即被阻于握手前）。注意：不要在处理器里调用 ws.close()——实测会让
      // page.goto 的 load 事件永久挂起，因此非本机 WS 只记账不 close。
      let parsed: URL;
      try {
        parsed = new URL(ws.url());
      } catch {
        parsed = new URL("about:blank");
      }
      if (!isLocal(parsed)) {
        const label = `websocket:${ws.url()}`;
        if (!external.includes(label)) external.push(label);
      }
      // 本地 WS 同样不 connectToServer：静态产物不应依赖 WebSocket。
    };

    const wire = (page: Page): void => {
      page.on("response", (response) => {
        const entry = entries.get(response.request());
        if (entry) entry.status = response.status();
      });
      page.on("requestfailed", (request) => {
        const entry = entries.get(request);
        if (entry) entry.failed = true;
      });
      page.on("console", (msg: ConsoleMessage) => {
        if (msg.type() !== "error") return;
        // 我方主动 abort 外链资源会引发浏览器自身的 "Failed to load resource"
        // 报错——该违规已归 CHK03 记账，不再计入 CHK08 重复处罚（qacore spec §4
        // 隐含前提：按 console 消息来源 URL ∈ 本次 abort 记账的 blocked 集合剔除）。
        let srcUrl = "";
        try {
          srcUrl = msg.location()?.url ?? "";
        } catch {
          srcUrl = "";
        }
        if (srcUrl && blockedUrls.has(srcUrl)) return;
        consoleErrors.push(`console.error: ${msg.text()}`);
      });
      page.on("pageerror", (exc) => consoleErrors.push(`pageerror: ${exc}`));
      // 探针注入每页面一次（重复注入会二次包装 AudioContext 导致计数失真）。
      void page.addInitScript(new Function(PROBE_JS) as () => void);
      void page.route("**/*", onRoute);
      void page.routeWebSocket("**/*", onWs);
    };

    const browser = await chromium.launch({ headless: true });
    try {
      const runPass = async (
        viewport: { width: number; height: number },
        label: string,
        shotPath: string,
        doAutoplay: boolean,
      ): Promise<[boolean, PassFacts]> => {
        const context = await browser.newContext({
          viewport: { width: viewport.width, height: viewport.height },
          isMobile: true,
          deviceScaleFactor: 2,
          // Service Worker 发出的请求不进入 page.route，必须整体禁用，
          // 否则页面可借 SW 绕过零外网拦截。
          serviceWorkers: "block",
        });
        const page = await context.newPage();
        wire(page); // 含 PROBE_JS 注入（仅一次，勿重复包装 AudioContext）
        const t0 = performance.now();
        await page.goto(url, { waitUntil: "load", timeout: GOTO_TIMEOUT_MS });
        const passLoadMs = (performance.now() - t0);
        if (label === "portrait") loadMs = passLoadMs;
        await page.waitForTimeout(SETTLE_MS);

        const factsPass: PassFacts = { probeInstalled: await probeInstalled(page) };
        if (doAutoplay) {
          // 教程期文案先采（教程浮层在自动试玩开始数秒后即销毁）：
          // 字符串集合 + 文案对象 active+visible 实况各采一份。
          const textsEarly = await qcTexts(page);
          const [hookEarly, statesEarly] = await qcTextStates(page);
          const driveFacts = await driveAutoplay(page, autoplayTimeout);
          for (const [k, v] of Object.entries(driveFacts)) factsPass[k] = v;
          await page.waitForTimeout(300);
          // 结束页文案补采 + 替换素材像素对账（贴图此时必然已就绪）。
          const textsFinal = await qcTexts(page);
          const [hookFinal, statesFinal] = await qcTextStates(page);
          const everVisible = new Set<string>();
          for (const s of [...statesEarly, ...statesFinal]) {
            if (s.active && s.visible) everVisible.add(s.text);
          }
          for (const t of (factsPass.qcVisibleTexts as string[] | undefined) ?? []) {
            everVisible.add(t);
          }
          const allTexts = new Set<string>([
            ...textsEarly, ...textsFinal,
            ...((factsPass.qcTexts as string[] | undefined) ?? []),
            ...[...statesEarly, ...statesFinal].map((s) => s.text),
          ]);
          factsPass.page_texts = [...allTexts].sort();
          factsPass.text_states = [...allTexts].sort().map((t) => ({
            text: t, everVisible: everVisible.has(t),
          }));
          factsPass.text_states_hook = Boolean(
            factsPass.textStatesHook || hookEarly || hookFinal);
          factsPass.asset_audit = await qcAssets(page);
        } else {
          // 未驱动试玩时，加载后的静音态即"首交互前静音"事实。
          const ms = (await mediaSample(page)) ?? { unmuted: 0, playing: 0, playsBeforeFirst: 0 };
          factsPass.firstMutedBeforeInteraction = await pfMuted(page);
          factsPass.audioRunningBeforeInteraction = await audioRunning(page);
          factsPass.mediaUnmutedBeforeInteraction = Math.trunc(ms.unmuted);
          factsPass.mediaPlaysBeforeInteraction = Math.trunc(ms.playsBeforeFirst);
        }
        const rtc = await rtcCount(page);
        if (typeof rtc === "number") rtcMax = Math.max(rtcMax, rtc);
        await page.screenshot({ path: shotPath });
        const hasCanvas = Boolean(await ev(page, "() => !!document.querySelector('canvas')"));
        const pf = await hasPf(page);
        await context.close();
        return [pf, { has_canvas: hasCanvas, variance: grayscaleVariance(readFileSync(shotPath)), ...factsPass }];
      };

      // 第一趟：竖屏（可自动试玩）
      const [pf, portrait] = await runPass(
        VIEWPORT_PORTRAIT, "portrait", screenshotPath, autoplayEnabled);
      shots.portrait = portrait;
      pfPresent = pf;
      probeOk = Boolean(portrait.probeInstalled);
      if (autoplayEnabled) autoplayFacts = portrait;
      muteFacts = portrait;

      // 第二趟：横屏（仅加载与截屏，autoplay=off——qacore spec §5 冻结）
      const [, landscape] = await runPass(
        VIEWPORT_LANDSCAPE, "landscape",
        withSuffix(screenshotPath, "-landscape.png"),
        false);
      shots.landscape = landscape;
    } finally {
      await browser.close();
    }
  } finally {
    await server.stop();
  }

  const facts: Record<string, unknown> = {
    artifact_bytes: statSync(artifact).size,
    channel: args.channel,
    channel_max_bytes: loadChannelLimit(args.channel),
    channel_mute_required: loadChannelMuteRequired(args.channel),
    external_requests: external,
    runtime_stubs: runtimeStubs,
    rtc_connections: rtcMax,
    request_count: requests.length,
    console_errors: consoleErrors,
    load_ms: loadMs,
    max_load_sec: args.maxLoadSec,
    autoplay_enabled: autoplayEnabled,
    autoplay_timeout_sec: autoplayTimeout,
    autoplay: autoplayFacts,
    muteLoadTime: muteFacts,
    // CHK10 判定输入：要求的渲染文案 / 替换素材键，以及模板上报的已渲染文案
    // 集合与像素对账结果（仅竖屏趟采集）。text_states 为每条文案是否曾在采样
    // 时刻 active+visible；text_states_hook 标记模板是否提供 __PF_QC__.textStates。
    required_texts: args.requireTexts,
    required_sprites: args.requireSprites,
    page_texts: (shots.portrait?.page_texts as string[] | undefined) ?? [],
    text_states: (shots.portrait?.text_states as unknown[] | undefined) ?? [],
    text_states_hook: Boolean(shots.portrait?.text_states_hook),
    asset_audit: (shots.portrait?.asset_audit as unknown[] | undefined) ?? [],
    pf_present: pfPresent,
    probe_installed: probeOk,
    viewport_shots: shots,
    variance_threshold: VARIANCE_THRESHOLD,
  };

  const pageChecks = evaluate(facts);

  const report: Record<string, unknown> = {
    channel: args.channel,
    url: server.url_for(basename(artifact)),
    autoplay: autoplayEnabled,
    pf: {
      present: pfPresent,
      readyMs: autoplayFacts.pfReadyMs ?? null,
      endMs: autoplayFacts.pfEndMs ?? null,
      endWin: autoplayFacts.pfEndWin ?? null,
    },
    checks: pageChecks,
    screenshot: relative(dirname(outPath), screenshotPath).replace(/\\/g, "/"),
    requests,
    // facts 中不含 autoplay 明细（判定前抽出，不落盘到 facts）。
    facts: Object.fromEntries(Object.entries(facts).filter(([k]) => k !== "autoplay")),
  };
  writeFileSync(outPath, JSON.stringify(report, null, 2), "utf8");

  const failed = pageChecks.filter((c) => c.status === "fail");
  let tail = "";
  if (autoplayFacts && autoplayFacts.pfEndMs) {
    tail = `, pf:end ${Math.round(Number(autoplayFacts.pfEndMs))}ms`;
  }
  process.stdout.write(
    `qacore: ${basename(artifact)} @ ${args.channel} -> ${outPath} `
    + `(${requests.length} 请求, ${failed.length} FAIL${tail})\n`);
  return failed.length > 0 ? 1 : 0;
}
