# Tailscale 1.102.3 参考实现（Oracle）协议取证笔记

> 目的：为自研鸿蒙（HarmonyOS）客户端 `ohos-tailscale` 提供对真实 Tailscale 客户端的协议结构取证。
> Oracle = 本机已登录的 tailscale 1.102.3。**取证过程只读**，未执行任何改状态命令（见 §1.3）。
> 标注约定：【实测】= 本机命令输出直接可见的事实，对应 `raw/` 下转储文件；【上游语义】= Tailscale
> 上游源码的已知语义，本机转储无法直接验证，仅作背景，实现时需以源码为准。

## 1. 取证环境与方法

### 1.1 Oracle 身份【实测】

来自 `raw/version.txt`（`tailscale version`）与 `raw/hostinfo.json`（`tailscale debug hostinfo`）：

- 版本 `1.102.3`，long version `1.102.3-t9329c3677-ga522f65e9`，`other commit: a522f65e9…-dirty`，
  Go `go1.26.6 (tailscale/go 7275f792d4)` —— **是 fork 出来的自定义构建**（`-dirty`、短哈希后缀）。
- 宿主：Windows Server 10.0.20348（amd64），msi 安装，非 userspace（`TUN: true`）。
- 数据面依赖 `golang.zx2c4.com/wireguard/windows v0.5.3`（`raw/go-buildinfo.txt`）。
- 有趣的旁证：tailnet 内 `harmony-vm` 上报的 `IPNVersion` 也是 `1.102.3-t9329c3677-ga522f65e9`
  （openEuler 24.03 / arm64），`governance-machine` 是 `1.102.4-t3caf7d9e7-g084ee3b64` —— 该 tailnet
  的节点全部运行同一 fork 的自建版本（`raw/netmap-trimmed.json`）。

### 1.2 控制面是 Headscale，不是 Tailscale SaaS【实测】

- `raw/prefs.json`：`"ControlURL": "https://headscale.example.internal"`（自定义控制面）。
- `raw/status-json.json`：`CurrentTailnet = {Name: "headscale.example.internal", MagicDNSSuffix: "edgenet.lan", MagicDNSEnabled: true}`；
  `tailscale status` 列表里 tailnet 名显示为 `edgenet`。
- `raw/derp-map.json`：多出 region `999`，`RegionCode: "headscale"`，`RegionName: "Headscale Embedded DERP"`，
  单节点 `HostName: headscale.example.internal`，`IPv4: 198.51.100.30`，`STUNPort: 3478`，`DERPPort: 443`。
- peers 的 `Relay` 字段直接出现取值 `"headscale"`（即 region 999 的 RegionCode）。
- 结论：**鸿蒙客户端必须同时兼容"自定义 ControlURL + Headscale 风格 netmap"**，DERP map 里会混有
  官方 region（1–28）与自建 embedded DERP（999）。

### 1.3 执行过的只读命令清单

全部命令与输出一一对应 `raw/` 文件（清单见 `raw/README.txt`）：

`tailscale version`、`tailscale status`、`tailscale status --json`、`tailscale debug derp-map`、
`tailscale netcheck`、`tailscale debug prefs`、`tailscale debug netmap`、`tailscale debug control-knobs`、
`tailscale debug hostinfo`、`tailscale debug portmap`、`tailscale debug peer-relay-servers`、
`tailscale debug statedir`、`tailscale debug local-creds`（阻塞型，见下）、`tailscale debug env`、
`tailscale debug metrics`、`tailscale debug go-buildinfo`。

两个版本行为差异，实施同款取证时要注意：

1. **`tailscale debug netcheck` 在 1.102.3 不存在**：报 `tailscale debug: unknown subcommand: netcheck`
   （证据 `raw/debug-netcheck-error.txt`）。netcheck 在顶层：`tailscale netcheck`（`tailscale --help` 可见）。
