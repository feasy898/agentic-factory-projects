import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  DERP_MAGIC,
  DERP_MAX_FRAME_BYTES,
  DerpError,
  type DerpFrame,
  DerpFrameReader,
  DerpFrameType,
  derpFrameDecode,
  derpFrameEncode,
  parseDerpFrameType,
} from '../src/frame.ts';

/**
 * AU2 对齐后的帧格式（上游 tailscale main derp/derp.go）：
 *
 *   帧 = type u8 || length u32(大端) || payload
 *
 * 帧头 5 字节；length 不含帧头本身。全部期望字节按上游死写。
 */

function allFrameTypes(): number[] {
  return [
    DerpFrameType.ServerKey, // 0x01
    DerpFrameType.ClientInfo, // 0x02
    DerpFrameType.ServerInfo, // 0x03
    DerpFrameType.SendPacket, // 0x04
    DerpFrameType.RecvPacket, // 0x05
    DerpFrameType.KeepAlive, // 0x06
    DerpFrameType.NotePreferred, // 0x07
    DerpFrameType.PeerGone, // 0x08
    DerpFrameType.PeerPresent, // 0x09
    DerpFrameType.ForwardPacket, // 0x0a
    DerpFrameType.WatchConns, // 0x10
    DerpFrameType.ClosePeer, // 0x11
    DerpFrameType.Ping, // 0x12
    DerpFrameType.Pong, // 0x13
    DerpFrameType.Health, // 0x14
    DerpFrameType.Restarting, // 0x15
  ];
}

function derpCodeOf(e: Error): string | null {
  if (e instanceof DerpError) {
    return e.code;
  }
  return null;
}

function throwsCode(fn: () => void, code: string): void {
  assert.throws(fn, (e: Error): boolean => derpCodeOf(e) === code);
}

test('帧类型码表 / Magic / 长度上限死字节对照上游 derp.go', (): void => {
  assert.equal(DerpFrameType.ServerKey, 0x01);
  assert.equal(DerpFrameType.ClientInfo, 0x02);
  assert.equal(DerpFrameType.ServerInfo, 0x03);
  assert.equal(DerpFrameType.SendPacket, 0x04);
  assert.equal(DerpFrameType.RecvPacket, 0x05);
  assert.equal(DerpFrameType.KeepAlive, 0x06);
  assert.equal(DerpFrameType.NotePreferred, 0x07);
  assert.equal(DerpFrameType.PeerGone, 0x08);
  assert.equal(DerpFrameType.PeerPresent, 0x09);
  assert.equal(DerpFrameType.ForwardPacket, 0x0a);
  assert.equal(DerpFrameType.WatchConns, 0x10);
  assert.equal(DerpFrameType.ClosePeer, 0x11);
  assert.equal(DerpFrameType.Ping, 0x12);
  assert.equal(DerpFrameType.Pong, 0x13);
  assert.equal(DerpFrameType.Health, 0x14);
  assert.equal(DerpFrameType.Restarting, 0x15);
  // Magic = "DERP🔑"（8B，FrameServerKey 载荷开头）
  assert.deepEqual(Array.from(DERP_MAGIC), [0x44, 0x45, 0x52, 0x50, 0xf0, 0x9f, 0x94, 0x91]);
  assert.equal(DERP_MAX_FRAME_BYTES, 1048576); // 1MB（DoS 防护基线）
});

test('encode/decode 往返：全部帧类型 + u32BE 大端帧头字节断言', (): void => {
  const payload: Uint8Array = Uint8Array.from([0x00, 0xff, 0x7f, 0x80, 0x01]);
  for (const t of allFrameTypes()) {
    const bytes: Uint8Array = derpFrameEncode(t, payload);
    assert.equal(bytes.length, 5 + payload.length); // 帧头 5B
    assert.equal(bytes[0], t); // type u8
    assert.deepEqual(Array.from(bytes.slice(1, 5)), [0x00, 0x00, 0x00, 0x05]); // length u32BE 大端
    const f: DerpFrame = derpFrameDecode(bytes);
    assert.equal(f.type, t);
    assert.deepEqual(f.payload, payload);
  }
});

