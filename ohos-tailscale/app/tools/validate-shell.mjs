#!/usr/bin/env node
/**
 * app/ 壳工程静态资源离线校验（零依赖，Node 22+）。
 *
 * 背景：app/ 壳从未编译（无 DevEco/SDK，见 docs/build-feasibility-linux.md）。
 * 本脚本在纯 Node 侧把「不需要编译器也能判」的静态约束全部机检：
 *   V1  所有 .json5/.json 配置可解析（//- 与 [//] 注释、尾逗号剥除后 JSON.parse）
 *   V2  module.json5：mainElement 指向存在的 ability；abilities/extensionAbilities
 *       的 srcEntry 文件在盘；extensionAbilities 含 type:"vpn"（README §2.5 已知坑前置自检）
 *   V3  requestPermissions 含 INTERNET 与 GET_NETWORK_INFO（README §3 基线）
 *   V4  main_pages.json 路由表 ↔ pages/*.ets 双向对账
 *   V5  $r('app.string|color|media.*') 引用 ↔ 资源定义（string.json/color.json/media 目录）对账
 *   V6  bundleName：AppScope/app.json5 ↔ Index.ets BUNDLE_NAME 常量一致（README §6.10）
 *   V7  extensionAbilities[].name ↔ Index.ets VPN_ABILITY_NAME 常量一致
 *   V8  占位图标尺寸：app_icon.png 216×216、icon.png/startIcon.png 96×96（PNG IHDR 实读）
 * 退出码：0 = 全过；1 = 有 FAIL。输出每项 [PASS]/[FAIL] 明细供留痕。
 */
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const results = [];
let failed = 0;

const check = (id, ok, detail) => {
  if (!ok) failed += 1;
  results.push((ok ? '[PASS] ' : '[FAIL] ') + id + (detail ? ' — ' + detail : ''));
};

const read = (rel) => readFileSync(join(ROOT, rel), 'utf8');
const exists = (rel) => existsSync(join(ROOT, rel));

/** 剥 //- 与 [//] 注释（字符串感知）+ 尾逗号（字符串感知），返回可 JSON.parse 文本。 */
const stripJson5 = (text) => {
  let out = '';
  let i = 0;
  let quote = '';
  while (i < text.length) {
    const ch = text[i];
    if (quote !== '') {
      out += ch;
      if (ch === '\\') {
        out += text[i + 1] ?? '';
        i += 2;
        continue;
      }
      if (ch === quote) quote = '';
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      out += ch;
      i += 1;
      continue;
    }
    if (ch === '/' && text[i + 1] === '/') {
      while (i < text.length && text[i] !== '\n') i += 1;
      continue;
    }
    if (ch === '/' && text[i + 1] === '*') {
      i += 2;
      while (i < text.length && !(text[i] === '*' && text[i + 1] === '/')) i += 1;
      i += 2;
      continue;
    }
    if (ch === ',') {
      let j = i + 1;
      while (j < text.length && /\s/.test(text[j])) j += 1;
      if (text[j] === '}' || text[j] === ']') {
        i += 1;
        continue;
      }
    }
    out += ch;
    i += 1;
  }
  return out;
};

/** 解析 .json5/.json；失败返回 null 并登记 V1 FAIL。 */
const parseConfig = (rel) => {
  if (!exists(rel)) {
    check('V1 ' + rel, false, 'file missing');
    return null;
  }
  try {
    const value = JSON.parse(stripJson5(read(rel)));
    check('V1 ' + rel, true);
    return value;
  } catch (e) {
    check('V1 ' + rel, false, String(e && e.message ? e.message : e));
    return null;
  }
};

/** PNG IHDR 尺寸（宽, 高）；非 PNG 返回 null。 */
const pngSize = (rel) => {
  const buf = readFileSync(join(ROOT, rel));
  if (buf.length < 24 || buf[0] !== 0x89 || buf[1] !== 0x50) return null;
  return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) };
};

