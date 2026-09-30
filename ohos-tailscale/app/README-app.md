# ohos-tailscale 应用壳工程（app/）

- 生成日期：2026-09-28
- 定位：HarmonyOS NEXT 应用壳（UI + VPN 扩展 + 平台注入层），承载 `packages/` 下的纯 TS 协议核心库。
- 上游约束：`docs/arkts-constraints.md`（A/P/T 规则与 U 未验证项）、`docs/architecture.md`（D1–D4 依赖方向、注入接口契约）。`.ets → .ts` 单向依赖（A29/约束 §0），核心库不 import 本目录任何文件。
- 本机**无 DevEco Studio 与 HarmonyOS SDK，本工程从未编译**；所有文件按官方文档与模板惯例手写，导入后请先读「已知未验证事项」。

## 1. 目录结构

```
app/
├─ AppScope/
│  ├─ app.json5                               # 应用级配置（bundleName/version/icon/label）
│  └─ resources/base/element/string.json      # app_name
│  └─ resources/base/media/app_icon.png       # 占位图标（纯色生成，需替换）
├─ build-profile.json5                        # 工程级：product/compatibleSdkVersion/module 列表
├─ hvigorfile.ts                              # 工程级 hvigor 入口（appTasks）
├─ hvigor/hvigor-config.json5                 # hvigor 版本（modelVersion 5.0.0）与执行配置
├─ oh-package.json5                           # 工程级依赖
└─ entry/
   ├─ build-profile.json5                     # 模块级：stageMode、buildOption
   ├─ hvigorfile.ts                           # 模块级 hvigor 入口（hapTasks）
   ├─ oh-package.json5                        # 模块级依赖（核心库本地依赖 TODO 预留）
   └─ src/main/
      ├─ module.json5                         # 模块清单：权限声明 + EntryAbility + VpnExtensionAbility(type: vpn)
      ├─ ets/
      │  ├─ entryability/EntryAbility.ets     # 主 UIAbility：加载 Index 页
      │  ├─ pages/Index.ets                   # 登录页骨架：auth key 输入 / 状态展示 / 连接开关
      │  └─ vpnextensionability/VpnExtensionAbility.ets  # VPN 扩展桩：create→tun fd→核心库对接 TODO
      └─ resources/base/
         ├─ element/string.json, color.json   # 页面文案与配色
         ├─ media/icon.png, startIcon.png     # 占位图标（纯色生成，需替换）
         └─ profile/main_pages.json           # 页面路由表（pages/Index）
```

## 2. 在 DevEco Studio 中导入与构建

1. **环境**：DevEco Studio 5.0+（本工程按 `compatibleSdkVersion: "5.0.0(12)"`、hvigor `modelVersion: 5.0.0` 基线编写）。工程未带签名与构建产物，首次打开让 DevEco 完成 hvigor/npm 同步。
2. **导入**：`File → Open` 选择 `app/` 目录（工程根以 `build-profile.json5` 所在目录为准）。
3. **签名**：`File → Project Structure → Signing Configs` 勾选 Automatically generate（需登录华为开发者账号，用真机调试必须签名）。当前工程 `signingConfigs` 为空，未签名构建仍可通过。
4. **构建**：`Build → Build Hap(s)/APP(s) → Build Hap(s)`；真机运行选 `entry` 模块 `default` target。
5. **若提示无法识别 `"type": "vpn"`**（官方《连接VPN》指南明示的已知问题）：手动在 SDK 的 `toolchains\modulecheck\module.json` 中为 extensionAbilities 的 type 枚举补上 `"vpn"`，然后清除 build 缓存并重启 DevEco Studio。
6. **API 版本**：vpnExtension 模块基线为 API 11（OpenHarmony 文档标注），API 12 兼容版本应可用；若 DevEco 校验器对个别写法报警，优先核对本地 SDK 的 `.d.ts`（`@kit.NetworkKit` / `@ohos.net.vpnExtension`）。

## 3. 权限与受限权限申请

`entry/src/main/module.json5` 当前声明（均为 normal 级、system_grant，安装即授）：

| 权限 | 依据 | 说明 |
|---|---|---|
| `ohos.permission.INTERNET` | OpenHarmony《连接VPN》指南明确要求 | VPN 数据面 + 控制面长轮询必需 |
| `ohos.permission.GET_NETWORK_INFO` | 本工程选用 | UI 展示网络信息用，可删 |

- **VPN 授权不走权限系统**：首次 `vpnExtension.startVpnExtensionAbility()` 由系统弹「VPN 信任授权」对话框；`stopVpnExtensionAbility` 仅允许停止本应用拉起的 VPN。
- **受限/ACL 权限**：本工程**未**声明任何 restricted/ACL 权限。若后续上架 AppGallery 或需要系统级能力（如开机自启、后台保活类权限），需到 AGC 控制台走受限权限申请并提供用途证明——**具体清单未调研、未验证**，按届时官方权限列表执行。
- 已知系统约束（官方文档）：**同一时刻系统仅支持一个 VPN 连接服务**；`VpnConnection.create` 报 2203002 表示已有 VPN 在线，需先 `destroy()` 或提示用户断开其他 VPN。

