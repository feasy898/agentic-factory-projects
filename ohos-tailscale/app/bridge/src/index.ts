/**
 * app/bridge 公开入口（壳侧 TS 桥）。
 *
 * 五块：
 * - mock 注入层：MockHttpTransport（脚本化 HttpTransport）+ MockControlPlane（ts2021 假控制面）；
 * - mock 数据面：UdpDatagramBus（确定性 mock UDP + NAT 仿真）+ MockStunServer（STUN Binding 服务端）；
 * - 壳状态模型：ShellSessionState/ShellConnState/ShellStatus（Index.ets ConnState 镜像）；
 * - 壳会话门面：ShellControlSession（装配校验 + login/pollMap/statusSnapshot/close + authKey 纪律）；
 * - 壳发现面：ShellDiscoClient（disco Ping/Pong/CallMeMaybe 打洞会话）+ ShellStunProbe（STUN 公网映射探测）。
 * 真机实现（@ohos.net.http / @ohos.net.socket + protect(fd) / cryptoFramework 包装）按 README-app.md §4 替换 mock 即可。
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
  mapIp16FromV4,
  MockStunServer,
  parseEndpoint,
  UdpDatagramBus,
  UdpSocket,
  type EndpointParts,
  type UdpInbound,
  type UdpSocketParams,
} from './mock-udp-bus.ts';

export {
  ShellDiscoClient,
  ShellDiscoEventKind,
  ShellStunProbe,
  type ShellDiscoClientParams,
  type ShellDiscoEvent,
  type ShellDiscoEventKindE,
  type ShellStunProbeParams,
  type ShellStunResult,
} from './shell-discovery.ts';

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
