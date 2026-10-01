/**
 * DERP 真实互通脚本（Node 侧驱动，全栈协同）：
 * 1) 用自研控制面栈（noise.controlbase + control.tailcfg + h2c）把 A、B 两个节点注册进真实 headscale；
 * 2) 用同一对 node 密钥经 HTTP 升级连接真实 DERP（headscale 内嵌 /derp，需已注册 key）；
 * 3) A → B 包交换（SendPacket/RecvPacket）+ KeepAlive/NotePreferred。
 *
 * 协议依据（AU2 实读）：GET /derp + Upgrade: DERP + Connection: Upgrade → 101 → 裸连接即 DERP 帧。
 * 用法：node --experimental-strip-types interop/derp.node.ts <baseUrl> <authKey>
 */

import http from 'node:http';
import { randomBytes } from 'node:crypto';

import { ArrayRng, KEY_LEN_BYTES, utf8Encode } from '../packages/common/src/index.ts';
import { x25519GenerateKeyPair, type CryptoKeyPair } from '../packages/crypto/src/index.ts';
import {
  controlbaseBuildInitiation,
  controlbaseCompleteHandshake,
  type ControlBaseDuplex,
  type ControlBaseSession,
} from '../packages/noise/src/controlbase.ts';
import {
  TAILCFG_CURRENT_CAPABILITY_VERSION,
  decodeRegisterResponse,
  encodeRegisterRequest,
} from '../packages/control/src/index.ts';
import { H2OverNoise } from './h2c.node.ts';
import { DerpClient, DerpClientEventKind } from '../packages/derp/src/client.ts';
import type { DerpConnection, DerpDialer } from '../packages/derp/src/connection.ts';
import type { DerpNode } from '../packages/derp/src/region.ts';

function fail(message: string): never {
  console.error('FAIL: ' + message);
  process.exit(1);
}

const [, , baseUrlArg, authKeyArg] = process.argv;
if (baseUrlArg === undefined || authKeyArg === undefined) {
  fail('usage: node --experimental-strip-types interop/derp.node.ts <baseUrl> <authKey>');
}
const baseUrl: string = baseUrlArg.replace(/\/$/, '');
const authKey: string = authKeyArg;
const url: URL = new URL(baseUrl);
const authority: string = url.host;

function rand32(): Uint8Array {
  return new Uint8Array(randomBytes(KEY_LEN_BYTES));
}

/* ---------- 控制面注册（与 register.node.ts 同源逻辑） ---------- */

class SocketDuplex implements ControlBaseDuplex {
  private readonly queue: Buffer[] = [];
  private waiter: ((b: Uint8Array) => void) | null = null;
  private readonly socket: import('node:net').Socket;

  public constructor(socket: import('node:net').Socket, prefix: Buffer) {
    this.socket = socket;
    if (prefix.length > 0) {
      this.queue.push(prefix);
    }
    socket.on('data', (d: Buffer) => {
      if (this.waiter !== null) {
        const w: (b: Uint8Array) => void = this.waiter;
        this.waiter = null;
        w(new Uint8Array(d));
      } else {
        this.queue.push(d);
      }
    });
    socket.on('close', () => {
      if (this.waiter !== null) {
        const w: (b: Uint8Array) => void = this.waiter;
        this.waiter = null;
        w(new Uint8Array(0));
      }
    });
    socket.on('error', () => {
      /* close 事件随后到达 */
    });
  }

  public prepend(data: Uint8Array): void {
    if (data.length === 0) {
      return;
    }
    this.queue.unshift(Buffer.from(data));
    if (this.waiter !== null) {
      const w: (b: Uint8Array) => void = this.waiter;
      this.waiter = null;
      w(new Uint8Array(this.queue.shift() as Buffer));
    }
  }

  public async send(data: Uint8Array): Promise<void> {
    this.socket.write(Buffer.from(data));
  }

  public async receive(): Promise<Uint8Array> {
    const queued: Buffer | undefined = this.queue.shift();
    if (queued !== undefined) {
      return new Uint8Array(queued);
    }
    if (this.socket.destroyed) {
      return new Uint8Array(0);
    }
    return new Promise<Uint8Array>((resolve: (b: Uint8Array) => void) => {
      this.waiter = resolve;
    });
  }

  public async close(): Promise<void> {
    this.socket.destroy();
  }
}

interface UpgradeResult {
  socket: import('node:net').Socket;
  head: Buffer;
  statusOrCode: number;
}

