# ohos-tailscale 交付报告

- 生成日期：2026-09-28
- 交付范围：`packages/` 六个纯 TS 协议包（实现 + 测试）、`app/` HarmonyOS 工程壳（手写骨架，未编译）、`docs/` 约束/架构契约/协议取证。
- 本报告的"实测/跑绿"结论有两轮，均在 2026-09-28 本机（win32）实际执行：**初版轮** Node v22.23.2 / npm 10.9.8 / TypeScript 5.9.3（测试当时为 216/216）；**更新轮** Node v24.15.0 / npm 11.12.1 / TypeScript 5.9.3——wireguard 包测试经评审增强后（+1 用例）全量复跑，本文当前数字均出自更新轮。未执行的检查一律如实标注"未验证"。仓库当前未纳入 git 管理（`.gitignore` 为将来 git 化预留），无 CI。
- 编号约定（全文通用）：**AU\*** = `docs/architecture.md` §10.2 上游核对项（AU1–AU4）；**CU\*** = `docs/arkts-constraints.md` §6 未验证项（CU1–CU10）。两份源文档各自都有 U1 起的编号且同号异义（如 AU2=DERP 帧表、CU2=BigInt），本文加前缀区分。

---

## 0. 结论一览

| 项 | 状态 |
|---|---|
| 全仓测试 | ✅ `npm test` → 217 tests / 217 pass / 0 fail（更新轮 Node v24.15.0，连续 3 次一致；六包单独运行之和 40+24+35+45+40+33 = 217） |
| 类型检查 | ✅ `npm run typecheck`（tsc --noEmit）→ 0 错误（更新轮复跑，退出码 0） |
| 六包实现 | ✅ 40 个 src 文件 / 5503 行；28 个测试文件 / 6498 行（行数更新轮实测量） |
| 真实服务端互操作 | ❌ 未验证（无真实凭据；上游核对项 AU1–AU3 未清） |
| app/ 编译与真机 | ❌ 未验证（本机无 DevEco Studio / HarmonyOS SDK，工程从未编译） |
| netcheck / disco / LocalAPI / MagicDNS / PeerAPI | ❌ 未实现（二期范围，见 §3.2） |

## 1. 完成了什么（逐模块）

### 1.1 `packages/common` — 注入接口与基础工具（9 文件 / 747 行）

- `ByteReader`/`ByteWriter`（`packages/common/src/bytes.ts`）：u8–u64（BE/LE）、LEB128 uvarint、越界防护；`hex.ts`、`base64.ts`（RFC 4648 严格 canonical：长度 4 的倍数、`=` 只许末尾、尾部剩余位须 0）、`utf8.ts`（手写，编码拒孤立代理项、解码拒截断/overlong/代理区/>U+10FFFF，不用 `TextEncoder`）。
- 注入接口（`clock.ts` / `random.ts` / `http.ts`）：`Clock`、`Rng`、`HttpTransport`（缓冲 `send` + 流式 `open`/`HttpBodyStream`），配确定性测试实现 `FixedClock`/`ArrayRng`。P4（禁 `Date.now`/`Math.random`）由此落地。
- 公共常量（`constants.ts`）：`WG_DEFAULT_PORT=41641`、`DERP_DEFAULT_PORT=443`、`STUN_DEFAULT_PORT=3478`、CGNAT/TAILNET ULA CIDR 等（取值依据 `docs/oracle/protocol-notes.md`）。
- 公开 API 自本版本冻结（`docs/architecture.md` §10.1）；`packages/common/src/index.ts` 为 barrel。
- 收尾修复（2026-09-29，主会话）：评审遗留三项 ArkTS 合规问题全部清零——R4 tuple（`test/bytes.test.ts` uvarint 向量、`test/base64.test.ts` RFC 4648 向量 → 纯字段 interface 载体）、A14 string 下标取字符（`src/hex.ts` 2 处、`src/base64.ts` 9 处 → `charAt()`）、A2 对象字面量初始化带方法接口（`test/index.test.ts` → 顶层 `NullBodyStream implements HttpBodyStream`）；修复后全量 217/217、tsc 零错误（§2.2 收尾轮）。

### 1.2 `packages/crypto` — 密码学原语（6 文件 / 919 行）