// ---- V1/V2/V3/V6/V7：配置解析与模块清单 ----
const appJson5 = parseConfig('AppScope/app.json5');
const buildProfile = parseConfig('build-profile.json5');
const hvigorConfig = parseConfig('hvigor/hvigor-config.json5');
const ohPackage = parseConfig('oh-package.json5');
const entryBuildProfile = parseConfig('entry/build-profile.json5');
const entryOhPackage = parseConfig('entry/oh-package.json5');
const moduleJson = parseConfig('entry/src/main/module.json5');
const mainPages = parseConfig('entry/src/main/resources/base/profile/main_pages.json');
const appStrings = parseConfig('AppScope/resources/base/element/string.json');
const entryStrings = parseConfig('entry/src/main/resources/base/element/string.json');
const entryColors = parseConfig('entry/src/main/resources/base/element/color.json');

// 资源名集合（V5/V5b 对账共用；AppScope 与 entry 的 string.json 合并——app 级资源全局可见）
const stringNames = new Set((entryStrings?.string ?? []).concat(appStrings?.string ?? []).map((s) => s.name));
const colorNames = new Set((entryColors?.color ?? []).map((s) => s.name));
const mediaDir = 'entry/src/main/resources/base/media';
const mediaNames = new Set(existsSync(join(ROOT, mediaDir)) ? readdirSync(join(ROOT, mediaDir)) : []);

if (moduleJson !== null) {
  // 官方 module.json5 顶层是 {"module": {...}}} 包裹；兼容无包裹形态。
  const mod = moduleJson.module ?? moduleJson;
  const abilities = Array.isArray(mod.abilities) ? mod.abilities : [];
  const extensions = Array.isArray(mod.extensionAbilities) ? mod.extensionAbilities : [];
  const srcEntryOk = (rel) => exists('entry/src/main/' + rel);
  for (const a of abilities) {
    check('V2 abilities[' + String(a.name) + '].srcEntry=' + String(a.srcEntry), srcEntryOk(a.srcEntry));
  }
  for (const e of extensions) {
    check('V2 extensionAbilities[' + String(e.name) + '].srcEntry=' + String(e.srcEntry), srcEntryOk(e.srcEntry));
    check('V2 extensionAbilities[' + String(e.name) + '].type===' + String(e.type), e.type === 'vpn');
  }
  const names = abilities.map((a) => a.name);
  check('V2 mainElement=' + String(mod.mainElement), names.indexOf(mod.mainElement) >= 0);

  const perms = (mod.requestPermissions ?? []).map((p) => p.name);
  check('V3 ohos.permission.INTERNET declared', perms.indexOf('ohos.permission.INTERNET') >= 0);
  check('V3 ohos.permission.GET_NETWORK_INFO declared', perms.indexOf('ohos.permission.GET_NETWORK_INFO') >= 0);

  // V5b：module.json5 内 $string:/$color:/$media: 引用对账（如 startWindowBackground 的 $color:start_window_background）
  const rawModule = read('entry/src/main/module.json5');
  const resRefs = rawModule.matchAll(/\$(string|color|media):([A-Za-z0-9_]+)/g);
  const seen = new Set();
  for (const m of resRefs) {
    const key = m[1] + ':' + m[2];
    if (seen.has(key)) continue;
    seen.add(key);
    if (m[1] === 'string') check('V5b module.json5 $string:' + m[2], stringNames.has(m[2]));
    if (m[1] === 'color') check('V5b module.json5 $color:' + m[2], colorNames.has(m[2]));
    if (m[1] === 'media') check('V5b module.json5 $media:' + m[2], mediaNames.has(m[2] + '.png') || mediaNames.has(m[2]));
  }
}

