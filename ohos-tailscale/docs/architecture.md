# ohos-tailscale 核心库架构契约（architecture.md）

- 生成日期：2026-09-28
- 作者角色：协议库首席架构师
- 效力：本文是 `packages/` 下六个包的**实现契约**。并行实现者必须严格照办本文签名；本文与实现冲突时，以本文为准并回报架构师修订。
- 上位约束：`docs/arkts-constraints.md`（语法/工程禁则，下称【约束】）与 `docs/oracle/protocol-notes.md`（协议取证，下称【取证】）。本文不重复其条文，只做引用与裁定。
- 状态基线（本文定稿时实测）：Node v22.23.2 直接跑 `.ts`（type stripping）；根 `package.json` 已含 `"type": "module"` + `"workspaces": ["packages/*"]`（约束 P7 已满足）；根 `tsconfig.json` 已含 `erasableSyntaxOnly` + `verbatimModuleSyntax`（约束 T2 已满足）；`npm install` 已为 `packages/*` 建立 `node_modules/@ohos-tailscale/*` 链接。

---

## 1. 包拓扑与依赖方向（无环，强制）

```
            ┌──────────────┐
            │   control    │  控制面客户端（ts2021/Noise 长轮询 + TLV 消息 + netmap 状态）
            └──┬───────┬───┘
       依赖    │       │    依赖
      ┌────────▼─┐   ┌─▼────────┐
      │ wireguard │   │  noise   │   数据面协议核心        控制面握手协议核心
      └─────┬────┘   └────┬────┘
            │    依赖      │
            └──────►┌──────▼──────┐
                    │   crypto    │  密码学原语（X25519 / ChaCha20Poly1305 / BLAKE2s / SHA-256 / HKDF）
                    └──────┬──────┘
                    依赖    │
                    ┌──────▼──────┐
                    │   common    │  注入接口 + 字节/编码工具 + 公共常量（已实现，API 冻结）
                    └──────▲──────┘
                    依赖    │
                    ┌──────┴──────┐
                    │    derp     │  DERP 中继帧协议（编解码 + region 选择）
                    └─────────────┘
```

规则（编号 D1–D4，违反即为架构错误）：

- **D1 允许的 import 边** = 上图边的传递闭包：`control → {wireguard, noise, crypto, common}`、`wireguard → {crypto, common}`、`noise → {crypto, common}`、`crypto → {common}`、`derp → {common}`。直接 import 传递依赖合法（如 wireguard 直接 import common）。
- **D2 禁止一切反向边与跨支边**：common 不得 import 任何包；crypto 不得 import 协议包；wireguard 与 noise **互不** import；derp 只许 import common（不得 import crypto/wireguard/noise/control）。
- **D3 跨包 import 一律用包名** `@ohos-tailscale/<pkg>`（约束 §4 + P2；包内相对导入必须带 `.ts` 后缀）。各包 `package.json` 统一模板见 §9。
- **D4 核心库一律不碰 socket/TLS/UDP**：网络端点由 `common` 的注入接口（HttpTransport）或各包自定义注入接口（如 derp 的 Dialer，见 §7.4）从 `app/` 侧注入。核心库 = 纯协议逻辑 + 编解码 + 状态机。

---

## 2. 已裁定的约束裁定项（实现者必须遵守，不得另行解释）

| # | 裁定 | 依据 |
|---|---|---|
| R1 | 共享注入接口名为 **`Rng`**（方法签名保持约束 P4 示例 `randomBytes(into: Uint8Array): void` 不变）。约束 P4 示例中的 `RandomSource` 视为同一概念的历史名。 | 本架构定稿指令；P4 |
| R2 | **平台实现不进 common**：common 只含接口 + 确定性测试实现（`FixedClock`、`ArrayRng`）。Node/真机的系统实现（`Date.now`、`node:crypto`、`@ohos.security.cryptoFramework` 包装）放 `app/` 侧 adapter。理由：约束 P3（src 禁 node:*）与 P4 括注"Node 实现只在 common"存在张力，按 P4 自己给出的替代方案（"放 app/ 侧或独立 adapter 包"，§6-U7）裁定，保住 P3 的 lint 门禁形态。 | P3 / P4 / U7 |
| R3 | **核心库禁用 `JSON.parse`/`JSON.stringify` 处理协议消息**（A1 禁 any/unknown，JSON.parse 返回值无法静态定型）。控制面消息一律 TLV（见 §6）；JSON 只允许出现在 `app/` 侧 LocalAPI 展示层。 | A1 / 【取证】§8-1 |
| R4 | **全仓禁用 tuple 类型**（`[A, B]`）。多返回值用定长 `Uint8Array[]`（如 HKDF 输出）或纯字段 interface。约束 A 组未单列 tuple，本条按 ArkTS 不支持 tuple 的事实补裁定。 | A16 类比 |
| R5 | 字面量联合类型（`'ping' \| 'pong'`）禁用（A18）；一切"常量集合"用 **常量对象 + 运行时校验函数** 模式：`interface XE { A: number; B: number }` + `const X: XE = {...}`，配 `parseX(v: number): number \| null`。 | A18 / A34 |
| R6 | 一切函数（含测试）显式写返回类型；禁 `var`、禁解构（A7/A8/A9）、禁对象展开、禁 call/apply/bind、禁函数表达式（统一箭头函数）、禁嵌套函数声明（局部复用提升为模块级函数）。 | A22 / A24 / A27 / A36 |
| R7 | `throw` 只允许 `Error` 子类实例；每包定义自己的错误类（`XxxError extends Error`，带 `public code: string` 字段）。 | A25 |
| R8 | u64 槽位一律 `BigInt`；长度/计数在安全范围内的用 `number`。`Uint8Array` 跨层传递按需 `slice()` 拷贝，API 注释必须写明"返回拷贝"还是"共享视图"。 | P5 / P6 |

