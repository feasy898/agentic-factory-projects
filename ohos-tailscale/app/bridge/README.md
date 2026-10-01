# app/bridge —— 壳 ↔ 协议包 mock 集成层（纯 TS，Node 可跑）

> 2026-10-01 夜班 worker-A 交付。背景：app/ 壳因商业 SDK/登录墙不可编译（`docs/build-feasibility-linux.md`），
> 本层把 README-app.md §4「平台注入层」的壳侧半边用确定性 mock 钉死并测试，真机实现落地时按接口替换。

## 组成

| 文件 | 职责 |
|---|---|
| `src/mock-http-transport.ts` | `HttpTransport`（common 冻结接口）的脚本化 mock：路由表、请求留痕、流式 chunk、断网注入 |
| `src/mock-control-plane.ts` | ts2021 假控制面（noise `NoiseIkResponder` 承载）：IK 握手、注册帧解密留痕、netmap 下发入队 |
| `src/shell-status.ts` | UI 状态模型：`ShellSessionState`→`ShellConnState` 映射（Index.ets `ConnState` 常量逐值镜像） |
| `src/shell-session.ts` | `ShellControlSession`：装配 fail-fast 校验 + `login()/pollMap()/statusSnapshot()/close()` + authKey 纪律 |
| `src/mock-udp-bus.ts` | 确定性 mock UDP 总线（NAT 公网映射仿真：投递源呈现公网视图、目的按公网端点反查）+ `MockStunServer`（STUN Binding 服务端，回发端观察映射） |
| `src/shell-discovery.ts` | 发现面门面：`ShellDiscoClient`（disco Ping/自动 Pong/CallMeMaybe，密封经 disco 包）+ `ShellStunProbe`（`StunTransaction` 探测 + RTT 注入） |
| `test/bridge.test.ts` | node:test 套件（7 用例，控制面链路，确定性可复现） |
| `test/disco-netcheck.test.ts` | node:test 套件（6 用例，发现面链路：STUN NAT 映射/RTT、TxID 配对否定、Ping→Pong、CallMeMaybe、噪声/错钥容错、弃报计数） |

## 与核心库的依赖方向（D4/A29 不变）

```
app/bridge  ──import──▶  @ohos-tailscale/common|crypto|noise|control|disco|netcheck （只 import，零改动）
    ▲                        packages/*（worker-B 属地，公钥 API 冻结）
    └─ 未来 app/entry/src/main/ets/**（ArkTS）经本层接口消费协议核心
```

## authKey 纪律（红线 1 对齐）

- 只做形状校验（非空 / 无空白 / ASCII 可打印 / ≤128 字符）；
- 精简版 RegisterRequest（TLV）无 auth 字段，**authKey 永不进任何请求体/URL/日志**（测试对全部请求留痕做字节级断言）；
- `close()` 清内存；真实注册上行承载属上游核对项（docs/architecture.md §10 AU 清单）。

## 运行

```bash
npm run test:bridge        # node --test app/bridge/test/*.test.ts
npm run typecheck:bridge   # tsc --noEmit -p app/bridge
```

根 tsconfig 显式 exclude app/（六包 typecheck 面不变）；本层用 `app/bridge/tsconfig.json` 独立校验，编译选项与根一致（strict/nodenext/erasableSyntaxOnly）。

## 已知边界（如实）

- ~~mock 控制面不实现 UDP 数据面~~ → 第 2 轮已补确定性 mock UDP 总线（disco/STUN 发现面已打通）；**仍缺**：netcheck 引擎调度（多 server/端口映射协议）、disco 0x04–0x09 UDP relay 家族、DERP 随机选节点、netmap→WG 推导（协议侧二期，worker-B 面）；
- 真机 UDP socket（@ohos.net.socket + `conn.protect(fd)` 防环路）替换点 = `UdpSocket`（send/receive 语义不变，事件化适配）；
- mock 总线为同步队列形态（确定性测试用）；真机为异步回调，接口形状已钉死；
- `endpoints` 仍由调用方传入，但第 2 轮起壳侧可用 `ShellStunProbe` 自行派生公网映射（README-app.md §4「STUN 派生公网映射」的 mock 实现面）；
- ArkTS 未验证项（U6 `.ts` specifier 等）与本层无关：本层是 Node 侧桥，真机 ArkTS 侧集成形态见 README-app.md §4 三方案。
