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
| `test/bridge.test.ts` | node:test 套件（6 用例，全链路确定性可复现） |

## 与核心库的依赖方向（D4/A29 不变）

```
app/bridge  ──import──▶  @ohos-tailscale/common|crypto|noise|control   （只 import，零改动）
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

- mock 控制面不实现 UDP 数据面 / DERP / protect(fd)——数据面注入（UDP socket、Dialer）待协议包二期接口定稿后按同模式补；
- `endpoints` 由调用方传入（真机上来自 STUN 派生，二期）；
- ArkTS 未验证项（U6 `.ts` specifier 等）与本层无关：本层是 Node 侧桥，真机 ArkTS 侧集成形态见 README-app.md §4 三方案。
