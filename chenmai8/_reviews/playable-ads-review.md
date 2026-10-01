上一轮读到质检拦截和网关重试就断了。我补齐 WebSocket 拦截和已提交范围这两处证据，然后给出完整问题清单。Phase 0 的五盏绿灯里，真正跑起来的只有「进程退出码」和「报告里没有 `fail`」。质检被当成唯一裁判，但这条链路上跳过的检查也算通过，外链和静音都有绕过面。结论是：**需修后继续**。模板和 schema 可以接着写，但不能把这次绿灯当作 Phase 1 的质检通过线。

## A. 假绿灯

`llmgw.selftest` 打的是真客户端对本地 HTTP mock，没有把被测客户端换成假对象。弱的是验收门只认退出码，以及质检把 `skip` 当成通过。

- **[high]** `scripts/gate_phase0.py:277` — 门项 5 只把 `status=="fail"` 计为失败，`skip` 全部放行；夹具 `python/qacore/tests/fixtures/mini.html` 没有 `window.PF`、也没有 `--autoplay`，CHK02/04/06/07/10 会跳过，报告仍可全绿。修复：门禁点名 CHK03/08/09 必须为 `pass`，已实现项禁止 `skip`，并加变异样本，每项违规只击中对应 CHK。
- **[high]** `scripts/gate_phase0.py:214` — 门项 4 只要求 `llmgw.selftest` 退出码 0，不核对「6 项 PASS」或 `SELFTEST PASS`；把入口改成 `sys.exit(0)` 也会绿。修复：解析 stdout，断言 6 条 `[PASS]` 且含 `SELFTEST PASS`。
- **[med]** `scripts/gate_phase0.py:134` — 门项 1、2 只要求 `pfcore --help` 和 `packager --help` 退出码 0，不检查帮助文本，也不跑 `validate` / `build`。修复：断言帮助里有子命令名，并各跑一条最小成功命令和一条应失败命令。
- **[med]** `scripts/gate_phase0.py:173` — 门项 3 用 `_vendor/NOTES.md` 里的反引号路径做 `is_file()`，渠道覆盖只看文件名是否含 `_AL.` 这类代号；0 字节文件也能过，zip 内部结构不看。该目录在 `.gitignore` 中，干净克隆无法复现这盏灯。修复：校验最小体积、zip 条目名（google 的 `index.html`、tiktok 的 `config.json`、mintegral 的 `build.js`+`Template.html`），并把清单哈希写进入库的期望文件。
- **[med]** `scripts/gate_phase0.py:81` — 厂商扫描只覆盖 `python/llmgw/**/*.py`，正则是 `openai\.com` 而不是标识符 `openai`；`import openai` 或字符串拼接可以过，`python/requirements.txt:11` 的 `openai==3.19.2` 不在扫描范围。修复：扫整个入库树的依赖声明和 import，对拼接字符串做失败样本。
- **[med]** `python/llmgw/selftest.py:297` — 重试用例只断言「500 之后再请求一次成功」，`backoff=0.05` 且不测量间隔；超时用例在 `selftest.py:311` 把 `max_retries=0`，指数退避分支（`client.py:344`）从未被执行。删掉 `sleep` 自测仍绿。修复：注入假时钟，断言间隔为 `0.8s、1.6s` 且封顶 8s。

## B. qacore 外链与静音

fetch 和 XHR 会进 `page.route("**/*")`，非本机主机名加端口会被 `abort` 并记入 CHK03。WebSocket、Service Worker、WebRTC 不在这条链路上。