test('已知字节向量：KeepAlive 空帧与 SendPacket 300B 载荷', (): void => {
  assert.deepEqual(
    derpFrameEncode(DerpFrameType.KeepAlive, new Uint8Array(0)),
    Uint8Array.from([0x06, 0x00, 0x00, 0x00, 0x00]),
  );
  const big: Uint8Array = new Uint8Array(300);
  big[299] = 0x5a;
  const bytes: Uint8Array = derpFrameEncode(DerpFrameType.SendPacket, big);
  assert.equal(bytes.length, 5 + 300);
  assert.deepEqual(Array.from(bytes.slice(0, 5)), [0x04, 0x00, 0x00, 0x01, 0x2c]); // 300 = 0x012C 大端
  const f: DerpFrame = derpFrameDecode(bytes);
  assert.equal(f.type, DerpFrameType.SendPacket);
  assert.equal(f.payload.length, 300);
  assert.equal(f.payload[299], 0x5a);
});

test('u32BE 长度边界往返：0/1/127/128/16383/16384/65535/65536', (): void => {
  const lens: number[] = [0, 1, 127, 128, 16383, 16384, 65535, 65536];
  for (const n of lens) {
    const p: Uint8Array = new Uint8Array(n);
    if (n > 0) {
      p[n - 1] = 0x42;
    }
    const bytes: Uint8Array = derpFrameEncode(DerpFrameType.RecvPacket, p);
    assert.equal(bytes.length, 5 + n);
    const f: DerpFrame = derpFrameDecode(bytes);
    assert.equal(f.type, DerpFrameType.RecvPacket);
    assert.equal(f.payload.length, n);
    if (n > 0) {
      assert.equal(f.payload[n - 1], 0x42);
    }
  }
  // 65536 = 0x00010000 的帧头死字节（大端）
  const b64k: Uint8Array = derpFrameEncode(DerpFrameType.RecvPacket, new Uint8Array(65536));
  assert.deepEqual(Array.from(b64k.slice(0, 5)), [0x05, 0x00, 0x01, 0x00, 0x00]);
});

test('decode：未知帧类型透传；parseDerpFrameType 与 encode 拒绝未知类型', (): void => {
  const raw: Uint8Array = Uint8Array.from([0x63, 0x00, 0x00, 0x00, 0x02, 0xaa, 0xbb]);
  const f: DerpFrame = derpFrameDecode(raw);
  assert.equal(f.type, 0x63);
  assert.deepEqual(f.payload, Uint8Array.from([0xaa, 0xbb]));
  assert.equal(parseDerpFrameType(0x63), null);
  assert.equal(parseDerpFrameType(0x00), null);
  assert.equal(parseDerpFrameType(0x0b), null); // 码表空档（0x0b..0x0f 未定义）
  for (const t of allFrameTypes()) {
    assert.equal(parseDerpFrameType(t), t);
  }
  throwsCode((): void => { derpFrameEncode(0x63, new Uint8Array(0)); }, 'RANGE');
  throwsCode((): void => { derpFrameEncode(0, new Uint8Array(0)); }, 'RANGE');
  throwsCode((): void => { derpFrameEncode(0x0b, new Uint8Array(0)); }, 'RANGE');
});

test('reader：未知帧类型同样透传', (): void => {
  const raw: Uint8Array = Uint8Array.from([0x2a, 0x00, 0x00, 0x00, 0x01, 0x55]);
  const r: DerpFrameReader = new DerpFrameReader();
  const got: DerpFrame[] = r.push(raw);
  assert.equal(got.length, 1);
  assert.equal(got[0].type, 0x2a);
  assert.deepEqual(got[0].payload, Uint8Array.from([0x55]));
});

