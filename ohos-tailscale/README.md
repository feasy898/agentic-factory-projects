# ohos-tailscale（鸿蒙社区版 Tailscale 客户端）

纯 TypeScript（ArkTS 语法兼容）实现的 Tailscale 兼容 mesh VPN 协议核心库，目标平台 OpenHarmony / HarmonyOS。兼容**自定义 ControlURL + Headscale 风格控制面**（依据对本机 tailscale 1.102.3——**fork 自建版**，long version `1.102.3-t9329c3677-ga522f65e9`、`-dirty`，见 `docs/oracle/protocol-notes.md` §1.1——的只读协议取证，同文档 §1.2：该 tailnet 的 ControlURL 为 `https://headscale.example.internal`，DERP map 中混有官方 region 1–28 与 Headscale embedded DERP region 999）。

当前状态（2026-09-28）：

- `packages/` 下六个协议包已实现并有测试覆盖：**217/217 测试通过，`tsc --noEmit` 零错误**（2026-09-28 复测轮实跑，Node v24.15.0；初版轮 Node v22.23.2 时为 216/216，其后 wireguard 包测试增强 +1，见 `DELIVERY_REPORT.md` §2/§2.4）。
- `app/` 为 HarmonyOS 工程壳（UI + VPN 扩展 + 权限声明）。**本机无 DevEco Studio 与 HarmonyOS SDK，该工程从未编译**；`.ets` 均为按官方文档手写的骨架/桩，见 `app/README-app.md`。
- 与真实 tailscale/Headscale 服务端的互操作**尚未验证**：帧格式与消息字段以本地契约为基准，上游核对项未清（编号约定，全文通用：**AU\*** = `docs/architecture.md` §10.2 上游核对项，共 4 项；**CU\*** = `docs/arkts-constraints.md` §6 未验证项，共 10 项——两份源文档各自都有 U1 起的编号且同号异义，故本文加前缀区分。与互操作直接相关的是 AU1–AU3；AU4 属平台验证、与 CU2/CU5/CU6 重叠，见「与真实 tailnet 联调」）。

## 仓库结构

```
ohos-tailscale/
├─ package.json               # npm workspace 根（"type": "module"；npm test / npm run typecheck）
├─ tsconfig.json              # 严格基线：strict + erasableSyntaxOnly + verbatimModuleSyntax
├─ packages/                  # 六个纯 TS 协议包（npm workspace，@ohos-tailscale/*）
│  ├─ common/                 # 注入接口（Clock/Rng/HttpTransport）+ 字节/编码工具 + 公共常量（API 冻结）
│  ├─ crypto/                 # X25519 / ChaCha20-Poly1305 / BLAKE2s / SHA-256 / HKDF（纯计算，无 IO）
│  ├─ noise/                  # 控制面 Noise IK 握手 + 传输加密 + 通道帧
│  ├─ wireguard/              # WireGuard 数据面握手 + 传输加解密 + 反重放 + cookie 骨架
│  ├─ derp/                   # DERP 中继帧协议 + region 选择 + 客户端状态机
│  └─ control/                # 控制面客户端：TLV 消息 + Noise over HTTP 长轮询
├─ app/                       # HarmonyOS 工程壳（.ets，被根 tsconfig 排除；未编译）
│  └─ README-app.md           # 壳工程说明：导入构建、权限、核心库集成、tun fd 对接
└─ docs/
   ├─ arkts-constraints.md    # ArkTS 禁则（A1–A36）+ 本仓工程约束（P/T）+ 未验证项（CU1–CU10）
   ├─ architecture.md         # 六包实现契约：依赖方向 D1–D4、裁定 R1–R8、冻结规则、上游核对清单
   └─ oracle/                 # 真实 tailscale 1.102.3（fork 自建版）只读取证：protocol-notes.md + raw/ 转储 17 份
```

## 架构

依赖方向无环（`docs/architecture.md` §1，D1/D2 强制）：

