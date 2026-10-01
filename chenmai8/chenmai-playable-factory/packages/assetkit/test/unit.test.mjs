// packages/assetkit/test/unit.test.mjs — assetkit 单元测试（纯函数 + 小样本真实 sharp 往返）。
// 运行：node --test packages/assetkit/test/unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { classify, collect, specAssetRelPaths } from "../src/collect.ts";
import { NamePool, optimizeImages } from "../src/images.ts";
import { packShelf } from "../src/atlas.ts";
import { specSubsetText } from "../src/fonts.ts";
import sharp from "sharp";

test("classify：三类素材扩展名分桶，未知扩展名拒绝", () => {
  assert.equal(classify("a.PNG"), "image");
  assert.equal(classify("a.webp"), "image");
  assert.equal(classify("a.wav"), "audio");
  assert.equal(classify("a.m4a"), "audio");
  assert.equal(classify("a.ttc"), "font");
  assert.equal(classify("a.otf"), "font");
  assert.equal(classify("a.txt"), null);
  assert.equal(classify("noext"), null);
});

test("specAssetRelPaths：background → sprites → audio → fontSubset，按声明顺序", () => {
  const rels = specAssetRelPaths({
    assets: {
      background: "bg.png",
      sprites: { "piece-1": "p1.png", "piece-0": "p0.png" },
      audio: { tap: "t.wav", win: "w.wav" },
      fontSubset: "f.ttf",
    },
  });
  assert.deepEqual(rels, ["bg.png", "p1.png", "p0.png", "t.wav", "w.wav", "f.ttf"]);
  assert.deepEqual(specAssetRelPaths({ assets: {} }), []);
  assert.deepEqual(specAssetRelPaths({}), []);
});

test("specSubsetText：i18n 全语言 ∪ 标题 ∪ 数字内建 ∪ extra，去重保序跳空白", () => {
  const t = specSubsetText({
    meta: { title: "AB" },
    i18n: { strings: { zh: { cta: "下载", win: "赢!" }, en: { cta: "GO", win: "Win!" } } },
  }, "XY");
  assert.equal(t.includes("下"), true);
  assert.equal(t.includes("赢"), true);
  assert.equal(t.includes("G"), true);
  assert.equal(t.includes("W"), true);
  for (const d of "0123456789") assert.equal(t.includes(d), true, `数字 ${d} 应内建`);
  assert.equal(t.includes("X"), true);
  assert.equal(t.includes("A"), true);
  assert.equal(t.includes(" "), false, "空白字符不入集");
  // 首次出现序：标题先于 i18n 值
  assert.ok(t.indexOf("A") < t.indexOf("下"));
  assert.equal(specSubsetText(null, ""), "0123456789");
});

test("NamePool：同 stem 冲突加序号，大小写不敏感判重（序号后缀保留原 stem 大小写——oracle 同形）", () => {
  const pool = new NamePool("out");
  assert.ok(pool.base("gem").endsWith("gem"));
  assert.ok(pool.base("Gem").endsWith("Gem-2"));
  assert.ok(pool.base("GEM").endsWith("GEM-3"));
  assert.ok(pool.base("gem").endsWith("gem-4"));
  assert.ok(pool.base("other").endsWith("other"));
});

test("packShelf：next-fit 递减高装箱——不重叠、不出界、超宽跳过、宽度收紧", () => {
  const frames = [
    { key: "a", file: "a.png", width: 300, widthIsWide: undefined, height: 100 },
    { key: "wide", file: "w.png", width: 2000, height: 50 },
    { key: "b", file: "b.png", width: 400, height: 200 },
    { key: "c", file: "c.png", width: 300, height: 200 },
    { key: "d", file: "d.png", width: 100, height: 100 },
  ];
  const { placed, width, height, skipped } = packShelf(frames, 1024);
  assert.deepEqual(skipped.map((s) => s.key), ["wide"], "单图宽超图集宽 → skipped");
  // 递减高排序：b(200,400) c(200,300) a(100,300) d(100,100)
  assert.equal(placed.length, 4);
  const overlap = (a, b) => a.x < b.x + b.width && b.x < a.x + a.width
    && a.y < b.y + b.height && b.y < a.y + a.height;
  for (let i = 0; i < placed.length; i++) {
    for (let j = i + 1; j < placed.length; j++) {
      assert.ok(!overlap(placed[i], placed[j]), `${placed[i].key}/${placed[j].key} 不重叠`);
    }
  }
  for (const p of placed) {
    assert.ok(p.x + p.width <= width, "在界内（宽）");
    assert.ok(p.y + p.height <= height, "在界内（高）");
  }
  assert.equal(width, 1000, "宽度收紧到最右边界（a 顶到 x=700+300）");
  assert.equal(height, 300);
  // 逐位对齐 oracle pack_shelf 同输入实算（repo/python 实测：b(0,0) c(400,0) a(700,0) d(0,200)）
  const at = Object.fromEntries(placed.map((p) => [p.key, p]));
  assert.deepEqual([at.b.x, at.b.y], [0, 0]);
  assert.deepEqual([at.c.x, at.c.y], [400, 0]);
  assert.deepEqual([at.a.x, at.a.y], [700, 0]);
  assert.deepEqual([at.d.x, at.d.y], [0, 200]);
  // 同宽稳定序：key 字典序（oracle sort 稳定键对齐）
  assert.equal(placed[0].key, "b");
  assert.equal(placed[1].key, "c");
});