- `x25519.ts`：RFC 7748 X25519（含 clamp）、密钥对生成、`isZeroBytes`（WG 全零 DH 检查用）。
- `aead.ts`：ChaCha20-Poly1305（RFC 8439），密文布局 = ciphertext‖tag(16B)，认证失败 `CryptoError('AUTH')`。
- `hash.ts`：SHA-256、HMAC-SHA256、无键/键控 BLAKE2s-256、HKDF²/³（BLAKE2s 与 SHA-256 双实现，`Uint8Array[]` 定长输出，规避 tuple）。
- `util.ts`：常时比较 `constTimeEqual`、密钥擦除 `wipe`。
- 实现全部手写（ArkTS 兼容要求，无依赖库），正确性靠测试与权威向量 + `node:crypto` 交叉验证锚定（见 §2.3）。

### 1.3 `packages/noise` — 控制面握手协议（6 文件 / 570 行）

- `Noise_IK_25519_ChaChaPoly_BLAKE2s`（`packages/noise/src/handshake.ts:38`）：IK 模式 `NoiseIkInitiator`/`NoiseIkResponder`，msgA 固定头 80B、msgB 固定头 32B。
- 对齐 tailscale controlbase 口味（`packages/noise/src/handshake.ts` 头注逐项列出实读依据）：预消息 `<- s` 在 prologue 后 MixHash；DH 令牌走双输出 HKDF（无 temp_h 混入）；split 键序 client tx=c1/rx=c2。
- `transport.ts`：传输 cipher，nonce = 4B 零 ‖ **BE64** 计数器（对齐 controlbase `nonce.Increment()`，与 vanilla Noise 的 LE64 自 counter≥1 起刻意不同——counter=0 时两种编码同为全零 nonce；cacophony 向量在 counter=1 处断言不相等并注释，`packages/noise/test/external-vector.test.ts`）。
- `frame.ts`：2B BE 长度前缀帧 + `NoiseFrameReader` 跨 chunk 重组（半帧缓存）。

### 1.4 `packages/wireguard` — 数据面协议核心（8 文件 / 1458 行）

- `handshake.ts`：握手 initiator/responder 全流程（白皮书 5.4.2–5.4.6；键调度逐行对照 wireguard-go `noise-protocol.go`，头注列明）。148B/92B 报文向量为确定性字节级锚——上游 wireguard-go/boringtun/linux 均无公开的、可注入临时密钥的完整握手 KAT（头注记录 2026-09-28 web 检索再确认）；评审 finding"向量不得自产自锁"后增强为**三重锁定**：写死 hex 锚 == 测试内零共享参考推导（X25519/ChaCha20-Poly1305/HMAC 全经 `node:crypto`，键控 BLAKE2s 手写 RFC 7693 实现、KAT 锚定官方 blake2-kat 首向量）== 模块输出（`packages/wireguard/test/handshake.test.ts` 头注），另记录跨语言第三实现（CPython 3.12 hashlib/hmac + pyca-cryptography 47.0.0）对同组 fixture 逐字节复现两向量（该步骤记录于头注，更新轮未复跑）。
- `tai64n.ts`：TAI64N 时间戳编解码（挂钟毫秒派生）。
- `transport.ts`：`WgSendSession`/`WgRecvSession`，传输报文 16B 头 + AEAD；**2048 位滑动窗口反重放**；keepalive（空载荷）往返。传输 nonce 端序有 `node:crypto`（OpenSSL）独立锚定：`encryptPacket` 输出与 OpenSSL chacha20-poly1305 按 wireguard-go nonce 规则（4B 零 ‖ LE64(counter)）封装逐字节一致，counter=1/2 处区分端序（`packages/wireguard/test/transport.test.ts:139`，评审 finding 1 类 nonce 端序偏差的回归锚）。
- `cookie.ts`：MAC1/MAC2 计算与 `WgCookieCache`（白皮书 5.4.4/5.4.7 + wireguard-go `cookie.go` 双重核对）。**一期边界：不生成/不解析 Cookie Reply**（type=3 一律 `WgProtocolError('BAD_TYPE')`），响应端 cookie 派发留二期。
- `peers.ts`：`WgPeerTable` 会话索引表（localIndex/peerIndex 双向分发，新会话顶替旧会话，`removePeer` 级联移除）。

### 1.5 `packages/derp` — 中继协议（5 文件 / 743 行）

