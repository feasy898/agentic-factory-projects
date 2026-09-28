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
| `build --spec --channel --locale --out` | 占位 | 回显"尚未实现" → exit 2 |
| `pack --spec --all-channels --locale --out` | 占位 | 同上 |
| `rules-check` | 占位 | 同上（结构校验实际可复用 packager 的 `loadRules/validateRules`） |

- Windows 输出编码：入口 `sys.stdout/stderr.reconfigure(encoding="utf-8")`（GBK 控制台乱码坑）。
- webui：`webui/__init__.py` 仅占位 docstring；无任何实现。

## 3. 目标契约（实现时必须对齐 pipeline-contract）

- 唯一全流水线命令名：**已裁决为 `make`**（2026-09-28，与规划正文一致；占位 `run` 已删除，
  不得再引入第三名——见 pipeline-contract §1）。
- 矩阵：spec × locales × channels（6 渠道）全展开；`--quick` 只跑 match3×en×6 渠道。
- 每包质检 → 汇总 `summary`（产物大小表 / 总耗时 / 0 FAIL 断言）→ 预览伺服 → 二维码 = LAN IP 的预览 URL
  （127.0.0.1 不可扫）。
- 计时口径：从 spec 修改完成到二维码可扫；`--quick` 目标 ≤90s，全矩阵 ≤3 分钟（规划值，实现后实测回填）。
- 演示兜底：全绿产物复制到 `artifacts/demo-prebuilt/`（gitignore 之外的持久化方式待定，见 REGENERATE §7）。

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
python/.venv/Scripts/python.exe -m pfcore build --spec x.json                      # exit 2（占位语义本身是契约）
```

- 编排器全链验收 = `scripts/e2e_matrix.py`（规划；未实现）：4 golden × {en,ar} × 6 渠道 48 包 0 FAIL、
  `--quick ≤90s`。实现后本节必须回填实测命令与通过线。
- **禁止事项**：不许绕过 qacore 直接判定产物合格；不许在质检 FAIL 时输出二维码或把包挪入交付目录。