test('decode：空输入/截断/尾部字节 → FRAME', (): void => {
  const full: Uint8Array = derpFrameEncode(DerpFrameType.SendPacket, Uint8Array.from([1, 2, 3]));
  assert.equal(full.length, 8);
  throwsCode((): void => { derpFrameDecode(new Uint8Array(0)); }, 'FRAME');
  throwsCode((): void => { derpFrameDecode(full.slice(0, full.length - 1)); }, 'FRAME'); // payload 截断
  throwsCode((): void => { derpFrameDecode(Uint8Array.from([0x04])); }, 'FRAME'); // 头部不全
  throwsCode((): void => { derpFrameDecode(Uint8Array.from([0x04, 0x00, 0x00])); }, 'FRAME'); // 头部不全
  throwsCode((): void => { derpFrameDecode(Uint8Array.from([0x04, 0x00, 0x00, 0x00])); }, 'FRAME'); // 差 1B 头
  const withTrailing: Uint8Array = new Uint8Array(full.length + 1);
  withTrailing.set(full, 0);
  withTrailing[full.length] = 0x00;
  throwsCode((): void => { derpFrameDecode(withTrailing); }, 'FRAME'); // 尾部多余字节
});

test('超限拒绝：声明长度 > 1MB → RANGE（decode 与 reader push 均拒绝）', (): void => {
  // u32BE 1048577 = 0x00100001（上限 +1）
  const raw: Uint8Array = Uint8Array.from([DerpFrameType.ServerKey, 0x00, 0x10, 0x00, 0x01]);
  throwsCode((): void => { derpFrameDecode(raw); }, 'RANGE');
  const r: DerpFrameReader = new DerpFrameReader();
  throwsCode((): void => { r.push(raw); }, 'RANGE'); // push 即抛，不等 payload 到齐
  // u32BE 0xFFFFFFFF 同样越界
  const rawMax: Uint8Array = Uint8Array.from([DerpFrameType.ServerKey, 0xff, 0xff, 0xff, 0xff]);
  throwsCode((): void => { derpFrameDecode(rawMax); }, 'RANGE');
  // encode 侧：payload 超上限拒绝
  throwsCode((): void => {
    derpFrameEncode(DerpFrameType.SendPacket, new Uint8Array(DERP_MAX_FRAME_BYTES + 1));
  }, 'RANGE');
});

test('帧长上限边界：恰好 DERP_MAX_FRAME_BYTES 可往返', (): void => {
  const p: Uint8Array = new Uint8Array(DERP_MAX_FRAME_BYTES);
  p[0] = 0x11;
  p[DERP_MAX_FRAME_BYTES - 1] = 0x77;
  const bytes: Uint8Array = derpFrameEncode(DerpFrameType.RecvPacket, p);
  assert.deepEqual(Array.from(bytes.slice(1, 5)), [0x00, 0x10, 0x00, 0x00]); // 1048576 = 0x00100000 大端
  const f: DerpFrame = derpFrameDecode(bytes);
  assert.equal(f.payload.length, DERP_MAX_FRAME_BYTES);
  assert.equal(f.payload[0], 0x11);
  assert.equal(f.payload[DERP_MAX_FRAME_BYTES - 1], 0x77);
});

test('reader：分片逐字节重组与 pendingBytes 推进', (): void => {
  const p1: Uint8Array = Uint8Array.from([0x0a, 0x0b, 0x0c]);
  const f1: Uint8Array = derpFrameEncode(DerpFrameType.RecvPacket, p1);
  const p2: Uint8Array = Uint8Array.from([0xde, 0xad, 0xbe, 0xef]);
  const f2: Uint8Array = derpFrameEncode(DerpFrameType.SendPacket, p2);
  const both: Uint8Array = new Uint8Array(f1.length + f2.length);
  both.set(f1, 0);
  both.set(f2, f1.length);
  assert.equal(f1.length, 8); // 5B 帧头 + 3B payload
  assert.equal(f2.length, 9); // 5B 帧头 + 4B payload

  const r: DerpFrameReader = new DerpFrameReader();
  const got: DerpFrame[] = [];
  for (let i: number = 0; i < both.length; i += 1) {
    const chunkFrames: DerpFrame[] = r.push(both.slice(i, i + 1));
    for (const f of chunkFrames) {
      got.push(f);
    }
    if (i < 7) {
      assert.equal(r.pendingBytes(), i + 1); // 第一帧（8B）逐字节累积
    }
    if (i === 7) {
      assert.equal(r.pendingBytes(), 0); // 第一帧完整吐出，第二帧未开始
    }
  }
  assert.equal(got.length, 2);
  assert.equal(got[0].type, DerpFrameType.RecvPacket);
  assert.deepEqual(got[0].payload, p1);
  assert.equal(got[1].type, DerpFrameType.SendPacket);
  assert.deepEqual(got[1].payload, p2);
  assert.equal(r.pendingBytes(), 0);
});