- `frame.ts`：帧 = type u8 ‖ uvarint(LEB128) 长度 ‖ payload；10 个帧类型码表；未知 type 解码层透传、编码/分发层拒绝；单帧上限 1 MiB（`DERP_MAX_FRAME_BYTES`，本地 DoS 基线）。**该常量表为本地契约基准，tailscale 上游实读核对项 AU2 未清**（`packages/derp/src/frame.ts` 头注）。
- `region.ts`：`DerpNode`/`DerpRegion`（certName 空串 = TLS 校验回退 hostName；stunPort/derpPort 0 = 按 3478/443 兜底；latencyMs −1 = 未测出）+ `DerpRegionPicker`（最小非负延迟；全未测出回退首个非空 region）。字段语义对齐取证（`docs/oracle/protocol-notes.md` §3/§5）。
- `client.ts`：`DerpClient` 状态机 Idle→Connecting→Ready→Closed；connect 读 ServerKey/发 ClientInfo；按 peer 公钥订阅集合；`sendPacket`/`receive`（上抛 RecvPacket/Pong/PeerGone，KeepAlive 静默消费，ServerPing 自动回 Pong）；网络 IO 全部经 `DerpDialer` 注入（D4）。

### 1.6 `packages/control` — 控制面客户端（6 文件 / 1066 行）

- `tlv.ts`：TLV 编解码（字段 = type u16be ‖ len u16be ‖ value；8 个类型码；未知 type 保序保留；截断/超长抛 `ControlError('TLV')`）。**TLV 为本包本地契约，非 tailcfg 原文**（R3：核心不碰 JSON）。
- `messages.ts`：类型化消息层——`RegisterRequest`/`RegisterResponse`/精简版 `NetworkMap`（语义仿 tailcfg，字段值编码约定见 `packages/control/src/messages.ts` 头注；重复同义字段一律抛错，确定性优先）。
- `client.ts`：`ControlClient`（`packages/control/src/client.ts:110`）——`dial()`（POST `<controlUrl>/ts2021`，Noise IK 握手）→ `send()`（TLV→尺寸预检 65519B→noise 加密→帧→POST）→ `receive()`（GET 流式长轮询，跨 chunk 重组 + backlog 逐条）→ `close()`/重新 `dial()` 会话恢复（半帧缓存随流复位、Noise 计数器跨流连续；AEAD 失步唯一恢复路径为重建会话）。错误映射 `'HTTP'|'NOISE'|'TLV'|'STATE'`；错误路径一律先 `body.close()` 不泄漏长轮询连接。会话地址拼接、prologue 常量 `CONTROL_NOISE_PROLOGUE`（`packages/control/src/client.ts:73`）均为本地契约，列入上游核对项 AU1。
- 契约增补：`ControlClientConfig.serverStaticPublic`（控制面服务端 Noise IK 静态公钥，必填）——评审裁定记录于 `docs/architecture.md` §10.3 v1.1。

### 1.7 `app/` — HarmonyOS 工程壳（**未编译**）

- 完整 stage 工程骨架：`AppScope`（app.json5/图标）、工程级与模块级 `build-profile.json5`/`hvigorfile.ts`/`oh-package.json5`、`entry/src/main/module.json5`（声明 `ohos.permission.INTERNET`、`ohos.permission.GET_NETWORK_INFO`，均 normal/system_grant；`VpnExtensionAbility` 以 `"type": "vpn"` 声明）。
- 三个 `.ets`：`EntryAbility`（加载 Index）、`pages/Index.ets`（登录页骨架：auth key 输入/状态展示/连接开关，按 ArkTS 禁则写法）、`VpnExtensionAbility.ets`（VPN 扩展**桩**：createVpnConnection → VpnConfig 占位（addresses 为空，真实调用会失败）→ tun fd → 核心库对接全部为 TODO 注释）。
- `app/README-app.md`：DevEco 导入构建步骤、权限说明、核心库集成三方案（ohpm 本地目录/源码并入/HAR）、tun fd 官方流程、11 项未验证事项。
- **事实**：本机无 DevEco Studio 与 HarmonyOS SDK，`npx tsc` 也不覆盖 `app/`（根 tsconfig `exclude: ["app"]`），该目录所有文件未经任何编译器检验。

### 1.8 `docs/` — 约束、契约与协议取证

