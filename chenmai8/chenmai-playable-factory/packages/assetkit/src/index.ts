// packages/assetkit/src/index.ts — assetkit 公共面（oracle python/assetkit/__init__.py 同构移植）。
//
// 四项能力（docs/specs/assetkit.md，规格源 repo/docs/assets/specs/assetkit.md）：
// - 压图：sharp 多编码竞标——有损 WebP / 近无损 WebP / 调色板量化 PNG / 常规 PNG，
//   取最小者；压缩不过原图则保留原图（永不增大）。宿主适配：oracle 经
//   python→node 子进程助手（python/assetkit/node/optimize.mjs），factory 单栈
//   直接进程内 import sharp（语义逐条对齐，决策 §2.2 迁移表）。
// - 音频：ffmpeg 转低码率 AAC（.m4a）；ffmpeg 缺席/单文件失败保留原始并如实记录。
// - 字体子集：按 spec i18n.strings 字符集（∪ 标题 ∪ 数字）子集化，woff2 输出；
//   宿主适配：oracle fontTools → subset-font(harfbuzzjs)，cmap 覆盖率由 fontkit 判定。
// - 图集：自研 shelf（next-fit 递减高）装箱，合成单张图集 + atlas.json 帧表。
//
// 输出（out 目录，整体重建）：优化素材（平面文件名冲突自动加序号）、
// asset-optmap.json（键 = spec 声明串或绝对路径 → 优化产物，模板构建经
// 环境变量 PF_ASSET_OPTMAP 接线）、report.json（逐素材前后字节/候选明细/汇总降幅）。

export const ASSETKIT_VERSION = "1.0.0";

export const OPTMAP_NAME = "asset-optmap.json";
export const REPORT_NAME = "report.json";

/** 带退出码语义的素材管线失败：1=处理失败，2=用法/环境错误（oracle AssetkitError 同形）。 */
export class AssetkitError extends Error {
  exitCode: number;
  constructor(message: string, exitCode = 1) {
    super(message);
    this.exitCode = exitCode;
  }
}
