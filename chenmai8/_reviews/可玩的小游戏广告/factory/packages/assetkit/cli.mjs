#!/usr/bin/env node
// packages/assetkit/cli.mjs — assetkit CLI（oracle python/assetkit/cli.py run/selftest 两子命令
// 的宿主移植；`python -m assetkit` → `node packages/assetkit/cli.mjs`，决策 §2.2 迁移表）。
//
// 用法：
//   node packages/assetkit/cli.mjs run <素材目录|文件...> --out <dir> [--spec <spec.json>]
//        [--quality 75] [--audio-bitrate 48000] [--max-edge 0] [--no-atlas]
//        [--atlas-max-width 1024] [--extra-text ""] [--min-reduction 30]
//   node packages/assetkit/cli.mjs selftest
// 退出码：0 全过；1 素材处理失败（宁可失败不可带病出报告）；2 用法/环境错误。

import process from "node:process";

main(process.argv.slice(2)).then((code) => {
  process.exitCode = code;
}, (err) => {
  process.stderr.write(`assetkit: 未捕获异常：${err?.stack || err}\n`);
  process.exitCode = 1;
});

function usage() {
  process.stderr.write(`素材处理流水线（M5 · assetkit）

用法：
  node packages/assetkit/cli.mjs run <素材目录|文件...> --out <dir> [--spec <spec.json>]
       [--quality 75] [--audio-bitrate 48000] [--max-edge 0] [--no-atlas]
       [--atlas-max-width 1024] [--extra-text ""] [--min-reduction 30]
  node packages/assetkit/cli.mjs selftest
`);
}

async function main(argv) {
  const cmd = argv[0];
  if (cmd === undefined || cmd === "--help" || cmd === "-h" || cmd === "help") {
    usage();
    return cmd === undefined ? 2 : 0;
  }
  const { AssetkitError } = await import("./src/index.ts");
  try {
    if (cmd === "run") {
      const { runAssetkit } = await import("./src/pipeline.ts");
      const inputs = [];
      const flags = {};
      for (let i = 1; i < argv.length; i++) {
        const a = argv[i];
        if (a.startsWith("--")) {
          const eq = a.indexOf("=");
          const key = eq > 0 ? a.slice(2, eq) : a.slice(2);
          const value = eq > 0 ? a.slice(eq + 1) : true;
          if (value === true) {
            const nxt = argv[i + 1];
            if (nxt !== undefined && !nxt.startsWith("--")) {
              flags[key] = nxt;
              i += 1;
              continue;
            }
          }
          flags[key] = value;
        } else {
          inputs.push(a);
        }
      }
      if (!flags.out || typeof flags.out !== "string") {
        process.stderr.write("assetkit: run 需要 --out <dir>\n");
        usage();
        return 2;
      }
      const num = (name, dflt) => (flags[name] === undefined ? dflt : Number(flags[name]));
      const report = await runAssetkit({
        inputs,
        out: String(flags.out),
        spec: typeof flags.spec === "string" ? flags.spec : null,
        imageQuality: num("quality", 75),
        audioBitrate: num("audio-bitrate", 48000),
        maxEdge: num("max-edge", 0),
        atlas: flags["no-atlas"] !== true,
        atlasMaxWidth: num("atlas-max-width", 1024),
        extraText: typeof flags["extra-text"] === "string" ? flags["extra-text"] : "",
        minReductionPct: flags["min-reduction"] === undefined ? null : Number(flags["min-reduction"]),
      });
      const t = report.totals;
      if (t.minReductionMet === false) {
        process.stderr.write(`assetkit: 汇总降幅 ${t.reductionPct}% 未达 --min-reduction=${t.minReductionPct}%（exit 1）\n`);
        return 1;
      }
      return 0;
    }
    if (cmd === "selftest") {
      const { runSelftest } = await import("./selftest.mjs");
      return runSelftest();
    }
    process.stderr.write(`assetkit: 未知子命令 '${cmd}'\n`);
    usage();
    return 2;
  } catch (err) {
    if (err instanceof AssetkitError) {
      process.stderr.write(`assetkit: FAIL：${err.message}\n`);
      return err.exitCode;
    }
    throw err;
  }
}