2. **`tailscale debug local-creds` 不是一次性打印**：它会阻塞式启动一个 `127.0.0.1` 本地 HTTP 代理来
   转发 LocalAPI（输出示例 `Serving LocalAPI proxy on http://127.0.0.1:13201` +
   `curl.exe http://127.0.0.1:13201/localapi/v0/status`），需 Ctrl+C 结束；取证时以 `timeout 20` 终止，
   未改动 tailscaled 状态。这也证明 **LocalAPI 可经普通 HTTP 访问**，对鸿蒙端本地 IPC 设计有参考价值。

明确排除的子命令（`tailscale debug --help` 列出、按语义属改状态或破坏性）：`restun`、`rebind`、
`rotate-disco-key`、`derp-set-on-demand`、`derp-unset-on-demand`、`break-tcp-conns`、`break-derp-conns`、
`pick-new-derp`、`force-prefer-derp`、`force-netmap-update`、`reload-config`、`set-expire`、`dev-store-set`、
`clear-netmap-cache`、`test-risk`、`component-logs`、`capture`（抓包）、以及顶层的
`up/down/set/login/logout/switch/configure` 等。

## 2. `tailscale status --json` 的结构【实测】

对应 `raw/status-json.json`（约 9KB，已打码）。

### 2.1 顶层字段

| 字段 | 实测值/类型 | 说明 |
|---|---|---|
| `Version` | string，`1.102.3-t9329c3677-ga522f65e9` | 后端版本 |
| `TUN` | bool，`true` | 是否 TUN 模式 |
| `BackendState` | string，`"Running"` | 后端状态机当前态 |
| `AuthURL` | string，`""` | 登录跳转 URL，登录后为空 |
| `TailscaleIPs` | [v4, v6] | 本机 `100.100.0.5` + `fd7a:115c:a1e0::5` |
| `Self` | PeerStatus 对象 | 本机自身（结构与 Peer 相同） |
| `Health` | [] | 健康告警列表，健康时为空数组 |
| `MagicDNSSuffix` | `"edgenet.lan"` | MagicDNS 后缀 |
| `CurrentTailnet` | {Name, MagicDNSSuffix, MagicDNSEnabled} | Name 是控制面域名 |
| `CertDomains` / `ExtraRecords` | null | TLS 证书域名等 |
| `Peer` | **map：key 是 `nodekey:<hex64>` 公钥字符串**，value 是 PeerStatus | 不是数组！ |
| `User` | map：`"1"` → {ID, LoginName, DisplayName} | 用户（Headscale 单用户 `edgenet`） |
| `ClientVersion` | null | 客户端版本元数据（本环境未启用） |

### 2.2 PeerStatus 字段（Self 与 Peer 共用）

以 `harmony-vm`（离线）与 `hk-gateway`（在线直连）两个实例对照：

