/**
 * HTTP-over-ts2021（AU1 应用层对齐）——真实控制面在 Noise 连接上承载的极简 HTTP/1.1
 * （headscale v0.29.4 hscontrol/noise.go：controlbase 升级后以 chi 路由服务
 * POST /machine/register 与 POST /machine/map）。
 *
 * 本模块提供：
 * - encodeMachineRequest：把一次请求编码为线上字节（请求行 + Host + Content-Type +
 *   Content-Length + body；HTTP/1.1 默认持久连接，两连发 register/map 同连接复用）；
 * - HttpOverNoiseReader：从 ControlBaseSession.read() 的明文流中解出 HTTP 响应，
 *   支持 Content-Length 与 Transfer-Encoding: chunked 两种响应体（headscale 的 map
 *   响应为 chunked 流式多行 JSON）。
 *
 * 线格式证据（2026-09-29 实读）：tailscale controlhttp 的升级请求只发生一次且在
 * Noise 握手前（POST /ts2021 + Upgrade 头）；升级后的 /machine/* 是普通 HTTP/1.1
 * over Noise record 流。
 */

import { ControlError } from './errors.ts';

/** 组装一次机器 API 请求的线上字节。authority 为 Host 头值（如 "headscale.internal:8080"）。 */
export function encodeMachineRequest(
  method: 'POST',
  authority: string,
  path: '/machine/register' | '/machine/map',
  jsonBody: string,
): Uint8Array {
  const head: string =
    method + ' ' + path + ' HTTP/1.1\r\n' +
    'Host: ' + authority + '\r\n' +
    'Content-Type: application/json\r\n' +
    'Content-Length: ' + String(jsonBody.length) + '\r\n' +
    'Connection: keep-alive\r\n' +
    '\r\n';
  return concatUtf8(head, jsonBody);
}

function concatUtf8(head: string, body: string): Uint8Array {
  const headBytes: Uint8Array = utf8EncodeStrict(head);
  const bodyBytes: Uint8Array = utf8EncodeStrict(body);
  const out: Uint8Array = new Uint8Array(headBytes.length + bodyBytes.length);
  out.set(headBytes, 0);
  out.set(bodyBytes, headBytes.length);
  return out;
}

/** ASCII/UTF-8 无 BOM 编码（请求体为 JSON 文本，字符集受限）。 */
function utf8EncodeStrict(text: string): Uint8Array {
  const out: Uint8Array = new Uint8Array(text.length);
  for (let i: number = 0; i < text.length; i += 1) {
    const c: number = text.charCodeAt(i);
    if (c < 0x80) {
      out[i] = c;
    } else {
      // 多字节交给通用编码器：逐字符 UTF-8（JSON 内容只含 ASCII 与转义，防御性分支）
      return utf8EncodeFallback(text);
    }
  }
  return out;
}

function utf8EncodeFallback(text: string): Uint8Array {
  const bytes: number[] = [];
  for (let i: number = 0; i < text.length; i += 1) {
    let code: number = text.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff && i + 1 < text.length) {
      const lo: number = text.charCodeAt(i + 1);
      if (lo >= 0xdc00 && lo <= 0xdfff) {
        code = 0x10000 + ((code - 0xd800) << 10) + (lo - 0xdc00);
        i += 1;
      }
    }
    if (code < 0x80) {
      bytes.push(code);
    } else if (code < 0x800) {
      bytes.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    } else if (code < 0x10000) {
      bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    } else {
      bytes.push(
        0xf0 | (code >> 18),
        0x80 | ((code >> 12) & 0x3f),
        0x80 | ((code >> 6) & 0x3f),
        0x80 | (code & 0x3f),
      );
    }
  }
  const out: Uint8Array = new Uint8Array(bytes.length);
  for (let i: number = 0; i < bytes.length; i += 1) {
    out[i] = bytes[i];
  }
  return out;
}

/** 解析完成的响应。mode='full' 时 bodyText 为完整响应体；'firstJsonLine' 为首行 JSON。 */
export interface HttpOverNoiseResponse {
  statusCode: number;
  contentType: string;
  bodyText: string;
}

