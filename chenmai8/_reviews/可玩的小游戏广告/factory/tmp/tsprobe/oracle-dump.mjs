// 用途：以子进程驱动 oracle 的 JS 镜像（repo/packages/spec），dump 11 件的 {ok,{path,code} 集}。
// 只读 oracle（不改任何文件）；结果作为 M1.2a 差分基线（F1 契约层差分，决策 §3.1/§3.2）。
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { validateSpec } from "../../../repo/packages/spec/src/validate.mjs";

const ROOT = path.resolve(import.meta.dirname, "..", "..");
const files = [
  "specs-eval/golden-match3.json", "specs-eval/golden-merge.json",
  "specs-eval/golden-pullpin.json", "specs-eval/golden-sort.json",
  "specs-eval/demo-zh.json",
  ...readdirSync(path.join(ROOT, "specs-eval/bad")).filter(f => f.endsWith(".json")).sort().map(f => `specs-eval/bad/${f}`),
];
for (const rel of files) {
  const spec = JSON.parse(readFileSync(path.join(ROOT, rel), "utf8"));
  const r = validateSpec(spec);
  const set = r.errors.map(e => `${e.path} [${e.code}]`);
  console.log(`${rel}\t${r.ok ? "OK" : "INVALID"}\t${r.ok ? "" : set.join(" | ")}`);
}
