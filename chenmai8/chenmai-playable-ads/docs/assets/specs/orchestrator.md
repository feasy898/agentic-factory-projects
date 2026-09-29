# 编排器（逻辑模块 = M9 pfcore CLI + M10 webui 壳）

> 重组说明：原规划 M9（编排 CLI）与 M10（webui）合并为一个逻辑模块——**命令行是主体，网页只是上传与
> 二维码的壳**。先有命令，再包页面。
> 状态：**partial**——`validate` 与 `make`（全流水线，2026-09-28 接通）frozen；
> `build/pack/rules-check` 为占位（exit 2）；webui 已完整实现（frozen，2026-09-29，commit `116d9e1`）。
> 流水线契约（命令名/退出码/目录/报告/二维码）见 [pipeline-contract](pipeline-contract.md)。

---

## 1. 职责与边界

**做**：一条命令串联 校验 → 构建 → 打包 → 质检 → 汇总报告 + 预览/二维码；多语言 × 多渠道矩阵展开；
单条全矩阵的墙钟计时口径。

**不做**：不做玩法/打包/质检本身（纯编排）；webui 不做登录与外网暴露（仅 LAN、无鉴权）；
质检不通过**不得**产出二维码（"质检不通过就没有可交付物"）。

## 2. 现状（对照 `python/pfcore/__main__.py`，2026-09-29）

| 子命令 | 状态 | 行为 |
|---|---|---|
| `validate <spec...>` | frozen（M1 交付） | glob 展开；逐文件 `OK/INVALID`；全过 exit 0 否则 1 |
| `make --spec [--locales] [--channels] [--out] [--serve-port] [--serve-host] [--no-serve]` | frozen（M9 交付，2026-09-28） | validate → 模板构建（真实可玩 HTML）→ 按规则库打包各渠道 → 首个 single-html 渠道 qacore `--autoplay` → summary.html + LAN 二维码 + 墙钟计时 + `artifacts/demo-prebuilt/` 兜底；质检 FAIL 则不出二维码（exit 1）。实现见 `python/pfcore/make.py` |
| `serve [--root] [--port] [--host]` | frozen（2026-09-29，反馈行动 2） | 对既有产物目录（demo-prebuilt/裸预览）起**前台**局域网静态伺服，现场重建汇总页（渠道包下载 + 质检报告链接，零外链）与二维码（内容规则同 make §5）；Ctrl+C 停止，端口被占向后顺延。实现见 `python/pfcore/serve.py`，契约 §5.1 |
| `build --spec --channel --locale --out` | 占位 | 回显"尚未实现" → exit 2 |
| `pack --spec --all-channels --locale --out` | 占位 | 同上 |
| `rules-check` | 占位 | 同上（结构校验实际可复用 packager 的 `loadRules/validateRules`） |

- Windows 输出编码：入口 `sys.stdout/stderr.reconfigure(encoding="utf-8")`（GBK 控制台乱码坑）。
- webui（M10，frozen，commit `116d9e1`）：`webui/app.py` FastAPI 服务——`GET /api/health`、
  `GET /api/meta`、`POST /api/build`（双入路：multipart 上传 spec JSON，或纯表单 选模板+传 PNG+填文案，
  经 `webui/specgen.py` 组装 PlayableSpec 后再过 `validate_spec_dict` 双校验）、`GET /api/jobs[/{id}]`
  轮询、`/artifacts/webui/<任务>/` StaticFiles 伺服产物；后台线程串行（信号量）调
  `python -m pfcore make`（质检是裁判：make 有 fail 即任务 failed，不产假链接），完成后按本机
  LAN 地址重出二维码。端到端自验收 `webui/selftest.py`（httpx，exit 0）；单页 `webui/static/index.html`
  零外链。详见 §4。

## 3. 目标契约（实现时必须对齐 pipeline-contract）

- 唯一全流水线命令名：**已裁决为 `make`**（2026-09-28，与规划正文一致；占位 `run` 已删除，
  不得再引入第三名——见 pipeline-contract §1）。
- 矩阵：spec × locales × channels 全展开；`--quick` 只跑 golden-match3×en×规则库全部投放渠道
  （T2.4 起六渠道；渠道集动态取自规则库，commit `690e51e`）。全量（缺省）= specs-eval 全部
  `golden-*.json`（四模板）× {en,zh} × 六投放渠道 = **48 包**（T2.5 冻结验收口径，commit `56191f2`；
  不传 --locales/--channels 即随规则库渠道集走，包数≠48 如实 FAIL）。
- 每包质检 → 汇总 `summary`（产物大小表 / 总耗时 / 0 FAIL 断言）→ 预览伺服 → 二维码 = LAN IP 的预览 URL
  （127.0.0.1 不可扫）。
- 计时口径：从 spec 修改完成到二维码可扫；`--quick` 预算 ≤90s（实测 74.4s / 78.0s / 84.5s 三次全绿）；
  全量 48 包预算 ≤1200s（gate_phase2 以 `--budget-sec 1200` 断言；实测 422.8s、独立裸跑 342.0s，见 §5）。
  旧「全矩阵 ≤3 分钟」口径已被 ≤1200s 取代。
