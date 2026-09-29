// test/assets.test.mjs — 数据资产验收：登记册逐项 sha 重算（真实执行 verify 脚本）、
// 渠道规则锚点、vendor bundle 在位、specs-eval 结构完整。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');

test('verify-reused-assets.mjs 真实执行 exit 0（登记册全项 sha256 逐项重算一致，项数随模块批次增长）', () => {
  // 项数从登记册 JSON 动态取（M1.1 时 16 项；各模块批次按纪律追加登记，写死会假失败）。
  // 锚定小节与 verify-reused-assets.mjs 同一正则，防误取文档其他 json 围栏。
  const md = readFileSync(join(root, 'REUSED-ASSETS.md'), 'utf8');
  const registry = JSON.parse(md.match(/### 机器可读登记册[\s\S]*?```json\r?\n([\s\S]*?)```/)[1]);
  const expectCount = registry.assets.length;
  const res = spawnSync(process.execPath, ['scripts/verify-reused-assets.mjs'], { cwd: root, encoding: 'utf8' });
  assert.equal(res.status, 0, `stdout=${res.stdout}\nstderr=${res.stderr}`);
  assert.match(res.stdout, new RegExp(`${expectCount} 项已核对`));
  assert.equal((res.stdout.match(/MATCH /g) ?? []).length, expectCount);
});

test('channel-rules 锚点：rulesVersion 1.1.0 + 七渠道', () => {
  const rules = JSON.parse(readFileSync(join(root, 'channel-rules', 'channel-rules.json'), 'utf8'));
  assert.equal(rules.rulesVersion, '1.1.0');
  assert.deepEqual(
    Object.keys(rules.channels).sort(),
    ['applovin', 'google', 'meta', 'mintegral', 'preview', 'tiktok', 'unity'],
  );
});

test('vendor 中性引擎 bundle 在位且体量在锚定区间（~1.2MB，版本锚 3.88.2）', () => {
  const p = join(root, 'packages', 'templates', 'vendor', 'engine.js');
  const size = statSync(p).size;
  assert.ok(size > 1_000_000 && size < 1_500_000, `engine.js 体量异常: ${size}`);
});

test('specs-eval 目录结构完整：assets/demo-zh 素材在位', () => {
  assert.ok(statSync(join(root, 'specs-eval', 'assets', 'demo-zh', 'piece-0.png')).isFile());
  const badDir = readdirSync(join(root, 'specs-eval', 'bad'));
  assert.equal(badDir.filter((f) => f.endsWith('.json')).length, 6);
});