```
control ──► { wireguard, noise, crypto, common }
wireguard ──► { crypto, common }          noise ──► { crypto, common }
crypto ──► { common }                      derp ──► { common }
```

核心设计约束（全部已落实到代码）：

- **D4 核心库零网络**：`packages/` 不碰 socket/TLS/UDP。网络端点、时钟、随机数一律构造注入——`HttpTransport` / `Clock` / `Rng` 三个接口定义在 `packages/common/src/`（`http.ts` / `clock.ts` / `random.ts`），测试用 `FixedClock` / `ArrayRng` 确定性实现，真机实现放在 `app/` 侧 adapter（待做）。
- **P4 无非确定来源**：核心 src 禁 `Date.now()` / `Math.random()` / `node:*`；`node:test` / `node:assert` 仅允许出现在 `*.test.ts`。
- **R3 协议消息不碰 JSON**：控制面消息用本包定义的 TLV 线格式（两端一致即可互操作）；JSON 只允许出现在 `app/` 侧展示层。

各包职责速览：

| 包 | 公开入口 | 要点 |
|---|---|---|
| `@ohos-tailscale/common` | `packages/common/src/index.ts` | `ByteReader`/`ByteWriter`、hex、RFC 4648 严格 canonical base64、手写 UTF-8（双向严格校验）、`Clock`/`Rng`/`HttpTransport` 注入接口、协议常量（`WG_DEFAULT_PORT` 41641——tailscale 实测节点默认端口、非 WireGuard 文档常写的 51820，依据 `docs/oracle/protocol-notes.md` §7 与 `packages/common/src/constants.ts` 注释；CGNAT `100.64.0.0/10` 等）。公开 API 已冻结 |
| `@ohos-tailscale/crypto` | `packages/crypto/src/index.ts` | X25519（RFC 7748 clamp）、ChaCha20-Poly1305（RFC 8439，密文‖tag 布局）、SHA-256/HMAC、BLAKE2s-256（含键控）、HKDF²/³（BLAKE2s 与 SHA-256 双实现）、常时比较与 `wipe` |
| `@ohos-tailscale/noise` | `packages/noise/src/index.ts` | `Noise_IK_25519_ChaChaPoly_BLAKE2s`（`packages/noise/src/handshake.ts:38`）IK 握手 + 传输 cipher + 2B BE 长度前缀帧（跨 chunk 重组）。对齐 tailscale controlbase 口味：预消息 `<- s` MixHash、DH 令牌双输出 HKDF、传输 nonce BE64；cacophony 外部向量锚定（握手与 counter=0 传输消息逐字节一致；传输 nonce 自 counter≥1 起与 vanilla LE64 刻意不同、对齐 controlbase BE64，测试锚定 counter=1，见 `packages/noise/test/external-vector.test.ts` 头注） |
| `@ohos-tailscale/wireguard` | `packages/wireguard/src/index.ts` | 握手 initiator/responder（白皮书 5.4.2–5.4.6，键调度对照 wireguard-go，见 `packages/wireguard/src/handshake.ts` 头注）、TAI64N、收发会话（2048 位滑动窗口反重放）、MAC1/MAC2 与 cookie 骨架（一期不生成/不解析 Cookie Reply，type=3 → `WgProtocolError('BAD_TYPE')`）、`WgPeerTable` 会话索引表 |
| `@ohos-tailscale/derp` | `packages/derp/src/index.ts` | 帧编解码（type u8 + uvarint 长度，**本地契约基准**，上游核对项 AU2）、`DerpFrameReader` 跨 chunk 重组、region/节点结构（CertName 优先/HostName 回退、端口缺省兜底、latency −1 兜底）、`DerpRegionPicker`、`DerpClient` 状态机（Idle→Connecting→Ready→Closed；按 peer key 订阅；ServerPing 自动回 Pong） |
| `@ohos-tailscale/control` | `packages/control/src/index.ts` | TLV 编解码（8 类型码，未知 type 保留）、类型化消息 `RegisterRequest`/`RegisterResponse`/精简版 `NetworkMap`（含 `PacketFilter` 规则字节透传——结构化解析与入站过滤执行未做，属二期）、`ControlClient`（`packages/control/src/client.ts`）：`dial()` POST `<controlUrl>/ts2021` 完成 Noise IK → `send()`/`receive()`（GET 流式长轮询 + backlog）→ `close()`/重新 `dial()` 会话恢复；错误码 `'HTTP'|'NOISE'|'TLV'|'STATE'`；单帧容量 65519B 尺寸预检 |

