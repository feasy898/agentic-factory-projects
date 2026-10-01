// EntryAbility：应用主 UIAbility。
// 职责：加载登录/控制页 pages/Index；为后续「恢复上次连接状态」预留钩子。
// 编写风格遵循 docs/arkts-constraints.md（显式类型、无解构、catch 不带类型标注等），降低日后 ArkTS 编译摩擦。
import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';

const DOMAIN: number = 0x0000;
const TAG: string = 'OhosTsEntryAbility';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'EntryAbility onCreate');
    // TODO(UI 状态恢复)：从 preferences 读取上次连接状态与（是否已在授权后的）VPN 状态，
    // 用于 Index 页面初始化展示。密钥类信息一律走 Asset Store Kit，不进明文 preferences。
  }

  onDestroy(): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'EntryAbility onDestroy');
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'EntryAbility onWindowStageCreate');
    windowStage.loadContent('pages/Index', (err: BusinessError) => {
      if (err.code) {
        hilog.error(DOMAIN, TAG, 'loadContent failed: %{public}s', JSON.stringify(err));
        return;
      }
      hilog.info(DOMAIN, TAG, '%{public}s', 'loadContent succeeded');
    });
  }

  onWindowStageDestroy(): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'EntryAbility onWindowStageDestroy');
  }

  onForeground(): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'EntryAbility onForeground');
    // TODO(状态回传)：回到前台时刷新连接状态（方案：VpnExtensionAbility 侧经 commonEventManager
    // 广播状态事件，此处订阅后写回 AppStorage，见 README-app.md「状态回传与通知」）。
  }

  onBackground(): void {
    hilog.info(DOMAIN, TAG, '%{public}s', 'EntryAbility onBackground');
  }
}
