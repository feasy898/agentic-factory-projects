// pf/src/static.ts — 零依赖静态文件伺服 handler（node:http）。
//
// 消费方两处：pf/static-server.mjs（make 的分离子进程）与 pf serve（前台伺服）。
// 语义 = python http.server 的常用子集：目录请求试 index.html、防路径穿越、
// 常见扩展名 MIME、404/403。仅伺服本机产物目录，无任何出站请求（防 SSRF 纪律）。

import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, join, normalize, resolve, sep } from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".htm": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".zip": "application/zip",
  ".txt": "text/plain; charset=utf-8",
  ".ogg": "audio/ogg",
  ".wav": "audio/wav",
  ".mp3": "audio/mpeg",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
};

export interface StaticHandlerOptions {
  root: string;
}

export function makeStaticHandler(opts: StaticHandlerOptions) {
  const root = resolve(opts.root);
  return function handler(req: IncomingMessage, res: ServerResponse): void {
    try {
      const url = new URL(req.url ?? "/", "http://localhost");
      let rel = decodeURIComponent(url.pathname);
      if (rel.endsWith("/")) rel += "index.html";
      const target = resolve(root, `.${normalize(rel).replaceAll("\\", "/")}`);
      if (target !== root && !target.startsWith(root + sep)) {
        res.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
        res.end("403 Forbidden");
        return;
      }
      let file = target;
      if (!existsSync(file)) {
        res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
        res.end("404 Not Found");
        return;
      }
      if (statSync(file).isDirectory()) {
        file = join(file, "index.html");
        if (!existsSync(file)) {
          res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
          res.end("404 Not Found");
          return;
        }
      }
      const type = MIME[extname(file).toLowerCase()] ?? "application/octet-stream";
      res.writeHead(200, {
        "Content-Type": type,
        "Content-Length": statSync(file).size,
        "Cache-Control": "no-store",
      });
      const stream = createReadStream(file);
      stream.on("error", () => {
        res.destroy();
      });
      stream.pipe(res);
    } catch {
      try {
        res.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
        res.end("500 Internal Server Error");
      } catch { /* 已响应 */ }
    }
  };
}
