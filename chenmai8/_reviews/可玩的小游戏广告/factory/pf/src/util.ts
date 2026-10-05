// pf/src/util.ts — 编排 CLI 公共件（oracle pfcore 同名函数的宿主移植）。
//
// 防 SSRF 纪律（pipeline-contract §5，照抄）：本模块对 loopback/私网**不发起任何
// HTTP 请求**——端口健康检查只做 TCP connect；LAN IP 探测用 UDP connect（不发包）
// 让内核选一次路由，候选地址按段优先级排序而非直接采信（默认路由常落在 TUN 虚拟网卡）。

import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, readdirSync, statSync } from "node:fs";
import os from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import dgram from "node:dgram";
import net from "node:net";

/** factory 仓根（pf/src/util.ts → 上两级）。 */
export const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

export const RULES_PATH = resolve(REPO_ROOT, "channel-rules", "channel-rules.json");
export const PACKAGER_BIN = resolve(REPO_ROOT, "packages", "packager", "bin.mjs");
export const QACORE_CLI = resolve(REPO_ROOT, "qacore", "cli.mjs");
export const STATIC_SERVER_SCRIPT = resolve(REPO_ROOT, "pf", "static-server.mjs");

// spec.game.template → 模板构建脚本（能产出"真实可玩 HTML"的模板才可入表；
// 与 oracle pfcore/make.py TEMPLATE_BUILDERS 同表，宿主路径按 factory 布局）。
export const TEMPLATE_BUILDERS: Record<string, string> = {
  match3: resolve(REPO_ROOT, "packages", "templates", "tmpl-match3", "build.mjs"),
  merge: resolve(REPO_ROOT, "packages", "templates", "tmpl-merge", "build.mjs"),
  pullpin: resolve(REPO_ROOT, "packages", "templates", "tmpl-pullpin", "build.mjs"),
  sort: resolve(REPO_ROOT, "packages", "templates", "tmpl-sort", "build.mjs"),
};

/** 带退出码语义的编排失败：exitCode ∈ {1 判定失败, 2 用法/环境错误}（契约 §2）。 */
export class MakeError extends Error {
  exitCode: number;
  constructor(message: string, exitCode = 1) {
    super(message);
    this.exitCode = exitCode;
  }
}

export function log(msg: string): void {
  console.log(`[make] ${msg}`);
}

/** 跑子进程（cwd 钉仓根，utf8 宽容解码）；非零退出抛 MakeError（exit 1，附输出尾部）。 */
export function run(
  cmd: readonly string[],
  label: string,
  opts: { timeoutSec?: number; env?: Record<string, string> } = {},
): string {
  const proc = spawnSync(cmd[0]!, cmd.slice(1), {
    cwd: REPO_ROOT,
    timeout: (opts.timeoutSec ?? 600) * 1000,
    encoding: "utf8",
    windowsHide: true,
    env: opts.env,
    maxBuffer: 64 * 1024 * 1024,
  });
  if (proc.error) {
    throw new MakeError(`${label} 启动失败：${String(proc.error)}`, 1);
  }
  if (proc.status !== 0) {
    const tail = ((proc.stderr ?? "") || (proc.stdout ?? ""))
      .trim().split(/\r?\n/).slice(-8).join("\n");
    throw new MakeError(`${label} 失败（exit ${proc.status}）：\n${tail || "(无输出)"}`, 1);
  }
  return proc.stdout ?? "";
}

// ---------------------------------------------------------------- glob 展开（validate）

/** 朴素 glob → 正则（支持 `*`、`?`、`**` 跨段；与 python glob 递归语义对齐的常用子集）。 */
function globToRegex(pattern: string): RegExp {
  let re = "";
  const segs = pattern.split("/");
  for (let i = 0; i < segs.length; i++) {
    const seg = segs[i]!;
    if (seg === "**") {
      re += "(?:.*/)?";
      continue;
    }
    for (const ch of seg) {
      if (ch === "*") re += "[^/]*";
      else if (ch === "?") re += "[^/]";
      else re += ch.replace(/[.+^${}()|[\]\\]/g, "\\$&");
    }
    if (i < segs.length - 1) re += "/";
  }
  return new RegExp(`^${re}$`);
}

function hasMagic(p: string): boolean {
  return /[*?]/.test(p);
}

function walkFiles(dir: string, prefix: string, out: string[]): void {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const e of entries) {
    const rel = prefix === "" ? e.name : `${prefix}/${e.name}`;
    if (e.isDirectory()) walkFiles(`${dir}/${e.name}`, rel, out);
    else if (e.isFile()) out.push(rel);
  }
}

