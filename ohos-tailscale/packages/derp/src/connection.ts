/**
 * derp 包自定义注入接口（架构 §10.1：各包自己的注入接口定义在本包内，不进 common；
 * D4：核心库不碰 socket/TLS —— app/ 侧实现 DerpDialer 完成 TLS 拨号，把连接交给核心库）。
 */

import { type DerpNode } from './region.ts';

/**
 * 一条已建立的 DERP 连接（TLS 之上、面向字节流）。
 * - write：写入任意长度字节块（调用方保证按帧整块写入）；
 * - read：返回新到达的字节块；返回 null 表示对端正常关闭（EOF）；
 *   关闭后再 read 的行为由实现自定（返回 null 或抛 Error）；
 * - close：立即关闭，幂等。
 */
export interface DerpConnection {
  write(data: Uint8Array): Promise<void>;
  read(): Promise<Uint8Array | null>;
  close(): void;
}

/** 拨号器：按目标 DERP 节点建立连接（app/ 侧注入实现）。 */
export interface DerpDialer {
  dial(node: DerpNode): Promise<DerpConnection>;
}
