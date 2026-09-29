// test/toolchain.test.mjs — 栈纪律守卫：Node ≥22、workspaces 双 glob（坑 14）、
// 构建链空跑 exit 0、单栈守卫（树内零 .py）。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');

test('运行时 Node ≥ 22（决策 §1 单栈锚）', () => {
  const major = Number(process.versions.node.split('.')[0]);
  assert.ok(major >= 22, `Node ${process.versions.node} < 22`);
});

test('workspaces 同时含 packages/* 与 packages/templates/*（坑 14）', () => {
  const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
  assert.deepEqual(pkg.workspaces, ['packages/*', 'packages/templates/*']);
  assert.equal(pkg.engines.node, '>=22');
});

test('npm run build exit 0（批次 2 起：模板包真实构建；批次 1 曾为无包空跑）', () => {
  const res = spawnSync('npm', ['run', 'build', '--silent'], { cwd: root, encoding: 'utf8', shell: true, maxBuffer: 16 * 1024 * 1024 });
  assert.equal(res.status, 0, `stdout=${res.stdout}\nstderr=${res.stderr}`);
  assert.doesNotMatch(res.stdout, /失败（exit/, 'build 脚本零失败行');
  assert.match(res.stdout, /构建完成/, '至少一个包真实构建完成（模板包 build 契约）');
});

test('单栈守卫：入库树范围（除 node_modules/.git/tmp/artifacts）零 .py 文件', () => {
  const offenders = [];
  const skip = new Set(['node_modules', '.git', 'tmp', 'artifacts']);
  (function walk(dir) {
    for (const ent of readdirSync(dir, { withFileTypes: true })) {
      if (skip.has(ent.name)) continue;
      const p = join(dir, ent.name);
      if (ent.isDirectory()) walk(p);
      else if (ent.name.endsWith('.py')) offenders.push(p);
    }
  })(root);
  assert.deepEqual(offenders, []);
});