function rawUpgrade(base: string, path: string, upgradeValue: string, extraHeaders: Record<string, string>): Promise<UpgradeResult> {
  const u: URL = new URL(base + path);
  return new Promise<UpgradeResult>((resolve: (r: UpgradeResult) => void, reject: (e: Error) => void) => {
    const req: http.ClientRequest = http.request(
      {
        host: u.hostname,
        port: Number(u.port),
        method: 'POST',
        path: u.pathname,
        headers: { Host: u.host, Connection: 'upgrade', Upgrade: upgradeValue, ...extraHeaders },
      },
      (res: http.IncomingMessage) => {
        let body: string = '';
        res.on('data', (d: Buffer) => {
          body += String(d);
        });
        res.on('end', () => reject(new Error('upgrade refused: HTTP ' + String(res.statusCode) + ' ' + body.slice(0, 160))));
      },
    );
    req.on('upgrade', (res: http.IncomingMessage, socket: import('node:net').Socket, head: Buffer) => {
      resolve({ socket: socket, head: head, statusOrCode: res.statusCode === undefined ? 0 : res.statusCode });
    });
    req.on('error', reject);
    req.end();
  });
}

async function readExactAllowExtra(duplex: ControlBaseDuplex, n: number): Promise<Uint8Array> {
  const acc: Uint8Array[] = [];
  let total: number = 0;
  while (total < n) {
    const chunk: Uint8Array = await duplex.receive();
    if (chunk.length === 0) {
      fail('connection closed during handshake response');
    }
    acc.push(chunk);
    total += chunk.length;
  }
  const out: Uint8Array = new Uint8Array(total);
  let off: number = 0;
  for (const c of acc) {
    out.set(c, off);
    off += c.length;
  }
  return out;
}

