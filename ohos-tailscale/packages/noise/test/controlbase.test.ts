/**
 * controlbase 帧封装层测试（AU1 对齐层）。
 *
 * 向量策略：initiation 帧的 5B 头与总长按上游 messages.go 常量写死断言（版本 1、
 * 类型 0x01、载荷 96、总长 101）；噪声载荷确定性由 ArrayRng 固定种子自锁（真实
 * 控制面互通由 interop 联调另行验证）。会话语义（分帧/空帧跳过/零写不发/error 帧）
 * 以包内 NoiseIkResponder 扮演服务器逐项验证。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ArrayRng,
  utf8Encode,
  KEY_LEN_BYTES,
} from '@ohos-tailscale/common';
import { x25519PublicKeyFromPrivate } from '@ohos-tailscale/crypto';
import {
  CONTROLBASE_MAX_PLAINTEXT_BYTES,
  ControlBaseSession,
  controlbaseBuildInitiation,
  controlbaseClientHandshake,
  controlbaseCompleteHandshake,
  type ControlBaseDuplex,
  type ControlBaseInitiation,
} from '../src/controlbase.ts';
import { NoiseIkResponder } from '../src/handshake.ts';
import { NoiseError } from '../src/errors.ts';

const RNG_SEED: Uint8Array = Uint8Array.from(
  [0xa3, 0x5c, 0x11, 0xd2, 0x7e, 0x04, 0x99, 0xb8, 0x2f, 0x61, 0xcc, 0x70, 0x18, 0xe5, 0x4a, 0xd7],
);
const MACHINE_PRIVATE: Uint8Array = Uint8Array.from(
  [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0x00,
   0x0f, 0x1e, 0x2d, 0x3c, 0x4b, 0x5a, 0x69, 0x78, 0x87, 0x96, 0xa5, 0xb4, 0xc3, 0xd2, 0xe1, 0xf0],
);
const CONTROL_PRIVATE: Uint8Array = Uint8Array.from(
  [0xfe, 0xdc, 0xba, 0x98, 0x76, 0x54, 0x32, 0x10, 0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef,
   0xf7, 0xe6, 0xd5, 0xc4, 0xb3, 0xa2, 0x91, 0x80, 0x7f, 0x6e, 0x5d, 0x4c, 0x3b, 0x2a, 0x19, 0x08],
);
const CONTROL_PUBLIC: Uint8Array = x25519PublicKeyFromPrivate(CONTROL_PRIVATE);

/** 测试用字节管道：两端互连，支持把发送拆成任意分片送达（模拟真实流式到达）。 */
class PipeEnd implements ControlBaseDuplex {
  public readonly inbox: Uint8Array[] = [];
  private waiter: ((chunk: Uint8Array) => void) | null = null;
  public closed: boolean = false;
  private peer: PipeEnd | null = null;

  public static link(): [PipeEnd, PipeEnd] {
    const a: PipeEnd = new PipeEnd();
    const b: PipeEnd = new PipeEnd();
    a.peer = b;
    b.peer = a;
    return [a, b];
  }

  public async send(data: Uint8Array): Promise<void> {
    if (this.closed || this.peer === null || this.peer.closed) {
      throw new Error('pipe closed');
    }
    this.peer.deliver(new Uint8Array(data));
  }

  public async receive(): Promise<Uint8Array> {
    if (this.inbox.length > 0) {
      const chunk: Uint8Array | undefined = this.inbox.shift();
      if (chunk === undefined) {
        throw new Error('unreachable');
      }
      return chunk;
    }
    if (this.closed) {
      return new Uint8Array(0);
    }
    return new Promise<Uint8Array>((resolve: (chunk: Uint8Array) => void) => {
      this.waiter = resolve;
    });
  }

  public async close(): Promise<void> {
    this.closed = true;
    if (this.waiter !== null) {
      this.waiter(new Uint8Array(0));
      this.waiter = null;
    }
  }

  /** 把对端发来的字节拆成 n 片入队（测试分片重组）。 */
  public deliver(chunk: Uint8Array): void {
    const parts: Uint8Array[] = [];
    const piece: number = Math.max(1, Math.floor(chunk.length / 3));
    let off: number = 0;
    while (off < chunk.length) {
      parts.push(chunk.slice(off, Math.min(off + piece, chunk.length)));
      off += piece;
    }
    for (const p of parts) {
      if (this.waiter !== null) {
        const w: ((chunk: Uint8Array) => void) | null = this.waiter;
        this.waiter = null;
        w(p);
      } else {
        this.inbox.push(p);
      }
    }
  }
}

/** 包内扮演 controlbase 服务器：读 initiation、回 response、返回服务端会话。 */
class MiniControlbaseServer {
  public readonly responder: NoiseIkResponder;
  public session: ControlBaseSession | null = null;

