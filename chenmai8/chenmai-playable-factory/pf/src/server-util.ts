// pf/src/server-util.ts — make 的分离静态伺服器管理（oracle pfcore/make.py 同款移植）。
//
// 复用判定依据 <out>/.demo-serve.json，且必须通过三重核实才复用（照抄 oracle）：
//   1) 记录的端口 TCP 可连；
//   2) 记录的 PID 存在且映像名为 node（tasklist /FI 核实，防 PID 跨重启被无关进程
//      复用——验不了身份就不复用，spawn 一个新伺服器 ~0.3s）；
//   3) 记录的伺服根 == 本次 demo_dir（伺服器按请求读盘，同根即可直接吃到重建后的文件）。
// 任一不满足：状态文件一律清理（跨重启残留清零），需要时杀掉验明正身的旧伺服器再起新。
// 端口被 PID 已死的未知进程占用时绝不 taskkill（可能是无关进程），只向后顺延找空闲口。

import { spawn } from "node:child_process";
import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import http from "node:http";
import { join, resolve } from "node:path";

import { makeStaticHandler } from "./static.ts";
import {
  STATIC_SERVER_SCRIPT,
  MakeError,
  killPid,
  log,
  pidIsOurServer,
  portListening,
  sleep,
} from "./util.ts";

export const DEFAULT_SERVE_PORT = 8618;
export const SERVE_STATE_NAME = ".demo-serve.json"; // 伺服状态存 <out>/ 下（demo-prebuilt 每次重建）

async function readState(stateFile: string): Promise<Record<string, unknown> | null> {
  let raw: string;
  try {
    raw = readFileSync(stateFile, "utf8");
  } catch {
    return null;
  }
  try {
    const loaded = JSON.parse(raw) as unknown;
    return loaded !== null && typeof loaded === "object" ? (loaded as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function discardServeState(stateFile: string, reason: string): void {
  try {
    unlinkSync(stateFile);
  } catch { /* 已不存在 */ }
  log(`伺服状态文件已清理（${reason}）；重新定位/启动静态伺服器`);
}

/** 以分离子进程启动 node pf/static-server.mjs（0.0.0.0，随本进程退出仍存活）。 */
function spawnStaticServer(root: string, port: number): number {
  const child = spawn(process.execPath, [STATIC_SERVER_SCRIPT, String(port), root], {
    detached: true,
    stdio: "ignore",
    windowsHide: true,
  });
  child.unref();
  return child.pid ?? -1;
}

/** 确保 demo_dir 正被静态伺服，返回 [port, reused]（oracle ensureServer 语义移植）。 */
export async function ensureServer(
  outRoot: string,
  demoDir: string,
  preferredPort: number,
): Promise<[number, boolean]> {
  const stateFile = join(outRoot, SERVE_STATE_NAME);
  let state: Record<string, unknown> | null = null;
  if (stateFileExists(stateFile)) {
    state = await readState(stateFile);
    if (state === null) {
      discardServeState(stateFile, "状态文件不可读/不是对象");
    }
  }

  if (state !== null) {
    const port = state.port;
    const pid = state.pid;
    const portOk = typeof port === "number" && Number.isInteger(port) && port > 0
      && (await portListening(port));
    const identityOk = pidIsOurServer(pid);
    const rootOk = typeof state.root === "string" && resolve(state.root) === resolve(demoDir);
    if (portOk && identityOk && rootOk) return [port as number, true];
    if (identityOk) {
      // 验明正身是我方 node 伺服器（端口失守/根目录不符/已僵死）：杀旧防累积，
      // 等旧口释放（有界 3s），状态清零，重起伺服正确根目录的新伺服器。
      const reason = portOk && !rootOk
        ? "伺服根目录变更"
        : !portOk ? "记录端口已不在监听" : "伺服根目录不符";
      killPid(pid as number);
      if (typeof port === "number" && port > 0) {
        const deadline = Date.now() + 3000;
        while ((await portListening(port)) && Date.now() < deadline) {
          await sleep(100);
        }
      }
      discardServeState(stateFile, `${reason}，旧伺服器（PID ${pid}）已终止`);
    } else {
      // PID 已死（典型：跨重启残留）或 PID 已被非 node 进程复用：状态是陈旧的，
      // 清掉；占用端口的若非我方进程则绝不动手，只换口。
      discardServeState(stateFile, "记录 PID 不存在或映像名非 node（跨重启残留/PID 复用）");
    }
  }

  let port = preferredPort;
  let found = false;
  for (let i = 0; i < 20; i++) {
    if (!(await portListening(port))) {
      found = true;
      break;
    }
    port += 1;
  }
  if (!found) {
    throw new MakeError(
      `端口 ${preferredPort}~${port} 均被占用，无法启动静态伺服（--serve-port 换口）`, 2);
  }
  const pid = spawnStaticServer(demoDir, port);
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    if (await portListening(port)) {
      writeFileSync(stateFile, `${JSON.stringify({
        port, pid, root: demoDir, started: new Date().toISOString().slice(0, 19),
      })}\n`, "utf8");
      return [port, false];
    }
    await sleep(250);
  }
  throw new MakeError(`静态伺服器启动后端口 ${port} 未进入监听（防火墙或权限问题？）`, 1);
}

function stateFileExists(p: string): boolean {
  try {
    readFileSync(p);
    return true;
  } catch {
    return false;
  }
}

/** 前台伺服器（serve 子命令用；区别于 make 的分离子进程）：Ctrl+C 停止、端口即释放。 */
export function startForegroundServer(root: string, port: number): Promise<http.Server> {
  const server = http.createServer(makeStaticHandler({ root }));
  return new Promise<http.Server>((res, rej) => {
    server.once("error", rej);
    server.listen(port, "0.0.0.0", () => res(server));
  });
}