- `arkts-constraints.md`：ArkTS 官方禁则 A1–A36（逐条规则名 + 正反例）、工程约束 P1–P7、tsconfig/package.json 基线、未验证项 CU1–CU10。规则文本取自 openharmony/docs 镜像 master 的官方迁移指南（2026-09-28 抓取 99,951 字节；抓取来源与过程记录见 `docs/arkts-constraints.md` 附录 A）。
- `architecture.md` v1.1：六包实现契约——依赖方向 D1–D4、裁定 R1–R8、common 冻结流程、上游核对清单 AU1–AU4、版本记录。
- `oracle/protocol-notes.md` + `raw/` 17 份转储：对真实 tailscale 1.102.3（fork 自建版）的**只读**取证——status/netmap/derp-map/netcheck/prefs 等结构逐字段记录；全流程未执行任何改状态命令（清单与排除项见该文档 §1.3）；密钥/凭据全部打码（公钥只留前 8 hex、私钥由 tailscaled 自身置零），域名与拓扑信息明文（取舍见 §3.4）。

## 2. 测试证据（本机实跑）

### 2.1 环境

```
node --version  → v24.15.0        （更新轮；初版轮为 v22.23.2）
npm --version   → 11.12.1         （更新轮；初版轮为 10.9.8）
npx tsc --version → Version 5.9.3
```

### 2.2 命令与输出（更新轮实跑，2026-09-28）

| 命令 | 实测输出 |
|---|---|
| `npm test`（= `node --test packages/**/*.test.ts`，`package.json:11`） | `ℹ tests 217 / ℹ pass 217 / ℹ fail 0`（连续 3 次一致） |
| `npm run typecheck`（= `tsc --noEmit -p .`，`package.json:12`） | 无输出，退出码 0（零错误） |
| `node --test "packages/common/**/*.test.ts"` | `ℹ tests 40 / ℹ pass 40 / ℹ fail 0` |
| `node --test "packages/crypto/**/*.test.ts"` | `ℹ tests 24 / ℹ pass 24 / ℹ fail 0` |
| `node --test "packages/noise/**/*.test.ts"` | `ℹ tests 35 / ℹ pass 35 / ℹ fail 0` |
| `node --test "packages/wireguard/**/*.test.ts"` | `ℹ tests 45 / ℹ pass 45 / ℹ fail 0` |
| `node --test "packages/derp/**/*.test.ts"` | `ℹ tests 40 / ℹ pass 40 / ℹ fail 0` |
| `node --test "packages/control/**/*.test.ts"` | `ℹ tests 33 / ℹ pass 33 / ℹ fail 0` |

注（输出字面格式随 Node 版本/reporter 而异）：更新轮 Node v24.15.0 的 `node --test` 默认 spec reporter 打印 `ℹ tests …`；初版轮 Node v22.23.2 为 TAP 格式，打印 `# tests …`（§2.4 引用的是初版轮当时的字面量）。数字与格式对照请以所装 Node 版本实跑为准。

每包之和 40+24+35+45+40+33 = 217，与全仓运行一致。规模（更新轮实测）：28 个测试文件 / 6498 行测试代码对 40 个源文件 / 5503 行（六个包 src 文件/行数分别为 common 9/747、crypto 6/919、noise 6/570、wireguard 8/1458、derp 5/743、control 6/1066）。较初版轮净增 1 个 wireguard 用例、约 365 行测试代码（评审增强，见 §1.4）。

收尾轮（2026-09-29，主会话在 control/wireguard 评审修复与 §1.1 common 收尾修复之后复跑，Node v22.23.2 / TAP 格式）：全仓 `# tests 217 / # pass 217 / # fail 0`、`tsc --noEmit -p .` 零错误、全仓 tuple 与 string 下标模式残留扫描为零，与更新轮数字一致。

### 2.3 测试策略与证据等级（如实区分）

