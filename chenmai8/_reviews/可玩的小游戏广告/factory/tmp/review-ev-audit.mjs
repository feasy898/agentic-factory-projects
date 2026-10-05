// 复核脚本：审计 qacore/src 内 ev(page, …) 全部实参是否为仓内冻结字符串字面量
import { readFileSync } from "node:fs";

const files = ["qacore/src/autoplay.ts", "qacore/src/run.ts", "qacore/src/probe.ts", "qacore/src/checks.ts"];
let multi = 0, nonLiteral = 0, interpolated = 0;
for (const f of files) {
  const lines = readFileSync(f, "utf8").split("\n");
  lines.forEach((l, i) => {
    const m = l.match(/ev\(page,\s*(.*)$/);
    if (!m) return;
    const inline = m[1].trim();
    if (inline === "" || inline === ");") {
      // 多行调用：看续行（下一个非空行）
      let j = i + 1;
      while (j < lines.length && !lines[j].trim()) j++;
      const cont = (lines[j] || "").trim();
      multi++;
      if (!/^["'`]/.test(cont)) { nonLiteral++; console.log(`【续行非字符串字面量】${f}:${i + 1} -> ${cont.slice(0, 90)}`); }
      else if (cont.startsWith("`") && /\$\{/.test(cont)) { interpolated++; console.log(`【模板串插值】${f}:${i + 1} -> ${cont.slice(0, 90)}`); }
    } else {
      if (!/^["'`]/.test(inline)) { nonLiteral++; console.log(`【实参非字符串字面量】${f}:${i + 1} -> ${inline.slice(0, 90)}`); }
      else if (inline.startsWith("`") && /\$\{/.test(inline)) { interpolated++; console.log(`【模板串插值】${f}:${i + 1} -> ${inline.slice(0, 90)}`); }
    }
  });
}
console.log(`\n审计汇总：多行调用 ${multi}，非字面量实参 ${nonLiteral}，模板插值 ${interpolated}`);
