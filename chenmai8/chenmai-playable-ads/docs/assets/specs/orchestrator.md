# 编排器（逻辑模块 = M9 pfcore CLI + M10 webui 壳）

> 重组说明：原规划 M9（编排 CLI）与 M10（webui）合并为一个逻辑模块——**命令行是主体，网页只是上传与
> 二维码的壳**。先有命令，再包页面。
> 状态：**partial**——`validate` 与 `make`（全流水线，2026-09-28 接通）frozen；
> `build/pack/rules-check` 为占位（exit 2）；webui 空壳。
> 流水线契约（命令名/退出码/目录/报告/二维码）见 [pipeline-contract](pipeline-contract.md)。

---

## 1. 职责与边界

**做**：一条命令串联 校验 → 构建 → 打包 → 质检 → 汇总报告 + 预览/二维码；多语言 × 多渠道矩阵展开；
单条全矩阵的墙钟计时口径。

**不做**：不做玩法/打包/质检本身（纯编排）；webui 不做登录与外网暴露（仅 LAN、无鉴权）；
质检不通过**不得**产出二维码（"质检不通过就没有可交付物"）。

## 2. 现状（对照 `python/pfcore/__main__.py`，2026-09-28）

| 子命令 | 状态 | 行为 |
|---|---|---|
| `validate <spec...>` | frozen（M1 交付） | glob 展开；逐文件 `OK/INVALID`；全过 exit 0 否则 1 |
| `make --spec [--locales] [--channels] [--out] [--serve-port] [--serve-host] [--no-serve]` | frozen（M9 交付，2026-09-28） | validate → 模板构建（真实可玩 HTML）→ 按规则库打包各渠道 → 首个 single-html 渠道 qacore `--autoplay` → summary.html + LAN 二维码 + 墙钟计时 + `artifacts/demo-prebuilt/` 兜底；质检 FAIL 则不出二维码（exit 1）。实现见 `python/pfcore/make.py` |
| `serve [--root] [--port] [--host]` | frozen（2026-09-29，反馈行动 2） | 对既有产物目录（demo-prebuilt/裸预览）起**前台**局域网静态伺服，现场重建汇总页（渠道包下载 + 质检报告链接，零外链）与二维码（内容规则同 make §5）；Ctrl+C 停止，端口被占向后顺延。实现见 `python/pfcore/serve.py`，契约 §5.1 |
| `build --spec --channel --locale --out` | 占位 | 回显"尚未实现" → exit 2 |
| `pack --spec --all-channels --locale --out` | 占位 | 同上 |
| `rules-check` | 占位 | 同上（结构校验实际可复用 packager 的 `loadRules/validateRules`） |

- Windows 输出编码：入口 `sys.stdout/stderr.reconfigure(encoding="utf-8")`（GBK 控制台乱码坑）。
- webui：`webui/__init__.py` 仅占位 docstring；无任何实现。

## 3. 目标契约（实现时必须对齐 pipeline-contract）

- 唯一全流水线命令名：**已裁决为 `make`**（2026-09-28，与规划正文一致；占位 `run` 已删除，
  不得再引入第三名——见 pipeline-contract §1）。
- 矩阵：spec × locales × channels 全展开；`--quick` 只跑 match3×en×冻结投放渠道
  （2026-09-29 实装于 `scripts/e2e_matrix.py` 时规则库冻结三渠道，规划里的"6 渠道 48 包"
  待 unity/google/tiktok 入库后自然扩到，届时 --quick 预算断言会同步收紧）。
- 每包质检 → 汇总 `summary`（产物大小表 / 总耗时 / 0 FAIL 断言）→ 预览伺服 → 二维码 = LAN IP 的预览 URL
  （127.0.0.1 不可扫）。
- 计时口径：从 spec 修改完成到二维码可扫；`--quick` 目标 ≤90s，全矩阵 ≤3 分钟
  （2026-09-29 实测：--quick 35.7s / 全量 golden-match3×{en,ar}×三渠道 69.2s，见 §5）。
- 演示兜底：全绿产物复制到 `artifacts/demo-prebuilt/`；定稿流程 =
  `python scripts/finalize_demo_prebuilt.py`（2026-09-29 实装：make 整体重建六包
  match3×{en,zh}×三渠道 + 逐包补齐 qacore 质检 + README 静态伺服说明；
  任一 fail 整体撤除兜底目录；artifacts/ 不入库，本命令即可复现重建）。

## 4. webui 壳边界（暂缓，触发条件）

- 职责（规划冻结）：表单上传 spec + 素材 zip → 后台跑编排命令 → 状态轮询 → 二维码（本机 LAN）+ 质检报告页；
  无登录、仅 LAN。
- 触发条件：CLI 全链（make + 二维码）先通并真机扫码成功；webui 只是同一命令的网页皮，不新增第二套流水线
  调用方式。
- eval（规划，实现时冻结）：`python -m webui.app --port 8788` → `/api/health` 返回 ok；httpx 端到端
  selftest（上传 golden → 轮询至完成 → 报告 PASS）exit 0。

## 5. eval：现状可执行项

```bash
python/.venv/Scripts/python.exe -m pfcore validate specs-eval/golden-match3.json   # exit 0
python/.venv/Scripts/python.exe -m pfcore validate "specs-eval/bad/*.json"         # 全 exit 1
python/.venv/Scripts/python.exe -m pfcore make --spec specs-eval/golden-match3.json  # exit 0：三渠道包+质检+二维码+demo-prebuilt（实测 make 墙钟 ~42s）
python/.venv/Scripts/python.exe -m pfcore serve --root artifacts/demo-prebuilt     # 前台伺服兜底目录，重建汇总页+二维码；httpx 拉页面 200、QR 可解码回读预览 URL（2026-09-29 实测，见 pipeline-contract §5.1）
python/.venv/Scripts/python.exe -m pfcore build --spec x.json                      # exit 2（占位语义本身是契约）
```

- 编排器全链验收 = `scripts/e2e_matrix.py`（**2026-09-29 实装并回填**）：矩阵展开
  golden-*.json × locales × 冻结渠道，每格「模板构建→打包→qacore run --autoplay 逐包质检」，
  0 FAIL 才 exit 0，大小表与逐格墙钟落 `artifacts/matrix/summary.json`。
  实测（2026-09-29，64 核机）：

  ```bash
  python scripts/e2e_matrix.py --quick   # exit 0；golden-match3×en×三渠道 3 包全 pass，总墙钟 35.7s（预算 ≤90s）
  python scripts/e2e_matrix.py           # exit 0；golden-match3×{en,ar}×三渠道 6 包全 pass，总墙钟 69.2s
  ```

  通过线：`--quick` 0 FAIL 且 ≤90s（每日冒烟门，硬预算断言）；全量 0 FAIL，
  「4 golden×{en,ar}×6 渠道 48 包 ≤3 分钟」待其余模板构建器与渠道规则入库后按同门真跑。
  zip 渠道（mintegral）先解包按规则库入口（Template.html）质检——qacore 只收单 HTML。
- 演示兜底定稿 = `python scripts/finalize_demo_prebuilt.py`（exit 0：六包齐全且各自
  index.report.json 零 fail、win=True；README.md 落兜底目录含 `python -m http.server` 伺服说明；
  本机实测 `http://127.0.0.1:8618/` 汇总页/双语言预览/二维码/渠道包均 200）。
- **禁止事项**：不许绕过 qacore 直接判定产物合格；不许在质检 FAIL 时输出二维码或把包挪入交付目录。
