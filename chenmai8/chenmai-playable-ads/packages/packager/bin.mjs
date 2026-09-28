#!/usr/bin/env node
/**
 * 打包器命令行入口（骨架占位版，M4）。
 *
 * 用法：node packages/packager/bin.mjs --help
 * 设计要点：配置驱动（channel-rules 规则库）+ 零第三方运行时依赖。
 * 当前阶段仅提供 --help 骨架，build 子命令随里程碑落地。
 */
import process from "node:process";

const HELP = `pf-packager —— 配置驱动的多渠道打包器（骨架占位版）

用法：
  node packages/packager/bin.mjs <command> [options]

命令：
  build    按渠道规则库打包模板构建产物
           --spec <path>       PlayableSpec JSON 文件
           --channel <id>      目标渠道
           --locale <tag>      输出语言（默认 en）
           --out <dir>         输出目录（默认 artifacts）

选项：
  -h, --help            显示本帮助
  -v, --version         显示版本号
`;

function main(argv) {
  if (argv.length === 0 || argv.includes("--help") || argv.includes("-h")) {
    process.stdout.write(HELP);
    return 0;
  }
  if (argv.includes("--version") || argv.includes("-v")) {
    process.stdout.write("0.1.0\n");
    return 0;
  }
  process.stdout.write(
    `[packager] 子命令 ${String(argv[0])} 尚未实现（当前为骨架占位）。\n`,
  );
  return 0;
}

process.exit(main(process.argv.slice(2)));
