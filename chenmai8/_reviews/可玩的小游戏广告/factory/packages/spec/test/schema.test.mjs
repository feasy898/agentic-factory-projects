// packages/spec/test/schema.test.mjs — M1.1 ajv 实测骨架。
// 判定矩阵以本机 ajv 8.20.0 实测为准（2026-09-30）：
//   schema-only 通过：golden×4 + demo-zh；bad/02(不可解)/04(缺 locale 串) 属不变式层（I1–I5，M1 落地）；
//   schema-only 拦截：bad/01(缺 flow)/03(时长超 30)/05(bad url)/06(未知模板)；
//   spike-manifest 非 PlayableSpec（不进 spec 校验矩阵，仅要求可解析）。
// 11 件完整裁定矩阵（错误码集/校验次序）由 M1 模块任务按决策 §2.1 落地。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import Ajv2020 from 'ajv/dist/2020.js';

const here = dirname(fileURLToPath(import.meta.url));
const specPkg = join(here, '..');            // packages/spec
const root = join(specPkg, '..', '..');      // factory 根

const schema = JSON.parse(readFileSync(join(specPkg, 'playable-spec.schema.json'), 'utf8'));
const ajv = new Ajv2020({ strict: false, allErrors: true });
const validate = ajv.compile(schema);

function loadSpec(rel) {
  return JSON.parse(readFileSync(join(root, rel), 'utf8'));
}

test('schema 契约锚点：draft 2020-12 / specVersion 恒 1.0.0 / required 七键', () => {
  assert.equal(schema.$schema, 'https://json-schema.org/draft/2020-12/schema');
  assert.equal(schema.properties.specVersion.const, '1.0.0');
  assert.deepEqual(
    [...schema.required].sort(),
    ['assets', 'channels', 'flow', 'game', 'i18n', 'meta', 'qc', 'specVersion'],
  );
});

test('golden×4 + demo-zh 通过 schema 校验', () => {
  for (const f of ['golden-match3.json', 'golden-merge.json', 'golden-pullpin.json', 'golden-sort.json', 'demo-zh.json']) {
    const ok = validate(loadSpec(join('specs-eval', f)));
    assert.ok(ok, `${f} 应通过 schema：${JSON.stringify(validate.errors ?? [])}`);
  }
});

test('bad/01,03,05,06 被 schema 拦截（缺失必填/时长上限/url 模式/模板枚举）', () => {
  const expectFail = ['01-missing-field.json', '03-duration-over-budget.json', '05-bad-url.json', '06-unknown-template.json'];
  for (const f of expectFail) {
    const ok = validate(loadSpec(join('specs-eval/bad', f)));
    assert.equal(ok, false, `bad/${f} 应被 schema 拦截`);
  }
  // bad/02、bad/04 在 schema 层合法——由 invariants（M1 落地）拦截，勿在此放宽。
  for (const f of ['02-pullpin-unsolvable.json', '04-missing-locale-strings.json']) {
    const ok = validate(loadSpec(join('specs-eval/bad', f)));
    assert.equal(ok, true, `bad/${f} schema 层应放行（不变式层拦截）`);
  }
});

test('specs-eval 全部 JSON 可解析（golden×4 + bad×6 + demo-zh + spike-manifest）', () => {
  const top = readdirSync(join(root, 'specs-eval')).filter((f) => f.endsWith('.json'));
  const bad = readdirSync(join(root, 'specs-eval', 'bad')).filter((f) => f.endsWith('.json'));
  assert.equal(top.length, 6); // golden×4 + demo-zh + spike-manifest
  assert.equal(bad.length, 6);
  for (const f of [...top.map((f) => join('specs-eval', f)), ...bad.map((f) => join('specs-eval/bad', f))]) {
    assert.doesNotThrow(() => loadSpec(f), `${f} 应可解析`);
  }
});