  public constructor() {
    this.responder = new NoiseIkResponder(utf8Encode('Tailscale Control Protocol v148'), CONTROL_PRIVATE, new ArrayRng(RNG_SEED));
  }

  /** 处理客户端 initiation 帧（101B），返回服务器 response 帧（51B）。 */
  public accept(initiationFrame: Uint8Array): Uint8Array {
    assert.equal(initiationFrame.length, 101);
    assert.equal(initiationFrame[0], 0x00); // 版本 148 = 0x0094（BE16 高字节）
    assert.equal(initiationFrame[1], 0x94);
    assert.equal(initiationFrame[2], 0x01); // msgTypeInitiation
    assert.equal(initiationFrame[3], 0x00); // 载荷长度 96
    assert.equal(initiationFrame[4], 0x60);
    this.responder.readMessageA(initiationFrame.slice(5));
    const payload: Uint8Array = this.responder.writeMessageB(new Uint8Array(0));
    assert.equal(payload.length, 48);
    const frame: Uint8Array = new Uint8Array(3 + 48);
    frame[0] = 0x02;
    frame[1] = 0x00;
    frame[2] = 0x30;
    frame.set(payload, 3);
    const pair = this.responder.split();
    this.session = new ControlBaseSession(pair.send, pair.recv);
    return frame;
  }
}

test('initiation 帧确定性与头部常量（AU1 写死断言）', () => {
  const a: ControlBaseInitiation = controlbaseBuildInitiation(MACHINE_PRIVATE, CONTROL_PUBLIC, new ArrayRng(RNG_SEED));
  const b: ControlBaseInitiation = controlbaseBuildInitiation(MACHINE_PRIVATE, CONTROL_PUBLIC, new ArrayRng(RNG_SEED));
  assert.equal(a.frame.length, 101);
  assert.equal(a.frame.length, b.frame.length);
  for (let i: number = 0; i < 5; i += 1) {
    assert.equal(a.frame[i], b.frame[i]);
  }
  // 噪声载荷也确定性（同种子同输出）
  for (let i: number = 5; i < a.frame.length; i += 1) {
    assert.equal(a.frame[i], b.frame[i], 'byte ' + String(i));
  }
  // 两台机器（不同静态）→ 载荷必须不同（防写死假实现）
  const other: Uint8Array = MACHINE_PRIVATE.slice();
  other[16] = (other[16] + 1) & 0xff; // 改高位字节（低 3 位会被 X25519 clamp 清零，改 byte0 无效）
  const c: ControlBaseInitiation = controlbaseBuildInitiation(other, CONTROL_PUBLIC, new ArrayRng(RNG_SEED));
  let diff: number = 0;
  for (let i: number = 5; i < a.frame.length; i += 1) {
    if (a.frame[i] !== c.frame[i]) {
      diff += 1;
    }
  }
  assert.ok(diff > 32, 'different machine key must change ciphertext');
});

