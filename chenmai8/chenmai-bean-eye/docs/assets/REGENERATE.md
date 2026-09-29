# 整仓再生手册（REGENERATE）

> 目标：新 agent 只凭本手册 + 各 spec + 契约（CONTRACTS.md），在干净 Windows 机器上从零
> 重建全部已实现模块并通过验收门。所有命令在**仓库根**执行（另有注明除外）；
> 通过线数字为 2026-09-29 `.venv` 实测（门禁与全绿态见 §3 的当日注记）。

---

## 1. 环境准备（实测版本，钉版即契约）

| 件 | 实测版本 | 说明 |
|---|---|---|
| OS / Shell | Windows Server 2022 + Git Bash / PowerShell / cmd 均可 | **仓库路径含中文**——图像 IO 见 §7 坑 1 |
| Python | **3.12.10**（venv 固定 `.venv/`） | 纯 CPU，无 GPU/Docker/WSL 依赖 |
| 关键钉版 | 见 `requirements.txt`（钉版内部版，注释含装配说明） | numpy 2.2.6 / opencv 4.10.0.84 / scipy 1.18.1 / pydantic 2.13.5 / fastapi 0.141.1 / jinja2 3.1.6 / matplotlib 3.11.2 / segno 1.6.6 / zxing-cpp 3.1.1 / pytest 9.1.1 等 |

```powershell
# 一键装配（脚本内含特殊处理与顺序，勿手工绕过）：
powershell -File scripts/setup_env.ps1
# 要点：① venv 建在 .venv；② 依赖按 requirements.txt 钉版安装；③ 图像增强件以 --no-deps
#   装最小闭包（其默认依赖会拉入 opencv-headless 可到 5.x，覆盖钉版 cv2 4.10——固定闭包
#   清单写在 requirements.txt 头注释，2026-09-28 pip 解析实测）；④ 装完自动跑 doctor 自检。
./.venv/Scripts/python.exe scripts/doctor.py     # 任何时点的环境体检，输出 DOCTOR: PASS
```

- 不需要 `pip install -e .`：`pyproject.toml` 配了 `pythonpath=["."]`，仓库根直接
  `pytest tests/...` 即可 import `beaneye` 包。
- `pytest` 出口在仓库根（testpaths=tests）；门禁脚本用**系统 python** 跑（任意 cwd），
  内部自定位仓库根并切 `.venv` 解释器 + `PYTHONUTF8=1`。

## 2. 模块重生成顺序（依赖图即拓扑序）

| 步 | 模块 | 验收命令（仓库根） | 通过线 | spec |
|---|---|---|---|---|
| 1 | M1 契约 | `./.venv/Scripts/python.exe -m pytest tests/test_schemas.py -q` | 60 passed（2026-09-29 实测） | CONTRACTS |
| 2 | M2 采集 | `... -m pytest tests/test_acquisition.py -q` | 22 passed；Mock 帧标定 px_per_mm 误差 <1% | REGENERATE §7 坑 1/2 |
| 3 | M3 标定 | `... -m pytest tests/test_calibration.py -q` | 34 passed；反投影 ≤0.5mm；12MP ≤3s | [markers-geometry](specs/markers-geometry.md) |
| 4 | M6 配对 | `... -m pytest tests/test_pairing.py -q` | **2026-09-29：24 passed / 3 failed**（密排 3 例已知回归，见 [pairing §7](specs/pairing.md)；修复前此步不算全绿） | [pairing](specs/pairing.md) |
| 5 | M7 严重度 | `... -m pytest tests/test_severity.py -q` | 83 passed | [severity](specs/severity.md) |
| 6 | M8 计量 | `... -m pytest tests/test_metrology.py -q` | 31 passed；直径误差 ≤2%；350 粒 3.6ms | [metrology](specs/metrology.md) |
| 7 | M9 标准 | `... -m pytest tests/test_standards.py -q` | 57 passed；三 YAML 全载 | [standards-yaml](specs/standards-yaml.md) |
| 8 | M10 护照 | `... -m pytest tests/test_report.py -q` | 27 passed；三语各 94–98KB；QR 解码回读一致 | [passport](specs/passport.md) |
| 9 | M11 溯因 | `... -m pytest tests/test_agent.py -q` | 79 passed；断网全绿 | [rootcause-kb](specs/rootcause-kb.md) |
| 10 | M13 应用 | `... -m pytest tests/test_app.py -q`；起服务 `... -m beaneye.app`（默认 127.0.0.1:8600） | 14 passed；`/demo` 零外链 | [passport §6](specs/passport.md) |
| 11 | M12 合成 + M4 分割 / M5 分类 | **重生成中（D4 在飞）**——工作树在飞件未入库；本包不提供其再生步骤 | 待落地后回填 | （regenerating） |

