// pages/Index：登录页骨架（auth key 输入 + 连接状态展示 + 连接开关）。
// 启停 VPN 采用官方流程（OpenHarmony《连接VPN》指南 + @ohos.net.vpnExtension API 11+）：
//   开：vpnExtension.startVpnExtensionAbility(want) → 首次弹系统「VPN 信任授权」框 → 授权后 VpnExtensionAbility.onCreate
//   关：vpnExtension.stopVpnExtensionAbility(want)（仅允许停止本应用自己拉起的 VPN）
// 风格遵循 docs/arkts-constraints.md：常量对象替代 enum、显式类型、箭头函数、无解构。
import { Want } from '@kit.AbilityKit';
import { vpnExtension } from '@kit.NetworkKit';
import { promptAction } from '@kit.ArkUI';
import { BusinessError } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN: number = 0x0001;
const TAG: string = 'OhosTsIndex';
const BUNDLE_NAME: string = 'com.ohostailscale.app'; // 与 AppScope/app.json5 的 bundleName 保持一致
const VPN_ABILITY_NAME: string = 'VpnExtensionAbility'; // 与 module.json5 extensionAbilities[].name 保持一致

// 连接状态常量表（docs/arkts-constraints.md A34：禁 enum；按 A18 用「显式 interface + 常量对象」替代）
interface ConnStateE {
  Disconnected: number;
  Connecting: number;
  Connected: number;
}
const ConnState: ConnStateE = { Disconnected: 0, Connecting: 1, Connected: 2 };

// 构造拉起/停止 VPN 扩展的 Want（bundleName 必须与本应用一致，abilityName 为 VpnExtensionAbility 名）
const buildVpnWant = (): Want => {
  const want: Want = {
    deviceId: '',
    bundleName: BUNDLE_NAME,
    abilityName: VPN_ABILITY_NAME
  };
  return want;
};

@Entry
@Component
struct Index {
  @State authKey: string = '';
  @State connState: number = ConnState.Disconnected;
  @State statusDetail: string = '核心库尚未接入，当前仅演示 UI 与系统能力接线';

  private statusText(): Resource {
    if (this.connState === ConnState.Connected) {
      return $r('app.string.status_connected');
    }
    if (this.connState === ConnState.Connecting) {
      return $r('app.string.status_connecting');
    }
    return $r('app.string.status_disconnected');
  }

  private statusColor(): Resource {
    if (this.connState === ConnState.Connected) {
      return $r('app.color.status_connected');
    }
    if (this.connState === ConnState.Connecting) {
      return $r('app.color.status_connecting');
    }
    return $r('app.color.status_disconnected');
  }

  private isBusy(): boolean {
    return this.connState === ConnState.Connected || this.connState === ConnState.Connecting;
  }

  build() {
    Column({ space: 24 }) {
      Text($r('app.string.app_title'))
        .fontSize(28)
        .fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary'))

      // ---- 连接状态展示 ----
      Column({ space: 8 }) {
        Row({ space: 8 }) {
          Circle()
            .width(12)
            .height(12)
            .fill(this.statusColor())
          Text(this.statusText())
            .fontSize(18)
            .fontColor($r('app.color.text_primary'))
        }
        .alignItems(VerticalAlign.Center)

        Text(this.statusDetail)
          .fontSize(13)
          .fontColor($r('app.color.text_secondary'))
      }
      .width('100%')
      .padding(16)
      .borderRadius(12)
      .backgroundColor($r('app.color.card_background'))

      // ---- auth key 输入框 ----
      Column({ space: 8 }) {
        Text($r('app.string.authkey_label'))
          .fontSize(15)
          .fontColor($r('app.color.text_primary'))
        TextInput({ placeholder: $r('app.string.authkey_hint'), text: this.authKey })
          .type(InputType.Password)
          .width('100%')
          .height(44)
          .onChange((value: string) => {
            this.authKey = value;
          })
        // TODO(登录流程)：真实登录应支持两种形态——
        //  a) 一次性 auth key（tskey-auth-...，用后即弃）；b) 持久 node key 登录（核心库 ControlClient）。
        //  密钥持久化走 Asset Store Kit（加密存储），不得明文写 preferences（见 README-app.md）。
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)

      // ---- 连接开关按钮 ----
      Button(this.isBusy() ? $r('app.string.btn_disconnect') : $r('app.string.btn_connect'))
        .width('100%')
        .height(44)
        .fontSize(16)
        .backgroundColor(this.isBusy() ? $r('app.color.btn_secondary') : $r('app.color.brand_primary'))
        .onClick(() => {
          this.onToggleClick();
        })
    }
    .width('100%')
    .height('100%')
    .padding(24)
    .justifyContent(FlexAlign.Center)
    .backgroundColor($r('app.color.page_background'))
  }

  private onToggleClick(): void {
    if (this.isBusy()) {
      this.stopVpn();
      return;
    }
    if (this.authKey.trim() === '') {
      promptAction.showToast({ message: $r('app.string.toast_need_authkey'), duration: 2000 });
      return;
    }
    this.startVpn();
  }

  private startVpn(): void {
    // TODO(authKey 传递)：不要把 authKey 放进 want.parameters——
    // ① 该通道 API 22 才支持在首次启动时透传；② Want 里带密钥有泄露面。
    // 约定：startVpn 前先把 authKey 加密写入 Asset Store / 应用私有 preferences，
    // VpnExtensionAbility.onCreate 再读取（见 VpnExtensionAbility.ets 步骤 1）。
    vpnExtension.startVpnExtensionAbility(buildVpnWant())
      .then(() => {
        this.connState = ConnState.Connecting;
        this.statusDetail = '已发起连接，等待系统 VPN 授权与核心库就绪';
        hilog.info(DOMAIN, TAG, '%{public}s', 'startVpnExtensionAbility success');
      })
      .catch((err: BusinessError) => {
        this.connState = ConnState.Disconnected;
        this.statusDetail = '启动失败，详见日志';
        hilog.error(DOMAIN, TAG, 'startVpnExtensionAbility error: %{public}s', JSON.stringify(err));
        // 已知约束（官方文档）：系统同一时刻仅支持一个 VPN 连接服务；
        // 若已有其他 VPN 在线，此处会收到系统拒绝错误，应提示用户先断开。
      });
  }

  private stopVpn(): void {
    vpnExtension.stopVpnExtensionAbility(buildVpnWant())
      .then(() => {
        this.connState = ConnState.Disconnected;
        this.statusDetail = '已停止（核心库未接入，仅系统侧断开）';
        hilog.info(DOMAIN, TAG, '%{public}s', 'stopVpnExtensionAbility success');
      })
      .catch((err: BusinessError) => {
        hilog.error(DOMAIN, TAG, 'stopVpnExtensionAbility error: %{public}s', JSON.stringify(err));
      });
  }
}