/** 响应读取器：从明文流（ControlBaseSession.read 的返回序列）解 HTTP 响应。 */
export class HttpOverNoiseReader {
  private buf: Uint8Array = new Uint8Array(0);
  private headDone: boolean = false;
  private contentLength: number = -1;
  private chunked: boolean = false;
  private statusCode: number = 0;
  private contentType: string = '';
  private body: Uint8Array = new Uint8Array(0);
  // chunked 状态机
  private chunkPhase: 'size' | 'data' | 'size-end' | 'trailer' = 'size';
  private chunkRemain: number = 0;

  /**
   * 读出一个完整响应。mode='full' 读到响应体声明长度结束；
   * mode='firstJsonLine' 在 chunked 流中解出第一个以 \n 结尾的 JSON 行即返回
   * （map 流式场景；返回后不应再继续用本 reader 读，调用方负责关闭连接）。
   */
  public async read(
    readSource: () => Promise<Uint8Array>,
    mode: 'full' | 'firstJsonLine',
  ): Promise<HttpOverNoiseResponse> {
    for (;;) {
      if (this.headDone) {
        const finished: string | null = this.tryExtractBody(mode);
        if (finished !== null) {
          const out: HttpOverNoiseResponse = {
            statusCode: this.statusCode,
            contentType: this.contentType,
            bodyText: finished,
          };
          return out;
        }
      } else if (this.tryParseHead()) {
        continue;
      }
      const chunk: Uint8Array = await readSource();
      if (chunk.length === 0) {
        throw new ControlError('HTTP', 'noisehttp: connection closed before complete response') as Error;
      }
      this.append(chunk);
    }
  }

  private append(chunk: Uint8Array): void {
    const merged: Uint8Array = new Uint8Array(this.buf.length + chunk.length);
    merged.set(this.buf, 0);
    merged.set(chunk, this.buf.length);
    this.buf = merged;
  }

  /** 尝试从头缓冲解析响应头；成功返回 true 并裁掉已消费字节。 */
  private tryParseHead(): boolean {
    const limit: number = Math.min(this.buf.length, 64 * 1024);
    let eoh: number = -1;
    for (let i: number = 0; i + 3 < limit + 1 && i + 3 <= this.buf.length; i += 1) {
      if (this.buf[i] === 0x0d && this.buf[i + 1] === 0x0a && this.buf[i + 2] === 0x0d && this.buf[i + 3] === 0x0a) {
        eoh = i;
        break;
      }
    }
    if (eoh < 0) {
      return false;
    }
    const headText: string = asciiDecode(this.buf.slice(0, eoh));
    const lines: string[] = headText.split('\r\n');
    const statusLine: string[] = (lines[0] === undefined ? '' : lines[0]).split(' ');
    if (statusLine.length < 2 || statusLine[0] !== 'HTTP/1.1') {
      throw new ControlError('HTTP', 'noisehttp: bad status line: ' + (lines[0] === undefined ? '' : lines[0])) as Error;
    }
    this.statusCode = Number(statusLine[1]);
    for (let i: number = 1; i < lines.length; i += 1) {
      const line: string = lines[i] === undefined ? '' : lines[i];
      const colon: number = line.indexOf(':');
      if (colon < 0) {
        continue;
      }
      const name: string = line.slice(0, colon).toLowerCase();
      const value: string = line.slice(colon + 1);
      if (name === 'content-length') {
        this.contentLength = Number(value.trim());
      } else if (name === 'transfer-encoding') {
        this.chunked = value.toLowerCase().indexOf('chunked') >= 0;
      } else if (name === 'content-type') {
        this.contentType = value.trim();
      }
    }
    this.buf = this.buf.slice(eoh + 4);
    this.headDone = true;
    return true;
  }

  /** 从已缓冲的 body 区提取目标文本；未完成返回 null。 */
  private tryExtractBody(mode: 'full' | 'firstJsonLine'): string | null {
    // 把新缓冲并入 body 工作区
    if (this.buf.length > 0) {
      const merged: Uint8Array = new Uint8Array(this.body.length + this.buf.length);
      merged.set(this.body, 0);
      merged.set(this.buf, this.body.length);
      this.body = merged;
      this.buf = new Uint8Array(0);
    }
    if (this.chunked) {
      return this.extractChunked(mode);
    }
    if (this.contentLength >= 0) {
      if (this.body.length < this.contentLength) {
        return null;
      }
      return asciiSliceUtf8(this.body.slice(0, this.contentLength));
    }
    // 既无长度也无 chunked：读到连接关闭为止（对端 close 表现为 readSource 抛错/空）
    return null;
  }