在飞注记：M13 装配器按 `<pkg>.build_default()` 工厂探测接线——M4/M5 落地即自动进管线，
缺位时显式降级（0 检出 + degraded_stages 标注），**不要为了"看起来完整"而伪造识别实现**。

## 3. 全仓验收（三道门，验收顺序固定）

```bash
python scripts/gate_d1.py    # D1 契约门：doctor / test_schemas / oss_smoke 现场重跑（aruco+QR 硬项）/ 数据集 README
python scripts/gate_d2.py    # D2 门：doctor / pytest 全绿 / W3·W6·W7·W2 入口逐个 / 中性名 28 条 / 禁止 IO 3 条
python scripts/gate_d3.py    # D3 门：doctor / pytest 全绿 / W8·W9·W10·W11 入口逐个 / 中性名 23 条
```

- 门禁纪律：skip 不是 pass；入口文件缺失按该模块 FAIL；中性名扫描对 git 跟踪文本文件
  全量扫描（产品面 beaneye/ tests/ configs/ docs/ **零豁免**，豁免名单只收不入库内部版
  文件与门脚本自身——门脚本须枚举上游名清单才能扫描）。
- **2026-09-29 实测态（如实记录）**：
  - gate_d1 → FAIL (1/4)：① doctor PASS、② test_schemas 60 绿、④ README PASS；
    **③ oss_smoke 现场重跑超时 >600s**——本机当时网络受限（doctor 输出同步出现 SSL 握手
    超时告警），NN 冒烟件拉取超时，**非产物回归**；网络恢复后复跑即可。
  - gate_d2 → FAIL (2/5)：①④⑤ PASS；② 全绿项 3 failed/431 passed、③ W6 入口 FAIL
    ——均为 [pairing §7](specs/pairing.md) 的密排 3 例（确定性）。
  - gate_d3 → FAIL (1/4)：① doctor PASS、③ W8/W9/W10/W11 四入口 4/4 exit0
    （31/57/27/79 各全绿）、④ 中性名零命中（88 文件 × 23 条模式）；② 全绿项起跑正逢
    在飞代理向 tests/ 并发落文件，读到中间态快照（11 failed/444 passed，含收集期破损）；
    稳定复跑失败集合始终只有密排 3 例。**复跑门禁应等在飞代理落定后进行。**

## 4. 替换/重生成模块时的回归清单

| 被替换模块 | 必跑回归 | 额外人工检查 |
|---|---|---|
| M1 契约 | test_schemas + 全套件（13 份 fixture 是契约样例） | 不变式无删改；`GradingDecision.warnings` 等 v1.1 增补键的消费方（M9/M10）同步 |
| M2 采集 | test_acquisition + test_calibration（Mock 帧喂标定） | imencode 字节缓冲封装未被绕过；scan_id 稳定序；manifest 回读 |
| M3 标定 | test_calibration + test_acquisition（<1% 锚点）+ 禁止 IO 扫描 | tray.yaml 未漂移；2mm 自洽门语义；calibrate_pair 组装锁 |
| M6 配对 | test_pairing（含 3 例已知回归的现状比对）+ test_app | 哑节点/BIG/守卫常量未漂移；bean_id 稳定序 |
| M7 严重度 | test_severity + test_schemas（契约校验器逐位一致）+ test_standards | 与 `_resolve_worst` 共用 `defect_is_countable`，不得单侧改 |
| M8 计量 | test_metrology + test_standards（sieve/ΔE 消费） | lab8↔CIE 仿射系数；round-half-up 舍入；默认值表 |
| M9 标准 | test_standards + test_report（角标）+ test_app | 语义错误行号格式；单调放宽校验；passed 阻断 |
| M10 护照 | test_report + test_app（端点/下载头） | 三语键集对等；QR 往返；占位图确定性；字体链按语言 |
| M11 智能体 | test_agent + test_report（溯因段） | 降级路径全等断言；知识表 12 类一一对应 |
| M13 应用 | test_app + 全套件 | 降级语义（绝不静默伪装）；timings 与护照定型顺序 |
| 任何模块 | 三道门（§3）+ 中性名/禁止 IO 扫描 | 门禁先清疑问再跑：FAIL 时先对照本文与 spec 的"已知状态"，分清**产物回归**与**环境/在飞干扰** |