- **crypto**：RFC 权威向量（RFC 7748 §5.2/§6.1、RFC 8439 §2.8.2/§2.5.2、HMAC 用 RFC 4231 TC1/TC2）+ 与 `node:crypto` 实时交叉验证（`diffieHellman`/`createCipheriv('chacha20-poly1305')`/`createHash`/`createHmac`；`node:crypto` 仅出现在 `*.test.ts`，P3 例外）。键控 BLAKE2s 无 node 对应，KAT 写死 hex 断言——向量取自独立参考实现 CPython `hashlib.blake2s(key=…)` 的运行时输出，其中 key=00..1f 空输入即官方 blake2-kat 首向量（注意：KAT 出处是参考实现与 blake2-kat，RFC 7693 原文并无 KAT 附录；实现本身按 RFC 7693，出处见 `packages/crypto/test/hash.test.ts` 头注）。
- **noise**：cacophony 社区 Noise 已知答案向量逐字节锚定握手 msgA/msgB、握手哈希与 counter=0 传输消息（`packages/noise/test/external-vector.test.ts`）；另有两端同进程往返、跨 2^32 计数器、分片/粘包重组等价、失败路径（prologue 不一致/密钥不匹配→DECRYPT 等）。
- **wireguard**：两端完整握手往返 + 148B/92B 完整报文 hex 向量锁定（确定性 `ArrayRng`+`FixedClock`），向量经**三重锁定**——写死锚 == 测试内零共享参考推导（`node:crypto`/OpenSSL 全原语 + 手写 RFC 7693 键控 BLAKE2s，后者 KAT 锚定官方 blake2-kat 首向量与 CPython hashlib.blake2s 参考值）== 模块输出，任一漂移即失败；另每轮断言键调度独立第二实现逐字段对照（防双方同错自洽漏检）。头注记录跨语言第三实现（CPython 3.12 hashlib/hmac + pyca-cryptography 47.0.0，OpenSSL 底座）于 2026-09-28 对同组 fixture 逐字节复现两向量——**该跨语言步骤记录于测试头注，本更新轮未复跑**。传输层：`encryptPacket` 与 OpenSSL chacha20-poly1305 逐字节对照（LE64 nonce，counter≥1 区分端序，`packages/wireguard/test/transport.test.ts:139`）+ 反重放窗口边界（2^31、2^53+1、2048 位窗外）+ 篡改 1 bit。**边界如实说明**：公开渠道不存在可注入临时密钥的完整握手官方向量（wireguard-go/boringtun/linux selftest，头注记录 2026-09-28 web 检索再确认），写死锚仍为本仓自产、经上述独立推导链锁定；未与真实 WireGuard 对端做过互操作测试。
- **control**：脚本化 fake `HttpTransport` + `NoiseIkResponder` 扮演服务端的全流程测试（`packages/control/test/client.test.ts`）：dial→RegisterRequest→服务端解密→回 NetworkMap→receive 等价还原；跨 chunk 分片、多帧 backlog、流中断恢复（半帧缓存复位/计数器连续/close+dial 重建）、生命周期 STATE 错误、错误路径 `body.close()` 断言、发送尺寸预检边界 65519B、同一脚本两次运行字节级确定性。
- **derp**：脚本化 fake `DerpDialer`/`DerpConnection` 状态机全流程（`packages/derp/test/client.test.ts`）+ 帧编解码往返/粘包分片/未知 type 透传/截断抛错（`frame.test.ts`）+ region 选择兜底（`region.test.ts`）。

### 2.4 运行波动记录

- 初版轮（Node v22.23.2）：全仓 `npm test` 首次运行输出 `# tests 213 / # pass 213`（漏收 3 个用例），随后连续 4 次稳定输出 216/216/0，且六包单独运行之和恰为 216。判定为 Windows 下 `node --test` glob 文件发现的偶发漏收（不可复现），非测试不稳定。
- 更新轮（Node v24.15.0）：全仓 `npm test` 连续 3 次输出 217/217/0，首次运行即为 217，未复现漏收；六包单独运行之和亦为 217。
- 结论不变：核对测试数字时以每包单独运行数字之和为准。

## 3. 已知限制与未覆盖项

### 3.1 互操作（最重要的限制）

- **与真实 tailscale/Headscale 未做任何互操作测试**（本机无可用凭据与联调环境）。当前互操作结论仅覆盖"本仓实现两端自洽"。
- 上游核对清单 AU1–AU4 未清（`docs/architecture.md` §10.2，共 4 项）。与真实服务端互操作直接相关的是前三项：
  - AU1：ts2021/controlbase 帧格式（2B BE 前缀、消息上限、nonce 编码）与 control prologue——本地契约，实现层已按 controlbase 语义对齐 Noise 部分并经 cacophony 向量锚定，但帧层常量未对上游源码实读核对；
  - AU2：DERP 帧类型码表与 uvarint 长度——同上，本地契约基准；
  - AU3：Headscale 对 MapRequest/MapResponse 的字段语义——TLV 字段表结构已定，语义增补待核对。核对后"只改常量表不改签名"是设计前提，但改动量未实测。连带确认项：当前 TLV 类型码固定 8 个（`packages/control/src/types.ts:10`，{0x01..0x08}；解码层对未知 type 保序保留），换成 tailcfg 语义后现有类型码是否够用未评估，应随 AU3 核对一并确认。
  - AU4：ArkTS 侧 BigInt / `.ts` specifier / 动态键遍历的真机表现——属平台/运行时验证而非协议互操作，且与 CU2/CU5/CU6 重叠（`docs/architecture.md` §10.2 AU4 行自己标注了这一重叠），故不列入互操作前置条件，随「真机集成」路线推进（§4 第 2–4 步）。