| 字段 | 类型 | 实测语义 |
|---|---|---|
| `ID` / `NodeID` | string `"4"` / number `4` | 同一 ID 的两种编码；netmap 里则叫 `ID`(int)/`StableID`(string) |
| `PublicKey` | `nodekey:<hex64>` | 节点公钥（WireGuard 层） |
| `HostName` | string，`harmony-vm` | 裸主机名 |
| `DNSName` | string，`harmony-vm.edgenet.lan.` | **全称域名，末尾带点**（FQDN 标准形式） |
| `OS` | string，`linux`/`windows` | 上报的操作系统 |
| `UserID` | number，`1` | 归属用户 |
| `TailscaleIPs` | [v4, v6] | `100.100.0.4` + `fd7a:115c:a1e0::4`（CGNAT 100.64.0.0/10 + ULA fd7a:115c:a1e0::/48） |
| `AllowedIPs` | []string CIDR | 路由指向；exit node 会带 `0.0.0.0/0`、`::/0`（hk-gateway 即如此） |
| `Addrs` | []string `ip:port` | **候选 UDP 端点列表**。实测：Self 有值（公网映射 + 内网 `198.51.100.20:41641` + TUN 地址），普通 peer 为 `null` —— 端点列表实际由 netmap 下发（见 §4），status 里多数为空 |
| `CurAddr` | string | **当前实际使用的直连地址**。实测仅 Active peer `hk-gateway` 为 `203.0.113.10:4500`，其余全空 |
| `Relay` | string | 该节点 home DERP 的 **RegionCode**：实测 `sfo`(self)/`hkg`/`lax`/`headscale`；与 netmap 的 `HomeDERP`(region ID) 一一对应：`lax`↔17、`hkg`↔20、`headscale`↔999、self `sfo`↔2 |
| `PeerRelay` | string | 空（本 tailnet 无 peer relay） |
| `RxBytes`/`TxBytes` | number | 收发字节；hk-gateway 107404644/90282000 |
| `Created` | RFC3339 | 节点创建时间 |
| `LastSeen` | RFC3339 | **只对离线节点有值**（harmony-vm `2026-09-10T11:15:50.354871721+08:00`）；在线节点为零值 `0001-01-01T00:00:00Z` |
| `LastHandshake` | RFC3339 | WireGuard 握手时间，仅 Active peer 有值（hk-gateway 实测有近时刻值） |
| `Online` | bool | 控制面视角在线与否（由 control 汇聚各端上报） |
| `ExitNode` / `ExitNodeOption` | bool | 是否正在用作 / 是否可用作 exit node（hk-gateway `ExitNodeOption: true`） |
| `Active` | bool | **wgengine 中有活跃连接**（`InEngine` 同义；hk-gateway true，其余 false） |
| `PeerAPIURL` | []string | `http://100.100.0.4:37067`、`http://[fd7a:…]:40203` —— 随机端口的 peer API（与 netmap `Hostinfo.Services` 的 `peerapi4`/`peerapi6` 端口一致，已交叉验证） |
| `TaildropTarget` | number | Taildrop 可用性枚举 |
| `Capabilities` | []string | URL 形式能力串（`https://tailscale.com/cap/ssh`、`…/cap/is-admin` 等） |
| `CapMap` | map[string][]json.RawMessage | 能力串 → 参数 |
| `InNetworkMap`/`InMagicSock`/`InEngine` | bool | 该节点分别被 netmap/magicsock/wgengine 持有的状态位 |

要点：**`Online=true` 但 `Active=false`** 表示"在网、无流量"（本 tailnet 6 个 peer 中 5 个如此）；
只有 `Active=true` 的 peer 才有 `CurAddr`/`LastHandshake`/`InEngine=true`。

### 2.3 harmony-vm（离线节点）专记【实测】

`tailscale status` 文本（`raw/status.txt`）显示 `harmony-vm … offline, last seen 18d ago`；
`status --json` 中该 peer：`Online:false`，`LastSeen: 2026-09-10T11:15:50+08:00`，`Relay:"lax"`，
`TailscaleIPs:[100.100.0.4, fd7a:115c:a1e0::4]`，`Active:false`，`CurAddr:""`。
netmap（`raw/netmap-trimmed.json`，ID=4 全量保留）补充：`HomeDERP:17`(lax)、
`Endpoints:["223.198.166.92:30387","172.16.105.2:41641"]`、`DiscoKey:discokey:2f153b4c…`、
`Hostinfo`: openEuler 24.03 / arm64 / aarch64 / 内核 6.6.0、`NetInfo`: `WorkingUDP:true`、
`MappingVariesByDestIP:false`、`PreferredDERP:17`、`DERPLatency` 覆盖 26 个官方 region。
即：**节点离线后其端点、disco 公钥、home DERP 仍在 netmap 中保留**，客户端必须能处理"对端离线、
netmap 信息过期"的状态（打洞必然失败，退回经 DERP 排队，直至放弃）。

## 3. `tailscale debug derp-map` 的结构【实测】

对应 `raw/derp-map.json`（21KB，未打码——公网中继信息，无敏感字段）：

```jsonc
{
  "Regions": {
    "<RegionID 的十进制字符串>": {        // 注意 JSON key 是字符串 "1"…"28","999"
      "RegionID": 1,                     // int
      "RegionCode": "nyc",               // 短码，status --json 的 Relay 字段用它
      "RegionName": "New York City",
      "Latitude": 40.7128, "Longitude": -74.006,
      "Nodes": [ /* 同 region 多节点，客户端应随机挑选/故障切换 */ ]
    }
  }
}
```

