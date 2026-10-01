/**
 * ShellControlSession —— 壳（VpnExtensionAbility / Index.ets）面向协议核心的会话门面。
 *
 * 职责（README-app.md §4 平台注入层的壳侧半边；真机注入实现落地前用 mock 打通全链路）：
 * - 校验并装配 ControlClientConfig（fail-fast：坏参数拒绝进入任何网络路径）；
 * - login(endpoints)：Noise IK dial → 发 RegisterRequest（node/disco 公钥 + 候选端点）；
 * - pollMap()：长轮询 receive() → NetworkMap 解码 → 会话转 Online；
 * - statusSnapshot()：UI 三态快照（Index.ets ConnState 语义）；
 * - authKey 纪律（红线 1 对齐）：
 *     1) 只做形状校验（非空/无空白/ASCII 可打印），永不进任何 HTTP 请求体/日志；
 *        ——精简版 RegisterRequest（TLV）无 auth 字段，authKey 上行承载属上游核对项
 *        （docs/architecture.md §10 AU 清单），真实注册扩展在前；
 *     2) close() 时从内存清空；
 *     3) 测试面：对 transport 留痕的每个请求体做「authKey 字节不出现」断言。
 *
 * 不做的事：不碰 socket/TLS（D4）、不内嵌平台 API（P3——本文件在 app/ 侧无此约束但保持
 * 纯净以利未来 ArkTS 移植）、不改 packages/ 任何文件。
 */

import {
  KEY_LEN_BYTES,
  type Clock,
  type HttpTransport,
  type Rng,
} from '@ohos-tailscale/common';
import { type CryptoKeyPair } from '@ohos-tailscale/crypto';
import {
  ControlClient,
  ControlError,
  ControlMsgKind,
  networkMapDecode,
  registerRequestEncode,
  type ControlMessage,
  type NetworkMap,
} from '@ohos-tailscale/control';
import {
  buildDetail,
  ShellSessionState,
  uiConnStateOf,
  type ShellStatus,
} from './shell-status.ts';

/** 壳会话装配参数（真机上由 EntryAbility 从 Asset Store/preferences 组装）。 */
export interface ShellSessionParams {
  /** 控制面 URL（例 'https://net.example.test'）。 */
  controlUrl: string;
  /** ts2021 machine key 对（Noise IK 本端静态）。 */
  machineKeyPair: CryptoKeyPair;
  /** WireGuard 层 node key 对。 */
  nodeKeyPair: CryptoKeyPair;
  /** disco 发现协议公钥（32B）。 */
  discoKey: Uint8Array;
  /** 控制面 Noise IK 服务端静态公钥（32B）。 */
  serverStaticPublic: Uint8Array;
  /** 登录密钥（形状校验 + 零传输面；见文件头纪律节）。 */
  authKey: string;
  /** 平台注入：HTTP 传输（真机 = @ohos.net.http 包装；mock = MockHttpTransport/MockControlPlane）。 */
  transport: HttpTransport;
  /** 平台注入：时钟。 */
  clock: Clock;
  /** 平台注入：随机源。 */
  rng: Rng;
}

const AUTH_KEY_MAX_LEN: number = 128;

const isAsciiPrintableNoSpace = (s: string): boolean => {
  for (let i: number = 0; i < s.length; i += 1) {
    const code: number = s.charCodeAt(i);
    if (code <= 0x20 || code >= 0x7f) {
      return false;
    }
  }
  return true;
};

const requireKey32 = (key: Uint8Array, what: string): void => {
  if (key.length !== KEY_LEN_BYTES) {
    throw new Error('shell-session: ' + what + ' must be ' + String(KEY_LEN_BYTES) + ' bytes');
  }
};

export class ShellControlSession {
  private params: ShellSessionParams;
  private client: ControlClient | null = null;
  private state: number = ShellSessionState.Idle;
  private lastMap: NetworkMap | null = null;
  private authKey: string;

  public constructor(params: ShellSessionParams) {
    if (params.controlUrl.length === 0) {
      throw new Error('shell-session: controlUrl required');
    }
    requireKey32(params.discoKey, 'discoKey');
    requireKey32(params.serverStaticPublic, 'serverStaticPublic');
    const key: string = params.authKey;
    if (key.length === 0 || key.length > AUTH_KEY_MAX_LEN || !isAsciiPrintableNoSpace(key)) {
      throw new Error('shell-session: authKey shape invalid (non-empty printable ASCII, <=128 chars)');
    }
    this.params = params;
    this.authKey = key;
  }

  /** 仅测试/审计可见：authKey 当前是否仍在内存（close 后必须 false）。 */
  public authKeyResident(): boolean {
    return this.authKey.length > 0;
  }

  /** dial + 发注册请求。成功后会话转 Connecting（等待首个 netmap 转 Online）。 */
  public async login(endpoints: string[]): Promise<void> {
    if (this.client !== null) {
      throw new Error('shell-session: already logged in');
    }
    this.client = new ControlClient({
      controlUrl: this.params.controlUrl,
      nodeKeyPair: this.params.nodeKeyPair,
      machineKeyPair: this.params.machineKeyPair,
      serverStaticPublic: this.params.serverStaticPublic,
      transport: this.params.transport,
      clock: this.params.clock,
      rng: this.params.rng,
    });
    this.state = ShellSessionState.Connecting;
    try {
      await this.client.dial();
      await this.client.send(
        registerRequestEncode({
          nodeKey: this.params.nodeKeyPair.publicKey,
          discoKey: this.params.discoKey,
          endpoints: endpoints,
        }),
      );
    } catch (e) {
      this.state = ShellSessionState.Idle;
      this.client = null;
      throw e;
    }
  }

  /** 取下一条控制面消息；MapResponse 时解码 netmap 并转 Online，其余原样返回。 */
  public async pollMessage(): Promise<ControlMessage> {
    const client: ControlClient = this.requireClient();
    const msg: ControlMessage = await client.receive();
    if (msg.kind === ControlMsgKind.MapResponse) {
      this.lastMap = networkMapDecode(msg);
      this.state = ShellSessionState.Online;
    }
    return msg;
  }

  /** 便捷轮询：取下一条 MapResponse（其余消息跳过继续收）。 */
  public async pollMap(): Promise<NetworkMap> {
    for (;;) {
      const msg: ControlMessage = await this.pollMessage();
      if (msg.kind === ControlMsgKind.MapResponse) {
        const map: NetworkMap = this.lastMap as NetworkMap;
        return map;
      }
    }
  }

  /** UI 快照（Index.ets ConnState 语义 + 人读明细）。 */
  public statusSnapshot(): ShellStatus {
    const map: NetworkMap | null = this.lastMap;
    const peerCount: number = map === null ? 0 : map.peers.length;
    const derpRegionIds: number[] = map === null ? [] : map.peers.map((p) => p.homeDerpRegionId);
    const status: ShellStatus = {
      sessionState: this.state,
      uiConnState: uiConnStateOf(this.state),
      detail: buildDetail(peerCount, map === null ? 0n : map.seqNo, derpRegionIds),
      peerCount: peerCount,
      seqNo: map === null ? 0n : map.seqNo,
    };
    return status;
  }

  /** 关闭会话并清 authKey；幂等。 */
  public close(): void {
    if (this.client !== null) {
      this.client.close();
      this.client = null;
    }
    this.state = ShellSessionState.Closed;
    this.authKey = '';
  }

  private requireClient(): ControlClient {
    if (this.client === null) {
      throw new ControlError('STATE', 'shell-session: not logged in') as Error;
    }
    return this.client;
  }
}
