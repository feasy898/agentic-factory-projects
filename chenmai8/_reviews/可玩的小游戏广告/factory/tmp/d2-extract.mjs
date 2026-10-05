// d2-extract.mjs — 从 playwright-core coreBundle 中提取 WebSocketRouteDispatcher.install 实现。
import { readFileSync } from "node:fs";
const s = readFileSync("node_modules/playwright-core/lib/coreBundle.js", "utf8");
const k = s.indexOf("kBindingName3");
console.log("kBindingName3 at", k);
console.log(s.slice(Math.max(0, k - 2600), k + 500));