  /** chunked 解码状态机；firstJsonLine 模式在首个 \n 结尾 JSON 行完成时提前返回。 */
  private extractChunked(mode: 'full' | 'firstJsonLine'): string | null {
    for (;;) {
      if (this.chunkPhase === 'size') {
        const lineEnd: number = findCrlf(this.body);
        if (lineEnd < 0) {
          return null;
        }
        const sizeText: string = asciiDecode(this.body.slice(0, lineEnd)).split(';')[0].trim();
        const size: number = parseInt(sizeText, 16);
        if (Number.isNaN(size) || size < 0) {
          throw new ControlError('HTTP', 'noisehttp: bad chunk size: ' + sizeText) as Error;
        }
        this.body = this.body.slice(lineEnd + 2);
        if (size === 0) {
          this.chunkPhase = 'trailer';
        } else {
          this.chunkPhase = 'data';
          this.chunkRemain = size;
        }
      } else if (this.chunkPhase === 'data') {
        if (this.body.length === 0) {
          return null;
        }
        const take: number = Math.min(this.chunkRemain, this.body.length);
        const piece: Uint8Array = this.body.slice(0, take);
        this.decoded = concatBytes(this.decoded, piece);
        this.body = this.body.slice(take);
        this.chunkRemain -= take;
        if (this.chunkRemain === 0) {
          this.chunkPhase = 'size-end';
        }
        if (mode === 'firstJsonLine') {
          const nl: number = findLf(this.decoded);
          if (nl >= 0) {
            return asciiSliceUtf8(this.decoded.slice(0, nl));
          }
        }
      } else if (this.chunkPhase === 'size-end') {
        if (this.body.length < 2) {
          return null;
        }
        this.body = this.body.slice(2);
        this.chunkPhase = 'size';
      } else {
        // trailer：等终止空行（\r\n）——本端拿到目标内容后即关闭连接，这里读满即返回 null
        if (this.body.length >= 2 && this.body[0] === 0x0d && this.body[1] === 0x0a) {
          return null;
        }
        const lineEnd: number = findCrlf(this.body);
        if (lineEnd < 0) {
          return null;
        }
        this.body = this.body.slice(lineEnd + 2);
      }
    }
  }

  private decoded: Uint8Array = new Uint8Array(0);
}

function findCrlf(b: Uint8Array): number {
  for (let i: number = 0; i + 1 < b.length; i += 1) {
    if (b[i] === 0x0d && b[i + 1] === 0x0a) {
      return i;
    }
  }
  return -1;
}

function findLf(b: Uint8Array): number {
  for (let i: number = 0; i < b.length; i += 1) {
    if (b[i] === 0x0a) {
      return i;
    }
  }
  return -1;
}

function concatBytes(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out: Uint8Array = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

function asciiDecode(b: Uint8Array): string {
  let out: string = '';
  for (let i: number = 0; i < b.length; i += 1) {
    out += String.fromCharCode(b[i]);
  }
  return out;
}

/** 响应体按 UTF-8 解码（JSON 文本）。 */
function asciiSliceUtf8(b: Uint8Array): string {
  let out: string = '';
  let i: number = 0;
  while (i < b.length) {
    const c: number = b[i];
    if (c < 0x80) {
      out += String.fromCharCode(c);
      i += 1;
    } else if (c >= 0xc0 && c < 0xe0 && i + 1 < b.length) {
      out += String.fromCharCode(((c & 0x1f) << 6) | (b[i + 1] & 0x3f));
      i += 2;
    } else if (c >= 0xe0 && c < 0xf0 && i + 2 < b.length) {
      out += String.fromCharCode(((c & 0x0f) << 12) | ((b[i + 1] & 0x3f) << 6) | (b[i + 2] & 0x3f));
      i += 3;
    } else if (c >= 0xf0 && i + 3 < b.length) {
      const cp: number = ((c & 0x07) << 18) | ((b[i + 1] & 0x3f) << 12) | ((b[i + 2] & 0x3f) << 6) | (b[i + 3] & 0x3f);
      const v: number = cp - 0x10000;
      out += String.fromCharCode(0xd800 + (v >> 10), 0xdc00 + (v & 0x3ff));
      i += 4;
    } else {
      out += '\uFFFD';
      i += 1;
    }
  }
  return out;
}