test('reader：粘包（多帧一片）与空 chunk', (): void => {
  const f1: Uint8Array = derpFrameEncode(DerpFrameType.KeepAlive, new Uint8Array(0));
  const f2: Uint8Array = derpFrameEncode(DerpFrameType.Ping, Uint8Array.from([0x01, 0x02]));
  const f3: Uint8Array = derpFrameEncode(DerpFrameType.Pong, Uint8Array.from([0x01, 0x02]));
  const all: Uint8Array = new Uint8Array(f1.length + f2.length + f3.length);
  all.set(f1, 0);
  all.set(f2, f1.length);
  all.set(f3, f1.length + f2.length);
  const r: DerpFrameReader = new DerpFrameReader();
  const got: DerpFrame[] = r.push(all);
  assert.equal(got.length, 3);
  assert.deepEqual(
    [got[0].type, got[1].type, got[2].type],
    [DerpFrameType.KeepAlive, DerpFrameType.Ping, DerpFrameType.Pong],
  );
  assert.deepEqual(got[0].payload, new Uint8Array(0));
  assert.deepEqual(got[1].payload, Uint8Array.from([0x01, 0x02]));
  assert.deepEqual(r.push(new Uint8Array(0)), []);
  assert.equal(r.pendingBytes(), 0);
});

test('reader：u32BE 长度字段跨 chunk 分界', (): void => {
  const p: Uint8Array = new Uint8Array(128);
  p[127] = 0x42;
  const bytes: Uint8Array = derpFrameEncode(DerpFrameType.NotePreferred, p);
  assert.deepEqual(Array.from(bytes.slice(0, 5)), [0x07, 0x00, 0x00, 0x00, 0x80]); // 128 = 0x00000080
  const r: DerpFrameReader = new DerpFrameReader();
  assert.deepEqual(r.push(bytes.slice(0, 3)), []); // type + 长度前 2 字节，长度字段未完
  assert.equal(r.pendingBytes(), 3);
  const got: DerpFrame[] = r.push(bytes.slice(3));
  assert.equal(got.length, 1);
  assert.equal(got[0].type, DerpFrameType.NotePreferred);
  assert.equal(got[0].payload.length, 128);
  assert.equal(got[0].payload[127], 0x42);
  assert.equal(r.pendingBytes(), 0);
});

test('reader：半帧缓存与残余帧等待', (): void => {
  const f: Uint8Array = derpFrameEncode(DerpFrameType.Ping, Uint8Array.from([1, 2, 3, 4]));
  assert.equal(f.length, 9); // 5B 帧头 + 4B payload
  const r: DerpFrameReader = new DerpFrameReader();
  assert.deepEqual(r.push(f.slice(0, 6)), []); // 头已齐、payload 差 3B
  assert.equal(r.pendingBytes(), 6);
  const rest: DerpFrame[] = r.push(f.slice(6));
  assert.equal(rest.length, 1);
  assert.deepEqual(rest[0].payload, Uint8Array.from([1, 2, 3, 4]));
  assert.equal(r.pendingBytes(), 0);
});

test('拷贝语义：解码 payload、编码输出、reader payload 均为独立拷贝', (): void => {
  const frameBytes: Uint8Array = derpFrameEncode(DerpFrameType.Ping, Uint8Array.from([0x11, 0x22, 0x33]));
  const f: DerpFrame = derpFrameDecode(frameBytes);
  f.payload[0] = 0xff;
  assert.equal(frameBytes[5], 0x11); // decode 的 payload 是独立拷贝

  const input: Uint8Array = Uint8Array.from([0x42]);
  const out: Uint8Array = derpFrameEncode(DerpFrameType.ServerInfo, input);
  input[0] = 0x00;
  assert.equal(out[out.length - 1], 0x42); // encode 输出是独立拷贝

  const r: DerpFrameReader = new DerpFrameReader();
  const got: DerpFrame[] = r.push(out);
  assert.equal(got.length, 1);
  got[0].payload[0] = 0xff;
  assert.equal(out[out.length - 1], 0x42); // reader 返回的 payload 也是独立拷贝
});