## 5. 合成器真值语义（M12 · regenerating，契约先于实现冻结）

> M12 在 D4 重生成中（在飞件未入库）；本节是**成对真值契约**——实现落地时按此验收，
> 下游（M4 Oracle 腿 / M6 配对 eval / M14 e2e）按此消费。

- **成对语义**：同一布局生成 top 与 bottom 两图，**两图共享同一布局坐标与 bean_id**。
  bottom 面素材不可知（翻面看不见另一面），就重采样"同 mm 同类"的另一粒或镜像同粒——
  **配对真值仍成立**：M6 拿到的两面观测本来就允许质心抖动（σ 级）与类别以面为单位
  （`class_top`/`class_bottom` 分记）。Mock 采集源是此约定的现行参考实现
  （`mock_source.py`：共享布局 + bottom 逐豆微抖动 1.2→2.0mm + 双面独立光照扰动 + 镜像不翻转）。
- **真值 manifest**：逐粒记录 `{bean_id, class_top, class_bottom, poly_mm, eq_diameter_mm}`
  （M1 兼容 + 掩码编码），batch index 记录实际生效参数 + 种子——反序列化后可直接再驱动
  一次合成（可复现）。托盘几何与四角码布局**不进合成配置**：单一真源是 configs/tray.yaml。
- **验收线（规划冻结）**：固定种子 5 盘**像素级一致**；真值与渲染 alpha 重合 IoU=1.0；
  mm 尺寸与素材规格偏差 ≤0.1mm；labels 过 M1 契约校验。
- **口径纪律**：合成图上的全部精度数字是**管线自洽性数字**（oracle 管线 vs 真值），
  不是现场检测精度——与 docs/calibration-error-budget.md 同一口径纪律。

## 6. 中性名纪律（每次提交前自查）

- 公开树（git 跟踪文本文件）**零上游名**：上游数据集/模型/工具一律用中性内部名
  （素材映射原标签只允许存在于不入库内部文件 `configs/upstream_mapping.internal.yaml`，
  已 gitignore；taxonomy 不含该节时 `map_upstream` 恒 None）。
- 自查方法：跑 `python scripts/gate_d2.py`（门项④）与 `python scripts/gate_d3.py`（门项④）
  ——分别为 28 条 / 23 条模式，大小写不敏感、短词带词边界。**新文档（含本资产包）按此
  红线书写**：坑与上游信息写"内部代号"或中性描述。
- 禁止 IO 扫描（gate_d2 门项⑤）：产品代码不得出现 cv2.imread / cv2.imwrite / np.fromfile
  三种直传路径调用形态（见坑 1）。

## 7. 已知坑清单（构建过程实测，重生成必读）

1. **中文路径 × 图像 IO（imencode 坑，全仓红线）**：工程路径含中文（如 `澄迈8项目/咖啡豆质检`），
   OpenCV 的 `cv2.imread` / `cv2.imwrite` 对非 ASCII 路径**静默失败**（不抛异常，返回
   None/False——错数据比崩溃更危险），`np.fromfile` 在 Windows 同样不可靠。**全仓图像
   落盘/读回一律走 `beaneye/acquisition/base.py` 的 `imwrite_bgr` / `imread_bgr`**：
   内部 `cv2.imencode(扩展名, img)` → `Path.write_bytes`；`Path.read_bytes` →
   `cv2.imdecode(字节缓冲)`——文件路径只经 Python 的 `pathlib`（Unicode 安全），字节缓冲
   过 cv2。失败显式抛 `AcquisitionError`。护照证据图读回（evidence.py）与应用上传解码
   （app/main.py）同约定。gate_d2 门项⑤对此做静态扫描，命中即 FAIL。
2. **ArUco 内缩规则（静区坑）**：四角定位码的白色静区（码外白边）是检测的必要条件——
   **码贴盘角时静区伸出盘面之外**（码心 (30,30)mm、码边 60mm、静区码边 1/4≈15mm 伸出盘外），
   正射网格裁边或画布不留白会把静区裁掉 → 检测失败（W2 实测坑）。**正解 = 画布四周留
   外缘**（Mock `_MARGIN_MM=20`，`px_per_mm = min(w,h)/(tray+2×margin)`，静区完整落画布）；
   **错误解法 = 把码心往盘内缩**——内缩后码位与 tray.yaml 脱钩，「检测点对配置点」的自洽门
   照样放行约 +14% 尺度误差（W13 前真实事故，跨距 210mm 被配到 240mm）。打印板生成器
   （make_aruco.py）静区取码边 1/8；Mock 取 1/4。对称坑在分割侧：码是盘面印刷暗块，
   经典分割须先抑制码区再做全局阈值（在飞 segment 配置的 `mask_markers` 项）。
   显式覆盖 board/marker 尺寸时，布局退回角位公式（码心 = m/2 内缩）——那是"整板重定义"，
   与默认 tray.yaml 布局是两回事，勿混用。