### 3.2 协议面未实现（对照取证清单 `docs/oracle/protocol-notes.md` §8 的 12 项部件）

已落地：#2 控制面客户端骨架（消息语义为本地 TLV，非 tailcfg JSON）、#3 netmap 状态机的载体结构（精简版）、#4 DERP 客户端 + region 选择、#7 WireGuard 数据面（握手/传输/反重放，缺 Cookie Reply 与重钥调度器）、#8 PacketFilter 的字节透传（未做结构化解析与入站过滤执行）。
未实现：#1 LocalAPI/IPC 层、#5 netcheck 引擎、#6 disco 发现协议、#9 PeerAPI、#10 MagicDNS、#11 能力/knob 体系、#12 完整状态机与展示层；netmap→WG peer 配置推导（control 包的 wireguard 依赖边预留未用）。

### 3.3 工程面未验证

- `app/` 从未编译（无 DevEco/SDK）；`"type": "vpn"` 识别问题、`@kit.NetworkKit` 导入路径、签名配置、真机启停与授权弹窗流程均未验证（`app/README-app.md` §6 列了 11 项）。
- 核心库进鸿蒙工程的三种集成方式（ohpm file 依赖/源码并入/HAR）**全部未实测**；成败点 CU6（ets loader 是否接受 `.ts` specifier）未验证。
- ArkTS 运行时差异未验证：BigInt 支持（CU2）、平台 `Rng`/`Clock` API 签名（CU7）、hypium 测试链路对 `node:test` 用例的复用（CU8）。
- 无 CI、无 lint 门禁（`docs/arkts-constraints.md` §3.3 的 typescript-eslint 配置仅为建议稿，未落地）；P3/P4（禁 node:*/禁非确定来源）目前靠 `tsc` 部分拦截 + 评审，未机器化全量把关。

### 3.4 其他

- 一期不做 Cookie Reply 的生成/消费（wireguard 包，接口已预留）；`WgPeerTable` 无重钥定时器/过期剔除调度。
- noise 传输 nonce 用 BE64（对齐 controlbase），与 vanilla Noise/cacophony 的 LE64 在 counter≥1 时刻意不同——连 vanilla Noise 服务端互通时需知悉（测试内已断言该差异）。
- 测试仅在 Node 22 直跑链路验证；未在 browsers/ArkTS runtime 验证。
- **敏感信息取舍**：oracle 取证的密钥/凭据已打码（`nodekey:/mkey:/discokey:` 只留前 8 hex，prefs 私钥由 tailscaled 自身置零，`docs/oracle/raw/README.txt`），但**控制面域名与拓扑为明文**——真实私有 tailnet 的 Headscale 域名 `headscale.example.internal` 与 tailnet 名 `edgenet` 明文出现在 `docs/oracle/protocol-notes.md`、`docs/architecture.md`（§7.2 `controlUrl` 字段示例注释，`docs/architecture.md:396`）、`docs/oracle/raw/`（如 `derp-map.json` 本身未打码）、`packages/control/src/client.ts:82` 代码注释与 `README.md` 首段。仓库若公开，需先决定是否脱敏这些明文（未打码的 `derp-map.json` 只含公网中继信息、无密钥字段——`docs/oracle/protocol-notes.md` §3 原文注明"未打码——公网中继信息，无敏感字段"）。
- 性能基线：BigInt X25519 `scalarMult` 本机（win32，Node v22.23.2）实测 **5.25 ms/op ≈ 190 ops/s**（200 次取均值，预热 20 次）——仅为桌面 Node 基线，供真机对照参考；真机吞吐仍未评估。
- 仓库根曾有 34 字节 `nul` 文件（Windows 命令重定向误产物，内容为"信息: 用提供的模式无法找到文件。"），已于 2026-09-29 核实内容后删除。

## 4. 下一步建议

按依赖顺序：

