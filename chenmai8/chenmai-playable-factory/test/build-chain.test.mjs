// test/build-chain.test.mjs — esbuild 构建链 smoke：用 esbuild API 真实打包一个
// 双模块入口（iife），断言产物含标记且无残留 import 语句（链路可用，exit 语义真实）。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as esbuild from 'esbuild';

const here = dirname(fileURLToPath(import.meta.url));

test('esbuild 构建链：双模块 iife 打包产物正确', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'pf-build-chain-'));
  try {
    writeFileSync(
      join(dir, 'lib.mjs'),
      'export const PF_TEST_MARK = "pf-build-chain-ok";\n',
      'utf8',
    );
    writeFileSync(
      join(dir, 'entry.mjs'),
      'import { PF_TEST_MARK } from "./lib.mjs";\nglobalThis.PF_TEST_OUT = PF_TEST_MARK;\n',
      'utf8',
    );
    const result = await esbuild.build({
      entryPoints: [join(dir, 'entry.mjs')],
      bundle: true,
      format: 'iife',
      target: 'es2019',
      write: false,
    });
    const out = result.outputFiles[0].text;
    assert.match(out, /pf-build-chain-ok/);
    assert.doesNotMatch(out, /^\s*import\s/m, 'iife 产物不应残留 import 语句');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
