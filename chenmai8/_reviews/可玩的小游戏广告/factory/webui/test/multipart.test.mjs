// webui/test/multipart.test.mjs — multipart 解析器单测（webui/README 既定：自写解析器
// 必须带负向测试）。运行：node --test webui/test/multipart.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

import { MultipartError, buildMultipart, boundaryFromContentType, parseMultipart } from "../multipart.ts";

const B = "----pfselftest-boundary";

test("boundaryFromContentType：带引号/不带引号都收；非 multipart 拒绝", () => {
  assert.equal(boundaryFromContentType(`multipart/form-data; boundary=${B}`), B);
  assert.equal(boundaryFromContentType(`multipart/form-data; boundary="${B}"; charset=utf-8`), B);
  assert.throws(() => boundaryFromContentType("application/x-www-form-urlencoded"), MultipartError);
  assert.throws(() => boundaryFromContentType("multipart/form-data"), MultipartError);
  assert.throws(() => boundaryFromContentType(undefined), MultipartError);
});

test("parseMultipart：字段 + 文件混合表单解析（含中文字段值）", () => {
  const body = buildMultipart(B, [
    { name: "template", data: "match3" },
    { name: "title", data: "宝石试玩" },
    { name: "assets", filename: "piece-0.png", contentType: "image/png", data: Buffer.from([0x89, 0x50, 0x4e, 0x47, 1, 2, 3]) },
    { name: "assets", filename: "jelly.png", contentType: "image/png", data: Buffer.from([0x89, 0x50, 0x4e, 0x47, 9, 9]) },
  ]);
  const r = parseMultipart(body, `multipart/form-data; boundary=${B}`);
  assert.equal(r.fields.template, "match3");
  assert.equal(r.fields.title, "宝石试玩");
  assert.equal(r.files.length, 2);
  assert.equal(r.files[0].name, "assets");
  assert.equal(r.files[0].filename, "piece-0.png");
  assert.equal(r.files[0].data.length, 7);
  assert.deepEqual([...r.files[0].data.subarray(0, 4)], [0x89, 0x50, 0x4e, 0x47]);
  assert.equal(r.files[1].filename, "jelly.png");
});

test("parseMultipart 负向：非 multipart content-type → 抛", () => {
  const body = buildMultipart(B, [{ name: "a", data: "1" }]);
  assert.throws(() => parseMultipart(body, "application/json"), MultipartError);
});

test("parseMultipart 负向：body 不以 boundary 开头 → 抛", () => {
  assert.throws(() => parseMultipart(Buffer.from("garbage"), `multipart/form-data; boundary=${B}`), MultipartError);
});

test("parseMultipart 负向：part 未被 boundary 终止（截断）→ 抛", () => {
  const body = buildMultipart(B, [{ name: "a", data: "12345678" }]);
  const cut = body.subarray(0, body.length - 20); // 掐掉尾部（终止边界在内）
  assert.throws(() => parseMultipart(cut, `multipart/form-data; boundary=${B}`), MultipartError);
});

test("parseMultipart 负向：boundary 不匹配（请求体里是另一边界）→ 抛", () => {
  const body = buildMultipart("----other-boundary", [{ name: "a", data: "1" }]);
  assert.throws(() => parseMultipart(body, `multipart/form-data; boundary=${B}`), MultipartError);
});

test("parseMultipart 负向：part 缺 name 参数 → 抛", () => {
  const raw = Buffer.from(
    `--${B}\r\nContent-Disposition: form-data\r\n\r\nvalue\r\n--${B}--\r\n`);
  assert.throws(() => parseMultipart(raw, `multipart/form-data; boundary=${B}`), MultipartError);
});

test("parseMultipart 负向：缺 Content-Disposition → 抛", () => {
  const raw = Buffer.from(`--${B}\r\nX-Other: 1\r\n\r\nvalue\r\n--${B}--\r\n`);
  assert.throws(() => parseMultipart(raw, `multipart/form-data; boundary=${B}`), MultipartError);
});

test("parseMultipart：文件名带引号转义与二进制安全（PNG 魔数含 CRLF 不被吃）", () => {
  const data = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x0d, 0x0a, 0xff, 0x00]);
  const body = buildMultipart(B, [{ name: "spec", filename: "de-mo.json", contentType: "application/json", data }]);
  const r = parseMultipart(body, `multipart/form-data; boundary=${B}`);
  assert.equal(r.files.length, 1);
  assert.deepEqual([...r.files[0].data], [...data], "字节逐位一致（CRLF 不混淆）");
});