1. **上游核对 AU1–AU3**：实读 tailscale 上游 `control/controlbase`（帧格式与 prologue）、`derp/`（帧类型码表）、`tailcfg.go`（注册/映射字段），对齐三张常量表——这是连真实 tailnet 的前置条件，且按设计只改常量不改签名。清单第 4 项 AU4 为平台验证项（与 CU2/CU5/CU6 重叠，见 §3.1），不阻塞协议互操作，随第 2–4 步推进。
2. **DevEco 首次编译 `app/`**：装 DevEco Studio 5.0+，导入 `app/`，自动签名，`Build Hap(s)`，把首次编译报错清零（工程从未编译，预期有报错）；顺带验证 `"type": "vpn"` 识别问题的处理方案（`app/README-app.md` §2 第 5 步）。
3. **核心库集成选型**：先试 CU6（ets loader 对 `.ts` specifier 的接受度），据结果在"ohpm file 依赖 / 源码并入 / HAR"三方案中定一条。
4. **平台注入层**：实现 `HttpTransport`/`Rng`/`Clock`/UDP socket/DERP TLS 拨号五个注入点（`app/entry/src/main/ets/platform/`），真机核对 `cryptoFramework`/`@ohos.net.socket` 实际签名（CU7）。
5. **真机数据面打通**：按 `VpnExtensionAbility.ets` 桩内 TODO 接线 tun fd 读写（评估 worker 线程模型），先做"WG 会话 + tun 环回"最小闭环。
6. **真实 tailnet 联调**：向 tailnet 管理员索取 **auth key**（Headscale 用 `headscale preauthkeys create` 签发的 pre-auth key）与**控制面服务端 Noise IK 静态公钥**（`serverStaticPublic`，或先实现 `/key` 端点发现），配置自定义 ControlURL 后按 §3.1 清单逐项联调；auth key 在端侧经 Asset Store Kit/私有 preferences 中转，不走 `want.parameters`。
7. **工程化收尾**：配 CI 跑 `npm test` + `npm run typecheck`；落地 §3.3 所述 lint 门禁机器化 P3/P4（`nul` 杂物已删除，git 化时无需再处理）。

## 5. 追加轮成果（2026-09-29，主会话：上游核对、真实互通、官方 ArkTS 检查）

### 5.1 AU1–AU3 上游核对全部清账（架构 §10.2 表已更新，v1.2 修订记录）

实读 tailscale main（control/controlbase、control/controlhttp、derp、tailcfg、types/key）与 headscale v0.29.4 源码（hscontrol/noise.go、capver、poll），关键更正：

- **控制面协议版本字段 = tailcfg CurrentCapabilityVersion（148）**，不是早期 noise 协议版本 1——headscale 的 earlyNoise 直接拿它当最低版本门禁（min=113），发 1 被拒。prologue 相应为 `"Tailscale Control Protocol v148"`。
- **Noise 之上是 HTTP/2**：headscale 用 `http2.Server.ServeConn(noiseConn)`，无 HTTP/1.1 回退；握手完成后服务器先发 EarlyNoise（5B magic + 4B BE 长度 + JSON）。
- **DERP 帧头长度是 u32 大端**（原 uvarint 为核对前过渡形态）；码表 0x01~0x15 与原表存在错位（原 Ping=0x06 实为 KeepAlive 等），已全部对齐；ServerKey 载荷 = Magic("DERP🔑",8B)+公钥；ClientInfo = 公钥+nonce+**标准 NaCl box**(json)。
- **NaCl box 的标准构造含 beforenm**：sharedKey = HSalsa20(X25519(...), 全零)，secretbox 内部再对 nonce 做一次 HSalsa20；Go 布局 = nonce ‖ tag ‖ 密文，MAC 输入是密文。本仓此前缺 beforenm，已修（与 tweetnacl 逐字节互验通过，新增 `crypto/src/naclbox.ts` + 5 个交叉验证用例）。
- **map 流消息 = 4B 小端长度前缀 + JSON**（非换行分隔），实测锚定。

### 5.2 真实控制面互操作打通（本机 WSL headscale v0.29.4，双侧验证）

新增 `packages/noise/src/controlbase.ts`（ts2021 帧封装/握手/会话）、`packages/control/src/tailcfg.ts`（tailcfg JSON 编解码）、`packages/control/src/noisehttp.ts`（HTTP-over-Noise 帮助层）与 `interop/` 联调脚本（register.node.ts、h2c.node.ts——极简 h2c 客户端、headscale.yaml、start-headscale.sh）。