---

## 3. common 包（已实现，API 冻结）

职责：共享注入接口（Clock/Rng/HttpTransport）、字节流 reader/writer、hex/base64/UTF-8 编解码、公共常量。**零平台依赖**（P3/P4），**公开 API 自本版本起冻结**（§8 冻结流程）。

实现文件与导出（与 `packages/common/src` 现状一一对应，已由 `packages/common/test/*.test.ts` 覆盖，40/40 绿）：

```ts
// bytes.ts
export class ByteReader {
  constructor(buf: Uint8Array);                 // 持引用，不拷贝
  get offset(): number;
  get remaining(): number;
  atEnd(): boolean;
  readU8(): number;
  readU16be(): number;  readU16le(): number;
  readU32be(): number;  readU32le(): number;    // u32 上界校验
  readU64be(): bigint;  readU64le(): bigint;
  readUvarint(): bigint;                        // LEB128，最多 10 字节，>64 位抛 Error
  readBytes(n: number): Uint8Array;             // 返回独立拷贝
  takeRemaining(): Uint8Array;                  // 返回独立拷贝
  skip(n: number): void;                        // 越界抛 Error 且 offset 不前移
}
export class ByteWriter {
  constructor(initialCapacity?: number);        // 缺省 64，自动倍增扩容
  get length(): number;
  writeU8(v: number): void;
  writeU16be(v: number): void;  writeU16le(v: number): void;
  writeU32be(v: number): void;  writeU32le(v: number): void;
  writeU64be(v: bigint): void;  writeU64le(v: bigint): void;
  writeUvarint(v: bigint): void;
  writeBytes(b: Uint8Array): void;
  toUint8Array(): Uint8Array;                   // 已写区域的独立拷贝
  reset(): void;
}
// 越界/超域一律 throw new Error（A25 合规）
```

```ts
// hex.ts
export function hexEncode(src: Uint8Array): string;      // 小写
export function hexDecode(s: string): Uint8Array;        // 大小写通吃；奇数长/非法字符抛 Error
```

```ts
// base64.ts —— RFC 4648，严格 canonical
export function base64Encode(src: Uint8Array): string;   // std：'+' '/'，带 '=' 填充
export function base64Decode(s: string): Uint8Array;     // 长度须 4 的倍数、'=' 只许末尾 1~2 个、
                                                         // 尾部剩余位须为 0，否则抛 Error
export function base64UrlEncode(src: Uint8Array): string; // url：'-' '_'
export function base64UrlDecode(s: string): Uint8Array;
```

```ts
// utf8.ts —— 纯手写（U3：不用 TextEncoder/TextDecoder），双侧严格
export function utf8Encode(s: string): Uint8Array;       // 孤立代理项抛 Error
export function utf8Decode(bytes: Uint8Array): string;   // 拒绝截断/overlong/代理区/>U+10FFFF，抛 Error
```

```ts
// clock.ts —— 共享注入接口（冻结）
export interface Clock {
  wallMs(): number;        // 挂钟毫秒
  monotonicMs(): number;   // 单调毫秒
}
export class FixedClock implements Clock {   // 测试用确定性实现
  constructor(startWallMs?: number);         // 缺省 0；mono 轴从 0 起
  advanceMs(delta: number): void;            // 双轴同步前进；负值抛 Error
  setWallMs(v: number): void;                // 只平移挂钟轴
  wallMs(): number;  monotonicMs(): number;
}
```

```ts
// random.ts —— 共享注入接口（冻结；命名裁定见 R1）
export interface Rng {
  randomBytes(into: Uint8Array): void;       // 必须填满整个 into
}
export class ArrayRng implements Rng {       // 测试用确定性实现：从 pool 循环取字节
  constructor(pool: Uint8Array);             // 构造时拷贝
  randomBytes(into: Uint8Array): void;       // 空 pool 抛 Error；零长度填充为 no-op
}
```

