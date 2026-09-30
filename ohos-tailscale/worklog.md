# worklog — ohos-tailscale（append-only：每日做了什么/决策/下一步）

- 2026-10-01 迁移完成：windev-01 .zcode/workspace/default/ohos-tailscale → anolis-gpu-01:/opt/gpumachine/projects/ohos-tailscale（线1-2B 迁移批；sha256=1a4af1cf 两端核对过；验证：npm test **238 pass / 0 fail**，Node v22.23.2）。接续卡：continue-cards/ohos-tailscale.md。下一步：git 化（.gitignore 已预留）+ AU/CU 未验证项 + DevEco 环境裁定。

- 2026-10-01 夜班 worker-A（编译链与壳工程）：① git 化核对：仓库已 git 化（main，4 commits，working tree clean，前轮完成），本轮变更前复跑基线 **npm test 238 pass / 0 fail exit 0**。② Linux 编译链调研：GPU 机实测网络探测（repo.huawei.com/mirrors.openharmony.cn 不可达；developer.huawei.com 可达但 commandline-tools/SDK 需账号登录；@ohos/hvigor 不在 npmjs/npmmirror/ohpm 任何可达 registry；huaweicloud 镜像仅有开源 OpenHarmony SDK，与本壳 runtimeOS:HarmonyOS 不同 runtime 且不含 hvigor）→ **结论：GPU 机不可编译 app/ 壳，证据成文 docs/build-feasibility-linux.md，未硬闯登录墙**。③ 纯 TS 推进：新增 `app/tools/validate-shell.mjs`（壳静态资源机检 V1-V8，**54 pass/0 fail exit 0**，壳全部 .json5/.json 首次过解析器验证）+ `app/bridge/`（壳↔协议包 mock 集成层：MockHttpTransport/MockControlPlane/ShellControlSession/shell-status，**测试 7 pass/0 fail exit 0，typecheck exit 0**；authKey 明文零传输面有字节级断言）。root package.json 增量脚本 test:bridge/typecheck:bridge/validate:shell（test/typecheck 原样）；README-app.md 新增 §8 补记。收尾全量复验：npm test **238 pass / 0 fail exit 0**、根 typecheck exit 0（GPU 首次复验通过）。遗留：数据面注入（UDP/Dialer/protect）待二期接口；真编译需 owner 裁定带账号机器。

- 2026-10-01 夜班（worker-B · 协议完善，DELIVERY_REPORT §3.2 二期范围三面落地）：
  - 考古：db.sqlite（mode=ro）两个 ohos-tailscale 子代理会话（derp AU2 测试重写、ArkTS linter 清零）确认无新增未登记规划；本轮范围按 DELIVERY_REPORT §3.2 未实现清单（#5 netcheck / #6 disco / Cookie Reply 预留接口）+ §3.4 定为三面。
  - 上游实读（原文归档 docs/upstream/2026-10-01-phase2/，jsdelivr/datatracker/rfc-editor）：tailscale disco/disco.go + types/key/disco.go、net/stun/stun.go、wireguard-go device/cookie.go + noise-protocol.go + constants.go、draft-irtf-cfrg-xchacha-03、RFC 5769。
  - 新增面 1（crypto）：xchacha.ts = HChaCha20 + XChaCha20-Poly1305，draft-irtf-cfrg-xchacha-03 §2.2.1 向量与附录 A.1 全 KAT 锚定（期间纠正一处凭记忆写错的外部向量——以实拉原文为准）。
  - 新增面 2（wireguard）：cookie-reply.ts = Cookie Reply（type=3）64B 编解码 + 响应端 WgCookieResponder（R_m 120s 轮换/τ=Mac(R_m,src)/XChaCha20 密封 AAD=MAC1）+ 发起端 WgCookieReplyConsumer（ConsumeReply 语义）+ verifyMac2，收口一期"响应端 cookie 派发留二期"预留；transport.ts 对 type=3 的 BAD_TYPE 分发保持原样（UDP 收发环集成另轮做，不破 238 基线）。
  - 新增面 3（disco 新包）：disco.go 上游对齐——wrapper（"TS💬" + 发端公钥 + nonce + secretbox）与 Ping/Pong/CallMeMaybe 编解码（宽松解析语义逐条保留）；0x04–0x09 UDP relay 家族如实标注二期；tweetnacl 互开互验 + 共享密钥与 box.before 逐字节一致。
  - 新增面 4（netcheck 新包）：stun.go 上游对齐——Binding Request（SOFTWARE="tailnode" + FINGERPRINT CRC32-IEEE^"STUN"）、Response/ParseResponse（XOR-MAPPED 优先 MAPPED 回退）、StunTransaction（Rng/Clock 注入）；RFC 5769 §2.2/§2.3 官方向量锚定；引擎调度（端点枚举/端口映射协议）留二期。
  - 验证：`npm test` → **273 pass / 0 fail**（238 基线全绿未动，新增 35）；分包 40/35/39/53/44/41/13/8；`npm run typecheck` → 0 错误；退出码均 0。
  - 决策：不接线 transport 分发；disco relay 家族与 netcheck 引擎调度、DERP 随机选节点、netmap→WG 推导留下一轮（如实未做）。