## 如何跑测试

环境要求：Node ≥ 22（直接以 type stripping 方式运行 `.ts`，无需转译器）、npm。本文实测数据采自 Node v24.15.0 / npm 11.12.1 / TypeScript 5.9.3 / win32（2026-09-28 复测轮；初版轮环境为 Node v22.23.2 / npm 10.9.8。完整命令与输出见 `DELIVERY_REPORT.md` §2）。

```bash
npm install                 # 首次：建立 workspace 链接 node_modules/@ohos-tailscale/*

npm test                    # 全仓测试 = node --test packages/**/*.test.ts
                            #   实测 217/217/0（连续 3 次一致）。输出字面格式随 Node 版本/reporter 而异：
                            #   Node 24（spec reporter）为 "ℹ tests <N>"，Node 22（TAP）为 "# tests <N>"
npm run typecheck           # tsc --noEmit -p . （实测 0 错误，TypeScript 5.9.3）

node --test "packages/control/**/*.test.ts"   # 单包测试（把 control 换成任意包名）
node packages/common/test/clock.test.ts       # 单文件亦可（实测 5/5 通过）
```

注意：Windows 下 `node --test` 的 glob 发现在初版轮曾出现一次偶发漏收——单次运行只发现 213 个用例（另有 3 个未被 glob 收到，**是漏收不是失败**），复跑即为全量（详见 `DELIVERY_REPORT.md` §2.4）；2026-09-28 复测轮 3 次全仓运行均为 217，未复现。核对数字时仍建议以每包单独运行之和为准（实测 40+24+35+45+40+33 = 217）。

测试形态与证据等级说明（详见 `DELIVERY_REPORT.md` §2）：

- crypto 包：RFC 权威向量 + 与 `node:crypto` 实时交叉验证（`node:crypto` 只出现在测试文件，P3 例外）。
- noise 包：cacophony 社区 Noise 已知答案向量逐字节锚定。
- wireguard 包：上游（wireguard-go/boringtun/linux）均未发布可注入临时密钥的完整握手 KAT（测试头注记录 2026-09-28 web 检索再确认）。148B/92B 报文向量改为**三重锁定**（评审 finding"向量不得自产自锁"后的增强，见 `packages/wireguard/test/handshake.test.ts` 头注）：写死 hex 锚 == 测试内零共享参考推导（X25519/AEAD/HMAC 全走 `node:crypto`，键控 BLAKE2s 手写 RFC 7693 实现、KAT 锚定官方 blake2-kat）== 模块输出；头注另记录跨语言第三实现（CPython 3.12 hashlib/hmac + pyca-cryptography 47.0.0）对同组 fixture 逐字节复现两向量——该跨语言步骤记录于测试头注，本更新轮未复跑。传输层另有 `encryptPacket` 与 OpenSSL chacha20-poly1305 的逐字节对照（LE64 nonce，counter≥1 区分端序，`packages/wireguard/test/transport.test.ts:139`）。键调度依据为白皮书原文 + wireguard-go 转录（头注列明）。**仍未与真实 WireGuard 对端互操作测试**。
- control / derp 包：脚本化 fake `HttpTransport` / `DerpDialer` 全流程往返（`NoiseIkResponder` 扮演服务端），全程 `FixedClock`/`ArrayRng`，字节可复现。

## ArkTS 兼容策略