```ts
// http.ts —— 共享注入接口（冻结）
export interface HttpRequest  { method: string; url: string; headers: Record<string, string>; body: Uint8Array; }
export interface HttpResponse { status: number; headers: Record<string, string>; body: Uint8Array; }
export interface HttpBodyStream {
  read(): Promise<Uint8Array | null>;        // 流结束 → null；出错 reject Error
  close(): void;
}
export interface StreamingHttpResponse { status: number; headers: Record<string, string>; body: HttpBodyStream; }
export interface HttpTransport {
  send(request: HttpRequest): Promise<HttpResponse>;            // 缓冲全量（短请求）
  open(request: HttpRequest): Promise<StreamingHttpResponse>;   // 流式响应（长轮询/推送）
}
// headers 约定：请求键按原样发送；响应键一律小写；取值按可能 undefined 处理（A17）
```

```ts
// constants.ts —— 公共常量
export const KEY_LEN_BYTES: number;         // 32
export const AEAD_NONCE_LEN_BYTES: number;  // 12
export const AEAD_TAG_LEN_BYTES: number;    // 16
export const MAX_U64: bigint;               // 2^64-1
export const WG_DEFAULT_PORT: number;       // 41641（【取证】§7）
export const DERP_DEFAULT_PORT: number;     // 443（【取证】§3）
export const STUN_DEFAULT_PORT: number;     // 3478（【取证】§3）
export const CGNAT_V4_CIDR: string;         // '100.64.0.0/10'（【取证】§2.2）
export const TAILNET_ULA_V6_CIDR: string;   // 'fd7a:115c:a1e0::/48'（【取证】§2.2）
```

```ts
// index.ts —— barrel，re-export 上述全部
```

---

## 4. crypto 包 `@ohos-tailscale/crypto`

职责：协议所需的全部密码学原语，**纯计算、无 IO、无状态驻留**（每次调用独立）。wireguard 与 noise 是它仅有的两个消费方。内部实现自选（手写或移植），但**签名与语义按本节冻结**。

```ts
// index.ts barrel 导出以下全部

export interface CryptoKeyPair { publicKey: Uint8Array; privateKey: Uint8Array }  // 各 32B
export class CryptoError extends Error { public code: string }  // code: 'AUTH' | 'RANGE' | 'INVALID'

// ---- x25519.ts ----
// 全部函数入参出参 32B；长度不符抛 CryptoError('RANGE')
export function x25519GenerateKeyPair(rng: Rng): CryptoKeyPair;
  // 32 随机字节 → clamp（RFC 7748：bits[0..2]=0, bit[255]=0, bit[254]=1）后作为 privateKey 存储并派生 publicKey
export function x25519PublicKeyFromPrivate(privateKey: Uint8Array): Uint8Array;
  // clamp 后 base point 乘法（等价 Go curve25519.X25519(k, basepoint)）
export function x25519(scalar: Uint8Array, point: Uint8Array): Uint8Array;
  // RFC 7748 X25519，内部 clamp（幂等）；输出全零不在此拦截，由调用方用 isZeroBytes 检查（WG 语义）
export function isZeroBytes(b: Uint8Array): boolean;

// ---- aead.ts：ChaCha20-Poly1305（RFC 8439）----
// key 32B、nonce 12B；密文布局 = ciphertext || tag(16B)
export function aeadSeal(key: Uint8Array, nonce: Uint8Array, plaintext: Uint8Array, aad: Uint8Array): Uint8Array;
export function aeadOpen(key: Uint8Array, nonce: Uint8Array, ciphertextWithTag: Uint8Array, aad: Uint8Array): Uint8Array;
  // 认证失败抛 CryptoError('AUTH')；aad 传零长度数组表示无 AAD

// ---- hash.ts ----
export function sha256(data: Uint8Array): Uint8Array;                       // 32B
export function hmacSha256(key: Uint8Array, data: Uint8Array): Uint8Array;  // 32B
export function blake2s256(data: Uint8Array): Uint8Array;                   // 无键 BLAKE2s-256，32B
export function blake2s256Keyed(key: Uint8Array, data: Uint8Array): Uint8Array;
  // 键控 BLAKE2s-256（key 1..32B，WG MAC1/MAC2 用 32B 键），32B
export function kdf2Blake2s(chainingKey: Uint8Array, ikm: Uint8Array): Uint8Array[];
  // HKDF-HMAC-BLAKE2s，输出定长 2（WG/Noise KDF²）
export function kdf3Blake2s(chainingKey: Uint8Array, ikm: Uint8Array): Uint8Array[];
  // 同上，输出定长 3（WG/Noise KDF³）
export function kdf2Sha256(chainingKey: Uint8Array, ikm: Uint8Array): Uint8Array[];
export function kdf3Sha256(chainingKey: Uint8Array, ikm: Uint8Array): Uint8Array[];

// ---- util.ts ----
export function constTimeEqual(a: Uint8Array, b: Uint8Array): boolean;  // 常时比较，长度不等直接 false
export function wipe(b: Uint8Array): void;                              // 全零覆写（清密钥用）
```

### 4.1 crypto 测试策略

