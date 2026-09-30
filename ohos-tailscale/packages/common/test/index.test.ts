import { test } from 'node:test';
import assert from 'node:assert/strict';
// barrel 冒烟：全部公开符号都能从包入口导入（模拟其他包 `import ... from '@ohos-tailscale/common'`）
import {
  ByteReader,
  ByteWriter,
  hexEncode,
  hexDecode,
  base64Encode,
  base64Decode,
  base64UrlEncode,
  base64UrlDecode,
  utf8Encode,
  utf8Decode,
  FixedClock,
  ArrayRng,
  KEY_LEN_BYTES,
  AEAD_NONCE_LEN_BYTES,
  AEAD_TAG_LEN_BYTES,
  MAX_U64,
  WG_DEFAULT_PORT,
  DERP_DEFAULT_PORT,
  STUN_DEFAULT_PORT,
  CGNAT_V4_CIDR,
  TAILNET_ULA_V6_CIDR,
} from '../src/index.ts';
import type { Clock, Rng, HttpTransport, HttpRequest, HttpResponse, HttpBodyStream, StreamingHttpResponse } from '../src/index.ts';

/** 立即结束的空响应体（A2：带方法的接口必须 class implements，禁止对象字面量初始化）。 */
class NullBodyStream implements HttpBodyStream {
  public read(): Promise<Uint8Array | null> {
    return Promise.resolve<Uint8Array | null>(null);
  }
  public close(): void {
    return undefined;
  }
}

test('barrel 导出全部符号并可正常工作', () => {
  const w: ByteWriter = new ByteWriter();
  w.writeU16be(0xabcd);
  assert.equal(new ByteReader(w.toUint8Array()).readU16be(), 0xabcd);
  assert.equal(hexDecode(hexEncode(Uint8Array.from([1, 2])))[1], 2);
  assert.equal(base64Decode(base64Encode(Uint8Array.from([9, 9, 9]))).length, 3);
  assert.equal(base64UrlDecode(base64UrlEncode(Uint8Array.from([0xfb]))).length, 1);
  assert.equal(utf8Decode(utf8Encode('ok')), 'ok');
  const clock: Clock = new FixedClock(5);
  assert.equal(clock.wallMs(), 5);
  const rng: Rng = new ArrayRng(Uint8Array.from([1]));
  const b: Uint8Array = new Uint8Array(1);
  rng.randomBytes(b);
  assert.equal(b[0], 1);
});

test('常量值与类型', () => {
  assert.equal(KEY_LEN_BYTES, 32);
  assert.equal(AEAD_NONCE_LEN_BYTES, 12);
  assert.equal(AEAD_TAG_LEN_BYTES, 16);
  assert.equal(MAX_U64, 18446744073709551615n);
  assert.equal(WG_DEFAULT_PORT, 41641);
  assert.equal(DERP_DEFAULT_PORT, 443);
  assert.equal(STUN_DEFAULT_PORT, 3478);
  assert.equal(CGNAT_V4_CIDR, '100.64.0.0/10');
  assert.equal(TAILNET_ULA_V6_CIDR, 'fd7a:115c:a1e0::/48');
});

test('HttpTransport 接口可用对象字面量实现（fake transport 形态）', async () => {
  class FakeTransport implements HttpTransport {
    public lastRequest: HttpRequest | null = null;
    public send(request: HttpRequest): Promise<HttpResponse> {
      this.lastRequest = request;
      const resp: HttpResponse = { status: 200, headers: { 'content-type': 'application/octet-stream' }, body: new Uint8Array(0) };
      return Promise.resolve<HttpResponse>(resp);
    }
    public open(request: HttpRequest): Promise<StreamingHttpResponse> {
      const stream: HttpBodyStream = new NullBodyStream();
      const resp: StreamingHttpResponse = { status: 200, headers: {}, body: stream };
      return Promise.resolve<StreamingHttpResponse>(resp);
    }
  }
  const t: FakeTransport = new FakeTransport();
  const req: HttpRequest = { method: 'POST', url: 'https://example.com/ts2021', headers: { 'content-type': 'application/octet-stream' }, body: Uint8Array.from([1]) };
  const resp: HttpResponse = await t.send(req);
  assert.equal(resp.status, 200);
  assert.equal(t.lastRequest?.method, 'POST');
  const streamed: StreamingHttpResponse = await t.open(req);
  assert.equal(await streamed.body.read(), null);
});
