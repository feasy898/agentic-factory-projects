/**
 * AU3 对齐层测试：tailcfg JSON 编解码 + HTTP-over-Noise 帧解析。
 * JSON 字段名以 tailscale main tailcfg.go（2026-09-29 实读）写死断言。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  TAILCFG_CURRENT_CAPABILITY_VERSION,
  decodeMapResponseSummary,
  decodeRegisterResponse,
  encodeMapRequest,
  encodeRegisterRequest,
  formatNodeKey,
  tailcfgError,
} from '../src/tailcfg.ts';
import { HttpOverNoiseReader, encodeMachineRequest } from '../src/noisehttp.ts';
import { ControlError } from '../src/errors.ts';

const NODE_PUB: Uint8Array = Uint8Array.from(
  [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f, 0x10,
   0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f, 0x20],
);

test('formatNodeKey 产出 nodekey:/discokey: 前缀小写 hex', () => {
  assert.equal(formatNodeKey(NODE_PUB, 'nodekey'), 'nodekey:0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20');
  assert.equal(formatNodeKey(NODE_PUB, 'discokey').startsWith('discokey:0102'), true);
});

test('encodeRegisterRequest 字段名与上游 tailcfg.go 一致', () => {
  const json: string = encodeRegisterRequest({
    capabilityVersion: TAILCFG_CURRENT_CAPABILITY_VERSION,
    nodeKeyPublic: NODE_PUB,
    oldNodeKeyPublic: null,
    authKey: 'taillock123',
    expiryRfc3339: '2030-01-01T00:00:00Z',
    hostname: 'ohos-dev-1',
    os: 'OpenHarmony',
    ephemeral: false,
  });
  assert.ok(json.includes('"Version":148'));
  assert.ok(json.includes('"NodeKey":"nodekey:0102'));
  assert.ok(json.includes('"Auth":{"AuthKey":"taillock123"}'));
  assert.ok(json.includes('"Expiry":"2030-01-01T00:00:00Z"'));
  assert.ok(json.includes('"Hostname":"ohos-dev-1"'));
  assert.ok(json.includes('"OS":"OpenHarmony"'));
  // 能被 JSON.parse 还原（结构合法）
  const back = JSON.parse(json) as { Version: number; Auth: { AuthKey: string } };
  assert.equal(back.Version, 148);
  assert.equal(back.Auth.AuthKey, 'taillock123');
});

test('encodeMapRequest 带 Stream 与 DiscoKey', () => {
  const json: string = encodeMapRequest({
    capabilityVersion: 148,
    nodeKeyPublic: NODE_PUB,
    discoKeyPublic: NODE_PUB,
    stream: true,
    hostname: 'ohos-dev-1',
    os: 'OpenHarmony',
  });
  assert.ok(json.includes('"Stream":true'));
  assert.ok(json.includes('"DiscoKey":"discokey:0102'));
  assert.ok(json.includes('"Compress":""'));
  assert.ok(json.includes('"Endpoints":[]'));
});

test('decodeRegisterResponse 成功与失败路径', () => {
  const ok: ReturnType<typeof decodeRegisterResponse> = decodeRegisterResponse(
    '{"User":{"ID":"1"},"Login":{},"MachineAuthorized":true,"AuthURL":""}',
  );
  assert.equal(ok.machineAuthorized, true);
  assert.equal(ok.error, '');
  assert.throws(
    () => decodeRegisterResponse('{"Error":"node key expired"}'),
    (e: unknown) => e instanceof ControlError && e.code === 'HTTP' && e.message.includes('node key expired'),
  );
  assert.ok(tailcfgError('x').message.startsWith('tailcfg:'));
});

test('decodeMapResponseSummary 数 peer', () => {
  const view: ReturnType<typeof decodeMapResponseSummary> = decodeMapResponseSummary(
    '{"KeepAlive":false,"Peers":[{"Node":{"ID":"1"}},{"Node":{"ID":"2"}}]}',
  );
  assert.equal(view.peerCount, 2);
  const empty: ReturnType<typeof decodeMapResponseSummary> = decodeMapResponseSummary('{"KeepAlive":true}');
  assert.equal(empty.keepAlive, true);
  assert.equal(empty.peerCount, 0);
});

test('encodeMachineRequest 请求行与头', () => {
  const bytes: Uint8Array = encodeMachineRequest('POST', 'hs.internal:8080', '/machine/register', '{"a":1}');
  const text: string = new TextDecoder().decode(bytes);
  assert.ok(text.startsWith('POST /machine/register HTTP/1.1\r\n'));
  assert.ok(text.includes('Host: hs.internal:8080\r\n'));
  assert.ok(text.includes('Content-Type: application/json\r\n'));
  assert.ok(text.includes('Content-Length: 7\r\n'));
  assert.ok(text.endsWith('\r\n\r\n{"a":1}'));
});

test('HttpOverNoiseReader：Content-Length 响应分片到达', async () => {
  const body: string = '{"MachineAuthorized":true}';
  const head: string = 'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ' + String(body.length) + '\r\n\r\n';
  const wire: string = head + body;
  const chunks: Uint8Array[] = [];
  // 按 3 字节一片打碎，模拟 record 流
  const raw: Uint8Array = new TextEncoder().encode(wire);
  for (let i: number = 0; i < raw.length; i += 3) {
    chunks.push(raw.slice(i, i + 3));
  }
  let idx: number = 0;
  const reader: HttpOverNoiseReader = new HttpOverNoiseReader();
  const resp = await reader.read(async () => {
    const c: Uint8Array | undefined = chunks[idx];
    idx += 1;
    if (c === undefined) {
      throw new Error('stream exhausted in test');
    }
    return c;
  }, 'full');
  assert.equal(resp.statusCode, 200);
  assert.equal(resp.bodyText, body);
});

test('HttpOverNoiseReader：chunked 流 firstJsonLine 模式', async () => {
  const line1: string = '{"KeepAlive":false,"Peers":[{"Node":{"ID":"1"}}]}\n';
  const line2: string = '{"KeepAlive":false,"Peers":[]}\n';
  const body: string = line1 + line2;
  const wire: string =
    'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n' +
    line1.length.toString(16) + '\r\n' + line1 + '\r\n' +
    line2.length.toString(16) + '\r\n' + line2 + '\r\n' +
    '0\r\n\r\n';
  const raw: Uint8Array = new TextEncoder().encode(wire);
  const chunks: Uint8Array[] = [];
  for (let i: number = 0; i < raw.length; i += 5) {
    chunks.push(raw.slice(i, i + 5));
  }
  let idx: number = 0;
  const reader: HttpOverNoiseReader = new HttpOverNoiseReader();
  const resp = await reader.read(async () => {
    const c: Uint8Array | undefined = chunks[idx];
    idx += 1;
    if (c === undefined) {
      throw new Error('stream exhausted in test');
    }
    return c;
  }, 'firstJsonLine');
  assert.equal(resp.statusCode, 200);
  const view: ReturnType<typeof decodeMapResponseSummary> = decodeMapResponseSummary(resp.bodyText);
  assert.equal(view.peerCount, 1);
});
