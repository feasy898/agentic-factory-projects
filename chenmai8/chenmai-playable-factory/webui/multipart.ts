// webui/multipart.ts — multipart/form-data 最小解析器（自写，node:http 无第三方依赖）。
//（webui/README.md 既定方案：multipart 自写最小解析器并加负向测试——oracle FastAPI
//  的表单解析由框架代劳，factory 单栈按同一 API 形状自给。）
//
// 只支持 application/form-data 的常规形态：
//   --<boundary>\r\n headers \r\n\r\n content \r\n--<boundary> ... \r\n--<boundary>--\r\n
// 结构性缺陷（坏 content-type / 边界不匹配 / 缺终止边界 / part 缺 name）一律抛
// MultipartError → 上层 400。不做任何大小自适应缓冲：全量 Buffer 后解析（入站体积
// 由调用方的上限纪律约束：spec 256KB / PNG 5MB×12）。

export class MultipartError extends Error {}

export interface MultipartFile {
  /** 表单字段名（如 "spec" / "assets"）。 */
  name: string;
  /** 客户端文件名（原样；不含路径——basename 由调用方按纪律再清洗）。 */
  filename: string;
  /** 文件字节。 */
  data: Buffer;
  /** part 的 Content-Type（可为空）。 */
  contentType: string;
}

export interface MultipartResult {
  /** 普通表单字段（同名后者覆盖——与表单语义一致）。 */
  fields: Record<string, string>;
  files: MultipartFile[];
}

/** 从 Content-Type 头提取 boundary 参数；非 multipart 或缺 boundary 抛错。 */
export function boundaryFromContentType(contentType: string | undefined): string {
  if (!contentType || !contentType.toLowerCase().startsWith("multipart/form-data")) {
    throw new MultipartError(`Content-Type 不是 multipart/form-data：${contentType ?? "(缺失)"}`);
  }
  const m = /boundary=(?:"([^"]+)"|([^;,\s]+))/i.exec(contentType);
  if (!m) throw new MultipartError("Content-Type 缺 boundary 参数");
  return (m[1] ?? m[2])!;
}

/** 解析 multipart 请求体（Buffer 全量入）。结构性不合法抛 MultipartError。 */
export function parseMultipart(body: Buffer, contentType: string | undefined): MultipartResult {
  const boundary = boundaryFromContentType(contentType);
  const dash = `--${boundary}`;
  const dashBuf = Buffer.from(dash);

  // 请求体必须以 --boundary 开头（允许前导 CRLF——部分客户端行为，宽松收下）。
  let pos = 0;
  if (body.subarray(0, 2).toString("binary") === "\r\n") pos = 2;
  if (body.subarray(pos, pos + dashBuf.length).toString("binary") !== dash) {
    throw new MultipartError("请求体未以 boundary 开头");
  }
  pos += dashBuf.length;

  const fields: Record<string, string> = {};
  const files: MultipartFile[] = [];
  let guard = 0;
  while (guard++ < 4096) {
    // 终止边界：--boundary--
    if (body.subarray(pos, pos + 2).toString("binary") === "--") break;
    if (body.subarray(pos, pos + 2).toString("binary") !== "\r\n") {
      throw new MultipartError("boundary 后缺 CRLF");
    }
    pos += 2;
    // headers 块直到空行
    const headEnd = body.indexOf("\r\n\r\n", pos, "binary");
    if (headEnd < 0) throw new MultipartError("part 缺 header/正文分隔空行");
    const headText = body.subarray(pos, headEnd).toString("utf8");
    const disp = /content-disposition\s*:\s*form-data([^\r\n]*)/i.exec(headText);
    if (!disp) throw new MultipartError("part 缺 Content-Disposition: form-data");
    const nameM = /\bname="((?:[^"\\]|\\.)*)"/i.exec(disp[1]!);
    if (!nameM) throw new MultipartError("part 缺 name 参数");
    const name = nameM[1]!.replace(/\\(.)/g, "$1");
    const fileM = /\bfilename="((?:[^"\\]|\\.)*)"/i.exec(disp[1]!);
    const ctM = /^content-type\s*:\s*([^\r\n]+)/im.exec(headText);
    pos = headEnd + 4;
    // 正文直到 \r\n--boundary
    const next = body.indexOf(`\r\n${dash}`, pos, "binary");
    if (next < 0) throw new MultipartError("part 未被 boundary 终止（请求体被截断）");
    const data = body.subarray(pos, next);
    pos = next + 2 + dashBuf.length;
    if (fileM) {
      files.push({ name, filename: fileM[1]!.replace(/\\(.)/g, "$1"), data, contentType: ctM ? ctM[1]!.trim() : "" });
    } else {
      fields[name] = data.toString("utf8");
    }
  }
  return { fields, files };
}

/** 构造一段合法 multipart 体（selftest 与单测用）。 */
export function buildMultipart(
  boundary: string,
  parts: Array<{ name: string; filename?: string; contentType?: string; data: Buffer | string }>,
): Buffer {
  const chunks: Buffer[] = [];
  for (const p of parts) {
    const disp = `Content-Disposition: form-data; name="${p.name}"` +
      (p.filename !== undefined ? `; filename="${p.filename}"` : "");
    chunks.push(Buffer.from(`--${boundary}\r\n${disp}\r\n`));
    if (p.contentType) chunks.push(Buffer.from(`Content-Type: ${p.contentType}\r\n`));
    chunks.push(Buffer.from("\r\n"));
    chunks.push(Buffer.isBuffer(p.data) ? p.data : Buffer.from(p.data, "utf8"));
    chunks.push(Buffer.from("\r\n"));
  }
  chunks.push(Buffer.from(`--${boundary}--\r\n`));
  return Buffer.concat(chunks);
}
