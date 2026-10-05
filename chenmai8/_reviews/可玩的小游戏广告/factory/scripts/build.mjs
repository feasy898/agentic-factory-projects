// build.mjs — esbuild 构建链入口（M1.1 脚手架）。
// 职责：遍历 workspaces 包（packages/* 与 packages/templates/*，坑 14），
// 包内有 "build" 脚本则执行（M3 模板契约：esbuild iife + escapeForInlineScript + PF_SPEC/
// PF_LOCALE/PF_ASSETS + .assets.json 旁车，坑 7）；无任何可构建包时空跑 exit 0。
import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));

function packageDirs() {
  const dirs = [];
  for (const pattern of ['packages', join('packages', 'templates')]) {
    const base = join(root, pattern);
    if (!existsSync(base)) continue;
    for (const name of readdirSync(base, { withFileTypes: true })) {
      if (!name.isDirectory()) continue;
      const dir = join(base, name.name);
      if (existsSync(join(dir, 'package.json'))) dirs.push(dir);
    }
  }
  return dirs.sort();
}

const buildable = packageDirs().filter((dir) => {
  const pkg = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8'));
  return Boolean(pkg.scripts?.build);
});

if (buildable.length === 0) {
  console.log('build: 无包定义 build 脚本，空跑通过（exit 0）');
  process.exit(0);
}

let failed = false;
for (const dir of buildable) {
  const rel = dir.slice(root.length + 1);
  console.log(`build: ${rel}`);
  const res = spawnSync('npm', ['run', 'build', '--silent'], { cwd: dir, stdio: 'inherit', shell: true });
  if (res.status !== 0) {
    console.error(`build: ${rel} 失败（exit ${res.status}）`);
    failed = true;
  }
}
process.exit(failed ? 1 : 0);
