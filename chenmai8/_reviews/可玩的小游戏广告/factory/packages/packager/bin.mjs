#!/usr/bin/env node
/**
 * pf-packager —— 配置驱动的多渠道打包器（M4）。
 *
 * 输入：模板构建产物（dist）+ PlayableSpec + channel-rules 规则库
 * 输出：<out>/<project>/<channel>/<locale>/ 下的渠道包
 *   - single-html 渠道（applovin/meta/preview）：单 HTML 全内联（base64 资源、零外链）
 *   - zip 渠道（条目与顺序由规则库 package.structure 声明）：mintegral=build.js+Template.html；
 *     google/unity=入口 index.html 全内联；tiktok=index.html+config.json+js-sdk 桩
 *
 * 退出码（spec §2，统一裁定）：0 成功；1 构建失败（含超规/外链/结构违规/未知或未冻结
 * 渠道）；2 仅限 CLI 用法层（未知子命令、多余位置参数、参数解析错误）。渠道拼写错误不是 2。
 * 成功时 stdout 末行输出 JSON：{ok:true, artifact, totalBytes, maxBytes}。
 * 本包零第三方运行时依赖；esbuild 仅为根工作区 devDependency（JS/CSS 压缩用）。
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { pack } from "./src/build.mjs";
import { loadRules } from "./src/rules.mjs";

const PKG = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));
const REPO_ROOT = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));

const HELP = `pf-packager —— 配置驱动的多渠道打包器

用法：
  node packages/packager/bin.mjs <command> [options]

命令：
  build     打包一个渠道
            --spec <path>        PlayableSpec JSON 文件（必填）
            --dist <dir>         模板构建产物目录（必填，含 index.html；
                                 若存在 <dist>/<locale>/index.html 则优先按语言产物）
            --channel <id>       目标渠道 id（必填，须在规则库中）
            --locale <tag>       输出语言（默认 en）
            --out <dir>          输出根目录（默认 artifacts；产物落在
                                 <out>/<project>/<channel>/<locale>/）
            --rules <path>       规则库路径（默认 channel-rules/channel-rules.json）
            --no-minify          跳过 esbuild 压缩（调试用）
  channels  列出规则库中的渠道及其包形态/上限
            --rules <path>       规则库路径（默认 channel-rules/channel-rules.json）

选项：
  -h, --help            显示本帮助
  -v, --version         显示版本号

示例：
  node packages/packager/bin.mjs build --spec specs-eval/golden-match3.json \\
    --dist packages/packager/test/fixture/match3-dist --channel applovin --locale en --out artifacts
`;

function parseArgs(argv) {
  const o = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const eq = a.indexOf("=");
      if (eq > 0) {
        o[a.slice(2, eq)] = a.slice(eq + 1);
      } else if (i + 1 < argv.length && !argv[i + 1].startsWith("--")) {
        o[a.slice(2)] = argv[++i];
      } else {
        o[a.slice(2)] = true;
      }
    } else if (o.command === undefined) {
      o.command = a;
    } else {
      throw new Error(`多余的位置参数: ${a}`);
    }
  }
  return o;
}

function defaultRulesPath() {
  return path.join(REPO_ROOT, "channel-rules", "channel-rules.json");
}

function readJsonFile(p, label) {
  const abs = path.resolve(p);
  let raw;
  try {
    raw = readFileSync(abs, "utf8");
  } catch (err) {
    throw new Error(`读取${label}失败: ${abs}（${err.message}）`);
  }
  try {
    return JSON.parse(raw);
  } catch (err) {
    throw new Error(`${label} 不是合法 JSON: ${abs}（${err.message}）`);
  }
}

function fmtMB(n) {
  return `${(n / 1024 / 1024).toFixed(2)}MB`;
}

async function cmdBuild(o) {
  for (const k of ["spec", "dist", "channel"]) {
    if (!o[k]) throw new Error(`build 缺少 --${k}`);
  }
  const specPath = path.resolve(o.spec);
  const spec = readJsonFile(specPath, "spec");
  const result = await pack({
    spec,
    specPath,
    dist: path.resolve(o.dist),
    channel: o.channel,
    locale: o.locale || "en",
    rulesPath: o.rules ? path.resolve(o.rules) : defaultRulesPath(),
    out: o.out ? path.resolve(o.out) : path.join(process.cwd(), "artifacts"),
    minify: !o["no-minify"],
  });
  console.log(`[packager] 渠道=${o.channel} 语言=${o.locale || "en"} 项目=${result.manifest.project}`);
  for (const f of result.files) {
    console.log(`[packager]   ${f.role.padEnd(13)} ${f.path.padEnd(28)} ${(f.bytes / 1024).toFixed(1)}KB`);
  }
  console.log(
    `[packager]   包体积 ${fmtMB(result.totalBytes)} / 上限 ${fmtMB(result.maxBytes)}；` +
      `白名单外链接=0；警告 ${result.warnings.length} 条`,
  );
  for (const w of result.warnings) console.log(`[packager]   警告: ${w}`);
  console.log(JSON.stringify({ ok: true, artifact: result.artifact, totalBytes: result.totalBytes, maxBytes: result.maxBytes }));
  return 0;
}

function cmdChannels(o) {
  const { rules, path: rulesPath } = loadRules(o.rules ? path.resolve(o.rules) : defaultRulesPath());
  console.log(`[packager] 规则库 ${rulesPath}（rulesVersion=${rules.rulesVersion}）`);
  for (const [id, ch] of Object.entries(rules.channels)) {
    console.log(
      `[packager]   ${id.padEnd(10)} ${ch.package.format.padEnd(12)} 上限 ${fmtMB(ch.maxBytes)}` +
        ` 文件数≤${ch.maxFiles} 退出=${ch.exit.call}`,
    );
  }
  return 0;
}

async function main(argv) {
  if (argv.length === 0 || argv.includes("--help") || argv.includes("-h")) {
    process.stdout.write(HELP);
    return 0;
  }
  if (argv.includes("--version") || argv.includes("-v")) {
    process.stdout.write(`${PKG.version}\n`);
    return 0;
  }
  let o;
  try {
    o = parseArgs(argv);
  } catch (err) {
    process.stderr.write(`[packager] 参数错误: ${err.message}\n（--help 查看用法）\n`);
    return 2;
  }
  switch (o.command) {
    case "build":
      return await cmdBuild(o);
    case "channels":
      return cmdChannels(o);
    default:
      process.stderr.write(`[packager] 未知命令 "${o.command}"（--help 查看用法）\n`);
      return 2;
  }
}

main(process.argv.slice(2))
  .then((code) => process.exit(code))
  .catch((err) => {
    process.stderr.write(`[packager] 失败: ${err.message}\n`);
    process.exit(1);
  });