核心库保持纯 `.ts`，依赖方向单向：`.ets`（UI/Ability）可 import `.ts`，反之编译错误（官方规则 `arkts-no-ts-deps`，`docs/arkts-constraints.md` §0）。落进 HarmonyOS 工程前，代码按以下策略写，使迁移只剩"搬文件"：

1. **只用可擦除语法**：根 `tsconfig.json:9` 开 `erasableSyntaxOnly`，编译期直接拒绝 enum / namespace / 构造参数属性（Node 22 strip-only 同样不支持，双重保险）。
2. **禁则逐条规避**：`docs/arkts-constraints.md` A1–A36 逐条给出官方规则名与正反例，实现按正例写——无 `any`/`unknown`、无解构、无对象展开、无 `call/apply/bind`、无字面量联合类型、无 tuple（架构裁定 R4）、`throw` 仅 `Error` 子类（R7，每包自有 `XxxError`）。
3. **常量集合用常量对象模式**（A18/R5）：`interface XxxE { A: number; ... }` + `const Xxx: XxxE = {...}` + `parseXxx(v): number | null` 运行时校验，替代 enum 与字面量联合。
4. **`verbatimModuleSyntax`**（`tsconfig.json:10`）：类型导入强制显式 `import { type Clock }`；相对导入一律带 `.ts` 后缀（P2，Node ESM 精确解析要求），跨包用包名 `@ohos-tailscale/<pkg>`。
5. **字节/大整数**：一律 `Uint8Array`（禁 `Buffer`）与 `BigInt`（u64 槽位），API 注释写明"返回拷贝/共享视图"（P5/P6/R8）。
6. **平台差异收敛到注入接口**：时钟/随机/HTTP（未来再加 UDP/TLS 拨号）全部走构造注入，真机迁移只换 `app/` 侧实现。

残余风险（未在真机验证，列入 `docs/arkts-constraints.md` §6）：BigInt 的 ArkTS 运行时支持度（CU2）、ets loader 对 `.ts` specifier 的接受度（CU6）、`@ohos.security.cryptoFramework` 等 API 实际签名（CU7）。

## 后续路线

### 1. DevEco 构建 HAP

前提：安装 DevEco Studio 5.0+（本工程按 `compatibleSdkVersion: "5.0.0(12)"`、hvigor `modelVersion: 5.0.0` 基线手写）。**该工程从未编译，首次构建预期会出现需要修正的报错**。步骤（详见 `app/README-app.md` §2）：

1. `File → Open` 选择 `app/`（工程根以 `build-profile.json5` 所在目录为准），让 DevEco 完成 hvigor/npm 同步。
2. `File → Project Structure → Signing Configs` 勾选自动签名（需华为开发者账号；真机调试必须签名。当前工程 `signingConfigs` 为空）。
3. `Build → Build Hap(s)/APP(s) → Build Hap(s)`；真机运行选 `entry` 模块 `default` target。
4. 已知坑：若提示无法识别 `"type": "vpn"`（官方指南明示的已知问题），按 `app/README-app.md` §2 第 5 步在 SDK 的 `toolchains\modulecheck\module.json` 补枚举后清缓存重启。

### 2. 真机集成步骤

核心库进 HarmonyOS 工程的三条候选路径（**均未实测**，按优先级试错，见 `app/README-app.md` §4）：

1. ohpm 本地目录依赖：`entry/oh-package.json5` 中 `"@ohos-tailscale/common": "file:../../packages/common"`（TODO 已预留）；
2. 源码并入 `entry/src/main/ets/core/`——成败点在 CU6（ets loader 是否接受 `./x.ts` specifier）；
3. 打成 HAR 以本地 HAR 依赖引入。

随后实现平台注入层（放 `app/entry/src/main/ets/platform/`，当前仅 TODO）：`HttpTransport`（`@ohos.net.http`）→ control 包；`Rng`/`Clock`（`@ohos.security.cryptoFramework` + 系统时钟）→ 各包；UDP socket（`@ohos.net.socket`，fd 须 `conn.protect(fd)` 防环路）→ wireguard 包；DERP TLS 拨号 → derp 包。

