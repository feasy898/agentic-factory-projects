// webui/test/specgen.test.mjs — specgen 组装器单测（oracle specgen.py 行为语义对齐）。
// 运行：node --test webui/test/specgen.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

import { match3Board, match3FindMove, pullpinLevelRoles, pullpinSimulate } from "../../packages/spec/src/invariants.ts";
import { validateSpec } from "../../packages/spec/src/validate.ts";
import {
  DEFAULT_CHANNELS,
  SpecBuildError,
  assembleSpec,
  defaultsTable,
  localeDefaults,
  sanitizeProjectId,
} from "../specgen.ts";

test("sanitizeProjectId：清洗为 ^[a-z0-9][a-z0-9-]{0,63}$，洗空回退 webui-<模板>", () => {
  assert.equal(sanitizeProjectId("My Game! 2026", "match3"), "my-game-2026");
  assert.equal(sanitizeProjectId("  --__  ", "merge"), "webui-merge");
  assert.equal(sanitizeProjectId("-abc-", "pullpin"), "abc");
  assert.equal(sanitizeProjectId("9lives", "match3"), "9lives");
  const long = "x".repeat(100);
  assert.equal(sanitizeProjectId(long, "match3").length, 64);
});

test("localeDefaults/defaultsTable：五键齐全 + 模板×语言全覆盖（I5 恒可满足）", () => {
  for (const tpl of ["match3", "merge", "pullpin"]) {
    for (const loc of ["zh", "en", "ja", "ko", "pt-BR", "de", "ar"]) {
      const d = localeDefaults(tpl, loc);
      for (const k of ["cta", "tutorial", "win", "lose", "score"]) {
        assert.ok(typeof d[k] === "string" && d[k].length > 0, `${tpl}/${loc}/${k} 非空`);
      }
      // title 只在 defaultsTable 层下发（oracle locale_defaults 不含 title 同形）
      const entry = defaultsTable()[tpl][loc];
      assert.ok(entry.title && entry.title.length > 0, `${tpl}/${loc} title 非空`);
      assert.equal(entry.tutorial, d.tutorial);
    }
  }
  const table = defaultsTable();
  assert.deepEqual(Object.keys(table).sort(), ["match3", "merge", "pullpin"]);
  assert.equal(table["match3"]["zh"].cta, "立即下载");
  assert.equal(table["pullpin"]["en"].tutorial, "Tap to pull the pin and rescue!");
  // merge/pullpin 无全语言教程 → 回退 en
  assert.equal(table["merge"]["ja"].tutorial, "Drag to merge and upgrade!");
});

test("assembleSpec（match3）：组装即过 schema+不变式双校验；表单覆盖文案生效", () => {
  const spec = assembleSpec("match3", {
    projectId: "My Demo 1", title: "自定义标题", locale: "zh",
    texts: { cta: "马上玩", tutorial: "拖！", win: "赢", lose: "输", score: "分" },
    seed: 20260930, landingUrl: "https://example.com/x", nearWin: true,
  });
  assert.equal(spec.meta.projectId, "my-demo-1");
  assert.equal(spec.meta.seed, 20260930);
  assert.deepEqual(spec.i18n.locales, ["zh"]);
  assert.equal(spec.i18n.strings.zh.cta, "马上玩");
  assert.equal(spec.channels.targets.join(","), DEFAULT_CHANNELS.join(","));
  const issues = validateSpec(spec).errors;
  assert.deepEqual(issues, [], `组装 spec 必须零 issue：${JSON.stringify(issues)}`);
});

test("assembleSpec（match3）：留空 seed 自动选可解 seed（I3 预检）", () => {
  for (let i = 0; i < 5; i++) {
    const spec = assembleSpec("match3", {});
    assert.ok(spec.meta.seed >= 0 && spec.meta.seed < 2 ** 31);
    assert.ok(match3FindMove(match3Board(spec.meta.seed, 6, 6, 5)) !== null, "随机 seed 必可解");
  }
});