实测流程（`interop/register.node.ts`，全链路纯自研协议栈）：

1. `/key?v=148` 密钥发现 → 2. `POST /ts2021` 升级（initiation 内嵌 `X-Tailscale-Handshake` 头）→ 101 → 3. Noise IK 握手完成 → 4. HTTP/2 over Noise `POST /machine/register` → **`MachineAuthorized=true`** → 5. `POST /machine/map` → **MapResponse 解析成功（peers 数正确）**。

服务端双侧验证：`headscale nodes list` 列出注册节点（`ohos-interop-node*`，分配 100.100.0.1~4 tailnet IP）。对应新测试：noise controlbase 4 用例、control interop 8 用例。

### 5.3 DERP 真实协议对齐（帧层 + naclbox）与真实 DERP 互通

`packages/derp/src/frame.ts` 改为 u32BE 长度 + 上游 0x01~0x15 码表 + Magic；`client.ts` 握手改为 ServerKey(Magic+key) → ClientInfo(naclbox) → ServerInfo(跳过) 真实流，`DerpClientConfig` 增补 `nodePrivateKey`；测试按新协议重写（44/44，其中 ClientInfo 由测试侧用 tweetnacl 独立解封验证）。

**✅ 真实 DERP 互通（2026-09-29，headscale 内嵌 DERP）**：`interop/derp.node.ts` 实测全链路——A、B 两节点先用自研控制面栈注册（双 `MachineAuthorized=true`），同一对 node key 经 `GET /derp` 升级连入真实 DERP（ServerKey/ClientInfo/ServerInfo 握手），**A → B 跨客户端包交换成功**（B 的 receive() 收到 `RecvPacket("hello-from-ohos-derp-interop")`，srcKey 校验一致），KeepAlive/NotePreferred 正常发送。实测新发现：**ClientInfo 的 MeshKey 字段必须整字段省略**（headscale 的 DERPMesh 类型拒收空串："incorrect size mesh key len: 0, must be 32"，已按此修正 `client.ts` 并同步测试死值）。

### 5.4 官方 ArkTS linter 实测（OpenHarmony 7.0 SDK ets-loader）与 src 清零

从华为公开镜像下载 ohos-sdk 7.0-Release，解包 ets 组件，用其内置 ArkTSLinter（华为魔改 TypeScript 4.9.5）实测：

- **lintEtsOnly 只扫 .ets**——核心库以 .ets 形态全量可扫（镜像脚本 `interop/arkts-mirror.sh` + 驱动 `interop/arkts-check.js`，负对照文件验证 linter 确实在工作）；
- 首扫 **src 告警 154 条**（142 arkts-limited-throw / 6 any-unknown / 5 未类型化字面量 / 1 正则；注：早期报告的"76 条"是原始文件每文件截断 6 条造成的低估），原始报告见 `docs/arkts-linter-report-raw.txt`；
- **src 已全部清零**：根因是裸扫描下跨包自定义 Error 类型不可解析，`handleThrowStatement` 把所有 `throw new XxxError(...)` 判为任意类型——修法为 141 处追加 `as Error`（运行时零变化， ArkTS 下是合法的 Error 上溯）+ 1 处 catch 重抛、6 处 any 显式化、5 处字面量类型化、1 处正则改 new RegExp；
- 终态（主会话独立复扫复核）：**src=0 / test=321（按约定保留）/ 负对照=2（预期校准信号）**；这把 CU 系列中"arkts-* 规则靠文档转述"的部分升级为**官方编译器实测**，`app/` 真机集成前的静态合规已可机器把关。

### 5.5 追加轮收尾修复与最终门禁（2026-09-29 主会话终验）

- **controlbase 接收缓冲改为动态拼接**（互操作实测抓出的真实缺陷：固定 4096B 缓冲在 MapResponse 增大、TCP 多帧合并到达时必溢出；真机上同样会触发）。修复后 20-peer 大 MapResponse 解析通过。
- 最终门禁（全部主会话实跑）：全量测试 **238/238 通过**、`tsc --noEmit -p .` 零错误、官方 ArkTS linter **src=0**、真实 headscale 注册互通复跑 **INTEROP PASS**、真实 DERP 双客户端包交换复跑 **DERP INTEROP PASS**。
- 未变事项：HAP 未编译（无 DevEco Studio）、真机运行时验证（CU2 BigInt 等）仍待真机——**这些是拿到真机后第一优先级**。
