// pf/src/qr.ts — 二维码 PNG 本地生成（oracle qrcode 库同参数宿主移植：qrcode npm 包）。
//
// 契约 §5：二维码内容 = LAN 可达的预览 HTML 的 http URL（127.0.0.1 手机扫不出）。
// 参数对齐 oracle：border=2（margin）、box_size=6（scale）、纠错 M、黑字白底。
// 决策 §1.1(a) 预declare 的新增 npm 依赖（演示机 npm ci 离线包覆盖）。

import { toFile } from "qrcode";

export function writeQrPng(content: string, path: string): Promise<void> {
  return toFile(path, content, {
    errorCorrectionLevel: "M",
    margin: 2,
    scale: 6,
    color: { dark: "#000000", light: "#ffffff" },
  }).then(() => undefined);
}

/** 控制台 ASCII 二维码（oracle qr.print_ascii(invert=True) 同位；人读不锁字节）。 */
export async function printQrAscii(content: string): Promise<void> {
  const { create } = await import("qrcode");
  const qr = create(content, { errorCorrectionLevel: "M" });
  const modules = qr.modules;
  const rows: string[] = [];
  // invert=True：亮底暗块；上下各留 border=2 模块白边由 margin 已含在 modules 外？
  // qrcode npm 的 create() 不含 margin——手动补 2 行/列白边（对齐 oracle border=2）。
  const border = 2;
  const width = modules.size + border * 2;
  const line: string[] = new Array<string>(width).fill("\u001b[7m  \u001b[0m");
  rows.push(line.join(""));
  rows.push(line.join(""));
  for (let y = 0; y < modules.size; y++) {
    const row: string[] = ["\u001b[7m  \u001b[0m", "\u001b[7m  \u001b[0m"];
    for (let x = 0; x < modules.size; x++) {
      const dark = Boolean(modules.data[y * modules.size + x]);
      // print_ascii(invert=True)：暗模块打印两个空格（反白），亮模块打印 "▉▉"。
      row.push(dark ? "\u001b[7m  \u001b[0m" : "▉▉");
    }
    row.push("\u001b[7m  \u001b[0m", "\u001b[7m  \u001b[0m");
    rows.push(row.join(""));
  }
  rows.push(line.join(""));
  rows.push(line.join(""));
  console.log(rows.join("\n"));
}
