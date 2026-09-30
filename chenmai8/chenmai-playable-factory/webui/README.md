# webui/ — M10 网页壳（**已落地**，成品件）

node:http 单进程（FastAPI→node:http）；API 形状对齐（health/meta/build/jobs/qr/静态/负向 400）；
multipart 自写最小解析器并加负向测试（webui/test/multipart.test.mjs）；防 SSRF 纪律照抄
（零出站请求；质检是裁判；landingUrl 只做格式校验从不访问）。

## 用法

```bash
npm run webui                        # node webui/app.ts（默认 --host 0.0.0.0 --port 8788）
node webui/app.ts --port 8788        # 显式端口；浏览器开 http://<LAN-IP>:8788/
npm run test:webui                   # node webui/selftest.mjs（端到端：起服→两种构建→轮询 done→
                                     #   链接/二维码/渠道包逐个 200 + 负向 400；约 100s）
npm run typecheck:webui              # tsc strict
```

## 形状（oracle webui/app.py + specgen.py 同构移植）

- `GET /`：单页操作台（webui/static/index.html，零外链；选模板/传 PNG/填文案或直接传 spec）。
- `GET /api/health`、`GET /api/meta`（3 模板 × 7 语言缺省文案 + 槽位表）、
  `GET /api/jobs`、`GET /api/jobs/<id>`、`GET /api/jobs/<id>/qr.png`、
  `POST /api/build`（双模式：上传 spec JSON【sprites 同键覆盖】或纯表单组装）、
  `GET /artifacts/webui/<id>/...`（任务产物静态伺服，防目录穿越）。
- 表单组装（specgen.ts）：match3 seed 经 `@pf/spec` 不变式预检 I3（不可行自动换 seed）、
  pullpin orderSolution 由 `pullpinLevelRoles` 实算 + `pullpinSimulate` 复核 I1——
  校验算法只此一份权威实现（不复制）；组装后仍过 schema+不变式双校验。
- 任务：内存 + `artifacts/webui/<id>/job.json` 落盘；make 子进程串行（promise 链信号量，
  防质检资源互踩）；超时 900s；done 时以本服务 LAN URL 重出二维码（qrcode 本地生成）。
- 模板入表口径与 oracle 原状一致：match3/merge/pullpin 三模板；**sort 未入表**
  （oracle README 预留栏原文"待 specgen 注册后开放"——factory 如实登记同缺口，见根 README 预留/未做）。

## eval（双交付之二；真实执行 exit 0）

```bash
node --test webui/test/multipart.test.mjs webui/test/specgen.test.mjs
# multipart 8 件（负向：截断/坏边界/缺 name/缺 disposition/二进制安全）+ specgen 9 件
# （组装即过校验/I3 预检含死局 seed=13924 实测/pullpin 实算复核/负向表单）——已并入 npm test
npm run test:webui    # 2026-09-30 实测：30 断言全过 exit 0，99.0s
```
