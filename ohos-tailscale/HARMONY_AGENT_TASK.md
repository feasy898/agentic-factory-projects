# 鸿蒙电脑 Agent 任务书：构建 HAP + 真机验证（自包含，可独立执行）

> 本文件写给在 **HarmonyOS PC（鸿蒙电脑）** 上工作的 AI agent。你不需要本仓库之外的任何上下文。
> 目标：把 `app/` 工程构建出**可安装的调试 HAP**，装到本机（鸿蒙电脑）跑起来，把过程发现全部回传。
> 全程遇到不确定的事：先查本仓库文档（见 §7 文档索引），再实验验证，把结论写进工作报告——不要猜。

## 0. 你在哪、拿什么

- 本仓库已包含完整源码：`packages/`（六包 TypeScript 协议核心库，Node 侧测试全绿 238/238）、`app/`（HarmonyOS 工程壳，**从未编译过**）、`docs/`（协议取证、ArkTS 约束、架构契约）、`interop/`（真实 headscale 联调脚本，供参考）。
- 控制面/DERP 真实互通已在 x86 环境打通（见 `DELIVERY_REPORT.md` §5），你不需要重复协议联调——**你的战场是把 `app/` 编译出来并跑起来**。
- 克隆方式（匿名只读）：
  ```bash
  git clone http://203.0.113.10:9418/ohos-tailscale.git
  ```

## 1. 环境判定（第一步先做，结论写进报告）

按顺序探测，把每项结果记录到工作报告：

1. **DevEco Studio**：本机是否已装？查 `~/DevEcoStudio*`、应用列表、或 `devecostudio` 命令。鸿蒙电脑原生版 DevEco Studio 目前处于 Beta 阶段（2025-10 起招募）；若已装，记版本号。
2. **若未安装**：尝试从华为开发者站点获取鸿蒙电脑版（Beta）安装包；拿不到就明确报告"需要 Windows 辅助构建"并跳到 §5 的替代路径。
3. **命令行工具链**：`which hdc node npm git hvigor` 逐一检查并记录。有 hdc（HarmonyOS 设备连接器）最好——本机安装 HAP 用它。
4. **本机系统版本**：`param get const.product.software.version`（或设置-关于本机），记录 API 版本。`app/build-profile.json5` 按 `compatibleSdkVersion: "5.0.0(12)"` 手写，若本机 API 更高需调整（这是预期内的首次构建修正项）。

## 2. 首次构建（核心任务）

1. 用 DevEco 打开 `app/`（工程根 = `app/build-profile.json5` 所在目录），让它完成 hvigor/npm/ohpm 同步。命令行等价物：DevEco 内嵌的 `hvigorw`（`app/` 下应有包装脚本；没有就用 DevEco GUI 构建）。
2. **首次构建必然报错**（工程是按官方文档手写的骨架，从未编译）。逐个修：常见问题清单见 `app/README-app.md` §2/§5 与 `docs/arkts-constraints.md`。特别注意：
   - `@kit.NetworkKit` 等导入路径随 API 版本可能变化；
   - `module.json5` 里 `"type": "vpn"` 的识别问题（`app/README-app.md` §2 第 5 步有处理方案）；
   - `compatibleSdkVersion` 与本机 SDK 匹配；
   - **CU6 关键验证点**：`app/entry/src/main/ets/` 里的代码 import 了 `@ohos-tailscale/*` 包（本地 ohpm 依赖指向 `../../packages/`，若无则按 `app/README-app.md` §4 三方案选一个接上）——**hvigor/ets-loader 是否接受 `.ts` 后缀导入符（核心库全是 `import ... from 'xx.ts'`）是全项目最大的未知数**。若报错：在 app 侧加一层 .ets 适配文件（把核心库 API re-export），或把 packages 源码并入工程并把 `.ts` 改 `.ets`（脚本化处理，注意导入后缀同步改）。把结论记下来——这是全仓最想知道的答案之一。
3. **签名**：构建调试 HAP 需要登录华为开发者账号做自动签名（File → Project Structure → Signing Configs → 勾 Automatically generate signature）。若无账号/无权限，构建 unsigned HAP 也可以，安装时用 `hdc install` 或报告受阻点。
4. 产出：`app/entry/build/*/outputs/*/*.hap`。

