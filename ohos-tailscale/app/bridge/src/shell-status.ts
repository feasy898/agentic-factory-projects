/**
 * 壳 UI 状态模型 —— app/entry/src/main/ets/pages/Index.ets 的 ConnState 常量表（A34：禁 enum，
 * 显式 interface + 常量对象）在壳侧 TS 桥的等价镜像 + 会话态→UI 态映射。
 *
 * 契约：UI 侧（ArkTS）与桥侧（本包）只通过本文件的数值语义对齐；
 * Index.ets: ConnState = { Disconnected: 0, Connecting: 1, Connected: 2 } —— 本文件逐值断言（见 test）。
 */

/** 会话内部态（比 UI 三态多 Idle/Closed 两个非在线形态）。 */
export interface ShellSessionStateE {
  Idle: number;
  Connecting: number;
  Online: number;
  Closed: number;
}

export const ShellSessionState: ShellSessionStateE = { Idle: 0, Connecting: 1, Online: 2, Closed: 3 };

/** UI 三态（Index.ets ConnState 的镜像；数值必须逐值相等，测试锁定）。 */
export interface ShellConnStateE {
  Disconnected: number;
  Connecting: number;
  Connected: number;
}

export const ShellConnState: ShellConnStateE = { Disconnected: 0, Connecting: 1, Connected: 2 };

/** 一次状态快照（UI 订阅面；detail 为人读文本，真机上经 commonEventManager 广播）。 */
export interface ShellStatus {
  /** 会话内部态（ShellSessionState）。 */
  sessionState: number;
  /** UI 三态（ShellConnState），Index.ets 直接可消费。 */
  uiConnState: number;
  /** 人读明细（peer 数/seq/derp 区域），UI 侧 statusDetail 文本域。 */
  detail: string;
  /** 当前 netmap peer 数（无 netmap 时 0）。 */
  peerCount: number;
  /** 当前 netmap 序号（无 netmap 时 0n）。 */
  seqNo: bigint;
}

/** 会话态 → UI 三态映射（唯一换算点，测试锁定）。 */
export const uiConnStateOf = (sessionState: number): number => {
  if (sessionState === ShellSessionState.Connecting) {
    return ShellConnState.Connecting;
  }
  if (sessionState === ShellSessionState.Online) {
    return ShellConnState.Connected;
  }
  return ShellConnState.Disconnected;
};

/** 组装快照的明细文本（纯函数，无隐藏状态）。 */
export const buildDetail = (peerCount: number, seqNo: bigint, derpRegionIds: number[]): string => {
  const regions: string = derpRegionIds
    .map((r: number): string => String(r))
    .filter((s: string, i: number, arr: string[]): boolean => arr.indexOf(s) === i)
    .join(',');
  return 'peers=' + String(peerCount) + ' seq=' + seqNo.toString() + ' derpRegions=' + regions;
};

/** 空快照（Idle）。 */
export const idleStatus = (): ShellStatus => {
  const status: ShellStatus = {
    sessionState: ShellSessionState.Idle,
    uiConnState: uiConnStateOf(ShellSessionState.Idle),
    detail: 'idle',
    peerCount: 0,
    seqNo: 0n,
  };
  return status;
};
