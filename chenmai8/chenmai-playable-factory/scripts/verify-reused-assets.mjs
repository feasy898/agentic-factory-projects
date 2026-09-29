// verify-reused-assets.mjs — 重算 REUSED-ASSETS.md 机器可读登记册中每个资产的
// sha256 与字节数，漂移即 exit 1（数据契约零变更守卫，AGENTS.md「数据资产字节复用」）。
// 用法：node scripts/verify-reused-assets.mjs  （npm test 内亦真实执行）
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const mdPath = join(root, 'REUSED-ASSETS.md');
const md = readFileSync(mdPath, 'utf8');

// 提取「机器可读登记册」小节的 ```json 围栏（文档另有 markdown 表格，勿误取）。
const sectionMatch = md.match(/### 机器可读登记册[\s\S]*?```json\r?\n([\s\S]*?)```/);
if (!sectionMatch) {
  console.error('verify-reused-assets: 未找到机器可读登记册 JSON 围栏');
  process.exit(1);
}
let registry;
try {
  registry = JSON.parse(sectionMatch[1]);
} catch (err) {
  console.error('verify-reused-assets: 登记册 JSON 解析失败:', err.message);
  process.exit(1);
}
if (registry.registryVersion !== 1 || !Array.isArray(registry.assets) || registry.assets.length === 0) {
  console.error('verify-reused-assets: 登记册结构非法（registryVersion/assets）');
  process.exit(1);
}

const problems = [];
const lines = [];
for (const entry of registry.assets) {
  const abs = join(root, entry.path);
  let buf;
  try {
    buf = readFileSync(abs);
  } catch {
    problems.push(`${entry.path}: 文件缺失`);
    continue;
  }
  const sha = createHash('sha256').update(buf).digest('hex');
  const sizeOk = buf.length === entry.bytes;
  const shaOk = sha === entry.sha256;
  lines.push(`${shaOk && sizeOk ? 'MATCH ' : 'DIFFER'} ${entry.path} (${buf.length}B)`);
  if (!shaOk) problems.push(`${entry.path}: sha256 漂移 实际=${sha} 登记=${entry.sha256}`);
  if (!sizeOk) problems.push(`${entry.path}: 字节数漂移 实际=${buf.length} 登记=${entry.bytes}`);
}

for (const l of lines) console.log(l);
console.log(`verify-reused-assets: ${registry.assets.length} 项已核对`);
if (problems.length > 0) {
  console.error('verify-reused-assets: 失败 ——');
  for (const p of problems) console.error('  -', p);
  process.exit(1);
}
console.log('verify-reused-assets: OK');
