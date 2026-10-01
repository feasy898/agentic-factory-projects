/**
 * 真实控制面互操作脚本（interop 联调，Node 侧驱动）。
 *
 * 用本仓核心库（noise.controlbase + control.tailcfg/noisehttp）对真实 Headscale
 * 控制面完成：/key 密钥发现 → POST /ts2021 协议升级（initiation 内嵌 HTTP 头）→
 * Noise IK 握手 → HTTP-over-Noise 注册（RegisterRequest）→ MapRequest 拉取网络地图。
 *
 * 本脚本属于 Node 侧测试胶水（在 packages/ 之外，允许 node:* 导入）；核心库代码
 * 不依赖本文件的任何内容。
 *
 * 用法：node --experimental-strip-types interop/register.node.ts <baseUrl> <authKey> [hostname]
 * 操作者显式指定 baseUrl（本机自建联调用 headscale，如 http://127.0.0.1:8080）。
 */

import http from 'node:http';
import { randomBytes } from 'node:crypto';

import {
  ArrayRng,
  KEY_LEN_BYTES,
} from '../packages/common/src/index.ts';
import { x25519GenerateKeyPair } from '../packages/crypto/src/index.ts';
import {
  controlbaseBuildInitiation,
  controlbaseCompleteHandshake,
  type ControlBaseDuplex,
  type ControlBaseSession,
} from '../packages/noise/src/controlbase.ts';
import {
  TAILCFG_CURRENT_CAPABILITY_VERSION,
  decodeMapResponseSummary,
  decodeRegisterResponse,
  encodeMapRequest,
  encodeRegisterRequest,
} from '../packages/control/src/index.ts';
import { H2OverNoise } from './h2c.node.ts';

function fail(message: string): never {
  console.error('FAIL: ' + message);
  process.exit(1);
}

const [, , baseUrlArg, authKeyArg, hostnameArg] = process.argv;
if (baseUrlArg === undefined || authKeyArg === undefined) {
  fail('usage: node --experimental-strip-types interop/register.node.ts <baseUrl> <authKey> [hostname]');
}
const baseUrl: string = baseUrlArg.replace(/\/$/, '');
const authKey: string = authKeyArg;
const hostname: string = hostnameArg === undefined ? 'ohos-interop-node' : hostnameArg;

function rand32(): Uint8Array {
  return new Uint8Array(randomBytes(KEY_LEN_BYTES));
}

/** /key 端点发现控制面 Noise 静态公钥（hex → 32B；headscale 要求 ?v=<capabilityVersion>）。 */
function fetchControlKey(): Promise<Uint8Array> {
  return new Promise<Uint8Array>((resolve: (k: Uint8Array) => void, reject: (e: Error) => void) => {
    http
      .get(baseUrl + '/key?v=' + String(TAILCFG_CURRENT_CAPABILITY_VERSION), (res: http.IncomingMessage) => {        let body: string = '';
        res.on('data', (d: Buffer) => {
          body += String(d);
        });
        res.on('end', () => {
          // 兼容两种形态：纯 hex（tailscale 语义）与 JSON {"legacyPublicKey":"mkey:..","publicKey":"mkey:.."}（headscale v0.29+）
          const raw: string = body.trim();
          let hex: string = raw;
          if (raw.startsWith('{')) {
            try {
              const parsed = JSON.parse(raw) as { publicKey?: string };
              hex = (parsed.publicKey === undefined ? '' : parsed.publicKey).toLowerCase();
            } catch (e) {
              reject(new Error('/key JSON parse failed: ' + String(e)));
              return;
            }
          } else {
            hex = raw.toLowerCase();
          }
          hex = hex.replace(/^pubkey:/, '').replace(/^mkey:/, '').trim();
          if (!/^[0-9a-f]{64}$/.test(hex)) {
            reject(new Error('/key returned unexpected payload: ' + body.slice(0, 80)));
            return;
          }
          const out: Uint8Array = new Uint8Array(32);
          for (let i: number = 0; i < 32; i += 1) {
            out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
          }
          resolve(out);
        });
      })
      .on('error', reject);
  });
}

/** node socket → ControlBaseDuplex 适配。 */
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
      this.queue.push(d);
      if (this.waiter !== null) {
        const w: (b: Uint8Array) => void = this.waiter;
        this.waiter = null;
        w(new Uint8Array(this.queue.shift() as Buffer));
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

  public async send(data: Uint8Array): Promise<void> {
    this.socket.write(Buffer.from(data));
  }

  /** 把字节塞回流头部（Noise response 之后残留字节的归还通道）。 */
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
  statusOrCode: number;
  headers: http.IncomingHttpHeaders;
  /** 101 响应之后、upgrade 事件之前到达的字节（node 单独交付；这里是 noise response 的开头） */
  head: Buffer;
}

