#!/usr/bin/env node
/**
 * qacore 命令行入口（`python -m qacore` → `node qacore/cli.mjs`，决策 §2.2 迁移表）：
 *
 *   node qacore/cli.mjs run <产物.html> [--channel preview] [--out <report.json>]
 *                            [--port 0] [--max-load-sec 2.0] [--autoplay]
 *                            [--autoplay-timeout 45.0]
 *                            [--require-text <str>]... [--require-sprite <key>]...
 *
 * 退出码（qacore spec §2，冻结）：0 = 无 fail（skip 不算）；1 = 有 fail；
 * 2 = 产物不存在或非 .html / 用法错误。
 */
import process from "node:process";

import { cmdRun } from "./src/run.ts";

main(process.argv.slice(2)).then(
  (code) => {
    process.exitCode = code;
  },
  (err) => {
    process.stderr.write(`qacore: 未捕获异常：${err?.stack || err}\n`);
    process.exitCode = 1;
  },
);

function usage() {
  process.stderr.write(
    "用法：node qacore/cli.mjs run <artifact.html> [--channel preview] [--out <report.json>]\n"
    + "                       [--port 0] [--max-load-sec 2.0] [--autoplay]\n"
    + "                       [--autoplay-timeout 45.0]\n"
    + "                       [--require-text <str>]... [--require-sprite <key>]...\n");
}

async function main(argv) {
  if (argv.length === 0 || argv[0] !== "run") {
    usage();
    if (argv[0] === "--help" || argv[0] === "-h") return 0;
    return 2;
  }
  const opts = {
    artifact: "",
    channel: "preview",
    out: undefined,
    port: 0,
    maxLoadSec: 2.0,
    autoplay: false,
    autoplayTimeout: 45.0,
    requireTexts: [],
    requireSprites: [],
  };
  const VALUE_OPTS = new Set([
    "--channel", "--out", "--port", "--max-load-sec", "--autoplay-timeout",
    "--require-text", "--require-sprite",
  ]);
  let positional = 0;
  for (let i = 1; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--autoplay") {
      opts.autoplay = true;
    } else if (VALUE_OPTS.has(a)) {
      const v = argv[++i];
      if (v === undefined) {
        process.stderr.write(`qacore: ${a} 缺少参数值\n`);
        usage();
        return 2;
      }
      switch (a) {
        case "--channel": opts.channel = String(v); break;
        case "--out": opts.out = String(v); break;
        case "--port": opts.port = Number.parseInt(v, 10); break;
        case "--max-load-sec": opts.maxLoadSec = Number.parseFloat(v); break;
        case "--autoplay-timeout": opts.autoplayTimeout = Number.parseFloat(v); break;
        case "--require-text": opts.requireTexts.push(String(v)); break;
        case "--require-sprite": opts.requireSprites.push(String(v)); break;
      }
    } else if (a.startsWith("--")) {
      process.stderr.write(`qacore: 未知选项：${a}\n`);
      usage();
      return 2;
    } else {
      positional += 1;
      if (positional === 1) opts.artifact = a;
      else {
        process.stderr.write(`qacore: 多余的位置参数：${a}\n`);
        usage();
        return 2;
      }
    }
  }
  if (!opts.artifact) {
    process.stderr.write("qacore: 缺少产物路径参数\n");
    usage();
    return 2;
  }
  if (!Number.isFinite(opts.port) || !Number.isFinite(opts.maxLoadSec)
    || !Number.isFinite(opts.autoplayTimeout)) {
    process.stderr.write("qacore: 数值参数解析失败\n");
    usage();
    return 2;
  }
  return cmdRun(opts);
}
