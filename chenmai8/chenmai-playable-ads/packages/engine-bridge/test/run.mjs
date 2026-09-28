#!/usr/bin/env node
// M2 eval 入口（开发指令 §6）：node packages/engine-bridge/test/run.mjs
// 与自验收命令 `node --test packages/engine-bridge/test/` 等价（转发执行）。
//
// 注意：node --test 会把 test/ 目录下所有文件都当用例收集；当本文件被
// 收集执行时（NODE_TEST_CONTEXT 已设置）直接静默退出，避免递归自举。

import { spawnSync } from "node:child_process";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

if (process.env.NODE_TEST_CONTEXT) process.exit(0);

const here = dirname(fileURLToPath(import.meta.url));
const result = spawnSync(process.execPath, ["--test", here], {
  stdio: "inherit",
});
process.exit(result.status ?? 1);
