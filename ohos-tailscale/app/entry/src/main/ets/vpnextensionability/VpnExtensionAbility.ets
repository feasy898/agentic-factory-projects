// VpnExtensionAbility（三方 VPN 扩展）—— 桩实现。
//
// 基类与 API 依据（本工程骨架撰写时核对自 OpenHarmony 官方文档 master 分支，基线 API 11+）：
//   - 基类：import { VpnExtensionAbility } from '@kit.NetworkKit'（@ohos.app.ability.VpnExtensionAbility）
//   - API：vpnExtension.createVpnConnection(context) / VpnConnection.create(config) / protect(fd) / destroy()
//   - 生命周期：onCreate(want) / onDestroy()
// 生命周期回调之外的 API 调用为按官方文档重写的骨架流程，未经真机/DevEco 编译验证（见 README-app.md）。
import { Want } from '@kit.AbilityKit';
import { vpnExtension, VpnExtensionAbility as VpnAbilityBase } from '@kit.NetworkKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN: number = 0x0200;
const TAG: string = 'OhosTsVpnExt';

export default class VpnExtensionAbility extends VpnAbilityBase {
  private tunFd: number = -1;
  private vpnConnection: vpnExtension.VpnConnection | null = null;

  onCreate(want: Want): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'VpnExtensionAbility onCreate（系统已获得用户 VPN 授权）');

    // 步骤 1：读取登录信息 ------------------------------------------------------
    // TODO(登录信息)：登录页（pages/Index.ets）在 startVpnExtensionAbility 之前已把 authKey
    // 加密写入 Asset Store Kit / 应用私有 preferences；此处读取并交给核心库。
    // 不要经 want.parameters 透传密钥（want.parameters 透传 API 22 才支持，且有泄露面）。

    // 步骤 2：创建 VpnConnection（须在 startVpnExtensionAbility 已启用 VPN 后调用） ---------
    let conn: vpnExtension.VpnConnection = vpnExtension.createVpnConnection(this.context);
    this.vpnConnection = conn;

    // 步骤 3：构造 VpnConfig 并建立虚拟网卡（create 成功后返回 TUN 设备的文件描述符 fd） -------
    // TODO(核心库对接·控制面)：以下占位参数应由核心库会话状态决定，不要写死：
    //   - addresses：Tailscale 侧分配的本机地址，落在 CGNAT 段（packages/common constants:
    //     CGNAT_V4_CIDR = 100.64.0.0/10；TAILNET_ULA_V6_CIDR = fd7a:115c:a1e0::/48）
    //   - routes：一期可先下 0.0.0.0/0 兜底，再按 netmap 的 PacketFilter 精细化（待 control 包二期）
    //   - dnsAddresses：MagicDNS 用 100.100.100.100（是否接管 DNS 待定）
    //   - mtu：取值范围 [576, 1500]；Tailscale 常用 1280
    //   LinkAddress/RouteInfo 的字段名以随 SDK 的 .d.ts 为准（connection.LinkAddress / connection.RouteInfo）。
    const config: vpnExtension.VpnConfig = {
      addresses: [],        // TODO(核心库对接)：填入 LinkAddress[]（当前为空，真实调用会失败——桩仅示意流程）
      routes: [],           // TODO(核心库对接)：填入 RouteInfo[]
      dnsAddresses: [],     // TODO(核心库对接)：['100.100.100.100']（MagicDNS，可选）
      mtu: 1280,
      isIPv4Accepted: true,
      isIPv6Accepted: false,
      isBlocking: false
    };
    conn.create(config)
      .then((fd: number) => {
        this.tunFd = fd;
        hilog.info(DOMAIN, TAG, 'tun fd = %{public}d', this.tunFd);
        this.handTunFdToCore();
      })
      .catch((err: BusinessError) => {
        // 2203002 = VPN 已存在，需先 destroy()（系统同一时刻仅允许一个 VPN 连接服务）
        hilog.error(DOMAIN, TAG, 'VpnConnection.create error: %{public}s', JSON.stringify(err));
      });
  }

  private handTunFdToCore(): void {
    // 步骤 4：把 tunFd 交给核心库收发 IP 包（官方《连接VPN》：create 返回 fd 后由应用自行读写该 fd）。
    //
    // 方案 A（本仓库主路径，纯 TS/ArkTS 核心库 @ohos-tailscale/*）：
    //   - 数据面：用 @ohos.file.fs 按 fd 轮询读写 IP 包：
    //       读：tunFd → IP 包 → wireguard 包 WgRecvSession.decryptPacket 解密前的对端选择/分发（netmap 驱动）
    //       写：wireguard 包 WgSendSession.encryptPacket 输出 → UDP socket 发往对端/DERP
    //   - 网络出口：核心库不碰 socket（docs/architecture.md D4），UDP/TLS 由本文件所在的 app 侧注入层实现：
    //       HttpTransport 注入 control 包（长轮询）、derp Dialer 注入 derp 包、WG UDP socket 自建；
    //   - 关键：核心库自建的 UDP socket fd 必须调用 conn.protect(socketFd) 防止路由环路
    //     （隧道流量本身不能再被 VPN 虚拟网卡捕获）。
    //   - TODO(工程化)：fs 读写 fd 的同步阻塞方式会卡扩展进程，需评估 worker/线程池 + isBlocking 配置。
    //
    // 方案 B（备选：Go 版核心 libtailscale.so）：
    //   - 以 NAPI 模块封装 .so（entry/libs/arm64-v8a/libtailscale.so + cpp 类型声明），
    //     把 tunFd 经 NAPI 传给 Go 侧（例如 expose tailscale_set_tun_fd(fd: number)），
    //     由 Go 侧接管 fd 读写与 WireGuard 加解密，ArkTS 侧只做生命周期与配置下发。
    //   - 该方案与当前仓库「纯 TS 实现」路线冲突，仅作预留（见 README-app.md「核心库本地依赖集成」）。
    //
    // TODO(状态回传)：连接状态变化经 commonEventManager 自定义事件广播给 UI（AppStorage 不跨进程），
    // 并按官方「VPN 应用的显示体验」要求在通知栏展示连接状态（通知为后续迭代项）。
  }

  onDestroy(): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'VpnExtensionAbility onDestroy');
    // 与 create/protect 配对清理：先通知核心库停止（关闭轮询线程、注销事件），再销毁 VPN 网络。
    // TODO(核心库对接)：通知核心库退出并等待其排空在途包后再 destroy。
    let conn: vpnExtension.VpnConnection | null = this.vpnConnection;
    if (conn !== null) {
      conn.destroy()
        .then(() => {
          hilog.info(DOMAIN, TAG, '%{public}s', 'VpnConnection destroy success');
          this.vpnConnection = null;
          this.tunFd = -1;
        })
        .catch((err: BusinessError) => {
          hilog.error(DOMAIN, TAG, 'VpnConnection destroy error: %{public}s', JSON.stringify(err));
        });
    }
  }
}