- **[high]** `python/qacore/cli.py:116` — 只注册了 `page.route`。Playwright 1.63 的 WebSocket 要走另一套 `page.route_web_socket`（已安装包 `sync_api/_generated.py:10705`），这里没有调用。页面可以 `new WebSocket("wss://外部")` 把数据送出去，CHK03 仍为 pass。修复：导航前 `route_web_socket("**/*")`，握手主机不是本次伺服地址就关闭，并计为外链失败。
- **[high]** `python/qacore/cli.py:129` — `new_context` 没有 `service_workers="block"`。该版本文档写明 Service Worker 拦截的请求不会进入 `page.route`。修复：上下文固定 `service_workers="block"`，再用一个注册了 SW 的夹具证明外链仍失败。
- **[med]** `python/qacore/cli.py:79` — 拦截范围是 HTTP（含 fetch、XHR、script、img、css、媒体、beacon），WebRTC（`RTCPeerConnection`）不经过 route，也无法被 abort。修复：注入探针统计 `RTCPeerConnection` 构造次数，大于 0 则 CHK03 失败。
- **[high]** `python/qacore/checks.py:66` — 没有 `window.PF` 时 CHK04 直接 skip。门禁用的 `mini.html` 无音频、无桥、无 `--autoplay`，静音项根本不执行。无 `AudioContext` 时 `running` 为 0 或 `None`（`checks.py:75` 把 `None` 放行），等于「没声音」自动通过。修复：渠道要求静音时，缺 PF 或探针未安装判 fail；无音频页面改为断言「不存在未静音的媒体元素」，而不是断言缺少 AudioContext。
- **[high]** `python/qacore/autoplay.py:35` — 探针只包了 `AudioContext` / `webkitAudioContext`，不看 `HTMLAudioElement`、`<audio>`、`<video>`、`new Audio()`。`autoplay.py:171` 在第一次循环采样后就不再更新，稍后才 `resume()` 或 `play()` 的声音采不到。修复：同样包住媒体元素的 `play`，直到第一次 pointer 之前每轮重采样。

## C. llmgw 密钥与重试

指数退避**已经写了**：`client.py:344` 为 `backoff * 2^attempt`，封顶 8 秒。缺的是测试锁，以及 429 和超时路径上的放大。

- **[med]** `python/llmgw/client.py:351` — 正常日志和异常文本没有拼接密钥；`raise ... from None` 也去掉了异常链。密钥仍在 `_post` 的帧局部变量 `headers["Authorization"]` 和 `self.api_key` 里，打开 locals 的错误上报会带走。`client.py:200` 把错误响应体前 200 字节原样放进 `LLMError`，上游若回显密钥就会进 `.summary()`。修复：`__repr__` 脱敏，错误体先抹掉 `Bearer` / key，再加一条「summary 与 traceback 文本不得含密钥」的自测。
- **[med]** `python/llmgw/client.py:50` — 429 与 5xx 一样按固定退避重试，不读 `Retry-After`；同一密钥换备用模型时立即再打（模型之间没有间隔）。一次限流最多变成 `模型数 × (max_retries+1)` 次连打。超时只停客户端读，服务端工作不取消，重试会叠加上游负载。修复：429 遵守 `Retry-After` 且同密钥全模型共享冷却；超时重试加抖动，并设单次调用的总尝试上限。
- **[low]** `python/llmgw/client.py:356` — 使用默认 `urlopen`，跟随重定向。Python 3.12 对跨主机重定向会去掉 `Authorization`，同主机重定向仍会带上密钥，且没有测试。修复：自写 opener，任何重定向都不转发 `Authorization`。

## D. Windows

当前 Python 代码没有 `cv2`。现有路径走 `pathlib`、带 `encoding="utf-8"` 的 `open`、PIL 和 Node 的 Unicode 文件 API，仓库所在的中文目录不会踩 `cv2.imread` 那条 ANSI 旧坑。

