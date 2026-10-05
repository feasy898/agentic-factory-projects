#!/usr/bin/env node
// pf/pf.mjs — 编排 CLI 入口（`python -m pfcore` → `node pf.mjs`，决策 §2.2 迁移表）。
//
// 子命令（pipeline-contract §1 冻结；oracle pfcore/__main__.py 同表移植）：
//   validate     校验 PlayableSpec JSON（schema v1 + 不变式，错误定位到字段路径）
//   make         全流水线：校验→模板构建→渠道打包→判官质检→summary+二维码+计时+demo-prebuilt
//   serve        局域网静态伺服既有产物目录（demo-prebuilt/裸预览）+ 重建汇总页与二维码
//   build        按 spec 构建单个模板产物                    （占位，exit 2——占位语义本身是契约）
//   pack         全渠道打包                                  （占位，exit 2）
//   rules-check  校验渠道规则库                              （占位，exit 2）
//
// 退出码（pipeline-contract §2，冻结）：0 全部通过；1 判定失败（校验 issue/质检 fail/
// 打包违规/门禁 FAIL）；2 用法错误/占位子命令未实现/产物不存在。
import process from "node:process";

main(process.argv.slice(2)).then((code) => {
  process.exitCode = code;
}, (err) => {
  process.stderr.write(`pf: 未捕获异常：${err?.stack || err}\n`);
  process.exitCode = 1;
});

function usage() {
  process.stderr.write(`编排 CLI（试玩广告生产线 · factory）

用法：
  node pf/pf.mjs validate <spec.json> [more.json ...]   # 支持 glob
  node pf/pf.mjs make --spec <spec.json> [--locales en,zh] [--channels all]
                       [--out artifacts] [--serve-port 8618] [--serve-host <ip>]
                       [--no-serve] [--no-assetkit]
  node pf/pf.mjs serve [--root artifacts/demo-prebuilt] [--port 8618] [--host <ip>]
  node pf/pf.mjs build <spec.json> [--channel preview] [--locale en] [--out artifacts]   # 占位
  node pf/pf.mjs pack <spec.json> [--all-channels] [--locale en] [--out artifacts]       # 占位
  node pf/pf.mjs rules-check                                                            # 占位
`);
}

async function main(argv) {
  const cmd = argv[0];
  if (cmd === undefined || cmd === "--help" || cmd === "-h" || cmd === "help") {
    if (cmd !== undefined) usage();
    else console.log("编排 CLI（validate/make/serve 已实现；build/pack/rules-check 为占位）。用 --help 看用法。");
    return 0;
  }
  const rest = argv.slice(1);

  // 旗标解析（oracle argparse 对齐：--k=v 与 --k v 两形态都收；未知旗标 → exit 2）。
  const flags = {};
  const positionals = [];
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    if (a.startsWith("--")) {
      const eq = a.indexOf("=");
      let key;
      let value;
      if (eq > 0) {
        key = a.slice(2, eq);
        value = a.slice(eq + 1);
      } else {
        key = a.slice(2);
        value = true;
      }
      const BOOL = new Set(["no-serve", "no-assetkit", "all-channels"]);
      if (value === true && !BOOL.has(key)) {
        const nxt = rest[i + 1];
        if (nxt !== undefined && !nxt.startsWith("--")) {
          value = nxt;
          i += 1;
        }
      }
      flags[key] = value;
    } else {
      positionals.push(a);
    }
  }
  const num = (name, dflt) => {
    if (flags[name] === undefined || flags[name] === true) return dflt;
    const v = Number.parseInt(String(flags[name]), 10);
    if (!Number.isFinite(v)) throw Object.assign(new Error(`--${name} 不是整数：${flags[name]}`), { pfUsage: true });
    return v;
  };
  const str = (name) => (typeof flags[name] === "string" ? flags[name] : undefined);

  try {
    switch (cmd) {
      case "validate": {
        if (positionals.length === 0 && flags.spec === undefined) {
          process.stderr.write("pf: validate 需要至少一个 spec 路径参数\n");
          usage();
          return 2;
        }
        const { cmdValidate } = await import("./src/validate-cmd.ts");
        return cmdValidate({ spec: positionals });
      }
      case "make": {
        if (typeof flags.spec !== "string") {
          process.stderr.write("pf: make 需要 --spec <spec.json>（必填）\n");
          usage();
          return 2;
        }
        const { cmdMake } = await import("./src/make-cmd.ts");
        return await cmdMake({
          spec: flags.spec,
          locales: str("locales"),
          channels: typeof flags.channels === "string" ? flags.channels : "applovin,meta,mintegral",
          out: typeof flags.out === "string" ? flags.out : "artifacts",
          servePort: num("serve-port", 8618),
          serveHost: str("serve-host"),
          noServe: flags["no-serve"] === true,
          noAssetkit: flags["no-assetkit"] === true,
        });
      }
      case "serve": {
        const { cmdServe } = await import("./src/serve-cmd.ts");
        return await cmdServe({
          root: str("root") ?? "artifacts/demo-prebuilt",
          port: num("port", 8618),
          host: str("host"),
        });
      }
      case "build":
      case "pack":
      case "rules-check":
        console.log(`[pf] 子命令 '${cmd}' 尚未实现（当前为占位）。`);
        return 2;
      default:
        process.stderr.write(`pf: 未知子命令 '${cmd}'\n`);
        usage();
        return 2;
    }
  } catch (err) {
    if (err && typeof err === "object" && err.pfUsage === true) {
      process.stderr.write(`pf: ${err.message}\n`);
      usage();
      return 2;
    }
    throw err;
  }
}