## 3. 本机安装与冒烟

1. `hdc list targets`（本机设备应出现）；`hdc install <hap>` 或鸿蒙电脑的包管理安装。
2. 启动应用，验证：入口页渲染（auth key 输入框 + 连接开关）、点击连接时弹出 **VPN 授权弹窗**（说明 VpnExtensionAbility 声明被系统识别）。授权后的数据面未接线（桩内有 TODO），弹窗出现即算本阶段成功。
3. 全程截图或抄录关键界面文本，写进报告。

## 4. 核心库验证（若环境允许）

若本机有 Node（没有就尝试包管理器装，装不了就跳过本节）：

```bash
npm install --save-dev typescript@5.9 @types/node tweetnacl   # 在仓库根
node --test "packages/**/*.test.ts"        # 期望 238/238
npx tsc --noEmit -p .                      # 期望零错误
```

ArkTS 官方检查（可选，价值高）：DevEco 的 SDK 里有 ets-loader（`<SDK>/default/openharmony/toolchains/` 或 `ets/build-tools/ets-loader`），内置 ArkTSLinter（华为魔改 TS）。仓库根 `interop/arkts-check.js` + `interop/arkts-mirror.sh` 是 x86 上的独立调用脚本，可在鸿蒙侧参照适配（要点：只扫 .ets、把 packages 镜像成 .ets、用 watch compiler host 触发 afterProgramCreate）。跑通则报告 src 告警数（x86 基线：src=0 / test=321）。

## 5. 替代路径（鸿蒙电脑上装不了 DevEco 时）

- 用一台 **Windows 机器 + DevEco Studio 6.x** 构建（仓库推到 git 后 Windows 侧同样克隆执行 §2），产物 HAP 传回鸿蒙电脑安装。任务书其余步骤不变。
- 报告里说明实际用了哪条路径。

## 6. 结果回传（必须做）

把以下内容写成 `HARMONY_PC_REPORT.md`（放仓库根）：

- §1 环境判定结果（逐项）；§2 构建最终成功/失败 + **修复了哪些文件**（git diff 清单）+ 每个修法的理由；CU6 的最终答案（.ts 导入符能否被 ets-loader 接受）；§3 安装与冒烟结果；§4 测试数字（若执行）；遗留问题清单。

回传通道（按可用性选一）：

1. **git push**（有 hk-gateway SSH 权限时）：`git checkout -b harmony-pc-work && git add -A && git commit -m "harmony-pc build" && git push origin harmony-pc-work`（push URL 用 `ssh://root@203.0.113.10:22/srv/git/ohos-tailscale.git`，端口非 22 则按实际）。
2. **HTTP 收件箱**（无 SSH 时）：
   ```bash
   curl -X POST --data-binary @HARMONY_PC_REPORT.md "http://203.0.113.10:8090/upload/<TOKEN>/HARMONY_PC_REPORT.md"
   ```
   `<TOKEN>` 见克隆来源渠道提供的说明（一次性令牌，仅写不读）。HAP 产物同理上传（文件名带日期）。
3. 都不通：把报告全文直接粘贴给用户。

## 7. 仓库文档索引（遇到问题先查这里）

| 文档 | 内容 |
|---|---|
| `app/README-app.md` | 壳工程：DevEco 导入构建、权限、核心库集成三方案、tun fd 对接、11 项未验证事项 |
| `docs/arkts-constraints.md` | ArkTS 禁则 A1–A36、工程约束 P1–P7、未验证项 CU1–CU10 |
| `docs/architecture.md` | 六包契约 + 上游核对清账（§10.2 AU1–AU4 全部 ✅） |
| `DELIVERY_REPORT.md` §5 | 控制面/DERP 真实互通证据、官方 ArkTS linter 实测（src=0） |
| `docs/oracle/protocol-notes.md` | 真实 tailscale 取证与 12 项部件清单 |

## 8. 边界与红线

- 不要动 `packages/` 六包源码（它们已被真实互通与全量测试锚定；集成问题在 `app/` 侧解决，适配层放 `app/entry/src/main/ets/`）。
- 仓库内不得出现真实密钥/令牌（auth key、签名证书一律不入库）。
- 构建报错的修复优先保"能编译能安装"，协议语义问题记录待议，不要顺手重构协议代码。
