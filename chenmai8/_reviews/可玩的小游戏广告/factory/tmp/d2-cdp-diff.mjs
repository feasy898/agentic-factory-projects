// d2-cdp-diff.mjs — 归一化对比 node/python 两份 pw:protocol 抓包：按 (method) 序列对齐，
// 打出「命令序列差异」与「addScript 源差异指纹」。
import { readFileSync } from "node:fs";

function parse(file) {
  const text = readFileSync(file, "utf8");
  const events = [];
  for (const line of text.split(/\r?\n/)) {
    const m = line.match(/^\S+ pw:protocol SEND \u25BA (\{.*)$/);
    if (!m) continue;
    const json = m[1];
    if (!m) continue;
    let obj;
    try { obj = JSON.parse(json); } catch { continue; }
    if (obj.method) events.push({ dir: "send", method: obj.method, params: obj.params ?? {}, sessionId: obj.sessionId ?? "" });
    else if (obj.result !== undefined || obj.error) events.push({ dir: "recv", method: `(reply)`, ok: !obj.error, params: obj.error ?? {} });
  }
  return events;
}

function fingerprint(params) {
  const s = JSON.stringify(params);
  return s.length + ":" + (s.match(/"glob[^,}]*/)?.[0] ?? s.slice(0, 120));
}

const a = parse("tmp/d2-cdp-node.log");
const b = parse("tmp/d2-cdp-py.log");
const seqA = a.filter((e) => e.dir === "send").map((e) => e.method);
const seqB = b.filter((e) => e.dir === "send").map((e) => e.method);
console.log("== node 发送序列 ==");
console.log(seqA.join(","));
console.log("== python 发送序列 ==");
console.log(seqB.join(","));
// 简单 LCS 序列差
const lcs = [];
let i = 0, j = 0;
while (i < seqA.length && j < seqB.length) {
  if (seqA[i] === seqB[j]) { lcs.push(seqA[i]); i++; j++; }
  else if (seqB.indexOf(seqA[i], j) !== -1 || seqA.slice(i).includes(seqB[j])) {
    if (!seqA.slice(i + 1).includes(seqA[i])) { console.log("only-in-node:", seqA[i]); i++; }
    else if (!seqB.slice(j + 1).includes(seqB[j])) { console.log("only-in-py:", seqB[j]); j++; }
    else { console.log(`order-diff node=${seqA[i]} py=${seqB[j]}`); i++; j++; }
  } else { console.log("only-in-node:", seqA[i]); i++; }
}
while (i < seqA.length) { console.log("only-in-node:", seqA[i]); i++; }
while (j < seqB.length) { console.log("only-in-py:", seqB[j]); j++; }
// addScript 源指纹（长度 + 是否含 webSocketMock 特征）
for (const [name, ev] of [["node", a], ["py", b]]) {
  console.log(`== ${name} addScript 指纹 ==`);
  for (const e of ev) {
    if (e.method !== "Page.addScriptToEvaluateOnNewDocument") continue;
    const src = String(e.params.source ?? "");
    console.log(` len=${src.length} hasWsMock=${src.includes("WebSocketMock")} hasDispatch=${src.includes("__pwWebSocketDispatch")} world=${e.params.worldName ?? "-"} head=${JSON.stringify(src.slice(0, 60))}`);
  }
  for (const e of ev) {
    if (e.method !== "Runtime.addBinding") continue;
    console.log(` addBinding name=${e.params.name}`);
  }
}
