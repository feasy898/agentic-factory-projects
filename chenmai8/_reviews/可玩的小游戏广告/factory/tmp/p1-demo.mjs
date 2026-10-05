// P1 演示：模板侧注册 check(spec)，validateSpec 进程内消费（一次性脚本，产物为零）。
import { readFileSync } from "node:fs";
import { clearTemplateChecks, registerTemplateCheck, listTemplateChecks } from "../packages/spec/src/invariants.ts";
import { validateSpec } from "../packages/spec/src/validate.ts";

clearTemplateChecks();
registerTemplateCheck({ template: "match3", check: () => ["I6-demo: 模板侧 check 已在进程内执行（演示）"] });
console.log("已注册模板 check:", JSON.stringify(listTemplateChecks()));
const g = JSON.parse(readFileSync("specs-eval/golden-match3.json", "utf8"));
const r = validateSpec(g);
console.log("golden + 恒败 check → ok=", r.ok, "codes=", JSON.stringify(r.errors.map((e) => e.code)));
registerTemplateCheck({ template: "match3", check: (s) => (s.game.cols < 6 ? ["I6-demo2: cols<6"] : []) });
const r2 = validateSpec(g);
console.log("追加 cols<6 check（golden cols 满足）→ ok=", r2.ok, "codes=", JSON.stringify(r2.errors.map((e) => e.code)));