Node 对象字段（以本 dump 为准）：

| 字段 | 实测出现情况 | 语义 |
|---|---|---|
| `Name` | `"1f"`、`"20b"`、自建 region 里是 `"999"` | 节点名（region 内多实例 `regionID+字母`） |
| `RegionID` | int | 所属 region |
| `HostName` | 全部有 | DERP 主机名，**客户端连它时用它做 DNS 解析与 TLS SNI** |
| `CertName` | **全部 29 个 region 均未出现** | 证书校验名。缺省时【上游语义】回退为 `HostName`；自建 DERP 用非公网 CA 签发的证书时才需要显式配置——鸿蒙端 TLS 校验逻辑必须实现"CertName 优先、HostName 回退" |
| `IPv4`/`IPv6` | 官方 region 两者都有；region 999 只有 IPv4 | DNS 解析失败时的直连备份 |
| `STUNPort` | 仅 region 999 显式 `3478`；官方 region 缺省 | 【实测】region 999 显式给出 3478。【上游语义】缺省表示默认 3478，负值表示该节点不做 STUN——netcheck 用它测各 region 延迟（`raw/netcheck.txt` 的延迟表与该字段一致） |
| `DERPPort` | 仅 region 999 显式 `443`；官方 region 缺省 | 【上游语义】缺省=443 |
| `CanPort80` | 官方 region 均 `true`；region 999 无 | 【上游语义】是否可用 80 端口做 DERP 回退（穿透 443 被封的网络） |

本 tailnet 实际有 **29 个 region**：官方 1–28（`derp1f…derp28d.tailscale.com`）+ 自建 999
（Headscale embedded，`headscale.example.internal`）。另外注意本机实测的 home region（sfo/2）并
不是延迟最低的（sin/3 才是 77.9ms），home region 由控制面指派 + 客户端报告 PreferredDERP 共同决定，
不是纯客户端决策。

## 4. `tailscale debug netmap`：协议真正的"配置下发"载体【实测】

对应 `raw/netmap-trimmed.json`（裁剪+打码版，结构与原 42KB 一致）。status --json 只是"展示层"，
**协议状态机真正消费的是 netmap**。关键字段：

- `SelfNode` / `Peers[]`：`Addresses`(本机 IP+掩码)、`AllowedIPs`、`Key`(nodekey)、`Machine`(mkey)、
  `DiscoKey`、`Endpoints`（候选 UDP 端点，含公网映射与内网地址）、`HomeDERP`(region ID)、
  `Cap`(能力版本号，本 tailnet 全部 142)、`MachineAuthorized`、`LastSeen`、`Online`、
  `Hostinfo`（含 `NetInfo`：`DERPLatency` map、`PreferredDERP`、`MappingVariesByDestIP`、
  `WorkingUDP/IPv6`、`UPnP/PMP/PCP`、`Services`（peerapi 端口）等）、`StableID`、`User`。
- `PacketFilter`：本 tailnet 为 allow-all：`Srcs:["0.0.0.0/0","::/0"]` → `Dsts:[0.0.0.0/0, ::/0, 全端口]`，
  `IPProto:[6,17,1,58]`（= TCP/UDP/ICMPv4/ICMPv6）。配套 `PacketFilterRules` 的简化形式。
  **客户端必须按此实现入站包过滤**。
- `DNS`：`Domains:["edgenet.lan"]`、`Proxied:true`、`Resolvers:[223.5.5.5, 119.29.29.29]`（控制面下发的
  全局 resolver）、`Routes`：64 条 `100.in-addr.arpa` 反解分片 + 1 条 `fd7a:115c:a1e0` 的 ip6.arpa 反解，
  值均为空数组（表示这些域走系统 resolver）。
- `DERPMap`：与 §3 完全同构（netmap 内嵌一份，`debug derp-map` 单独打印同一对象）。
- `Domain:"headscale.example.internal"`、`MachineKey`/`NodeKey`（本机公钥）、`SSHPolicy:null`、
  `TKAEnabled:false`（tailnet lock 未启用）、`TKAHead`：全 0 的 base64、`UserProfiles`、`CollectServices`。

