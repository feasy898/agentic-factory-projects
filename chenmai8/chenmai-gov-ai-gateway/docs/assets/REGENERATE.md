# 整仓再生手册（REGENERATE）

> 目标：新 agent 只凭本手册 + 各 spec，在干净机器上从零重建全部已实现模块并通过六道门。
> 所有命令在**仓库根**执行（另有注明除外）；实测基线 2026-09-29（windev-01，Windows Server 2022）。

---

## 1. 环境准备（实测版本，钉版即契约）

| 件 | 实测版本 | 说明 |
|---|---|---|
| OS / Shell | Windows Server 2022 + Git Bash | 路径含中文（D:/workspace/澄迈8项目/…）——见 §4 坑 2 |
| Python | **3.12.10**（系统 `C:\Program Files\Python312\python.exe`） | venv 固定在仓库根 `.venv/`；门脚本按此坐标定位 |
| git | 2.55 | — |

```bash
cd "D:/workspace/澄迈8项目/政务AI脱敏网关/repo"
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -U pip
./.venv/Scripts/python.exe -m pip install -e ".[dev,ocr,ml]"
cp .env.example .env    # 填 MASK_KEY（随机32字节hex）；MOCK_KEY 演示可任意值
```

- `constraints.txt` 是 D0 安装后 pip freeze 的**唯一版本真相**（铁律：重装按它钉版）；
- 一切命令统一加 `PYTHONUTF8=1`（§4 坑 1）；
- OCR/ML 依赖组是 m6_ocr/m2_semantic 的前置（纯 CPU 推理，无 GPU 要求）；
- 公开仓卫生：真实上游产品名/引擎库名**只允许出现在 config/**（源码 importlib 动态加载），
  新文档/新代码提交前跑 `python -m ops.name_lint --strict` 自检（词表 ops/forbidden_names.txt）。

## 2. 模块重生成顺序（依赖图即拓扑序）

```
0 venv+INFRA → 2 RECOG → 3 MASKING → 4 ROUTING → 5 OUTGUARD → 7 SEMANTIC
→ 6 FILECHAN（需 BENCH 夹具）→ 9 BENCH（可与 2-7 并行，夹具供 FILECHAN/E2E）
→ 1 GATEWAY 主链（组装位）→ 8 AUDIT+管理面+看板 → 10 六道门收口
```

每步验收命令（`PYTHONUTF8=1 ./.venv/Scripts/python.exe -m <eval>`，exit 0 = 通过）：

| 步 | 模块 | 验收 eval | 实测通过线（2026-09-29） |
|---|---|---|---|
| 0 | INFRA | m0_infra | `M0 INFRA: 20/20`（冷启动 ≈217s） |
| 2 | RECOG | m2_recognizers | `6/6`（2000 字 mean 2.29ms） |
| 3 | MASKING | m3_masking | `9/9`（≈4.3s；还原 0.046ms；T8.4 增改形还原项） |
| 4 | ROUTING | m4_routing | `43/43`（38 格+5 横切） |
| 5 | OUTGUARD | m5_outguard | `13/13`（≈21s） |
| 6 | FILECHAN | m6_filesvc / m6_ocr | `12/12`（≈106s）/ `6/6`（≈282s，OCR 渲染占大头） |
| 7 | SEMANTIC | m2_semantic | `11/11`（34 注入+45 正常；≈25s） |
| 9 | BENCH | m8_generator | `4/4`（≈11s；双跑复现） |
| 1 | GATEWAY | t0_gateway / t0_stream | exit 0 / `11/11`（≈57s） |
| 8 | AUDIT+看板 | m7_audit / m9_webui | `16/16`（≈14s）/ `14/14`（≈49s） |
| — | 标签文档 | t0_labels | `8/8`（≈379s，全仓 lint 占大头） |
| 10 | E2E | m10_e2e | `e2e_smoke: 7 PASS / 0 FAIL / 0 DEFERRED`（≈337s） |

## 3. 全仓验收（六道门）与超时预算

```bash
# 系统 python 从任意 cwd 可跑（门内部自定位仓库与 .venv）：
python "D:/workspace/澄迈8项目/政务AI脱敏网关/repo/ops/gate_b5.py"   # 最新门：name_lint+m0+m7全量+m9全量+m10_e2e+整门回归b4
python "D:/workspace/澄迈8项目/政务AI脱敏网关/repo/ops/gate_d0.py"   # 最小门：name_lint+m0+t0_stream+m10_e2e
```

**超时预算（门脚本常量，冻结）**：

| 门 | 单项 | 整门回归项 |
|---|---|---|
| gate_d0 | 900s | — |
| gate_b1 | 1200s | — |
| gate_b2 | 1800s | — |
| gate_b3 / b4 / b5 | 1800s | 3600s |

- 超时即该项 FAIL、门 exit 1——**给足墙钟**：嵌套整链（b5⊃b4⊃b3⊃b2 十项链）实际跑完
  是小时级，不要在窄超时窗口里启动整门；单项复验按 §2 表逐个 eval 跑（分钟级）；
- 门项清单与附加断言（DEFERRED=0、U7 在位）见 [specs/gates.md](specs/gates.md) §2；
- 2026-09-29 gate_b5 收工实跑记录：git log `827cdbf`（6/6 全 PASS）。

## 4. 已知坑清单（重生成必读）

1. **GBK 控制台坑**：门脚本与 e2e 入口对 stdout/stderr `reconfigure(encoding="utf-8")` +
   `os.environ["PYTHONUTF8"]="1"`——缺了会在中文 Windows GBK 控制台（cp936）上中文乱码/炸码。
   自己写新入口照抄这一段（gate_b1.py:109-112、e2e_smoke.py:1029-1032）。
2. **子进程控制台工具输出是 GBK**：中文 Windows 上 `netstat`/`wmic`/PowerShell 输出
   GBK（cp936/gb18030），而本仓脚本在 PYTHONUTF8=1 下 `text=True` 会按 UTF-8 解码并炸
   subprocess 读线程（0xBB 起始字节）。e2e 的 `_decode_console` 先 UTF-8、再 gb18030、
   最后 replace 兜底（e2e_smoke.py:265-274）——**仓库路径含中文，解码错表会让"本项目进程"
   识别失效**，动它前想清楚。
3. **端口竞争（已知项）**：m10_e2e / m9_webui / t0_gateway 系列独占 **9000（网关）/
   8901（互联网 mock）/ 8902（政务云 mock）** 三端口。e2e 启动前 `_assert_port_free`
   （e2e_smoke.py:315 起）：netstat -ano 找监听 PID → wmic/PowerShell CIM 查命令行 →
   **只有命令行同时含本仓库路径与 mock_upstream/e2e_smoke 标识**的残留进程才 taskkill，
   无关占用者一概不碰；清理后仍被占即报错拒绝运行。**并行批次（如政务批次 6 / 短剧作业）
   同时跑门会端口冲突——同一台机上串行跑门，或改 `ANONGW_LISTEN` 并接受 e2e 不可跑**。
   另：T6.1（2026-09-29，git `e79207d`）起本机 127.0.0.1:**9004** 为 GPU 机真实上游的
   ssh 隧道端口（ops/tunnel_gpu.sh 常驻，部署侧、非六门依赖；网关切换真实上游属后续批次）。
4. **两库分文件**：审计库 `data/audit.db` 与会话映射库 `data/session_map.db` **不得合并**——
   审计库要过 bytes 级全文件零明文扫描，masking_map 按设计必须存归一化原值（§5.4 vs §5.3.3）。
5. **门运行环境只有标准库**：gate 脚本自身 `import` 仅标准库（evals/thresholds.py 亦纯常量，
   系统 python 可导入）——给门加依赖 = 破坏"任意 cwd 系统 python 可跑"契约。
6. **eval 阈值只改一处**：全部阈值常量在 `evals/thresholds.py`；用例里散落魔法数字是违约。
   改阈值须同步核对 CONTRACTS 里引用它的通过线文案。
7. **占位符升位**：`DIGEST_WIDTHS=(8,10,12)` 插入期碰撞检测；测试显式注入词表用
   `set_*_terms`（绕过文件），不要改 config 词表文件来造测试条件。
8. **流式还原 48 字符缓冲**：`MAX_PLACEHOLDER_LEN = PLACEHOLDER_TOLERANT_MAX_LEN = 48`
   （T8.4 起 32→48，容忍模型对占位符的反引号/空白/换行改形；与占位符形状正则 hex 8–12 位
   联动，改占位符标签长度上限必须同步——超窗候选按普通文本放行首字符）。
9. **导出零残留是管线内硬闸**：不是仅验收断言——`ExportBlockedError` 宁可阻止不可漏删；
   收敛上限 `SANITIZE_MAX_PASSES=3`（删除后相邻文本拼接可能产生新命中）。
10. **`extra="forbid"`**：9 个契约模型全部禁额外字段（m0_infra 有负例）——新字段走
    CONTRACTS 变更流程，字段只增不改名不删。
11. **公开导出豁免面**：name_lint 默认档不扫 yaml/json（strict 档才扫）；豁免仅限仓库根
    固定坐标（pyproject.toml/constraints.txt/clone_oss.sh/词表自身）——别处同名文件照扫，
    不要把真实引擎名写进 docs/。

## 5. 再生 SOP（验证"spec+eval 可再生"）

1. **隔离**：新工作目录只拷入 `docs/assets/` 全部 spec + 被测模块冻结 eval（不拷原实现）；
2. **盲实现**：实现者只看 spec + eval；环境前置一切假设以 spec 为准（缺了判 spec 缺口，
   回炉补 spec，不许自创胶水凑路径）；
3. **裁定**：跑该模块 eval + 相关门项；判据 = exit 0 + 通过线达标（以 eval 自报摘要行为准）；
4. **记录**：结果与回炉清单追加进各 spec 的 eval 指针节。

## 6. 本资产包的变更史指针

| commit | 内容 |
|---|---|
| （本 commit） | docs/assets/ 四件套首发：manifest（十大模块+六门指针）、specs ×11、REGENERATE、CONTRACTS |
| `827cdbf` | gate_b5 收工门（T5.4，6/6 全 PASS 实跑记录） |
| 更早 | 各批次模块本体构建史（见 git log：T0.x 主链 → T1.x 规则/生成器 → T2.x 路由/输出 → T3.x 文件 → T4.x OCR/语义 → T5.x 审计管理面/看板） |