## 4. 核心库（@ohos-tailscale/*）本地依赖集成

核心库是 `packages/` 下六个 npm workspace TS 包（common 已冻结，crypto/wireguard/noise/control/derp 按架构契约实现）。集成目标：让 `entry/src/main/ets/**` 能 `import` 它们（A29 允许），并遵守 D4（socket/TLS/时钟/随机由 app 侧注入）。**以下方式均未在 DevEco/ohpm 实测**，按优先级试错：

1. **ohpm 本地目录依赖**：在 `entry/oh-package.json5` 的 dependencies 中写 `"@ohos-tailscale/common": "file:../../packages/common"`（预留 TODO 已在文件中）。风险：核心包是 npm workspace 形态（`exports: ./src/index.ts`），ohpm 期望 HAR/HSP 或含 `oh-package.json5` 的模块目录——不匹配则走方案 2/3。
2. **源码并入**：把 `packages/*/src` 拷贝/软链到 `entry/src/main/ets/core/` 下，import 改相对路径或包名别名。注意 P2（包内相对导入带 `.ts` 后缀）与未验证项 U6（ets loader 是否接受 `.ts` specifier——**这是方案 2 的成败点**；若不接受，需在 app 侧加一层 `.ets` 适配文件或批量改写后缀）。
3. **HAR 打包**：用 DevEco 把核心库打成 HAR（可含 `.ts` 源或产物），以本地 HAR 依赖引入（`"lib": "file:./libs/xxx.har"`）。工程化最正规，但打包配置本身也未经验证。

平台注入层（放 `entry/src/main/ets/platform/`，建议新建）：

- `HttpTransport` 实现 → 注入 `control` 包（ts2021 长轮询，`@ohos.net.http`）；
- `Rng`/`Clock` 实现 → `@ohos.security.cryptoFramework` 随机数 + 系统时钟（U7：API 签名未验证）；
- UDP socket 实现 → wireguard 包收发（`@ohos.net.socket`），socket fd 需 `vpnConnection.protect(fd)`；
- DERP TLS 拨号 → derp 包 Dialer 注入。

**Go 核心库备选路径**（与当前纯 TS 路线冲突，仅预留）：若未来改用 Go 编译的 `libtailscale.so`，将其放入 `entry/libs/arm64-v8a/`，经 NAPI 模块（`src/main/cpp/` + CMakeLists + `.d.ts`）封装，把 tun fd 以 `napi_create_int32` 传给 Go 侧接管收发。届时 UI/权限/扩展声明可全部复用。

## 5. 数据面：tun fd 与核心库对接（VpnExtensionAbility 桩内已标 TODO）

官方流程（OpenHarmony《连接VPN》+ `@ohos.net.vpnExtension` API 文档）：

```
UI: vpnExtension.startVpnExtensionAbility(want)          # want = {bundleName, abilityName}
    └─ 首次：系统弹 VPN 授权框 ──同意──▶ VpnExtensionAbility.onCreate(want)
扩展内: conn = vpnExtension.createVpnConnection(this.context)
        conn.create(VpnConfig)  ──Promise<number>──▶  TUN 设备 fd
        conn.protect(socketFd)                        # 核心库自建 UDP socket 防环路
        应用自行读写 fd 收发 IP 包                     # ← 核心库数据面接入点
UI 停止: vpnExtension.stopVpnExtensionAbility(want) ──▶ onDestroy → conn.destroy()
```

- VpnConfig 关键字段（API 文档）：`addresses`(LinkAddress[])、`routes`(RouteInfo[])、`dnsAddresses`、`mtu`（取值 [576,1500]，Tailscale 常用 1280）、`isIPv4Accepted`/`isIPv6Accepted`、`isBlocking`。Tailscale 地址落 CGNAT 段 `100.64.0.0/10`、V6 ULA `fd7a:115c:a1e0::/48`、MagicDNS `100.100.100.100`（见 `packages/common/src/constants.ts`）。
- TS 核心库方案：用 `@ohos.file.fs` 按 fd 读写 IP 包 → wireguard 包 `WgSendSession/WgRecvSession` 加解密 → UDP/DERP 出口；阻塞模型需评估 worker 线程（`isBlocking` 配合）。
- 状态回传：扩展与 UI 可能不同进程，用 commonEventManager 自定义事件（AppStorage 不跨进程）；通知栏常驻状态按官方「VPN 应用的显示体验」要求，列为后续迭代。

## 6. 已知未验证事项（导入后优先核对）