## 5. netcheck 观察结果【实测】

对应 `raw/netcheck.txt`（`tailscale netcheck`，输出为人类可读 Report，无 JSON flag）：

```
UDP: true
IPv4: yes, 203.0.113.10:41037
IPv6: no, but OS has support
MappingVariesByDestIP: false
PortMapping: (空)
CaptivePortal: false
Nearest DERP: Singapore
DERP latency: sin 77.9ms / hkg 80.8ms / blr 156.6ms / lax 198.2ms … (29 region 全量测速)
             syd/tok/headscale 本次无延迟（空）
```

- `MappingVariesByDestIP:false` = NAT 对目的地址不变化（EIM，endpoint-independent mapping），
  打洞成功率高；该值由 STUN 从两个不同 DERP 探测比较得出。
- **重要坑**：`IPv4: yes, 203.0.113.10:41037` 中的公网地址正是 hk-gateway 的公网 IP —— 本机默认
  路由在 Meta TUN（`198.18.0.1/30`）之后，netcheck 的 STUN 探测包经由上游隧道出去
  （`raw/portmap.txt` 也因此报 `no gateway or self IP`，UPnP/PMP/PCP 探测直接不可用）。
  **鸿蒙端要注意：netcheck 报告的是"探测路径"上的 NAT 映射，当设备存在 VPN/多路由时，
  打洞端点与业务流量路径可能不一致**，需按接口绑定探测。
- 自建 DERP（999/headscale）本次延迟为空（STUN 未测通），但该 region 的 peer（edge-server 等）
  仍能通信——客户端必须容忍"某 region 测不出延迟"并按策略回退。

## 6. prefs（LocalAPI 视角的用户偏好）【实测】

对应 `raw/prefs.json`：`ControlURL`、`WantRunning:true`、`LoggedOut:false`、`CorpDNS:true`、
`RouteAll:true`（接受子网路由）、`ExitNodeID/ExitNodeIP:""`（未使用 exit node，但 hk-gateway 的
0.0.0.0/0 路由被接受并在路由表中）、`Hostname:"windev-01"`、`NetfilterMode:2`、`AutoUpdate:{Check:true,Apply:false}`、
`ShieldsUp:false`、`RunSSH:false`、`NoStatefulFiltering:true`。
**安全相关实测**：`Config.PrivateNodeKey` 与 `NetworkLockKey` 被 tailscaled 输出时置零为
`privkey:000…`/`nlpriv:000…` —— **LocalAPI 对外从不吐私钥**，鸿蒙端必须同样脱敏。
（`nodekey`/`discokey`/`mkey` 是公钥，netmap 中可见，本笔记 raw 转储仍一律打码。）

## 7. 其他只读 debug 佐证【实测】

- `control-knobs.json`：全部 `false`/`null` —— 控制面未下发特殊开关；鸿蒙端需预留 knob 体系
  （控制面可远程改变客户端行为），默认全关。
- `metrics.txt`（Prometheus 文本）：`controlclient_map_response_map/map_delta/ping` 与
  `controlclient_patch_*`（patch_endpoints/patch_key/patch_online/patch_derp/patch_discokey…）
  系列计数器证明 **控制面存在全量 MapResponse + 增量 patch 两种下发**；
  `magicsock_disco_sent_ping:24067 / sent_pong:20939 / sent_callmemaybe:856 / recv_pong:21336`
  等非零计数证明 **disco 发现协议（ping/pong/call-me-maybe）在活跃运行**。
- `peer-relay-servers.json`：`[]`（peer relay 功能未用）；`statedir.txt`：状态目录 `C:\ProgramData\Tailscale`。
- `local-creds.txt`：LocalAPI 可经本地代理以普通 HTTP 访问（`/localapi/v0/status`）。

## 8. 对自研鸿蒙客户端：需要实现的协议部件清单

按本机取证到的证据，逐项映射：

