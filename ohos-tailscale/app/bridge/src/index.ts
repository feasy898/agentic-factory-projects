/**
 * app/bridge 公开入口（壳侧 TS 桥）。
 *
 * 三块：
 * - mock 注入层：MockHttpTransport（脚本化 HttpTransport）+ MockControlPlane（ts2021 假控制面）；
 * - 壳状态模型：ShellSessionState/ShellConnState/ShellStatus（Index.ets ConnState 镜像）；
 * - 壳会话门面：ShellControlSession（装配校验 + login/pollMap/statusSnapshot/close + authKey 纪律）。
 * 真机实现（@ohos.net.http/@ohos.net.socket/cryptoFramework 包装）按 README-app.md §4 替换 mock 即可。
 */

export {
  MockBodyStream,
  MockHttpTransport,
  type MockRoute,
  type MockRouteHandler,
  type MockRouteParams,
} from './mock-http-transport.ts';

export { MockControlPlane } from './mock-control-plane.ts';

export {
  buildDetail,
  idleStatus,
  ShellConnState,
  ShellSessionState,
  uiConnStateOf,
  type ShellConnStateE,
  type ShellSessionStateE,
  type ShellStatus,
} from './shell-status.ts';

export { ShellControlSession, type ShellSessionParams } from './shell-session.ts';