/** 用自研栈把一个 node key 注册进 headscale（RegisterRequest + MapRequest 首帧）。 */
async function registerNode(hostname: string, keyPair: CryptoKeyPair, tag: string): Promise<void> {
  const keyRes: http.IncomingMessage = await new Promise<http.IncomingMessage>((resolve: (r: http.IncomingMessage) => void, reject: (e: Error) => void) => {
    http.get(baseUrl + '/key?v=' + String(TAILCFG_CURRENT_CAPABILITY_VERSION), resolve).on('error', reject);
  });
  let keyBody: string = '';
  for await (const d of keyRes) {
    keyBody += String(d);
  }
  const parsedKey = JSON.parse(keyBody) as { publicKey?: string };
  const hex: string = (parsedKey.publicKey === undefined ? '' : parsedKey.publicKey).replace(/^mkey:/, '');
  const controlKey: Uint8Array = new Uint8Array(32);
  for (let i: number = 0; i < 32; i += 1) {
    controlKey[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }

  const init = controlbaseBuildInitiation(keyPair.privateKey, controlKey, new ArrayRng(randomBytes(64)));
  const up: UpgradeResult = await rawUpgrade(baseUrl, '/ts2021', 'tailscale-control-protocol', {
    'X-Tailscale-Handshake': Buffer.from(init.frame).toString('base64'),
  });
  if (up.statusOrCode !== 101) {
    fail('[' + tag + '] ts2021 upgrade status ' + String(up.statusOrCode));
  }
  const duplex: SocketDuplex = new SocketDuplex(up.socket, up.head);
  console.log('[' + tag + '] upgrade 101 ✓，读握手响应…');
  const respBytes: Uint8Array = await readExactAllowExtra(duplex, 51);
  console.log('[' + tag + '] resp ' + String(respBytes.length) + 'B（含 EarlyNoise ' + String(respBytes.length - 51) + 'B）');
  const session: ControlBaseSession = controlbaseCompleteHandshake(init, respBytes.slice(0, 51));
  duplex.prepend(respBytes.slice(51)); // EarlyNoise 等残留字节归还给流
  console.log('[' + tag + '] Noise IK ✓');
  const h2: H2OverNoise = new H2OverNoise(session, duplex);
  console.log('[' + tag + '] h2 connect…');

  const regBody: string = encodeRegisterRequest({
    capabilityVersion: TAILCFG_CURRENT_CAPABILITY_VERSION,
    nodeKeyPublic: keyPair.publicKey,
    oldNodeKeyPublic: null,
    authKey: authKey,
    expiryRfc3339: '2030-01-01T00:00:00Z',
    hostname: hostname,
    os: 'OpenHarmony',
    ephemeral: false,
  });
  const regText: string = new TextDecoder().decode(await h2.post(authority, '/machine/register', regBody));
  const reg: ReturnType<typeof decodeRegisterResponse> = decodeRegisterResponse(regText);
  if (!reg.machineAuthorized) {
    fail('[' + tag + '] machine not authorized');
  }
  console.log('[' + tag + '] 控制面注册 ✓（' + hostname + ' MachineAuthorized=true）');
}

/* ---------- DERP 连接 ---------- */

class SocketConn implements DerpConnection {
  private readonly queue: Buffer[] = [];
  private waiter: ((b: Uint8Array | null) => void) | null = null;
  private closed: boolean = false;
  private readonly socket: import('node:net').Socket;

  public constructor(socket: import('node:net').Socket, prefix: Buffer) {
    this.socket = socket;
    if (prefix.length > 0) {
      this.queue.push(prefix);
    }
    socket.on('data', (d: Buffer) => {
      if (this.waiter !== null) {
        const w: (b: Uint8Array | null) => void = this.waiter;
        this.waiter = null;
        w(new Uint8Array(d));
      } else {
        this.queue.push(d);
      }
    });
    socket.on('close', () => {
      this.closed = true;
      if (this.waiter !== null) {
        const w: (b: Uint8Array | null) => void = this.waiter;
        this.waiter = null;
        w(null);
      }
    });
    socket.on('error', () => {
      /* close 事件随后到达 */
    });
  }

  public async write(data: Uint8Array): Promise<void> {
    this.socket.write(Buffer.from(data));
  }

  public async read(): Promise<Uint8Array | null> {
    const queued: Buffer | undefined = this.queue.shift();
    if (queued !== undefined) {
      return new Uint8Array(queued);
    }
    if (this.closed || this.socket.destroyed) {
      return null;
    }
    return new Promise<Uint8Array | null>((resolve: (b: Uint8Array | null) => void) => {
      this.waiter = resolve;
    });
  }

  public close(): void {
    this.closed = true;
    this.socket.destroy();
  }
}

class HttpDialer implements DerpDialer {
  public async dial(node: DerpNode): Promise<DerpConnection> {
    const up: UpgradeResult = await rawUpgrade(baseUrl, '/derp', 'DERP', {});
    if (up.statusOrCode !== 101) {
      throw new Error('derp upgrade status ' + String(up.statusOrCode));
    }
    return new SocketConn(up.socket, up.head);
  }
}

function makeClient(tag: string, keyPair: CryptoKeyPair): DerpClient {
  const node: DerpNode = {
    name: 'interop',
    hostName: url.hostname,
    certName: '',
    ipv4: '',
    ipv6: '',
    stunPort: 0,
    derpPort: Number(url.port),
    canPort80: false,
  };
  return new DerpClient({
    node: node,
    nodeKey: keyPair.publicKey,
    nodePrivateKey: keyPair.privateKey,
    dialer: new HttpDialer(),
    clock: { monotonicMs: () => Date.now() },
    rng: { randomBytes: (into: Uint8Array) => { into.set(randomBytes(into.length)); } },
  });
}

async function main(): Promise<void> {
  console.log('[1/4] 生成 A/B 身份并用自研控制面栈注册进真实 headscale');
  const a = x25519GenerateKeyPair(new ArrayRng(randomBytes(64)));
  const b = x25519GenerateKeyPair(new ArrayRng(randomBytes(64)));
  await registerNode('ohos-derp-a', a, 'A');
  await registerNode('ohos-derp-b', b, 'B');

  console.log('[2/4] 同一对 node key 连接真实 DERP（/derp，握手=ServerKey/ClientInfo/ServerInfo）');
  const clientA: DerpClient = makeClient('A', a);
  const clientB: DerpClient = makeClient('B', b);
  await Promise.all([clientA.connect(), clientB.connect()]);
  console.log('      双方握手完成 ✓');

  console.log('[3/4] B 订阅 A；A → B 包交换');
  clientB.subscribePeer(a.publicKey);
  const payload: Uint8Array = utf8Encode('hello-from-ohos-derp-interop');
  await clientA.sendPacket(b.publicKey, payload);

  const deadline: number = Date.now() + 20000;
  for (;;) {
    if (Date.now() > deadline) {
      fail('20s 内未收到 RecvPacket');
    }
    const ev = await Promise.race([
      clientB.receive(),
      new Promise<'timeout'>((resolve: (v: 'timeout') => void) => setTimeout(() => resolve('timeout'), 3000)),
    ]);
    if (ev === 'timeout') {
      continue;
    }
    if (ev === null) {
      fail('B 连接被对端关闭');
    }
    if (ev.kind === DerpClientEventKind.RecvPacket) {
      const got: string = new TextDecoder().decode(ev.packet);
      console.log('      RecvPacket ← "' + got + '"');
      if (got !== 'hello-from-ohos-derp-interop') {
        fail('payload mismatch: ' + got);
      }
      break;
    }
    console.log('      事件（忽略）kind=' + String(ev.kind));
  }

  console.log('[4/4] KeepAlive 与 NotePreferred');
  await clientA.sendKeepAlive();
  await clientA.notePreferred(true);

  clientA.close();
  clientB.close();
  console.log('');
  console.log('DERP INTEROP PASS: 注册→同密钥连 DERP→跨客户端包交换全链路打通');
  process.exit(0);
}

main().catch((e: unknown) => {
  fail(e instanceof Error ? e.message : String(e));
});