- **[med]** `scripts/gate_phase0.py:113` — 子进程超时用 `subprocess.run` 的 `kill()`。Windows 上这是 `TerminateProcess`，只杀直接子进程，不杀进程树。qacore 拉起的 Playwright driver 和 Chromium 会留下，继续占调试端口和临时目录。修复：用 Job Object 启动门禁子进程，超时杀整棵树；qacore 在 `finally` 里按 pid 再清一次浏览器。
- **[low]** `python/qacore/server.py:19` — `allow_reuse_address = True` 在 Windows 上允许绑到仍被占用的端口。默认端口 0 所以门禁碰不到；一旦 `--port` 写死，残留进程会让新伺服偷偷接到旧连接。修复：固定端口时先探测拒绝占用，或关掉 `SO_REUSEADDR`。
- **[low]** `python/qacore/__main__.py:14` — qacore 和 llmgw 没有像 pfcore 那样把 stdout 改成 UTF-8。门禁给子进程设了 `PYTHONUTF8=1`，直接在代码页不是 UTF-8 的管道里跑中文输出仍可能 `UnicodeEncodeError`。修复：两个入口启动时同样 `reconfigure(encoding="utf-8")`。

## E. 公开仓库卫生

入库的 `package.json`、注释和 `python/llmgw` 源码里没有 `smoud`、`playable-sdk`、`Phaser`、`Kenney`、`Qwen` 这些名字。`_vendor/NOTES.md` 里有，但该目录被 gitignore。引擎包是把名字替换掉之后提交的，MIT 声明一并去掉了。

- **[med]** `python/requirements.txt:11` — 公开依赖钉了 `openai==3.19.2`，而 llmgw 声明只使用标准库。这是厂商包名，且不在门项 4 的扫描里。修复：确认无 import 后从 requirements 删除；网关继续只用 urllib。
- **[med]** `packages/templates/tmpl-match3/README.md:40` — 引擎单文件用 `--legal-comments=none` 再做标识符替换后提交。名字扫不到，MIT 要求保留的版权与许可声明也不在文件里。修复：在 `engine.js` 旁提交原始版权与 MIT 全文，保留上游包名与版本；公开前的扫描改为「禁止未声明的依赖」，而不是「禁止出现上游名字」。
- **[low]** `README.md:12` — 正文写了「Cocos 工程接入」。这不在法务清单的 `cocos-pnp` 上，但是引擎产品名。修复：公开稿改成「外部引擎工程接入」或在法务清单里明确允许这个词。

## F. 工程债 Top 5

| # | 风险 | 是否挡住 Phase 1–2 |
|---|---|---|
| 1 | 质检门把 `skip` 当通过，且没有变异测试 | **挡住**。D2 起不能用这盏绿灯宣布「QC 通过」。schema、模板编码可以并行。 |
| 2 | CHK03 不覆盖 WebSocket / Service Worker / WebRTC | **挡住**「零外网」这句合规结论。不挡模板函数本身。 |
| 3 | CHK04 在无 PF、无音频、只采样一次时形同虚设，且不看 `<audio>`/`<video>` | **挡住**静音合规结论。模板即使走 `PF.audio`，现有断言也证明不了。 |
| 4 | 退避有实现、无测试；429 会放大成连打；密钥留在栈帧局部变量 | **不挡** Phase 1 模板和打包。**挡住**接真实密钥的 director，以及 Phase 2 并发调用。 |
| 5 | 六渠道灯只查本机 gitignore 下的文件是否存在；两个 CLI 灯只查 `--help` | **不挡**自研 packager 开工。**挡住**把「六渠道已对照」当成可复现基线。换机器或 CI 会直接红。 |

Windows 残留浏览器和 MIT 声明被剥掉，分别是本机连跑和 D9 公开的问题，不改变上面的顺序。

**总体结论：需修后继续。** 先收紧三件高优先级的事再把 Phase 0 当成通过：门项 5 拒绝 `skip` 并加上变异样本；CHK03 拦截 WebSocket 且禁用 Service Worker；CHK04 在无桥、无音频和 `<audio>` 迟到出声时都必须失败。这三件未改之前，全绿只说明骨架进程能退出，不能说明质检在裁判。
