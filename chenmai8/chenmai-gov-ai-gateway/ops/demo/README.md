# 演示控制页场景材料（ops/demo，§10「每场景脚本 ops/demo/sceneN.md」）

演示控制页（webui 演示入口）：**GET /webui/demo** —— 五场景清单 + 材料一键下载
（按需调用同一构建器，幂等）。本目录是彩排/录像用的脚本与物化 CLI。

## 场景清单（编号按任务单 T4.3）

| # | 场景 | 载体页 | 脚本 | 状态 |
|---|---|---|---|---|
| 1 | 双屏对比（脱敏对话 + 上游实际收到） | /webui/chat | scene1（T5.2/T6.2 补） | 页面待上线 |
| 2 | 三份材料三路由（INTERNET/GOVCLOUD/BLOCK） | /webui/chat + 演示控制页 | scene2（T6.2 补） | 材料就绪 |
| 3 | 看板指标（审计统计 + bench 对照） | /webui/dashboard | scene3（T6.2 补） | 页面待上线 |
| 4 | **防注入**：检索网页里埋注入指令 → 被拦 | /webui/chat（现可 curl 驱动） | **scene4.md** | **已就绪（T4.3）** |
| 5 | **扫描件体检**：扫描 PDF → OCR 体检 → 重打码导出 | /webui/files | **scene5.md** | **已就绪（T4.3）** |

> 编号对照：开发指令 §10 表中「扫描件体检」列为场景 3、「看板指标页」列为
> 场景 5；本任务单（T4.3）按概念文档口径编号——场景4=防注入、场景5=扫描件
> 体检。两处均指向同一演示内容，T6.2 全量脚本化时统一。

## 材料物化（二选一）

```bash
# ① CLI（含双构建字节一致自证 + 场景4 预物化 curl 请求体）
cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m ops.demo.build_fixtures

# ② webui 演示入口按需构建（免 CLI）：GET /webui/demo → 材料下载链接
```

产物落 `data/fixtures/materials/`（构建物，不入库）；与 e2e（ops/e2e_smoke）、
场景 2 材料、场景 4/5 材料同源同构建器（benchmark/generator/materials.py）。

## 服务起法（场景 4/5 彩排前置）

```bash
./.venv/Scripts/python.exe -m gateway --port 9000                 # 网关（必起）
./.venv/Scripts/python.exe -m gateway.mock_upstream --port 8901   # 场景4 需要上游
./.venv/Scripts/python.exe -m gateway.mock_upstream --port 8902   # （多上游演示）
```

部门演示 Key 见 config/dept_keys.yaml（演示明文口径同 ops/e2e_smoke.py）。