/** POST /ts2021 升级请求；initiation 内嵌 X-Tailscale-Handshake 头。 */
function upgradeRequest(baseUrl: string, initFrame: Uint8Array): Promise<UpgradeResult> {
  const url: URL = new URL(baseUrl + '/ts2021');
  return new Promise<UpgradeResult>((resolve: (r: UpgradeResult) => void, reject: (e: Error) => void) => {
    const req: http.ClientRequest = http.request(
      {
        host: url.hostname,
        port: Number(url.port),
        method: 'POST',
        path: url.pathname,
        headers: {
          Host: url.host,
          Connection: 'upgrade',
          Upgrade: 'tailscale-control-protocol',
          'X-Tailscale-Handshake': Buffer.from(initFrame).toString('base64'),
        },
      },
      (res: http.IncomingMessage) => {
        // 非 101：服务器拒绝了升级
        let body: string = '';
        res.on('data', (d: Buffer) => {
          body += String(d);
        });
        res.on('end', () => reject(new Error('upgrade refused: HTTP ' + String(res.statusCode) + ' ' + body.slice(0, 200))));
      },
    );
    req.on('upgrade', (res: http.IncomingMessage, socket: import('node:net').Socket, head: Buffer) => {
      resolve({ socket: socket, statusOrCode: res.statusCode === undefined ? 0 : res.statusCode, headers: res.headers, head: head });
    });
    req.on('error', reject);
    req.end();
  });
}

async function main(): Promise<void> {
  console.log('[1/5] /key 密钥发现 ' + baseUrl + '/key');
  const controlKey: Uint8Array = await fetchControlKey();
  console.log('      control noise pubkey: ' + Buffer.from(controlKey).toString('hex').slice(0, 16) + '…');

  console.log('[2/5] 生成机器身份并构建 initiation（noise.controlbase）');
  const machine = x25519GenerateKeyPair(new ArrayRng(randomBytes(64)));
  const node = x25519GenerateKeyPair(new ArrayRng(randomBytes(64)));
  const disco = x25519GenerateKeyPair(new ArrayRng(randomBytes(64)));
  const init = controlbaseBuildInitiation(machine.privateKey, controlKey, new ArrayRng(randomBytes(64)));

  console.log('[3/5] POST /ts2021 升级 + Noise IK 握手');
  const up: UpgradeResult = await upgradeRequest(baseUrl, init.frame);
  if (up.statusOrCode !== 101) {
    fail('expected 101, got ' + String(up.statusOrCode));
  }
  console.log('      101 Switching Protocols ✓（Upgrade: ' + String(up.headers.upgrade) + '）');
  const duplex: SocketDuplex = new SocketDuplex(up.socket, up.head);
  const respBytes: Uint8Array = await readExactAllowExtra(duplex, 51);
  const session: ControlBaseSession = controlbaseCompleteHandshake(init, respBytes.slice(0, 51));
  duplex.prepend(respBytes.slice(51)); // EarlyNoise 等残留字节归还给流
  console.log('      Noise IK 握手完成 ✓');

  console.log('[4/5] HTTP/2 over Noise（headscale h2c）：POST /machine/register');
  const url: URL = new URL(baseUrl);
  const authority: string = url.host;
  const h2: H2OverNoise = new H2OverNoise(session, duplex);
  const registerBody: string = encodeRegisterRequest({
    capabilityVersion: TAILCFG_CURRENT_CAPABILITY_VERSION,
    nodeKeyPublic: node.publicKey,
    oldNodeKeyPublic: null,
    authKey: authKey,
    expiryRfc3339: '2030-01-01T00:00:00Z',
    hostname: hostname,
    os: 'OpenHarmony',
    ephemeral: false,
  });
  const regRespBytes: Uint8Array = await h2.post(authority, '/machine/register', registerBody);
  const regText: string = new TextDecoder().decode(regRespBytes);
  console.log('      register 响应: ' + regText.slice(0, 200));
  const reg: ReturnType<typeof decodeRegisterResponse> = decodeRegisterResponse(regText);
  console.log('      MachineAuthorized=' + String(reg.machineAuthorized) + ' AuthURL="' + reg.authUrl + '"');
  if (!reg.machineAuthorized) {
    fail('machine not authorized（检查 preauth key）');
  }

  console.log('[5/5] HTTP/2 over Noise：POST /machine/map（Stream=true，读首帧 MapResponse）');
  const mapBody: string = encodeMapRequest({
    capabilityVersion: TAILCFG_CURRENT_CAPABILITY_VERSION,
    nodeKeyPublic: node.publicKey,
    discoKeyPublic: disco.publicKey,
    stream: true,
    hostname: hostname,
    os: 'OpenHarmony',
  });
  const firstLine: string = await h2.postFirstLine(authority, '/machine/map', mapBody);
  console.log('      map 首帧前 100 字节: ' + firstLine.slice(0, 100));
  const view: ReturnType<typeof decodeMapResponseSummary> = decodeMapResponseSummary(firstLine);
  console.log('      MapResponse 解析 ✓（peers=' + String(view.peerCount) + ' keepAlive=' + String(view.keepAlive) + '）');

  await session.close(duplex);
  console.log('');
  console.log('INTEROP PASS: 真实 Headscale 注册 + 网络地图拉取全部成功（纯自研 TS 协议栈）');
  process.exit(0);
}

/** 从 duplex 精确读取 n 字节（允许一次读到超过 n 的额外字节，一并返回）。 */
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

main().catch((e: unknown) => {
  fail(e instanceof Error ? e.message : String(e));
});
