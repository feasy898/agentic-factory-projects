/**
 * 素材解析与 data URI 封装（单 HTML 全内联的资源侧）。
 * resolveDistRef 快速失败是 §3.3"拒绝"清单的实现：带 scheme、协议相对、根相对、
 * 逃逸出 dist 根的引用一律当场抛错。
 */
import { readFileSync } from "node:fs";
import path from "node:path";

const MIME = new Map([
  [".png", "image/png"],
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".gif", "image/gif"],
  [".webp", "image/webp"],
  [".svg", "image/svg+xml"],
  [".ico", "image/x-icon"],
  [".bmp", "image/bmp"],
  [".avif", "image/avif"],
  [".woff", "font/woff"],
  [".woff2", "font/woff2"],
  [".ttf", "font/ttf"],
  [".otf", "font/otf"],
  [".mp3", "audio/mpeg"],
  [".ogg", "audio/ogg"],
  [".oga", "audio/ogg"],
  [".m4a", "audio/mp4"],
  [".aac", "audio/aac"],
  [".wav", "audio/wav"],
  [".mp4", "video/mp4"],
  [".webm", "video/webm"],
]);

/**
 * dist 内相对引用 → 绝对路径。相对 baseDir 解析（CSS 中 url() 相对 CSS 文件所在
 * 目录），包含性检查针对 distRoot（允许走出子目录、不允许走出 dist 根）。
 */
export function resolveDistRef(distRoot, ref, baseDir = distRoot) {
  if (/^[a-z][a-z0-9+.-]*:/i.test(ref)) {
    throw new Error(`dist 内出现带协议的引用 "${ref}"（外链禁止，请先内联或移除）`);
  }
  if (ref.startsWith("//")) {
    throw new Error(`dist 内出现协议相对外链 "${ref}"（外链禁止）`);
  }
  if (ref.startsWith("/")) {
    throw new Error(`dist 内出现根相对路径 "${ref}"（打包器只接受相对路径）`);
  }
  const abs = path.resolve(baseDir, ref);
  const root = path.resolve(distRoot);
  if (abs !== root && !abs.startsWith(root + path.sep)) {
    throw new Error(`引用 "${ref}" 逃逸出 dist 目录`);
  }
  return abs;
}

export function mimeOf(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  return MIME.get(ext) || "application/octet-stream";
}

/** 读文件 → data URI。文件缺失时报错带引用来源（spec §4 失败路径）。 */
export function toDataUri(absPath, refForError) {
  let buf;
  try {
    buf = readFileSync(absPath);
  } catch (err) {
    throw new Error(`内联资源缺失: "${refForError}"（解析为 ${absPath}）`);
  }
  return `data:${mimeOf(absPath)};base64,${buf.toString("base64")}`;
}

export function readText(absPath, refForError) {
  try {
    return readFileSync(absPath, "utf8");
  } catch (err) {
    throw new Error(`内联资源缺失: "${refForError}"（解析为 ${absPath}）`);
  }
}
