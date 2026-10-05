// d2-extract2.mjs — 提取 WebSocketRouteDispatcher.install（拦截武装点：init script + binding）。
import { readFileSync } from "node:fs";
const s = readFileSync("node_modules/playwright-core/lib/coreBundle.js", "utf8");
const marker = "static async install(";
const k = s.indexOf(marker, s.indexOf("webSocketRouteDispatcher"));
console.log("install at", k);
console.log(s.slice(k - 200, k + 2600));