/**
 * 展开 validate 的路径参数（oracle _expand_spec_paths 同义：globlib.glob 递归形态
 * 的常用子集，命中按字典序排序）：
 * 返回 [存在的文件列表, 无匹配的模式列表]。
 */
export function expandSpecPaths(patterns: readonly string[]): {
  files: string[];
  unmatched: string[];
} {
  const files: string[] = [];
  const unmatched: string[] = [];
  for (const raw of patterns) {
    const pattern = raw.replace(/\\/g, "/");
    let hits: string[] = [];
    if (hasMagic(pattern)) {
      const slash = pattern.search(/[/][^/]*$/);
      let base = slash > 0 ? pattern.slice(0, slash) : ".";
      let sub = slash > 0 ? pattern.slice(slash + 1) : pattern;
      // base 段本身含魔法字符（如 "**\/*.json" 前置 **）→ 从根递归整体匹配。
      if (hasMagic(base)) {
        base = ".";
        sub = pattern;
      }
      const candidates: string[] = [];
      if (sub.includes("**/")) {
        // 递归（含前置/中置 **）：候选 = base 相对路径（含子目录），对整段 pattern 匹配
        walkFiles(base, "", candidates);
      } else {
        // 单层目录直读（eval 场景全是 specs-eval/bad/*.json 形态，够用且快）
        try {
          for (const e of readdirSync(base, { withFileTypes: true })) {
            if (e.isFile()) candidates.push(e.name);
          }
        } catch { /* 目录不存在 → 零命中 */ }
      }
      const re = globToRegex(sub);
      hits = candidates.filter((c) => re.test(c)).sort()
        .map((c) => (base === "." ? c : `${base}/${c}`));
    } else {
      try {
        if (statSync(pattern).isFile()) hits = [pattern];
      } catch { /* 不存在 */ }
    }
    if (hits.length > 0) files.push(...hits);
    else unmatched.push(raw);
  }
  return { files, unmatched };
}

// ---------------------------------------------------------------- 网络探测（TCP-only）

/** TCP connect 探测本机端口是否在听（不发 HTTP 请求——契约 §5"可扫"判定）。 */
export function portListening(port: number, timeoutMs = 400): Promise<boolean> {
  return new Promise((res) => {
    const sock = new net.Socket();
    let settled = false;
    const done = (ok: boolean): void => {
      if (settled) return;
      settled = true;
      sock.destroy();
      res(ok);
    };
    sock.setTimeout(timeoutMs);
    sock.once("connect", () => done(true));
    sock.once("timeout", () => done(false));
    sock.once("error", () => done(false));
    sock.connect(port, "127.0.0.1");
  });
}

/** 地址段优先级：手机大概率直达的段在前。0=192.168；1=10/8；2=172.16-31；
 *  3=100.64/10（CGNAT/tailnet）；5=其他；9=198.18/15（RFC2544 基准段/VPN TUN）。 */
export function addrTier(ip: string): number {
  if (ip.startsWith("192.168.")) return 0;
  if (ip.startsWith("10.")) return 1;
  if (ip.startsWith("172.")) {
    const second = Number.parseInt(ip.split(".")[1] ?? "", 10);
    return Number.isFinite(second) && second >= 16 && second <= 31 ? 2 : 8;
  }
  if (ip.startsWith("100.")) {
    const second = Number.parseInt(ip.split(".")[1] ?? "", 10);
    return Number.isFinite(second) && second >= 64 && second <= 127 ? 3 : 8;
  }
  if (ip.startsWith("198.18.") || ip.startsWith("198.19.")) return 9;
  return 5;
}

/** UDP connect（8.8.8.8:80，不发出任何包，仅让内核选一次路由）取默认路由本地地址。 */
function udpRouteAddress(timeoutMs = 500): Promise<string | null> {
  return new Promise((res) => {
    let settled = false;
    const finish = (v: string | null): void => {
      if (settled) return;
      settled = true;
      try { sock.close(); } catch { /* 已关闭 */ }
      res(v);
    };
    const sock = dgram.createSocket("udp4");
    sock.once("error", () => finish(null));
    sock.connect(80, "8.8.8.8", () => {
      try {
        const addr = sock.address();
        finish(typeof addr?.address === "string" ? addr.address : null);
      } catch {
        finish(null);
      }
    });
    setTimeout(() => finish(null), timeoutMs);
  });
}

