/**
 * UDP 收包环的报文分发核心（type=1/2/3/4 路由）。
 *
 * 上游对应（wireguard-go master，2026-10-01 实读）：
 * - device/receive.go 的入包类型分发：按首 u32le 类型字段路由握手/传输/Cookie
 *   Reply；未知类型静默丢弃；无法配对的握手报文在负载保护下回 Cookie Reply，
 *   回包的 receiver 字段回显来包 offset 4 的 u32le（来包 sender 索引）。
 * - device/cookie.go：CreateReply（响应端，键=被寻址方静态公钥）/ ConsumeReply
 *   （发起端，按"我已发出的握手 receiver 索引"配对）——本包 cookie-reply.ts 已实现，
 *   本分发器做接线。
 *
 * 骨架边界（如实保留）：
 * - 会话/响应端/发起端三类路由全部经注入函数/路由对象接入（D4 注入面），
 *   生产侧把 WgPeerTable.entryByLocalIndex 等现有结构适配成 lookup 即可，
 *   本类不新建第二份会话注册表。
 * - 握手处理回调优先；未配置握手回调且配置了响应端路由时，按上游 under-load
 *   语义回 Cookie Reply（AAD=来包 MAC1 字段，receiver=来包 sender 索引回显）。
 * - 未知类型静默忽略（handled=false）；<4B 抛 WgProtocolError('BAD_LEN')；
 *   type=4 的解密/反重放异常原样透传（WgRecvSession 自带语义）。
 */

import { ByteReader } from '@ohos-tailscale/common';
import { WgMessageType } from './constants.ts';
import { WgProtocolError } from './errors.ts';
import { type WgRecvSession } from './transport.ts';
import {
  WgCookieReplyConsumer,
  WgCookieResponder,
  cookieReplyDecode,
} from './cookie-reply.ts';

/** 分发结果载体（A2：纯字段 interface；四字段恒有值，未命中路径为 null/false）。 */
export interface WgDispatchResult {
  /** 来包类型（首 u32le 原值）。 */
  msgType: number;
  /** 是否有对应路由消费了该包。 */
  handled: boolean;
  /** type=4 且配对会话时的解密明文（keepalive 为零长度数组）。 */
  plaintext: Uint8Array | null;
  /** type=3 发起端消费成功时的 cookie（16B）。 */
  cookie: Uint8Array | null;
  /** type=1/2 under-load 时生成的 Cookie Reply（64B，调用方负责发送）。 */
  replyPacket: Uint8Array | null;
}

/** 响应端路由：under-load 回 Cookie Reply 所需的全部注入。 */
export interface WgCookieResponderRoute {
  responder: WgCookieResponder;
  /** 本端（响应端/被寻址方）静态公钥——Cookie Reply 加密键输入（cookie-reply.ts 头注）。 */
  responderStaticPublic: Uint8Array;
}

/** 发起端路由：Cookie Reply 消费所需注入。 */
export interface WgCookieConsumerRoute {
  consumer: WgCookieReplyConsumer;
  /** 本端已发出的握手的 receiver 索引（与 reply.receiver 相等才尝试消费）。 */
  awaitedReceiverIndex: number;
  /** 消费成功回调（调用方写 WgCookieCache/驱动重发）。 */
  onCookie(cookie: Uint8Array): void;
}

/** 未命中结果模板。 */
function unhandled(msgType: number): WgDispatchResult {
  const out: WgDispatchResult = {
    msgType: msgType,
    handled: false,
    plaintext: null,
    cookie: null,
    replyPacket: null,
  };
  return out;
}

export class WgPacketDispatcher {
  private transportLookup: ((receiverIndex: number) => WgRecvSession | null) | null = null;
  private handshakeHandler: ((packet: Uint8Array, srcAddr: Uint8Array) => void) | null = null;
  private responderRoute: WgCookieResponderRoute | null = null;
  private consumerRoute: WgCookieConsumerRoute | null = null;