数据面接线（`VpnExtensionAbility` 桩内已标 TODO，`app/entry/src/main/ets/vpnextensionability/VpnExtensionAbility.ets`）：`startVpnExtensionAbility` → 系统授权弹窗 → `createVpnConnection(context)` → `conn.create(VpnConfig)` 得 TUN fd → app 侧按 fd 读写 IP 包 → `WgSendSession`/`WgRecvSession` 加解密 → UDP/DERP 出口。VpnConfig 地址落 CGNAT 段与 ULA（`packages/common/src/constants.ts`），MTU 建议起点 1280。

### 3. 与真实 tailnet 联调

**✅ 已打通（2026-09-29）**：上游核对 AU1–AU3 清账后，纯自研协议栈已对真实 Headscale v0.29.4 完成全链路互通——`/key` 密钥发现 → `POST /ts2021` 升级（initiation 内嵌头）→ Noise IK 握手 → HTTP/2 over Noise 注册（`MachineAuthorized=true`）→ MapResponse 拉取，且同密钥连内嵌 DERP 的全栈流程见 `interop/derp.node.ts`。复现方式：`interop/` 目录（headscale.yaml + start-headscale.sh + register.node.ts + derp.node.ts，脚本头注有完整步骤）。证据与协议更正细节见 `DELIVERY_REPORT.md` §5、`docs/architecture.md` §10.2/§10.3 v1.2。

剩余的真机联调差异（相对本机 WSL 环境）仅有：TLS（headscale 生产形态为 HTTPS，本机为 HTTP 明文）、真机网络出口、以及 CU2/CU5/CU6 的 ArkTS 运行时项。如需连**已有** tailnet（而非自建联调环境），仍需向管理员索取 auth key（Headscale：`headscale preauthkeys create --user <u>`；Tailscale SaaS：管理后台生成），`serverStaticPublic` 已可经 `/key` 端点自动发现（`interop/register.node.ts` 实测）。App 侧凭据传递方案按 `app/README-app.md` §6 第 8 条：经 Asset Store Kit / 应用私有 preferences 中转，不走 `want.parameters`。

凭据与脱敏说明：本仓库不含任何密钥/令牌——oracle 取证中 `nodekey:/mkey:/discokey:` 打码为前 8 hex、prefs 私钥由 tailscaled 自身置零（`docs/oracle/raw/README.txt`）；但**控制面域名与拓扑信息为明文**（`headscale.example.internal` 见于本文首段、`docs/oracle/protocol-notes.md`、`docs/architecture.md` §7.2 与 `packages/control/src/client.ts` 注释），仓库公开前需自行评估是否脱敏。另：本仓取证仅覆盖 Headscale 形态（实测控制面是 fork 版 Headscale，非 Tailscale SaaS），官方 SaaS 形态未取证。

## 文档索引

| 文档 | 内容 |
|---|---|
| `docs/architecture.md` | 六包实现契约（依赖方向、签名、冻结规则、上游核对清单 AU1–AU4、版本记录） |
| `docs/arkts-constraints.md` | ArkTS 禁则 A1–A36、工程约束 P1–P7、tsconfig 基线、未验证项 CU1–CU10（含官方迁移指南抓取记录：附录 A） |
| `docs/oracle/protocol-notes.md` | 真实 tailscale 1.102.3（fork 自建版）只读取证：status/netmap/derp-map/netcheck 结构与 12 项待实现部件清单 |
| `docs/oracle/raw/README.txt` | 取证命令 → 转储文件映射与打码策略 |
| `app/README-app.md` | 壳工程：DevEco 导入构建、权限、核心库集成三方案、tun fd 对接、11 项未验证事项 |
| `DELIVERY_REPORT.md` | 交付报告：逐模块完成项、测试证据、已知限制、下一步建议 |