1. **全工程未编译**：无 DevEco/SDK 环境，所有 `.ets/.json5` 未经编译器与打包器检验；ArkTS 写法已按 `docs/arkts-constraints.md` 规避常见禁则，但不保证零报错。
2. **`@kit.NetworkKit` 导入路径**：`VpnExtensionAbility` 基类与 `vpnExtension` 均按 OpenHarmony 官方文档写为 `import { ... } from '@kit.NetworkKit'`（API 11+）；以本地 SDK `.d.ts` 实际导出为准。
3. **`"type": "vpn"` 识别问题**：DevEco/SDK 校验器可能不识别（官方指南明示），处理见 §2 第 5 步。
4. **版本基线假设**：`compatibleSdkVersion: "5.0.0(12)"` 与 hvigor `modelVersion: "5.0.0"` 是保守起点，与你安装的 DevEco 版本可能不匹配（DevEco 打开时按提示升级即可）。`VpnConfig` 部分字段（`vpnId` API 20+、`destroy(vpnId)` API 20+、want.parameters 透传 API 22+）高于基线，本工程未使用。
5. **U6 `.ts` specifier**：ets loader 对 `./x.ts` 导入形态的支持未验证（约束文档 §6-U6），决定核心库集成方案取舍。
6. **`createVpnConnection` 调用时机**：官方文档要求「先 startVpnExtensionAbility 启用 VPN 功能后再调用」，扩展内 `onCreate` 时序已满足，但真机表现未验证。
7. **UI 启停接线**：`startVpnExtensionAbility/stopVpnExtensionAbility` 的 Want 形态按官方示例写（bundleName + abilityName），未真机验证；授权弹窗生命周期与 `createVpnObserver` 监听未接线。
8. **authKey 传递**： Want.parameters 透传仅 API 22+ 支持且不安全，桩内按「Asset Store/preferences 中转」TODO 处理，加密存储 API（Asset Store Kit）未验证。
9. **图标为占位物**：三张 PNG 由脚本生成的纯色图，发布前必须替换（AppScope `app_icon.png` 216×216、entry `icon.png`/`startIcon.png` 96×96）。
10. **bundleName 未定版**：`com.ohostailscale.app` 为占位，正式发布前统一修改（`AppScope/app.json5`、`pages/Index.ets` 的 `BUNDLE_NAME` 两处必须同步）。
11. **平台注入层未实现**：HttpTransport/Rng/Clock/UDP/Dialer 五个注入点仅有 TODO 规划，`@ohos.net.http`、`@ohos.net.socket`、`cryptoFramework` 的具体 API 版本与签名未核对（约束文档 U7）。

## 7. 参考来源

- OpenHarmony 官方文档（raw.githubusercontent.com/openharmony/docs master 分支，2026-09-28 抓取）：
  - 《连接VPN》：`zh-cn/application-dev/network/net-vpnExtension.md`（扩展声明、启停流程、type:vpn 识别问题、单 VPN 限制）
  - API 参考：`zh-cn/application-dev/reference/apis-network-kit/js-apis-net-vpnExtension.md`（start/stop/createVpnConnection/create/protect/destroy、VpnConfig 字段）
  - 基类：`zh-cn/application-dev/reference/apis-network-kit/js-apis-VpnExtensionAbility.md`（onCreate/onDestroy）
- 仓库内：`docs/architecture.md`（D1–D4、注入接口）、`docs/arkts-constraints.md`（ArkTS 禁则与 U 未验证项）。

## 8. 2026-10-01 夜班补记（worker-A：壳工程纯 TS 推进面）

1. **Linux 编译链调研结论**：GPU 机不可编译本壳（商业 SDK 登录墙 + hvigor 无公开分发 + 华为制件仓不可达），完整证据与官方 commandline-tools 路径见 `docs/build-feasibility-linux.md`；§4 的三个集成方案在拿到 DevEco/commandline-tools 环境后按原文验证即可。
2. **`app/tools/validate-shell.mjs`（新增，`npm run validate:shell`）**：壳静态资源离线机检（V1 配置解析/V2 模块清单/V3 权限/V4 页面路由/V5+V5b 资源引用/V6 包名/V7 ability 名/V8 占位图标尺寸），当前 **54 项全过**（exit 0）。本壳全部 .json5/.json 首次经过解析器验证。
3. **`app/bridge/`（新增，`npm run test:bridge` / `npm run typecheck:bridge`）**：壳 ↔ 协议包 mock 集成层（Node 侧，确定性测试 7 用例全绿）：
   - `MockHttpTransport`：common 冻结接口 HttpTransport 的脚本化 mock（真机实现按 §4 替换）；
   - `MockControlPlane`：ts2021 假控制面（noise 包 NoiseIkResponder 承载，IK 握手/注册解码/netmap 下发）；
   - `ShellControlSession`：壳会话门面（装配 fail-fast、login/pollMap/statusSnapshot/close）；
   - `shell-status.ts`：UI 三态与 Index.ets `ConnState` 常量逐值镜像（测试锁定）；
   - **authKey 纪律**：只做形状校验、永不进请求体/URL/日志（测试对全部请求留痕做字节级断言）、close 清内存；真实注册上行承载属 AU 上游核对项（docs/architecture.md §10）。
4. 已知边界如实：bridge 不覆盖数据面（UDP/DERP/protect(fd)，待二期接口定稿）；根 tsconfig 仍 exclude app/（六包 typecheck 面不变），bridge 用独立 `app/bridge/tsconfig.json`（同 strict 基线）。