test("optimizeImages：小图竞标取最小且永不增大；kept-original 复制原图", async () => {
  const dir = mkdtempSync(join(tmpdir(), "assetkit-unit-"));
  try {
    // 平色小件（palette 候选应显著受益）
    const gemBuf = await sharp({
      create: { width: 96, height: 96, channels: 4, background: { r: 40, g: 120, b: 220, alpha: 1 } },
    }).png().toBuffer();
    const bigBuf = await sharp({
      create: { width: 128, height: 128, channels: 4, background: { r: 10, g: 10, b: 10, alpha: 1 } },
    }).png({ compressionLevel: 0 }).toBuffer(); // 不压缩的 PNG → 任何候选都能打赢

    writeFileSync(join(dir, "gem.png"), gemBuf);
    writeFileSync(join(dir, "big.png"), bigBuf);
    const materials = [
      { src: join(dir, "gem.png"), key: "gem.png", kind: "image" },
      { src: join(dir, "big.png"), key: "big.png", kind: "image" },
    ];
    const entries = await optimizeImages(materials, dir, { quality: 75 });
    assert.equal(entries.length, 2);
    const gemE = entries.find((e) => e.key === "gem.png");
    const bigE = entries.find((e) => e.key === "big.png");
    if (gemE.status === "optimized") {
      assert.ok(gemE.optimizedBytes < gemE.originalBytes, "gem 竞标变小");
      assert.ok(readFileSync(join(dir, gemE.out)).length === gemE.optimizedBytes, "产物字节=报告值");
    } else {
      assert.equal(gemE.status, "kept-original");
      assert.equal(gemE.encoding, "original");
    }
    assert.equal(bigE.status, "optimized", "无压缩 PNG 必被打赢");
    assert.ok(["webp-lossy", "webp-nearlossless", "png-palette", "png-plain"].includes(bigE.encoding));
    assert.ok(bigE.optimizedBytes < bigE.originalBytes);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("collect：spec 声明串为键 + 显式输入绝对路径为键 + 去重", () => {
  const dir = mkdtempSync(join(tmpdir(), "assetkit-collect-"));
  try {
    writeFileSync(join(dir, "spec.json"), JSON.stringify({
      assets: { sprites: { "piece-0": "p0.png" }, audio: {} },
    }), "utf8");
    writeFileSync(join(dir, "p0.png"), "not-a-real-png-but-classified-by-ext", "utf8");
    // spec 声明（键=声明串）；同一文件再经显式输入出现 → 去重先到先得
    const mats = collect([dir], join(dir, "spec.json"), dir);
    const p0 = mats.find((m) => m.key === "p0.png");
    assert.ok(p0, "spec 声明串为键");
    assert.equal(mats.filter((m) => m.src.endsWith("p0.png")).length, 1, "同文件去重");
    assert.equal(p0.kind, "image");
    // 不存在的声明与不可识别扩展名静默忽略
    writeFileSync(join(dir, "spec2.json"), JSON.stringify({
      assets: { sprites: { "x": "missing.png", "y": "note.txt" } },
    }), "utf8");
    const mats2 = collect([], join(dir, "spec2.json"), dir);
    assert.equal(mats2.length, 0, "缺素材不收集（构建脚本回退语义）");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
