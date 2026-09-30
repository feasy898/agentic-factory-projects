// 驱动华为 ets-loader 内置 ArkTSLinter 对本仓 packages/ 做官方 ArkTS 检查（WSL 内运行）
// 用法: node arkts-check.js <repoRoot>
'use strict';
const fs = require('fs');
const path = require('path');
const repo = process.argv[2] || '/mnt/c/Users/Administrator/.zcode/workspace/default/ohos-tailscale';
const ts = require('/home/dev/sdk/ets/ets/build-tools/ets-loader/node_modules/typescript');

function walk(dir, ext, out) {
  for (const f of fs.readdirSync(dir)) {
    const p = path.join(dir, f);
    const st = fs.statSync(p);
    if (st.isDirectory()) {
      walk(p, ext, out);
    } else if (p.endsWith(ext)) {
      out.push(p);
    }
  }
  return out;
}

const scanExt = process.env.SCAN_EXT || '.ts';
const scanRoot = process.env.SCAN_ROOT || path.join(repo, 'packages');
const files = walk(scanRoot, scanExt, []);
console.log('scanning ' + files.length + ' ' + scanExt + ' files under ' + scanRoot);
const options = {
  noEmit: true,
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.NodeNext,
  moduleResolution: ts.ModuleResolutionKind.NodeNext,
  skipLibCheck: true,
  strict: true,
  allowImportingTsExtensions: true,
  types: [],
};
const host = ts.createWatchCompilerHost(
  files,
  options,
  ts.sys,
  ts.createSemanticDiagnosticsBuilderProgram,
  () => undefined,
  () => undefined,
);
host.afterProgramCreate = (builderProgram) => {
  let diags = [];
  try {
    const linter = ts.ArkTSLinter_1_0 || ts.ArkTSLinter_1_1;
    diags = linter.runArkTSLinter(builderProgram, undefined, undefined, 'ArkTS_1_0');
  } catch (e) {
    console.error('runArkTSLinter threw:', e && e.message);
    process.exit(2);
  }
  console.log('arkts linter diagnostics: ' + diags.length);
  const byFile = new Map();
  for (const d of diags) {
    const f = d.file;
    let loc = '<no-file>';
    if (f) {
      const pos = f.getLineAndCharacterOfPosition(d.start || 0);
      loc = f.fileName.replace(scanRoot + '/', '').replace(repo + '/', '') + ':' + (pos.line + 1) + ':' + (pos.character + 1);
    }
    const msg = typeof d.messageText === 'string' ? d.messageText : JSON.stringify(d.messageText);
    const fileKey = loc.split(':')[0];
    if (!byFile.has(fileKey)) byFile.set(fileKey, []);
    byFile.get(fileKey).push(loc + ' [' + d.code + '] ' + msg);
  }
  for (const [f, lines] of byFile) {
    console.log('== ' + f + ' (' + lines.length + ')');
    for (const l of lines.slice(0, 6)) console.log('   ' + l.slice(0, 220));
  }
  process.exit(0);
};
ts.createWatchProgram(host);

let diags = [];
const byFile = new Map();
