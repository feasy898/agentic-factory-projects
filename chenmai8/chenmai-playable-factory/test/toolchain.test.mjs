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

test('npm run build 空跑 exit 0（尚无包定义 build 脚本）', () => {
  const res = spawnSync('npm', ['run', 'build', '--silent'], { cwd: root, encoding: 'utf8', shell: true });
  assert.equal(res.status, 0, `stdout=${res.stdout}\nstderr=${res.stderr}`);
  assert.match(res.stdout, /空跑通过/);
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
