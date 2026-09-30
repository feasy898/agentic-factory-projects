// pf/src/shared.ts — make 与 e2e-matrix 共用的判定输入推导（oracle 侧同源函数移植）。
//
// CHK10 判定输入（反馈行动 3）：首语言的 标题/教程/胜/CTA/分 文案必须真实上屏；
// lose 不要求——自动试玩走最优线必胜，lose 文案无出场机会（如实记录，oracle 注释照抄）。
// 构建真实嵌入的用户替换素材（旁车清单 .assets.json）必须像素对账通过。

import { readFileSync } from "node:fs";

import { MakeError } from "./util.ts";

/** CHK10 --require-text 推导：与 oracle pfcore/make.py required_texts 完全同源。 */
export function requiredTextsFor(spec: Record<string, unknown>, locale: string): string[] {
  const specRec = spec as {
    meta?: { title?: unknown }; i18n?: { strings?: Record<string, Record<string, unknown>> };
    flow?: { tutorial?: { enabled?: boolean }; endScreen?: { ctaKey?: unknown; showScore?: boolean } };
  };
  const loc = (key: string): string => {
    const v = specRec.i18n?.strings?.[locale]?.[key];
    return typeof v === "string" ? v : "";
  };
  const flow = specRec.flow ?? {};
  const endScreen = flow.endScreen ?? {};
  const texts: string[] = [String(specRec.meta?.title ?? "")];
  if ((flow.tutorial ?? { enabled: true }).enabled !== false) texts.push(loc("tutorial"));
  texts.push(loc("win"));
  texts.push(loc(String(endScreen.ctaKey ?? "cta")));
  if ((endScreen.showScore ?? true) !== false) texts.push(loc("score"));
  return texts.filter((t) => t.length > 0);
}

/** CHK10 --require-sprite：构建旁车 <preview>.assets.json 里真实内联的素材键。 */
export function requiredSpritesFor(previewHtml: string): string[] {
  try {
    const mf = JSON.parse(readFileSync(`${previewHtml}.assets.json`, "utf8")) as {
      sprites?: Array<{ spriteKey?: unknown }>;
    };
    return (mf.sprites ?? [])
      .map((s) => (typeof s.spriteKey === "string" ? s.spriteKey : ""))
      .filter((k) => k.length > 0);
  } catch {
    return []; // 旁车缺失/不可读 → 不提要求（构建日志已对缺失素材告警）
  }
}

/** 规则库只读加载；不可读抛用法/环境错误（exit 2）。 */
export function loadRules(rulesPath: string): Record<string, unknown> {
  try {
    return JSON.parse(readFileSync(rulesPath, "utf8")) as Record<string, unknown>;
  } catch (err) {
    throw new MakeError(`规则库不可读：${rulesPath}（${String(err)}）`, 2);
  }
}

/** spec 文件读取 + JSON 解析（make/matrix 用；不可读抛用法/环境错误 exit 2）。 */
export function readSpecJson(specPath: string): Record<string, unknown> {
  try {
    return JSON.parse(readFileSync(specPath, "utf8")) as Record<string, unknown>;
  } catch (err) {
    throw new MakeError(`spec 不可读：${specPath}（${String(err)}）`, 2);
  }
}
