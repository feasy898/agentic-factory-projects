/**
 * 质检变异样本构造（防"永远绿灯"假质检）——oracle scripts/gate_phase0.py
 * 门项 6 `_build_mutant_source` 构造算法**逐条照搬**（qacore spec §8，冻结）：
 *
 * | 样本 | 构造算法（对 mini.html 的最小变异）           | 必须命中 |
 * | MUT-01 外链资源 | QC 桥接桩锚点（`  <script>\n    // QC 桥接桩`）前注入
 * |                 | `<img src="https://cdn.example.com/mut01-external.png" ...>` | CHK03 |
 * | MUT-02 未静音   | 同锚点注入未静音 `<audio autoplay src="data:audio/wav;base64,...">` | CHK04 |
 * | MUT-04 超体积   | `</body>` → `<!--` + "x"×pad + `--></body>`，
 * |                 | pad 使总字节 = 渠道 maxBytes+4096（meta 3MB 压线） | CHK01 |
 *
 * 通用纪律：样本写 tmp/（先清旧产物再跑，报告存在=本次真事实）；
 * 夹具本身只读、永不被改；恰命中断言 = exit 1 且 fail 集合恰为 {期望 CHK}。
 * MUT-03（结束页不可达）与 mutation-test 独立子命令仍列 M8 全量里程碑。
 */
import { readFileSync } from "node:fs";
import { writeFile, mkdir, rm } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const PKG_DIR = fileURLToPath(new URL("..", import.meta.url));
export const FIXTURE_MINI = join(PKG_DIR, "tests", "fixtures", "mini.html");

const MUT_AUDIO_DATA_URI = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEA"
  + "RKwAAIhYAQACABAAZGF0YQAAAAA=";
export const MUTATION_OVERSIZE_CHANNEL = "meta"; // 规则库中该渠道上限 3MB，压线样本用它
const MUT_EXTERNAL_IMG = '<img src="https://cdn.example.com/mut01-external.png"'
  + ' alt="" width="1" height="1">';
const MUT_UNMUTED_AUDIO = `<audio autoplay src="${MUT_AUDIO_DATA_URI}"></audio>`;

export const MUTANTS = [
  {
    name: "MUT-01-external-img", inject: MUT_EXTERNAL_IMG,
    channel: "preview", expect: "CHK03",
    desc: "外链 <img>（qacore abort 拦截并记账，CHK08 不受扰）",
  },
  {
    name: "MUT-02-unmuted-audio", inject: MUT_UNMUTED_AUDIO,
    channel: "preview", expect: "CHK04",
    desc: "未静音 <audio autoplay>（媒体探针重采样捕获）",
  },
  {
    name: "MUT-04-oversize", inject: "PADDING",
    channel: MUTATION_OVERSIZE_CHANNEL, expect: "CHK01",
    desc: `包体压过 ${MUTATION_OVERSIZE_CHANNEL} 渠道 maxBytes 的注释填充`,
  },
];

/** 规则库 meta 渠道上限；规则库不可读时内部从严线 3MB（与 oracle 门禁同值）。 */
export function oversizeLimitBytes(rulesPath) {
  const FALLBACK = 3_145_728;
  try {
    const rules = JSON.parse(readFileSync(rulesPath, "utf8"));
    return Number(rules.channels[MUTATION_OVERSIZE_CHANNEL].maxBytes) || FALLBACK;
  } catch {
    return FALLBACK;
  }
}

/**
 * Python Path.read_text 的 universal-newline 语义（\r\n → \n）：oracle 门禁以
 * read_text 读夹具，Windows 检出为 CRLF 的夹具在其实现里按 LF 参与锚点匹配与
 * 变异写回——本移植同规格归一，保证 mutant 字节与 oracle 门禁产物一致。
 */
export function readTextUniversal(p) {
  return readFileSync(p, "utf8").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

/**
 * 按变异方式构造 mutant 源字节（oracle _build_mutant_source 逐条照搬）。
 * @returns {Promise<{name: string, expect: string, channel: string, html: Buffer}>}
 */
export async function buildMutantSource(mutant, base, limitBytes) {
  if (mutant.inject === "PADDING") {
    const baseBytes = Buffer.from(base, "utf8");
    const target = limitBytes + 4096;
    const pad = target - baseBytes.length - Buffer.byteLength("<!---->", "utf8");
    if (pad <= 0) throw new Error(`填充量异常：${pad}`);
    const filler = Buffer.concat([
      Buffer.from("<!--", "utf8"), Buffer.alloc(pad, 0x78), Buffer.from("--></body>", "utf8"),
    ]);
    const idx = baseBytes.indexOf("</body>");
    if (idx < 0) throw new Error("夹具缺少 </body>，超体积变异注入位置失效");
    return {
      name: mutant.name, expect: mutant.expect, channel: mutant.channel,
      html: Buffer.concat([baseBytes.subarray(0, idx), filler, baseBytes.subarray(idx + 7)]),
    };
  }
  const marker = "  <script>\n    // QC 桥接桩";
  if (!base.includes(marker)) {
    throw new Error("夹具缺少 QC 桥接桩锚点，变异注入位置失效");
  }
  return {
    name: mutant.name, expect: mutant.expect, channel: mutant.channel,
    html: Buffer.from(base.replace(marker, `  ${mutant.inject}\n${marker}`), "utf8"),
  };
}

/**
 * 在 outDir 现场构造全部变异样本（先清旧目录再生成——"先清后跑"纪律）。
 * @returns {Promise<Array<{name, expect, channel, path}>>}
 */
export async function materializeMutants(outDir, rulesPath, fixturePath = FIXTURE_MINI) {
  await rm(outDir, { recursive: true, force: true });
  await mkdir(outDir, { recursive: true });
  const base = readTextUniversal(fixturePath);
  const limitBytes = oversizeLimitBytes(rulesPath);
  const out = [];
  for (const mutant of MUTANTS) {
    const built = await buildMutantSource(mutant, base, limitBytes);
    const p = join(outDir, `${built.name}.html`);
    await writeFile(p, built.html);
    out.push({ name: built.name, expect: built.expect, channel: built.channel, path: p });
  }
  return out;
}

export function sha256File(p) {
  return createHash("sha256").update(readFileSync(p)).digest("hex");
}