- **与 `node:crypto` 交叉验证**（`node:crypto` 仅允许出现在 `*.test.ts`，P3）：
  - `x25519`/`x25519PublicKeyFromPrivate` 对照 `crypto.diffieHellman` + `crypto.createPublicKey({key, format:'jwk'})`（x25519 JWK）；
  - `aeadSeal/aeadOpen` 对照 `crypto.createCipheriv('chacha20-poly1305', ...)`（`setAAD` + `getAuthTag`，布局 `ciphertext||tag`）；
  - `sha256`/`hmacSha256`/`blake2s256` 对照 `crypto.createHash`/`createHmac`；
  - `kdf2/kdf3` 在测试里用 node 原语手工展开 HKDF 对照（测试内独立二次实现）。
- **键控 BLAKE2s 无 node 对应**：用 RFC 7693 与参考实现已知答案向量（KAT）写死 hex 断言。
- 往返：`aeadOpen(key, nonce, aeadSeal(...)) === plaintext`；篡改密文/AAD 任意 1 bit 必须抛 `CryptoError('AUTH')`。
- `constTimeEqual` 长度不等返回 false 不抛错；`wipe` 后全零。

---

## 5. wireguard 包 `@ohos-tailscale/wireguard`

职责：WireGuard 数据面协议核心（_noise_ 通道握手 + 传输加解密 + 反重放），纯字节进字节出，UDP socket 由 `app/` 侧负责。互操作对象是真实 WireGuard 对端，报文格式以 WireGuard 白皮书为准（D1 边：只 import crypto/common）。

### 5.1 报文布局常量（本包内集中定义）

| 报文 | 总长（字节） | 布局（字段序） |
|---|---|---|
| Handshake Initiation | 148 | `type u32le=1`、`sender u32le`、`ephemeral 32`、`enc(static) 48`、`enc(timestamp) 28`、`mac1 16`、`mac2 16` |
| Handshake Response | 92 | `type u32le=2`、`sender u32le`、`receiver u32le`、`ephemeral 32`、`enc(empty) 16`、`mac1 16`、`mac2 16` |
| Cookie Reply | 64 | `type u32le=3`、`receiver u32le`、`nonce 24`、`enc(cookie) 32` |
| Transport Data | 16 + payload | `type u32le=4`、`receiver u32le`、`counter u64le`、`enc(payload)+tag 16` |

其余固定量：键 32B、TAI64N 时间戳 12B（8B 秒 BE 带偏移 + 4B 纳秒 BE）、Poly1305 标签 16B、MAC1/MAC2 各 16B、所有整数**小端**（白皮书语义）。

```ts
// index.ts barrel 导出以下全部
export interface WgMessageTypeE { HandshakeInitiation: number; HandshakeResponse: number; CookieReply: number; TransportData: number }
export const WgMessageType: WgMessageTypeE;       // { 1, 2, 3, 4 }（R5 常量对象模式）
export function parseWgMessageType(v: number): number | null;

export class WgProtocolError extends Error { public code: string } // 'BAD_TYPE'|'BAD_LEN'|'MAC'|'DECRYPT'|'REPLAY'|'ZERO_DH'|'STATE'

// ---- handshake.ts ----
export interface WgInitiationInfo {
  senderIndex: number;        // u32le
  peerStaticPublic: Uint8Array; // 32B，已用本端静态私钥 DH 验证
  timestamp: Uint8Array;      // 12B TAI64N（调用方负责重放比较）
}
export interface WgHandshakeOutput {
  localIndex: number;         // 本端会话索引（responder 侧取 consume 到的对端 sender 之外的本地新值）
  peerIndex: number;          // 对端会话索引
  sendKey: Uint8Array;        // 32B（本端 → 对端）
  recvKey: Uint8Array;        // 32B（对端 → 本端）
}
export class WgHandshakeInitiator {
  constructor(staticPrivate: Uint8Array, peerStaticPublic: Uint8Array, rng: Rng, clock: Clock);
  createInitiation(): Uint8Array;               // 148B；时间戳取 clock.wallMs() 派生的 TAI64N；临时密钥取 rng
  consumeResponse(msg: Uint8Array): void;       // 校验 type/长度/mac1、解密；失败抛 WgProtocolError
  finish(): WgHandshakeOutput;                  // consumeResponse 成功后调用；否则抛 WgProtocolError('STATE')
}
export class WgHandshakeResponder {
  constructor(staticPrivate: Uint8Array, rng: Rng, clock: Clock);
  consumeInitiation(msg: Uint8Array): WgInitiationInfo;  // 失败抛 WgProtocolError
  createResponse(): Uint8Array;                 // 92B（在 consumeInitiation 成功后调用）
  finish(): WgHandshakeOutput;
}
// 一期不实现 Cookie Reply 的生成/消费：解析到 type=3 一律抛 WgProtocolError('BAD_TYPE')
// 由上层触发重新握手（二期再补，接口预留不变）。

// ---- transport.ts ----
export class WgSendSession {
  constructor(localIndex: number, sendKey: Uint8Array);
  encryptPacket(plaintext: Uint8Array): Uint8Array;
  // 输出完整可发报文（16B 头 + AEAD 密文）；counter 从 0 自增（u64le）；keepalive = 零长度明文
}
export class WgRecvSession {
  constructor(peerIndex: number, recvKey: Uint8Array);
  decryptPacket(packet: Uint8Array): Uint8Array;
  // 校验 type=4/receiver/counter 反重放（滑动窗口 2048 位）；keepalive 返回零长度数组；重放抛 'REPLAY'
}
```