test("assembleSpec（match3）：指定无可行步 seed → SpecBuildError（I3 预检拦截）", () => {
  // 找一个确定性的死局 seed（6×6×5；首个死局在 seed≈1.4 万，须搜到）
  let dead = null;
  for (let s = 1; s < 50000; s++) {
    if (match3FindMove(match3Board(s, 6, 6, 5)) === null) {
      dead = s;
      break;
    }
  }
  assert.ok(dead !== null, "应能找到死局 seed（盘面生成器存在死局）");
  assert.throws(() => assembleSpec("match3", { seed: dead }), (e) => e instanceof SpecBuildError
    && e.messages[0].includes("无可行步"));
});

test("assembleSpec（pullpin）：orderSolution 实算 + 模拟复核可解（I1）", () => {
  const seed = 20260930;
  const spec = assembleSpec("pullpin", { locale: "en", seed });
  assert.equal(spec.game.template, "pullpin");
  assert.equal(spec.meta.seed, seed);
  const order = spec.game.params.orderSolution;
  assert.equal(order.length, 3, "3 关");
  const roles = pullpinLevelRoles(seed, 3, 3);
  for (let i = 0; i < 3; i++) {
    const [rescuee, hazard] = roles[i];
    const lv = order[i];
    // 每关 = 中性针升序在前 + 救援针收尾（hazard 永不入序——golden 同约定）
    assert.ok(!lv.includes(hazard), `L${i} hazard 不入序`);
    assert.equal(lv[lv.length - 1], rescuee, `L${i} 救援针收尾`);
    const neutrals = [];
    for (let p = 0; p < 3; p++) if (p !== rescuee && p !== hazard) neutrals.push(p);
    assert.deepEqual(lv.slice(0, -1), neutrals, `L${i} 中性针升序在前`);
    const [solved, reason] = pullpinSimulate(lv, rescuee, hazard);
    assert.ok(solved, `L${i} 模拟复核可解（${reason}）`);
  }
  const issues = validateSpec(spec).errors;
  assert.deepEqual(issues, [], `pullpin 组装 spec 必须零 issue：${JSON.stringify(issues)}`);
});

test("assembleSpec（merge）：槽位缺省指向主题路径（缺失→程序化贴图回退）", () => {
  const spec = assembleSpec("merge", {});
  assert.equal(spec.game.template, "merge");
  assert.equal(spec.assets.sprites["tier-1"], "assets/theme-a/tier-1.png");
  assert.equal(spec.assets.background, "assets/theme-a/bg-portrait.png");
  assert.deepEqual(Object.keys(spec.assets.audio), ["tap", "win"]);
});

test("assembleSpec 负向：未知模板/未知语言/未知文案键/超长标题/坏 landingUrl → SpecBuildError", () => {
  assert.throws(() => assembleSpec("not-a-template"), (e) => e instanceof SpecBuildError
    && e.messages[0].includes("未知模板"));
  assert.throws(() => assembleSpec("match3", { locale: "xx" }), (e) => e instanceof SpecBuildError
    && e.messages[0].includes("不支持的语言"));
  assert.throws(() => assembleSpec("match3", { texts: { nope: "x" } }), (e) => e instanceof SpecBuildError
    && e.messages[0].includes("未知文案键"));
  assert.throws(() => assembleSpec("match3", { title: "长".repeat(81) }), (e) => e instanceof SpecBuildError
    && e.messages[0].includes("80 字符"));
  assert.throws(() => assembleSpec("match3", { landingUrl: "ftp://x" }), (e) => e instanceof SpecBuildError
    && e.messages[0].includes("landingUrl"));
  assert.throws(() => assembleSpec("match3", { landingUrl: "https://a b.com" }), (e) => e instanceof SpecBuildError
    && e.messages[0].includes("landingUrl"));
  // 留空 landingUrl → 内置缺省
  assert.equal(assembleSpec("match3", {}).flow.endScreen.landingUrl, "https://example.com/playable-lp");
});