test('两步式握手往返 + record 会话双向、分帧、空帧、空写', async () => {
  const [clientEnd, serverEnd] = PipeEnd.link();
  const init: ControlBaseInitiation = controlbaseBuildInitiation(MACHINE_PRIVATE, CONTROL_PUBLIC, new ArrayRng(RNG_SEED));
  await clientEnd.send(init.frame);
  const server: MiniControlbaseServer = new MiniControlbaseServer();

  const got: Uint8Array[] = [];
  // 收集恰好 101B（服务器侧逐片读）
  while (got.reduce((n: number, c: Uint8Array) => n + c.length, 0) < 101) {
    got.push(await serverEnd.receive());
  }
  const acc: Uint8Array = new Uint8Array(got.reduce((n: number, c: Uint8Array) => n + c.length, 0));
  let off: number = 0;
  for (const c of got) {
    acc.set(c, off);
    off += c.length;
  }
  const responseFrame: Uint8Array = server.accept(acc.slice(0, 101));
  await serverEnd.send(responseFrame);

  // 客户端从分片流中拼出 51B response 完成握手
  let respAcc: Uint8Array = new Uint8Array(0);
  let session: ControlBaseSession | null = null;
  while (session === null) {
    const chunk: Uint8Array = await clientEnd.receive();
    const merged: Uint8Array = new Uint8Array(respAcc.length + chunk.length);
    merged.set(respAcc, 0);
    merged.set(chunk, respAcc.length);
    respAcc = merged;
    if (respAcc.length >= 51) {
      session = controlbaseCompleteHandshake(init, respAcc.slice(0, 51));
    }
  }
  assert.ok(session !== null);
  assert.ok(server.session !== null);

  // 客户端 → 服务器
  await session.write(clientEnd, utf8Encode('hello controlbase'));
  const got1: Uint8Array = await server.session.read(serverEnd);
  assert.equal(new TextDecoder().decode(got1), 'hello controlbase');

  // 客户端空写：线上不产生任何字节
  const before: number = serverEnd.inbox.reduce((n: number, c: Uint8Array) => n + c.length, 0);
  await session.write(clientEnd, new Uint8Array(0));
  const after: number = serverEnd.inbox.reduce((n: number, c: Uint8Array) => n + c.length, 0);
  assert.equal(before, after);

  // 服务器 → 客户端：超 4077B 自动分两帧 + 夹一个零长度帧（客户端应跳过）
  const big: Uint8Array = new Uint8Array(CONTROLBASE_MAX_PLAINTEXT_BYTES + 100);
  for (let i: number = 0; i < big.length; i += 1) {
    big[i] = i & 0xff;
  }
  await server.session.write(serverEnd, big.slice(0, CONTROLBASE_MAX_PLAINTEXT_BYTES));
  await server.session.write(serverEnd, new Uint8Array(0));
  await server.session.write(serverEnd, big.slice(CONTROLBASE_MAX_PLAINTEXT_BYTES));
  const gotBig1: Uint8Array = await session.read(clientEnd);
  const gotBig2: Uint8Array = await session.read(clientEnd);
  const reassembled: Uint8Array = new Uint8Array(big.length);
  reassembled.set(gotBig1, 0);
  reassembled.set(gotBig2, gotBig1.length);
  for (let i: number = 0; i < big.length; i += 1) {
    assert.equal(reassembled[i], big[i], 'byte ' + String(i));
  }
  assert.ok(gotBig1.length <= CONTROLBASE_MAX_PLAINTEXT_BYTES);

  // 篡改一个 record → 客户端 DECRYPT，且会话报废
  const evil: Uint8Array = new Uint8Array(3 + 32 + 16);
  evil[0] = 0x04;
  evil[1] = 0x00;
  evil[2] = 48;
  await serverEnd.send(evil);
  await assert.rejects(
    () => session.read(clientEnd),
    (e: unknown) => e instanceof NoiseError && e.code === 'DECRYPT',
  );
  await assert.rejects(() => session.read(clientEnd), (e: unknown) => e instanceof NoiseError && e.code === 'STATE');
  await clientEnd.close();
  await serverEnd.close();
});

test('error 帧：握手被服务器拒绝时带出文本并抛 STATE', () => {
  const init: ControlBaseInitiation = controlbaseBuildInitiation(MACHINE_PRIVATE, CONTROL_PUBLIC, new ArrayRng(RNG_SEED));
  const text: Uint8Array = utf8Encode('wrong handshake initiation size');
  const errFrame: Uint8Array = new Uint8Array(3 + text.length);
  errFrame[0] = 0x03;
  errFrame[1] = (text.length >> 8) & 0xff;
  errFrame[2] = text.length & 0xff;
  errFrame.set(text, 3);
  assert.throws(
    () => controlbaseCompleteHandshake(init, errFrame),
    (e: unknown) => e instanceof NoiseError && e.code === 'STATE' && e.message.includes('wrong handshake initiation size'),
  );
});

test('一步式握手 + 错误控制面密钥 → DECRYPT（服务器侧 tag 校验失败）', async () => {
  const [clientEnd, serverEnd] = PipeEnd.link();
  const wrongControl: Uint8Array = CONTROL_PUBLIC.slice();
  wrongControl[0] = (wrongControl[0] + 1) & 0xff;
  const handshake: Promise<ControlBaseSession> = controlbaseClientHandshake(clientEnd, MACHINE_PRIVATE, wrongControl, new ArrayRng(RNG_SEED));
  const got: Uint8Array[] = [];
  while (got.reduce((n: number, c: Uint8Array) => n + c.length, 0) < 101) {
    got.push(await serverEnd.receive());
  }
  const acc: Uint8Array = new Uint8Array(got.reduce((n: number, c: Uint8Array) => n + c.length, 0));
  let off: number = 0;
  for (const c of got) {
    acc.set(c, off);
    off += c.length;
  }
  const server: MiniControlbaseServer = new MiniControlbaseServer();
  // 真实控制面密钥与服务端一致 → 客户端用了错误密钥 → 服务器解 initiation 失败
  assert.throws(
    () => server.accept(acc.slice(0, 101)),
    (e: unknown) => e instanceof NoiseError && e.code === 'DECRYPT',
  );
  await serverEnd.close();
  await clientEnd.close();
  await assert.rejects(() => handshake);
  assert.equal(KEY_LEN_BYTES, 32);
});