### 5.2 wireguard 测试策略

- **确定性向量**：注入 `ArrayRng`（固定临时密钥字节）+ `FixedClock`（固定 TAI64N 时间戳），对 `createInitiation()`/`createResponse()` 断言**完整 148B/92B 字节级 hex 向量**（向量对照 wireguard-go/白皮书参考值写死后锁定）。
- **两端往返**：同进程 initiator + responder 完成整场握手 → `finish()` 后互建 send/recv session → 双向 `encryptPacket/decryptPacket` 往返（含空载荷 keepalive、跨 counter 进位值如 `2^31`、`2^53+1`）。
- 失败路径：篡改 1 bit → `DECRYPT`/`MAC`；重放旧 counter 包 → `REPLAY`；错静态密钥对 → 握手解密失败；错误类型码/截断 → `BAD_TYPE`/`BAD_LEN`。

---

## 6. noise 包 `@ohos-tailscale/noise`

职责：控制面 ts2021 的 Noise 握手与传输加密（`Noise_IK_25519_ChaChaPoly_BLAKE2s`）+ 该通道的帧编解码。D1 边：只 import crypto/common。

```ts
// index.ts barrel 导出以下全部
export const NOISE_PROTOCOL_NAME: string;   // 'Noise_IK_25519_ChaChaPoly_BLAKE2s'
export class NoiseError extends Error { public code: string } // 'DECRYPT'|'STATE'|'FRAME'|'PROLOGUE'

// ---- handshake.ts：IK 模式（msg1: -> e, es, s, ss；msg2: <- e, ee, se）----
export interface NoiseIkPayload {
  payload: Uint8Array;        // 对端握手载荷（明文）
  remoteStatic: Uint8Array;   // 32B，对端静态公钥（仅 responder 侧）
}
export interface NoiseTransportPair { send: NoiseTransportCipher; recv: NoiseTransportCipher }
export class NoiseIkInitiator {
  constructor(prologue: Uint8Array, staticPrivate: Uint8Array, remoteStatic: Uint8Array, rng: Rng);
  writeMessageA(payload: Uint8Array): Uint8Array;  // 80B 头（32 e + 48 enc(s)）+ payload
  readMessageB(msg: Uint8Array): Uint8Array;       // 48B 头（32 e + 16 tag）+ payload → 返回 payload；失败抛 NoiseError('DECRYPT')
  split(): NoiseTransportPair;                     // msgB 读取成功后调用
}
export class NoiseIkResponder {
  constructor(prologue: Uint8Array, staticPrivate: Uint8Array, rng: Rng);
  readMessageA(msg: Uint8Array): NoiseIkPayload;
  writeMessageB(payload: Uint8Array): Uint8Array;
  split(): NoiseTransportPair;
}

// ---- transport.ts ----
export class NoiseTransportCipher {
  // nonce = 4B 零 || BE64 计数器（自 0 递增）；输出 = 密文 || 16B tag；两端计数器独立
  encrypt(plaintext: Uint8Array): Uint8Array;
  decrypt(ciphertextWithTag: Uint8Array): Uint8Array;  // 失败抛 NoiseError('DECRYPT')
}

// ---- frame.ts：通道帧（2B BE 长度前缀 + noise 消息，单帧 ≤ 65535B）----
// ⚠ 上游核对项（§10-U1）：长度前缀宽度/端序以 tailscale controlbase 实读为准；
//   两端同为本地实现时语义自洽，测试不受影响；常量集中本文件，便于核对后一次改齐。
export function noiseFrameEncode(msg: Uint8Array): Uint8Array;   // msg > 65535B 抛 NoiseError('FRAME')
export interface NoiseFrame { payload: Uint8Array }              // 单帧解码结果
export function noiseFrameDecode(src: Uint8Array): NoiseFrame;   // 格式错误抛 NoiseError('FRAME')
export class NoiseFrameReader {          // 跨 chunk 帧重组
  push(chunk: Uint8Array): NoiseFrame[]; // 输入新字节，返回本轮解出的完整帧（0..n 个）
  pendingBytes(): number;                // 半帧缓存字节数
}
```

### 6.1 noise 测试策略（模拟两端会话往返）

- 同进程构造 initiator 与 responder（静态密钥对用 `ArrayRng` 固定字节生成，`x25519GenerateKeyPair`），**prologue 一致** → `writeMessageA → readMessageA → writeMessageB → readMessageB → split()` 全程成功，responder 读到的 `remoteStatic` 等于 initiator 静态公钥。
- split 后两端 `NoiseTransportCipher` 多轮双向加解密往返（含空载荷、跨 2^32 计数器边界的序列）。
- 失败路径：prologue 不一致 → `DECRYPT`；对端静态私钥不匹配 → `DECRYPT`；`split()` 早调用 → `STATE`；帧 reader 分片喂入（1 字节一片）与粘包（多帧一片）重组等价。