- 演示兜底：全绿产物复制到 `artifacts/demo-prebuilt/`；定稿流程 =
  `python scripts/finalize_demo_prebuilt.py`（2026-09-29 实装：make 整体重建六包
  match3×{en,zh}×三渠道 + 逐包补齐 qacore 质检 + README 静态伺服说明；
  任一 fail 整体撤除兜底目录；artifacts/ 不入库，本命令即可复现重建）。

## 4. webui（M10，已实现，commit `116d9e1`）

- 职责（规划冻结，已落实）：表单上传 spec（或选模板+传 PNG+填文案）→ 后台跑编排命令 `pfcore make`
  → 状态轮询 → 二维码（本机 LAN）+ 质检报告页；无登录、仅 LAN。webui 只是同一命令的网页皮，
  不新增第二套流水线调用方式。
- 实现构成：`webui/app.py`（FastAPI：`/api/health`、`/api/meta`、`POST /api/build`、
  `/api/jobs[/{id}][/qr.png]`、`/artifacts/webui/<任务>/` 静态伺服）+ `webui/specgen.py`
  （表单 → PlayableSpec 组装；match3 seed 经 pfcore.invariants 规范生成器预检、pullpin
  orderSolution 由 seed 实算并 simulate 复核，组装后再过 `validate_spec_dict`）+
  `webui/static/index.html`（单页零外链，系统字体+内联 CSS/JS）+ `webui/selftest.py`（httpx 端到端）。
- 纪律（与 make 同一套）：防 SSRF——服务端零 HTTP 请求（landingUrl 只做格式校验从不访问，
  LAN 探测复用 `pfcore.make._lan_ip`）；上传 PNG 只收真 PNG（魔数+扩展名，≤5MB×12 个）；
  质检是裁判——make 有 fail 即任务 failed。
- eval（实测）：`python -m webui.app --port 8788` → `/api/health` 返回 ok；`python -m webui.selftest`
  （起服 → health → 单页零外链 → 上传 golden 走完整 make → 轮询 done → 质检 0 fail + 预览/汇总/
  报告/渠道包/二维码逐个 200 → 表单模式同断言 → 负向坏 JSON/未知模板 400）exit 0（实测 68.3s）。

## 5. eval：现状可执行项

```bash
python/.venv/Scripts/python.exe -m pfcore validate specs-eval/golden-match3.json   # exit 0
python/.venv/Scripts/python.exe -m pfcore validate "specs-eval/bad/*.json"         # 全 exit 1
python/.venv/Scripts/python.exe -m pfcore make --spec specs-eval/golden-match3.json  # exit 0：三渠道包+质检+二维码+demo-prebuilt（实测 make 墙钟 ≈29s，留档复核值见 pipeline-contract §5）
python/.venv/Scripts/python.exe -m pfcore serve --root artifacts/demo-prebuilt     # 前台伺服兜底目录，重建汇总页+二维码；httpx 拉页面 200、QR 可解码回读预览 URL（2026-09-29 实测，见 pipeline-contract §5.1）
python/.venv/Scripts/python.exe -m pfcore build --spec x.json                      # exit 2（占位语义本身是契约）
```

- 编排器全链验收 = `scripts/e2e_matrix.py`（**2026-09-29 实装并回填**）：矩阵展开
  golden-*.json × locales × 冻结渠道，每格「模板构建→打包→qacore run --autoplay 逐包质检」，
  0 FAIL 才 exit 0，大小表与逐格墙钟落 `artifacts/matrix/summary.json`；模板构建器表与
  `pfcore/make.py` 的 `TEMPLATE_BUILDERS` 同步（四模板）。
  实测（2026-09-29，64 核机）：

  ```bash
  python scripts/e2e_matrix.py --quick   # exit 0；golden-match3×en×六渠道 6 包全 pass（实测 74.4–84.5s ≤90s）
  python scripts/e2e_matrix.py           # exit 0；四模板 golden×{en,zh}×六渠道 48 包全 pass（实测 342.0s）
  ```

  通过线：`--quick` 0 FAIL 且 ≤90s（每日冒烟门，硬预算断言）；全量 0 FAIL 且 ≤1200s，
  已由总验收门 **`scripts/gate_phase2.py`**（T2.5，commit `56191f2`）固化，五项门 =
  ①gate_phase0 ②gate_phase1 ③gate_mainpath 三门真实子进程回归 exit 0 ④e2e 全量
  `--budget-sec 1200` exit 0 且读 `artifacts/matrix/summary.json` 双重对账
  totals={pass:48,fail:0,skip:0}/mode=full/wallSec≤1200 ⑤中性名扫描。
  2026-09-29 实测 gate_phase2 PASS 5/5，总墙钟 656.1s（其中 e2e 全量 422.8s、48 包 0 fail）。
  质检是唯一裁判：全量首检 FAIL 格用同一 qacore 至多重跑一次、以重跑为最终判定，
  summary 逐格 retried/firstAttemptFails 如实留痕。
  zip 渠道（mintegral/google/unity/tiktok）先解包按规则库入口质检——qacore 只收单 HTML。
- 演示兜底定稿 = `python scripts/finalize_demo_prebuilt.py`（exit 0：六包齐全且各自
  index.report.json 零 fail、win=True；README.md 落兜底目录含 `python -m http.server` 伺服说明；
  本机实测 `http://127.0.0.1:8618/` 汇总页/双语言预览/二维码/渠道包均 200）。
- **禁止事项**：不许绕过 qacore 直接判定产物合格；不许在质检 FAIL 时输出二维码或把包挪入交付目录。
