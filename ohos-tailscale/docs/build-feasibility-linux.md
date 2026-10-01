# Linux 侧鸿蒙编译链可行性调研（app/ 壳编译）

> 2026-10-01 夜班 · worker-A（线1 编译链与 git 化）
> 结论：**GPU 机（anolis-gpu-01）当前不可编译本壳工程**；官方无 GUI 路径存在但被「商业 SDK 登录墙 + 私有 hvigor 仓库」双重卡住。
> 本文只记录已核实事实与证据，所有网络探测均于 2026-10-01 在 GPU 机实跑（curl 退出码/状态码为证）。

## 1. 官方无 GUI 构建路径（文档核对）

HarmonyOS NEXT（API 12+）官方支持无 DevEco Studio 的命令行构建，载体是 **Command Line Tools**（Linux 版存在，推荐 5.1.0 Release+）：

- 组成：hvigor（构建）、ohpm（包管理）、hdc、codelinter、**sdkmgr**（SDK 下载器）；自带 Node.js（`command-line-tools/tool/node`）。
- 用法：解压后配 `DEVECO_SDK_HOME`/`PATH` → 工程内 `hvigorw assembleHap`（或 hvigor CLI）出 HAP；SDK 用 `sdkmgr` 拉取。
- **获取渠道**：华为开发者联盟 developer.huawei.com「资源下载」（**需登录华为开发者账号**）；开源侧无完整镜像。
- 参考来源（web 检索 2026-10-01）：华为开发者社区文档「如何解决搭建流水线时 commandline-tools-linux 中 sdkmgr 下载开发包报错」；OpenHarmony SIG 指引（gitcode.com/openharmony）。

本工程匹配基线：`compatibleSdkVersion: "5.0.0(12)"` + hvigor `modelVersion: 5.0.0`（app/build-profile.json5、app/hvigor/hvigor-config.json5）；未签名构建（signingConfigs 空）官方允许出未签名 HAP（app/README-app.md §2 第 3 步）。

## 2. GPU 机网络实测（2026-10-01，curl -sI 状态码）

| 端点 | 结果 | 含义 |
|---|---|---|
| `https://registry.npmjs.org/@ohos%2fhvigor` | `{"error":"Not found"}` | **@ohos/hvigor 不在公共 npm**（hvigor-ohos-plugin 同样 Not found） |
| `https://registry.npmmirror.com/@ohos%2fhvigor` | 404 | 国内 npm 镜像同样没有 |
| `https://ohpm.openharmony.cn/` | 200 | 可达，但只发三方库（搜索 API 未收录 hvigor） |
| `https://developer.huawei.com/` | 200 | 可达，但 commandline-tools/SDK 下载需账号登录 |
| `https://repo.huawei.com/` | 000（连接失败） | 华为制件仓整域不可达 |
| `https://mirrors.openharmony.cn/` | 000（连接失败） | OpenHarmony 官方镜像不可达 |
| `https://repo.huaweicloud.com/harmonyos/os/` | 200 | **可达**：仅开源 OpenHarmony 发行物（见 §3） |
| `https://ci.openharmony.cn/` | 502 | 每日构建站不可用 |
| gitee.com / github.com / gitcode.com | 200 | 可达；raw.githubusercontent.com 000 |

npm 全量搜索 `text=hvigor` 仅命中三方插件（如 `@ccgo/hvigor-ohos-plugin`，其宿主 hvigor 仍需官方渠道），无 hvigor 本体。

## 3. 为什么开源 OpenHarmony SDK 不是出路（当前工程形态下）

`repo.huaweicloud.com/harmonyos/os/5.0.0-Release/` 等目录可下载 `ohos-sdk-windows_linux-public.tar.gz`（开源 Full-SDK，含 ets/native/previewer/toolchains），但：

1. **runtime 不同**：本工程 product 声明 `"runtimeOS": "HarmonyOS"`（app/build-profile.json5），目标 API 面（`@kit.NetworkKit` 的 `VpnExtensionAbility`/`vpnExtension`、`@kit.*` 命名空间导入）按商业 HarmonyOS SDK 编写；开源 OpenHarmony SDK 对应 runtimeOS `openharmony`。切 runtime 属产品级变更（含 kit 导入改写、VPN API 面差异核对），需 owner 裁定，不是构建配置小步。
2. **仍缺构建编排器**：开源 SDK 包内无 hvigor（hvigor 只在 commandline-tools/DevEco Studio 内分发）；自手搓「ets_loader + tsc 拼装编译管」等于重写构建系统，属硬闯，不做。
3. 签名工具链（二进制签名工具）社区指引明示只在官方 commandline-tools（Linux 版）里带。

## 4. 结论与卡点（如实）

- **卡点 A（账号墙）**：commandline-tools Linux 版与 HarmonyOS SDK（商业）只能经 developer.huawei.com 登录账号获取（或登录后 sdkmgr 拉取）；当前无凭据，红线禁止硬闯登录墙。
- **卡点 B（网络）**：华为制件仓 repo.huawei.com / mirrors.openharmony.cn 从 GPU 机整域不可达；即使有账号也需先打通出网路由（owner/网络侧裁定）。
- **卡点 C（hvigor 无公开分发）**：`@ohos/hvigor` + `@ohos/hvigor-ohos-plugin` 不在任何可达 registry；唯一来源是 commandline-tools/DevEco 自带。
- **判定**：app/ 壳编译在 GPU 机「不可得」，转纯 TS 推进（README-app.md §4 平台注入层 + §6 未验证项为路线图）。本轮已交付：
  - `app/bridge/`：壳↔协议包 mock 集成层（Node 可跑、确定性测试，见 app/bridge/README.md）；
  - `app/tools/validate-shell.mjs`：壳静态资源离线校验（JSON5 解析 + 资源引用/页面路由/图标尺寸/权限/包名一致性）。
- **owner 裁定项（沿用接续卡）**：真编译需 (1) 有华为开发者账号的机器跑 commandline-tools Linux 版 + sdkmgr，或 DevEco Studio（Win/Mac）；(2) 该机出网可达华为仓。届时按 §1 命令路径验证，无需再调研。

## 5. 本轮试验记录（可复核命令）

```bash
# 状态码探测（GPU 机）
curl -sI -m 8 -o /dev/null -w '%{http_code}\n' https://repo.huawei.com/            # 000
curl -sI -m 8 -o /dev/null -w '%{http_code}\n' https://developer.huawei.com/       # 200
curl -sI -m 8 -o /dev/null -w '%{http_code}\n' https://repo.huaweicloud.com/harmonyos/os/  # 200
curl -s  'https://registry.npmjs.org/@ohos%2fhvigor'        # {"error":"Not found"}
curl -s  'https://registry.npmjs.org/-/v1/search?text=hvigor&size=8'  # 仅三方插件
curl -s https://repo.huaweicloud.com/harmonyos/os/5.0.0-Release/ | grep href   # 仅 ohos-sdk-*-public / code / 设备镜像，无 hvigor/commandline-tools
```

未做任何登录墙绕过、未下载未授权分发物；开源 SDK 未下载（本工程形态下无路径收益，见 §3）。