---

## 7. control 包 `@ohos-tailscale/control`

职责：控制面客户端。ts2021 长轮询经 `HttpTransport`（common 注入接口）承载 Noise 通道；**协议消息用 TLV 编解码**（R3：核心不碰 JSON）；维护 MapRequest/MapResponse 状态机。D1 边：可 import noise/wireguard/crypto/common；一期实现实际只 import noise + common（wireguard 边预留给二期"netmap → WG peer 配置推导"，允许不使用）。

### 7.1 TLV 线格式（本包定义，两端一致即可互操作）

```
字段  = type u16be || length u16be || value(length 字节)
消息  = TLV 字段序列；首个字段必须是 MsgKind(u8)
Endpoints 字段 value = { u8 len, utf8("ip:port") } 重复条目
```

```ts
// index.ts barrel 导出以下全部
export interface ControlTlvTypeE   { MsgKind: number; NodeKey: number; DiscoKey: number; Endpoints: number; DerpRegionId: number; PacketFilter: number; SeqNo: number; ErrorText: number }
export const ControlTlvType: ControlTlvTypeE;     // { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08 }
export function parseControlTlvType(v: number): number | null;
export interface ControlMsgKindE  { MapRequest: number; MapResponse: number; KeepAlive: number; Ping: number; Pong: number }
export const ControlMsgKind: ControlMsgKindE;     // { 1, 2, 3, 4, 5 }
export function parseControlMsgKind(v: number): number | null;

export interface ControlTlvField { type: number; value: Uint8Array }
export interface ControlMessage { kind: number; fields: ControlTlvField[] }

export function controlTlvEncode(fields: ControlTlvField[]): Uint8Array;
export function controlTlvDecode(bytes: Uint8Array): ControlTlvField[];
  // 未知 type 保留不丢；截断/超长抛 ControlError('TLV')
export function controlEncodeMessage(msg: ControlMessage): Uint8Array;   // kind 落为首个 MsgKind 字段
export function controlDecodeMessage(bytes: Uint8Array): ControlMessage; // 缺 MsgKind 抛 ControlError('TLV')
export class ControlError extends Error { public code: string } // 'TLV'|'HTTP'|'NOISE'|'STATE'
```

### 7.2 客户端

```ts
export interface ControlClientConfig {
  controlUrl: string;          // 例 'https://headscale.example.internal'（【取证】§1.2：自定义 ControlURL 必须支持）
  nodeKeyPair: CryptoKeyPair;    // WireGuard 层 nodekey（来自 crypto 包类型；D1 传递依赖）
  machineKeyPair: CryptoKeyPair; // ts2021 machine key
  serverStaticPublic: Uint8Array; // 控制面服务端 Noise IK 静态公钥（32B；实现阶段裁定增补，评审升级 dwfq-fe173e19-1；
                                  // 真实 tailscale 由控制面密钥发现机制（/key 端点）获得并固定/经配置注入，当前阶段由调用方显式传入）
  transport: HttpTransport;      // common 注入接口
  clock: Clock;                  // common 注入接口
  rng: Rng;                      // common 注入接口
}
export class ControlClient {
  constructor(cfg: ControlClientConfig);
  dial(): Promise<void>;         // POST controlUrl/ts2021 经 transport 完成 Noise IK 握手；失败抛 ControlError('NOISE'|'HTTP')
  send(msg: ControlMessage): Promise<void>;
  receive(): Promise<ControlMessage>;  // 从 open() 的流式响应读一帧 → noise 解密 → TLV 解码
  close(): void;
}
```

### 7.3 control 测试策略（TLV 往返 + fake transport 全流程）

- TLV：任意字段集编解码往返；未知 type 保序保留；畸形（截断、len 溢出、缺 MsgKind）抛错；`Endpoints` 嵌套条目往返。
- 全流程：测试内造一个**脚本化 fake `HttpTransport`**（记录请求 body；用 noise `NoiseIkResponder` 扮演服务端，把握手 msgB/后续密文按脚本返回）→ `dial()` → `send(MapRequest)` → fake 端解出 TLV → 回 `MapResponse` → `receive()` 得到等价 `ControlMessage`。全程 `FixedClock`/`ArrayRng` 注入，端到端字节可复现。

---

## 8. derp 包 `@ohos-tailscale/derp`

职责：DERP 中继帧协议（编解码 + 跨 chunk 帧重组）与 region/节点数据结构 + home region 选择策略。D2：**只 import common**（帧协议在 TLS 之上，TLS 由 app/ 侧拨号）。

### 8.1 帧格式与常量

```
帧 = type u8 || length uvarint(LEB128) || payload
```

⚠ 上游核对项（§10-U2）：tailscale DERP 实际帧格式（类型码表、uvarint 长度）以实读上游 `derp/` 源码为准；本表为本地契约基准，两端自洽，核对后只改常量表不改函数签名。

