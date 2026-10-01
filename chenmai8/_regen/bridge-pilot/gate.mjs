#!/usr/bin/env node
// 重生成验收 gate：以本目录为 cwd 跑 `npm test`，透传退出码（供工作流调用）。

import { spawnSync } from "node:child_process";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const cwd = dirname(fileURLToPath(import.meta.url));

const result = spawnSync("npm", ["test"], {
  cwd,
  stdio: "inherit",
  shell: process.platform === "win32", // Windows 需经 shell 解析 npm.cmd
});

process.exit(result.status ?? 1);