| # | 部件 | 证据 | 说明 |
|---|---|---|---|
| 1 | **LocalAPI/IPC 层** | §1.3 local-creds；prefs 经 LocalAPI 读取 | 桌面端是 named pipe/unix socket 上的 HTTP+JSON；鸿蒙端需自选 IPC（如本地 socket），协议是 `ipn` 状态 + prefs/netmap JSON |
| 2 | **控制面客户端（Noise/ts2021 over HTTPS）** | ControlURL 自定义；metrics 的 `controlclient_map_requests/map_response_*` | 到 `https://headscale.example.internal` 的长轮询：注册（nodekey/mkey）→ MapRequest → MapResponse（全量/patch）。具体握手帧格式【上游语义】需读上游 `control/`、`tailcfg.go`，本机取证无法覆盖 |
| 3 | **Netmap 状态机** | §4 | 解析 SelfNode/Peers/PacketFilter/DNS/DERPMap，维护 Online/LastSeen/过期（KeyExpiry）等；需处理离线节点（harmony-vm 案例） |
| 4 | **DERP 客户端 + region 选择** | §3 derp-map；netcheck 延迟表 | 解析 Regions/Nodes（CertName 回退 HostName 做 TLS 校验、STUNPort 默认 3478、DERPPort 默认 443、CanPort80 回退）；TLS+自定义帧协议【上游语义】需上游 `derp/` 源码；需实现"测不出延迟的 region 也能兜底" |
| 5 | **netcheck 引擎** | §5 | STUN 测 UDP/IPv4/IPv6/DERP 延迟、MappingVariesByDestIP、端口映射探测（UPnP/PMP/PCP）、CaptivePortal；**注意按接口绑定，避免 VPN 多路由干扰** |
| 6 | **Disco 发现协议** | §7 metrics 计数；netmap 的 DiscoKey/Endpoints | 节点互发 disco ping/pong/call-me-maybe 打洞；UDP 端口实测多用 41641（默认），也有随机映射端口；需实现 Endpoints 枚举（STUN 派生公网映射 + 内网地址） |
| 7 | **WireGuard 数据面** | §1.1 wireguard-windows v0.5.3；AllowedIPs | nodekey 对，AllowedIPs→路由，exit node（0.0.0.0/0+::/0）支持；鸿蒙需 userspace wireguard-go（或内核态），Windows 用的 wireguard-windows 不可复用 |
| 8 | **PacketFilter 防火墙** | §4 allow-all + IPProto[6,17,1,58] | 按 netmap 下发的 (src,dst,proto,ports) 四元组过滤入站流量 |
| 9 | **PeerAPI（HTTP over tailnet）** | §2.2 PeerAPIURL ↔ Hostinfo.Services(peerapi4/6) | 每节点在 Tailscale IP 上开随机端口 HTTP 服务；Taildrop 等功能走它 |
| 10 | **MagicDNS** | §4 DNS 结构 | 域名 `edgenet.lan`（DNSName 末尾带点）、反解路由、控制面下发 resolver 的转发策略 |
| 11 | **能力/开关体系** | §2.2 Capabilities/CapMap、§7 control-knobs | URL 形式能力串 + 参数；控制面 knob 远程开关 |
| 12 | **状态机与展示层** | §2.1 BackendState、Health | Running/NeedsLogin 等状态 + Health 告警列表 |

**本机取证无法确认、需另补的证据**（不猜）：DERP 帧格式与握手、Noise/ts2021 报文细节、MapRequest
的具体 JSON 字段、peerapi 端点语义、Cap 数值 142 的含义。建议下一步用只读但会主动建连的
`tailscale debug ts2021` / `tailscale debug derp`（测试型命令）抓包，或直接读上游源码
`tailcfg.go`/`control/controlbase`/`derp/derphttp` 对照。

## 9. raw/ 文件清单

见 `raw/README.txt`（命令→文件映射、打码策略）。全部文件 < 100KB；所有
`nodekey:/mkey:/discokey:` 已打码为前 8 hex + `...MASKED`，prefs 中私钥由 tailscaled 自身置零，
未在任何输出中发现私钥或令牌（env 输出中的宿主应用变量已整行删除）。