```ts
// index.ts barrel 导出以下全部
export interface DerpFrameTypeE { ServerKey: number; ClientInfo: number; ServerPing: number; SendPacket: number; RecvPacket: number; Ping: number; Pong: number; KeepAlive: number; NotePreferred: number; PeerGone: number }
export const DerpFrameType: DerpFrameTypeE;   // { 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a }
export function parseDerpFrameType(v: number): number | null;
export class DerpError extends Error { public code: string } // 'FRAME'|'RANGE'

export interface DerpFrame { type: number; payload: Uint8Array }
export function derpFrameEncode(type: number, payload: Uint8Array): Uint8Array;
export function derpFrameDecode(src: Uint8Array): DerpFrame;  // 截断/未知结构抛 DerpError('FRAME')；type 不在表内仍解出（透传）
export class DerpFrameReader {
  push(chunk: Uint8Array): DerpFrame[];  // 跨 chunk 重组，返回本轮完整帧
  pendingBytes(): number;
}
```

### 8.2 数据结构与 region 选择

```ts
export interface DerpNode {
  name: string;
  hostName: string;     // DNS + TLS SNI
  certName: string;     // '' = 未配置 → TLS 校验回退 hostName（【取证】§3：CertName 优先、HostName 回退）
  ipv4: string;         // '' = 无
  ipv6: string;         // '' = 无
  stunPort: number;     // 0 = 未显式下发（按 STUN_DEFAULT_PORT）；负值 = 该节点不做 STUN
  derpPort: number;     // 0 = 未显式下发（按 DERP_DEFAULT_PORT）
  canPort80: boolean;
}
export interface DerpRegion {
  regionId: number;
  regionCode: string;   // status --json 的 Relay 字段取值（【取证】§2.2）
  regionName: string;
  nodes: DerpNode[];
  latencyMs: number;    // -1 = 未测出（【取证】§5：测不出延迟的 region 也要能兜底）
}
export class DerpRegionPicker {
  constructor(regions: DerpRegion[]);
  setLatency(regionId: number, latencyMs: number): void;
  homeRegion(): DerpRegion | null;   // 最小非负 latencyMs；全部未测出 → nodes 非空的第一 region；无 region → null
  regionById(id: number): DerpRegion | null;
  pickNode(region: DerpRegion): DerpNode;  // nodes[0]（随机挑选策略二期注入 Rng 后启用）
}
```

### 8.3 derp 测试策略（帧编解码往返）

- 单帧/多帧编解码往返；粘包（两帧一片）与分片（一帧拆 N 片喂 `DerpFrameReader`）重组等价；空 payload 帧；未知 type 透传解码；截断抛 `DerpError('FRAME')`。
- `DerpRegionPicker`：有延迟取最小；全部 -1 回退第一个非空 region；空列表返回 null；`certName=''` 的回退语义在结构上保持（注释断言）。

---

## 9. 工程落地模板（各包照抄）

### 9.1 包 `package.json`（common 已建，其余各包自建）

```json
{
  "name": "@ohos-tailscale/<pkg>",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "exports": { ".": "./src/index.ts" }
}
```

建包后在仓库根跑一次 `npm install`（workspace 自动建立 `node_modules/@ohos-tailscale/<pkg>` 链接）。导出目标直接指向 `src/index.ts`（Node type stripping 与 tsc `allowImportingTsExtensions + noEmit` 均可解析，已在 common 上实测）。

### 9.2 目录与导入

```
packages/<pkg>/
├─ package.json          # §9.1 模板
├─ src/*.ts              # 协议实现；包内相对导入必须 './x.ts'（P2）
├─ src/index.ts          # barrel：export * from './x.ts'
└─ test/*.test.ts        # 唯一允许 import node:test / node:assert(/strict) 的文件（P3）
```

### 9.3 测试运行

```bash
node --test "packages/**/*.test.ts"     # 全仓（根 package.json 的 npm test）
node --test "packages/common/**/*.test.ts"   # 单包
npm run typecheck                        # tsc --noEmit -p .（T2 门禁：erasableSyntaxOnly + verbatimModuleSyntax）
```

### 9.4 编码红线速查（全条目见【约束】§1/§2；本表为实现者最低自检单）

1. 无 `any`/`unknown`/`ESObject`；2. 无 enum/namespace/参数属性/`#`私有字段；3. 无字面量联合（R5 常量对象模式）；4. 无 tuple（R4）；5. 无解构/对象展开/`call/apply/bind`/嵌套函数声明；6. 对外函数显式返回类型；7. `throw` 仅 Error 子类；8. src 内禁 `node:*`、禁 `Date.now()/Math.random()/TextEncoder/Buffer`；9. 字节一律 `Uint8Array`，u64 一律 `BigInt`；10. 相对导入带 `.ts`、跨包用 `@ohos-tailscale/<pkg>`。

---

## 10. 冻结规则与上游核对清单

### 10.1 common 冻结流程

