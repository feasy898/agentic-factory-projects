# M10 网页壳（webui，浏览器操作台）

> 状态：**已落地**（2026-09-30 成品切换批次）。规格源 = oracle 仓 `webui/`（app.py +
> specgen.py + static/index.html + selftest.py，无独立 spec 文档——本页为 factory 落位
> 改写：行为契约 + 宿主差异登记）。实现于 `webui/`；用法详见 [webui/README.md](../../webui/README.md)。

## 1. 职责与 API 形状（oracle app.py 语义移植，FastAPI→node:http）

浏览器单页（零外链）→ 选模板 / 传 PNG / 填文案（或直接上传 spec JSON）→ `POST /api/build`
组装 PlayableSpec（specgen）→ 后台子进程跑 `node pf/pf.mjs make`（真实流水线：校验→模板
构建→打包→qacore 自动试玩质检）→ 状态轮询 → 二维码（本服务 LAN URL）+ 质检报告 + 渠道包
下载（`/artifacts/webui/<id>/...` 静态挂载伺服）。

| 路由 | 行为 |
|---|---|
| `GET /` | 单页操作台（零外链；selftest 有零外链断言） |
| `GET /api/health` | `{status:"ok", time}` |
| `GET /api/meta` | 3 模板（label+槽位表）/ 7 语言 / 全量缺省文案表 / 渠道 / landingUrl 缺省 |
| `POST /api/build` | 双模式：上传 spec JSON（sprites 同键覆盖）或纯表单组装；坏 JSON/未知模板/超限 → 400 |
| `GET /api/jobs`、`/api/jobs/<id>` | 任务列表/详情（内存 + `artifacts/webui/<id>/job.json` 落盘） |
| `GET /api/jobs/<id>/qr.png` | 任务二维码（未产出 404） |
| `GET /artifacts/webui/<id>/...` | 任务产物伺服（防目录穿越；MIME 表有限集） |

纪律（照抄 oracle）：零出站请求（防 SSRF——landingUrl 只做 http/https 格式校验从不访问；
二维码 qrcode 包本地生成；LAN 地址探测复用 pf 的 UDP-connect lanIp）；质检是裁判
（make 有 fail 即任务失败，不产出二维码）；任务串行（oracle 线程信号量 → promise 链）；
超时 900s 如实记失败；done 时以本服务 LAN URL 重出二维码覆盖 make 的占位端口版
（参数对齐：纠错 M / border 2 / scale 6）。

## 2. 表单组装器（specgen.py → specgen.ts）

- 文案：每语言内置可改缺省（与 specs-eval golden 字符串表同源）；任意键留空回退缺省，
  I5（每语言五键齐全）恒可满足。
- seed：留空随机（`crypto.randomInt(0, 2^31)`）；match3 经 `@pf/spec` 不变式
  `match3Board`/`match3FindMove` 预检 I3（初始盘面存在可行步），不可行自动换 seed、
  指定不合规则 400。
- pullpin：orderSolution 由 `pullpinLevelRoles` 实算（中性针升序在前 + 救援针收尾），
  `pullpinSimulate` 复核 I1——校验算法单源在 `@pf/spec`，本模块不复制；组装后仍过
  schema+不变式双校验（双保险）。
- projectId 清洗为 `^[a-z0-9][a-z0-9-]{0,63}$`（洗空回退 `webui-<模板>`）；
  landingUrl 仅 http/https 且无空白（≤512）。
- 模板入表口径与 oracle 原状一致：match3/merge/pullpin；**sort 未入表**（oracle README
  预留栏原文"待 specgen 注册后开放"——登记于根 README 预留/未做）。

## 3. 宿主差异登记（语义冻结、宿主移植）

1. FastAPI/uvicorn → `node:http` 单进程；multipart 自写最小解析器（`multipart.ts`，
   负向测试钉死：截断/坏边界/缺 name/缺 disposition/二进制安全），并同收
   `application/x-www-form-urlencoded` 纯表单（FastAPI Form 同形，oracle 负向测试
   的 httpx data= 即此形态）。
2. 后台线程 → make detached 子进程 + promise 链串行；job 状态内存 + job.json 落盘。
3. `pfcore make` → `node pf/pf.mjs make … --no-serve`（产物统一由本服务挂载伺服）。
4. 错误响应体形状保持 FastAPI 风：`{"detail": <string | {errors: string[]}>}`。

## 4. eval（双交付之二；真实执行 exit 0）

- 单测：`node --test webui/test/multipart.test.mjs webui/test/specgen.test.mjs`
  （8 + 9 件，含 I3 死局 seed=13924 实测拦截、pullpin 实算复核、负向表单）——并入 `npm test`。
- 端到端：`npm run test:webui`（oracle `python -m webui.selftest` httpx 语义 → node:fetch）：
  2026-09-30 实测 30 断言全过 exit 0（99.0s）——两种构建模式各自 done、质检 0 fail、
  自动试玩 win=true、预览/汇总/报告/流水线链接与二维码逐个 200、3 渠道包逐个 200、
  坏 JSON 与未知模板 400、单页零外链。