3. **标定两级求解 + 2mm 自洽门**：中心解与角点精化必须带"不劣化回退"（精化 RMS 变差即回退
   中心解）；2mm 自洽门是布局核对（抓配错对），不是精度指标——码位配错时 4 点单应仍可能
   完美拟合。两面 reproj 误差组装必须先毫米化再比较（分辨率不同像素 RMS 不可比）。
4. **scipy 匈牙利 inf 不可行**：代价矩阵含 inf 且无完全避开 inf 的匹配时抛
   `ValueError: cost matrix is infeasible`——必须用有限 BIG 占位 + 哑节点保证恒可行；
   **哑-哑块要整体置 0**（只置对角会逼最优解拆散真对）。
5. **银行家舍入坑**：Python 内建 `round()` 是银行家舍入，筛目换算必须 `floor(x+0.5)`
   （round-half-up）——恰在 .5 目边界时两者结果不同。
6. **LAB 双标度坑**：OpenCV 8-bit LAB（lab8，三通道 0-255）与 CIELAB（L 0-100、a/b ±128）
   混用会把 ΔE 直接放大/缩小——契约构造期拒绝 color_lab 越界，配置面 `reference_lab_scale`
   加载期归一。**已知残留瑕疵**：三份标准 YAML 的 reference_lab 行内注释写"0-255 标度"
   与 loader 实际 CIE 口径矛盾（以 loader 为准，注释待清理）。
7. **YAML 行号坑**：PyYAML 顶层映射走 `construct_yaml_map`（注册表存函数对象）——自定义
   Loader 子类**必须重新 add_constructor("tag:yaml.org,2002:map")** 才能让顶层映射带行号，
   否则语义错误丢行号；重复键默认静默覆盖，必须显式拒绝。
8. **随机源切换坑（当前 3 例失败的根源）**：把测试随机源从标准库 random 换成 numpy
   `default_rng` 时，**同样的种子值产出完全不同的随机流**——"钉种子确定性不变"只对同源
   成立。统计型用例换源 = 换了场景实例，通过线可能不再成立（pairing 密排 3 例即此）。
9. **Windows 控制台编码**：门禁/CLI 入口统一 `PYTHONUTF8=1` + `reconfigure(encoding="utf-8")`
   （GBK 控制台中文乱码）；门禁子进程环境显式注入。
10. **护照校验和定型顺序**：QR 内嵌 sha256(BatchResult)——BatchResult 必须在护照生成前
    定型，护照耗时**不得写回** `timings_s`（写回即校验和与结果脱钩），单列
    `passport_runtime_s`。
11. **图表字体链**：matplotlib 中文字体 SimHei 优先 + `axes.unicode_minus=False`（CJK 缺
    U+2212 负号变方框）；**SimHei 缺越南语声调字形**（ố/ạ/ắ 渲染方框）——vi/en 必须
    DejaVu Sans 优先（eval 抓获后改按语言选链）。
12. **matplotlib 不进 pyplot**：用面向对象 `Figure` + Agg 后端，避免 pyplot 状态污染
    （服务进程里多次出图）。
13. **UVC 相机静默降档**：`cap.set` 请求分辨率后必须 `cap.get` 读回核对——UVC 设备可能
    静默忽略请求分辨率；读帧失败要"关-开恢复一次再试"（热插拔抖动），仍失败才抛错。
14. **LLM response_format 探测**：服务端不支持 json_object 时返回 HTTP≥400 且响应体含
    "response_format" 字样——按此去参重试一次走解析兜底；探测的是响应体子串，较脆弱，
    属已知边界（有降级兜底，不阻塞）。
15. **数据与模型不入库**：`data/*`、`models/`、`out/` 全部 gitignore（仅
    `data/datasets/README.md` 解锁说明随 git 跟踪）；重建后数据集按 README 解锁步骤操作，
    数据集本体 BLOCKED 不影响 aruco/QR 两硬项。

## 8. 本资产包的变更史指针

| commit | 内容 |
|---|---|
| （本包落成 commit） | manifest + 7 张 spec + REGENERATE + CONTRACTS 首版（对照 2026-09-29 HEAD 全量核验；含当日门禁/套件实测态与在飞件注记） |