- `packages/common/src/index.ts` 公开 API 自本版本**冻结**：六个包并行开发期间**只 import、不修改** common。
- 需要新增共享能力（新注入接口、新常量）→ 向架构师提修订：改 common + 同步本文 §3 + 升小版本号，一次性合入；禁止各包私下 fork 副本。
- 各包自己的注入接口（如 derp 的 TLS 拨号）**定义在本包内**，不进 common（不共享就不冻结）。

### 10.2 上游核对清单（不阻塞并行开发，核对前以本文为契约）

| # | 事项 | 影响 | 现状 |
|---|---|---|---|
| U1/AU1 | ts2021/controlbase 帧格式（帧头、Noise 消息上限、nonce 编码、HTTP 升级头） | noise `controlbase.ts`、transport nonce | 【已核对 ✅ 2026-09-29】实读 tailscale main `control/controlbase/{messages,handshake,conn}.go`、`control/controlhttp/{constants,client}.go` 并**真实互通验证**（对 headscale v0.29.4 注册成功）：record 帧 1B type+2B BE 长度、上限 4096/明文 4077、nonce=4B 零‖BE64 计数器（与本包实现一致）、initiation 101B 头 2B BE 版本、**版本字段=tailcfg CapabilityVersion（当前 148，非早期协议版本 1）**、prologue="Tailscale Control Protocol v"+版本、升级头 Upgrade: tailscale-control-protocol / X-Tailscale-Handshake: base64(101B initiation)、升级后为 **HTTP/2 over Noise**（headscale `http2.Server.ServeConn`，无 HTTP/1.1 回退），握手后服务器先发 EarlyNoise（5B magic+4B BE 长度+JSON） |
| U2/AU2 | DERP 帧类型码表与长度编码 | derp `DerpFrameType` 常量表、帧层 | 【已核对 ✅ 2026-09-29】实读 `derp/derp.go`、`derp_client.go`、`derphttp_client.go`：帧头第二字段为 **u32 大端**（原 uvarint 为核对前过渡形态，已改）；码表 0x01~0x15 对照（原表 Ping/Pong/KeepAlive 等错位，已纠正）；ServerKey 载荷=Magic(8B)+公钥；ClientInfo=公钥+nonce+**naclbox(json)**（标准 NaCl box：beforenm=HSalsa20(X25519,0) + secretbox，Go 布局 tag‖密文）；derive 依据已写入 frame.ts/client.ts 头注，测试按新格式重写（44/44） |
| U3/AU3 | Headscale 对 Register/Map 的字段语义 | control `tailcfg.ts`（JSON 层） | 【已核对 ✅ 2026-09-29】实读 tailcfg.go L1318/L1372/L1436 与 headscale noise.go：注册/地图载荷为 **tailcfg JSON over HTTP/2**（POST /machine/register、/machine/map），非本包 TLV 本地契约——新增 `tailcfg.ts`（JSON 编解码，Version=148、Auth.AuthKey、NodeKey "nodekey:" 前缀）与 map 流 **4B 小端长度前缀**格式（实测锚定）；本地 TLV 层保留为学习期契约，真机联网走 tailcfg 层 |
| AU4 | ArkTS 侧 BigInt / `.ts` specifier / 动态键遍历的真机表现 | R4/P6 的窄接口封装 | 【部分闭环 2026-09-29】已用 OpenHarmony 7.0 SDK ets-loader 内置官方 ArkTSLinter（华为魔改 TS 4.9.5）实测：**lintEtsOnly 只扫 .ets**，核心库以 .ets 形态全量可扫；src 告警 76 条（69 throw 重抛/3 any/3 字面量/1 正则）清零工作见 DELIVERY_REPORT；BigInt 等运行时项仍待真机 |

### 10.3 版本记录

- v1（2026-09-28）：初版定稿。common 已实现并冻结（40/40 测试绿 + tsc 零错误 + 包名导入冒烟通过）；其余五包契约发布，等待并行实现。
- v1.1（2026-09-28）：实现阶段裁定增补（评审升级 dwfq-fe173e19-1，架构师批准）：§7.2 ControlClientConfig 增补必填字段 `serverStaticPublic`（控制面服务端 Noise IK 静态公钥，32B）——§6 NoiseIkInitiator 发起方必需 remoteStatic，原六字段下 dial() 按字面不可实现；取值来源见 §7.2 字段注释。
- v1.2（2026-09-29）：AU1–AU3 上游核对清账（依据见 §10.2 表内证据）：①noise 包新增 `controlbase.ts`（ts2021 帧封装 + controlbase 客户端握手，版本=148）；②derp 帧层长度编码 uvarint→**u32 大端**、码表对齐上游、ServerKey 载荷含 Magic、ClientInfo 改为 naclbox 标准形态、DerpClientConfig 增补 `nodePrivateKey`；③control 包新增 `tailcfg.ts`（tailcfg JSON 编解码）与 `noisehttp.ts`（HTTP-over-Noise 帮助层，本地 TLV 契约保留）。全部改动有对应测试，全仓测试与 tsc 保持绿。