  /** 注册 type=4 的会话查找（生产侧适配 WgPeerTable.entryByLocalIndex）。 */
  public setTransportLookup(lookup: (receiverIndex: number) => WgRecvSession | null): void {
    this.transportLookup = lookup;
  }

  /** 注册 type=1/2 的握手处理回调（优先于 under-load Cookie Reply 路径）。 */
  public setHandshakeHandler(handler: (packet: Uint8Array, srcAddr: Uint8Array) => void): void {
    this.handshakeHandler = handler;
  }

  /** 注册响应端路由（under-load 回 Cookie Reply）。 */
  public setResponderRoute(route: WgCookieResponderRoute): void {
    this.responderRoute = route;
  }

  /** 注册发起端路由（消费 Cookie Reply）。 */
  public setConsumerRoute(route: WgCookieConsumerRoute): void {
    this.consumerRoute = route;
  }

  /** 分发一包。srcAddr 为对端源地址字节（回 Cookie Reply 的 cookie 派生输入）。 */
  public dispatch(packet: Uint8Array, srcAddr: Uint8Array, nowMs: number): WgDispatchResult {
    if (packet.length < 4) {
      throw new WgProtocolError(
        'BAD_LEN',
        'dispatch: packet must be at least 4 bytes, got ' + String(packet.length),
      ) as Error;
    }
    const r: ByteReader = new ByteReader(packet);
    const msgType: number = r.readU32le();

    if (msgType === WgMessageType.TransportData) {
      if (this.transportLookup === null) {
        return unhandled(msgType);
      }
      const rr: ByteReader = new ByteReader(packet);
      rr.readU32le();
      const receiverIndex: number = rr.readU32le();
      const session: WgRecvSession | null = this.transportLookup(receiverIndex);
      if (session === null) {
        return unhandled(msgType);
      }
      const plaintext: Uint8Array = session.decryptPacket(packet);
      const out: WgDispatchResult = {
        msgType: msgType,
        handled: true,
        plaintext: plaintext,
        cookie: null,
        replyPacket: null,
      };
      return out;
    }

    if (msgType === WgMessageType.CookieReply) {
      // 解码校验（64B + type=3）；格式非法向上抛 BAD_LEN/BAD_TYPE（骨架策略：
      // 分发层显式失败优于静默，收包环可自行捕获丢弃）。
      const reply = cookieReplyDecode(packet);
      if (
        this.consumerRoute !== null &&
        reply.receiver === this.consumerRoute.awaitedReceiverIndex
      ) {
        const cookie: Uint8Array | null = this.consumerRoute.consumer.consume(packet);
        if (cookie !== null) {
          this.consumerRoute.onCookie(cookie);
          const out: WgDispatchResult = {
            msgType: msgType,
            handled: true,
            plaintext: null,
            cookie: cookie,
            replyPacket: null,
          };
          return out;
        }
      }
      return unhandled(msgType);
    }

    if (msgType === WgMessageType.HandshakeInitiation || msgType === WgMessageType.HandshakeResponse) {
      if (this.handshakeHandler !== null) {
        this.handshakeHandler(packet, srcAddr);
        const out: WgDispatchResult = {
          msgType: msgType,
          handled: true,
          plaintext: null,
          cookie: null,
          replyPacket: null,
        };
        return out;
      }
      // under-load：无握手处理能力时按上游语义回 Cookie Reply；
      // 回包 receiver = 来包 offset 4 的 sender 索引（receive.go 同位回显）。
      if (this.responderRoute !== null) {
        const rr: ByteReader = new ByteReader(packet);
        rr.readU32le();
        const echoedIndex: number = rr.readU32le();
        const replyPacket: Uint8Array = this.responderRoute.responder.createReply(
          packet,
          echoedIndex,
          this.responderRoute.responderStaticPublic,
          srcAddr,
          nowMs,
        );
        const out: WgDispatchResult = {
          msgType: msgType,
          handled: true,
          plaintext: null,
          cookie: null,
          replyPacket: replyPacket,
        };
        return out;
      }
      return unhandled(msgType);
    }

    // 未知类型：上游静默丢弃
    return unhandled(msgType);
  }
}