/** 探测局域网可达地址：本机全部 IPv4 候选按段优先级排序（127.* 永不入选）。
 *  UDP connect 所得地址参与排序而非直接采信——默认路由可能落在 TUN 虚拟网卡上，
 *  该地址局域网手机不可达（oracle 实测教训，照抄）。探不准时用 --serve-host 显式指定。 */
export async function lanIp(): Promise<string> {
  const candidates: string[] = [];
  const viaRoute = await udpRouteAddress();
  if (viaRoute && !viaRoute.startsWith("127.")) candidates.push(viaRoute);
  for (const list of Object.values(os.networkInterfaces())) {
    for (const info of list ?? []) {
      if (info.family === "IPv4" && !info.address.startsWith("127.")) {
        candidates.push(info.address);
      }
    }
  }
  const unique = candidates.filter((ip, i) => candidates.indexOf(ip) === i);
  if (unique.length === 0) return "127.0.0.1";
  let best = unique[0]!;
  for (const ip of unique.slice(1)) {
    if (addrTier(ip) < addrTier(best)) best = ip; // 稳定：同 tier 保留先出现者（python min 语义）
  }
  return best;
}

// ---------------------------------------------------------------- 进程身份（Windows）

/** 跑系统命令（tasklist/taskkill/ps/kill），字节输出按 utf-8 宽容解码（oracle _run_tool 同因由：
 *  Windows 系统命令提示信息走本地 OEM 代码页，我们只依赖 ASCII 结构——映像名、退出码）。 */
function runTool(cmd: readonly string[], timeoutMs = 10_000): [number, string] {
  try {
    const proc = spawnSync(cmd[0]!, cmd.slice(1), {
      timeout: timeoutMs,
      windowsHide: true,
    });
    if (proc.error) return [-1, ""];
    const out = Buffer.concat(
      [proc.stdout ?? Buffer.alloc(0), proc.stderr ?? Buffer.alloc(0)].filter((b) => b.length > 0),
    );
    return [proc.status ?? -1, out.toString("utf8")];
  } catch {
    return [-1, ""];
  }
}

/** 查 PID 对应进程映像名（小写）；不存在/查询失败返回 null。
 *  Windows 用 tasklist /FI（不依赖任何第三方模块）；只认"首个 CSV 字段以 .exe 结尾"的行
 *  （无匹配时 tasklist 打印本地化提示——各语言不同，不能按前缀判；oracle 同款纪律）。 */
export function pidImageName(pid: number): string | null {
  if (process.platform === "win32") {
    const [code, out] = runTool(["tasklist", "/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"]);
    if (code !== 0) return null;
    for (const line of out.split(/\r?\n/)) {
      const first = line.trim().split(",")[0]?.trim().replaceAll('"', "").toLowerCase() ?? "";
      if (first.endsWith(".exe")) return first;
    }
    return null;
  }
  const [code, out] = runTool(["ps", "-p", String(pid), "-o", "comm="]);
  if (code !== 0) return null;
  const name = out.trim().split("/").pop()?.toLowerCase() ?? "";
  return name || null;
}

/** 进程身份核实：PID 存在且映像名以 node 开头（我方静态伺服器宿主；
 *  oracle 钉 python 映像名——宿主移植为 node，防 PID 复用误判语义不变）。 */
export function pidIsOurServer(pid: unknown): boolean {
  if (typeof pid !== "number" || !Number.isInteger(pid) || pid <= 0) return false;
  const image = pidImageName(pid);
  return image !== null && image.startsWith("node");
}

/** 终止已验明身份的旧伺服器进程（taskkill /F /T）；失败只返回 false 不抛。 */
export function killPid(pid: number): boolean {
  if (process.platform === "win32") {
    const [code] = runTool(["taskkill", "/PID", String(pid), "/F", "/T"]);
    return code === 0;
  }
  const [code] = runTool(["kill", "-9", String(pid)]);
  return code === 0;
}

export function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/**
 * 递归目录复制（shutil.copytree 同义；dirs_exist_ok 语义）。
 * 宿主注记：本机 Node 22.23.2 的 `fs.cpSync(recursive:true)` 原生绑定硬崩
 * （静默 exit 127、零输出，任意目录可复现——2026-09-30 实测三例），故此 hand-rolled
 * 实现：readdirSync + mkdirSync + copyFileSync（三者本机全程在用、稳定）。
 */
export function copyDirRecursive(src: string, dst: string): void {
  mkdirSync(dst, { recursive: true });
  for (const e of readdirSync(src, { withFileTypes: true })) {
    const s = join(src, e.name);
    const d = join(dst, e.name);
    if (e.isDirectory()) copyDirRecursive(s, d);
    else if (e.isFile()) copyFileSync(s, d);
  }
}
