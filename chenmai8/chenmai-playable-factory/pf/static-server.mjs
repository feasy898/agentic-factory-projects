#!/usr/bin/env node
// pf/static-server.mjs — make 的分离静态伺服子进程（oracle `python -m http.server` 的宿主移植）。
//
// make 以 detached 子进程启动本脚本（父进程退出后仍存活），伺服 demo-prebuilt 目录；
// 状态（port/pid/root）由父进程写 <out>/.demo-serve.json，跨会话复用判定在父进程
//（pf/src/server-util.ts：TCP 可连 + PID 映像名 node* + 伺服根一致 三重核实）。
//
// 用法：node pf/static-server.mjs <port> <rootDir>
import { makeStaticHandler } from "./src/static.ts";
import http from "node:http";
import process from "node:process";

const port = Number.parseInt(process.argv[2] ?? "", 10);
const root = process.argv[3] ?? "";
if (!Number.isInteger(port) || port <= 0 || !root) {
  process.stderr.write("用法：node pf/static-server.mjs <port> <rootDir>\n");
  process.exit(2);
}

const server = http.createServer(makeStaticHandler({ root }));
server.on("error", (err) => {
  process.stderr.write(`static-server: ${String(err)}\n`);
  process.exit(1);
});
server.listen(port, "0.0.0.0");
