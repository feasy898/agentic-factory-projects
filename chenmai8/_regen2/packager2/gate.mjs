#!/usr/bin/env node
/**
 * 门脚本（根包装）：委派到 packages/packager/gate.mjs（其以自身目录为 cwd 跑冻结自验收
 * node test/run.mjs 并透传退出码）。验收 = 全部断言 PASS 且 exit 0。
 */
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const r = spawnSync(process.execPath, [path.join("packages", "packager", "gate.mjs")], {
  cwd: here,
  stdio: "inherit",
});
process.exit(typeof r.status === "number" ? r.status : 1);