// ---- V4：页面路由表双向对账（官方模板键为 "src"；兼容 "pages" 旧写法） ----
if (mainPages !== null) {
  const rawPages = mainPages.src ?? mainPages.pages;
  const pages = Array.isArray(rawPages) ? rawPages : [];
  for (const p of pages) {
    check('V4 route ' + p, exists('entry/src/main/ets/' + p + '.ets'));
  }
  const declared = pages.map((p) => p.replace(/^pages\//, ''));
  const onDisk = readdirSync(join(ROOT, 'entry/src/main/ets/pages'))
    .filter((f) => f.endsWith('.ets'))
    .map((f) => f.replace(/\.ets$/, ''));
  const orphans = onDisk.filter((f) => declared.indexOf(f) < 0);
  check('V4 no orphan page files', orphans.length === 0, orphans.length ? orphans.join(',') : '');
}

// ---- V5：$r 资源引用对账 ----
const etsFiles = [
  'entry/src/main/ets/pages/Index.ets',
  'entry/src/main/ets/entryability/EntryAbility.ets',
  'entry/src/main/ets/vpnextensionability/VpnExtensionAbility.ets',
];
for (const f of etsFiles) {
  if (!exists(f)) {
    check('V5 ' + f, false, 'file missing');
    continue;
  }
  const src = read(f);
  const refs = src.matchAll(/\$r\(\s*['"]app\.(string|color|media)\.([A-Za-z0-9_.]+)['"]/g);
  for (const m of refs) {
    const kind = m[1];
    const name = m[2];
    if (kind === 'string') check('V5 $r(app.string.' + name + ') in ' + f, stringNames.has(name));
    if (kind === 'color') check('V5 $r(app.color.' + name + ') in ' + f, colorNames.has(name));
    if (kind === 'media') {
      check('V5 $r(app.media.' + name + ') in ' + f, mediaNames.has(name + '.png') || mediaNames.has(name));
    }
  }
}

// ---- V6/V7：壳内常量与配置一致性 ----
const indexEts = read(etsFiles[0]);
const bundleConst = indexEts.match(/BUNDLE_NAME:\s*string\s*=\s*'([^']+)'/);
const abilityConst = indexEts.match(/VPN_ABILITY_NAME:\s*string\s*=\s*'([^']+)'/);
check(
  'V6 bundleName app.json5 ↔ Index.ets',
  bundleConst !== null && appJson5?.app?.bundleName === bundleConst[1],
  'app.json5=' + String(appJson5?.app?.bundleName) + ' Index.ets=' + String(bundleConst?.[1]),
);
const extNames = (moduleJson?.module?.extensionAbilities ?? moduleJson?.extensionAbilities ?? []).map((e) => e.name);
check(
  'V7 VPN_ABILITY_NAME ↔ module.json5',
  abilityConst !== null && extNames.indexOf(abilityConst[1]) >= 0,
  'Index.ets=' + String(abilityConst?.[1]) + ' module.json5=' + extNames.join(','),
);

// ---- V8：占位图标尺寸（README-app.md §6.9：app_icon 216×216、icon/startIcon 96×96） ----
const iconChecks = [
  ['AppScope/resources/base/media/app_icon.png', 216],
  ['entry/src/main/resources/base/media/icon.png', 96],
  ['entry/src/main/resources/base/media/startIcon.png', 96],
];
for (const [rel, want] of iconChecks) {
  if (!exists(rel)) {
    check('V8 ' + rel, false, 'file missing');
    continue;
  }
  const size = pngSize(rel);
  check('V8 ' + rel + ' ' + want + 'x' + want, size !== null && size.w === want && size.h === want, size ? size.w + 'x' + size.h : 'not a PNG');
}

// ---- 附带：工程级配置存在性（build-profile 的 module 表与盘上一致） ----
if (buildProfile !== null) {
  const mods = (buildProfile.modules ?? []).map((m) => m.name + ':' + m.srcPath);
  check('V1 build-profile.modules declares entry', mods.join(',').indexOf('entry:./entry') >= 0, mods.join(','));
}
check('V1 hvigorfile.ts present', exists('hvigorfile.ts'));
check('V1 entry/hvigorfile.ts present', exists('entry/hvigorfile.ts'));

for (const line of results) console.log(line);
console.log('summary: ' + String(results.length - failed) + ' passed, ' + String(failed) + ' failed');
process.exit(failed === 0 ? 0 : 1);
