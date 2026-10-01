我按独立评审来读 D1–D2：先对规划、闸门脚本和契约实现做交叉核对，专门找自证、假绿灯和契约不一致，不改任何文件。**需修后继续。** D1 契约里有一批不变式是在构造时真校验的，采集主路径的中文写盘也是真的；但 0.41 mm 和 P 0.995 不能当成现场精度，而且 Mock 盘与 `tray.yaml` 的码位不一致，会在标定自洽门下静默放出约 14% 的尺度误差。这三项不修，合成器布局不要冻结。

## A. 自证风险

- **[high]** `tests/_calib_views.py:59` — 通过线只在无径向畸变的针孔投影、空盘、无亚克力、无反光、无遮挡上测检测器残差；`tests/test_calibration.py:53` 的 0.5 mm 卡的是四码中心（四点单应的插值残差），盘面内部网格放到了 `tests/test_calibration.py:55` 的 1.0 mm，仓库里没有「仅合成、未计折射/畸变」的误差预算。把 0.41 mm 标成合成空盘检测残差，另设现场项（镜头畸变、亚克力折射、反光、豆堆挡码）在 D7 前不得引用为标定精度。
- **[high]** `scripts/oss_smoke.py:159` — 冒烟用刚参与求解的四个码心做反投影，四点单应下该项代数上接近 0，中心闭合亦然，真正有信息的只剩对角线 `px_per_mm`。闸门硬项改成与生成单应独立的内点误差，不要用自反投影当精度。
- **[high]** `beaneye/acquisition/mock_source.py:159` — Mock 码心内缩到 45 mm（`marker/2+marker/4`），`configs/tray.yaml:16` 仍是 30 mm；跨距 210 mm 会被配到配置的 240 mm，尺度约 +14%（6 mm 豆会跳大约两目）。`beaneye/calibration/core.py:213` 的 2 mm 自洽门比的是「检测点对配置点」，错误布局也能过。码心只保留一份几何源，Mock、打印板、`tray.yaml` 同坐标；并加一条 Mock 帧对默认配置的标定测试。
- **[high]** `tests/test_pairing.py:282` — 统计场景 200 粒、最小间距 16 mm、门限 12 mm，错邻大多在门外，再叠加单一种子 `20260928` 和纯平移 5 mm；300+ 粒接触（间距约 7 mm）、上下非平移残差、边缘透视都没进分布。`beaneye/pairing/hungarian.py:32` 把「点阵中位数锁错模」说成真实豆盘不会出现，密排盘恰恰接近这个构型。补间距 ≤8 mm、≥300 粒、带透视残差的用例，第二遍结果变差时拒绝替换（`hungarian.py:186` 目前只要有解就覆盖）。
- **[high]** `configs/taxonomy.yaml:35` — 严重度序是契约默认序，被原样抄进三套标准 YAML；`peaberry` 位次高于破碎/褪色/花脸/未熟，`beaneye/severity/adjudicate.py:316` 再按 `counts_as_defect=false` 丢掉它，另一面的真实次缺陷被抹掉。没有「一面花豆、一面破碎」的计数用例。非缺陷类不参与「最严重缺陷」比较，或并列时保留另一面的可计缺陷。
- **[med]** `configs/taxonomy.yaml:8` — `verified: true` 的含义是「对照内部契约」，不是对照 CQI 原文；`dried`（`taxonomy.yaml:30`）被标成主缺陷，等级阈值在 `configs/standards/cqi_fine_robusta.yaml:56` 为 `verified: false`。`beaneye/standards/engine.py:169` 在未核对时仍给出 `passed=True` 和等级名，`verified: false` 只进 `loader.py:511` 的 warnings。`sample_g: 350` 被加载后 `evaluate` 完全不读，托盘粒数直接对比全样上限。`verified: false` 时 `passed` 不得为真；计数要么按 `sample_g` 换算，要么在字段上写明「本盘粒数，非 350 g 当量」。

## B. 假绿灯

- **[med]** `scripts/gate_d1.py:104` — D1 闸门不重跑 `oss_smoke.py`，只读已落盘的 `out/oss_smoke_report.json`；报告过期或只剩 aruco/qr 为真时仍可 PASS。闸门改为现场执行冒烟，或校验报告时间戳与代码版本。
- **[med]** `tests/test_calibration.py:404` — `calibrate_pair` 的组装约定（`px_per_mm` 取均值、`reproj_err_px` 取最大，见 `core.py:264`）没有断言；两面分辨率不同时，像素 RMS 取最大也不可比。测试锁死均值/最大值，并把重投影换算到毫米再取最大。
- **[low]** `tests/test_pairing.py:262` — 乱序输入有回归；`test_pairing.py:221` 只拒绝同一 `obs_id` 重复。同一粒两个不同 id 的近距双框、亚像素质心抖动都没有单独用例（3 mm 高斯加 16 mm 间距把亚像素淹没了）。加「双框相距 1–2 mm」和「质心抖动 0.2 mm」两条失败/稳定路径。
- **[low]** `scripts/gate_d2.py:155` — D2 的「pytest tests/ 全绿」把已在树上的计量、标准、报告、智能体测试算进 D2。D2 闸门只跑 D2 四个模块，避免半成品测试把绿灯含义冲淡。

## C. 契约一致性

- **[med]** `beaneye/calibration/core.py:239` — 开发指令写 `calibrate(...) -> CalibResult`，实现返回非契约的 `SingleCalib`，只有 `calibrate_pair` 才组装 `CalibResult`。文档与返回类型已经不一致，组装规则又无测试。要么改 spec 承认单面/双面两个类型，要么让单面结果也能序列化进 `TrayScan.calibration`，并把均值/最大值写进测试。
- **[med]** `beaneye/schemas.py:165` — 构造期真正强制的是：单应 3×3、四角 id、`obs_id==mask_id`、oracle 置信度、`PairedBean` 的 `final_*` 与存储的 `severity_rank` 一致、`defect_counts` 与逐粒直方一致。`defect` 不查 taxonomy（`schemas.py:9`），`severity_rank` 不要求等于序位，`side` 不要求与 `mask.side` 相同，双面 `pairing_cost` 可以为 -1（`schemas.py:227` 只约束单面），`primary_count` / `bean_count` 不与豆列表挂钩。这些缺口靠调用方自觉，测试只覆盖了已写进校验器的那一半。把 taxonomy 序位、`side` 一致、双面代价 ≥0、主/次计数与 `final_defect` 一致补进 `model_validator`。
- **[med]** `beaneye/schemas.py:162` — `color_lab` 注释为 0–255，构造不检查范围；CQI 参考色 `L=55, a=-12, b=22` 仍是 CIE 常规量纲，标度混用会直接放大 ΔE。冻结单一 Lab 标度并在构造时拒绝越界。

## D. Windows

- **[low]** `beaneye/acquisition/base.py:41` — 采集落盘走 `imencode`/`Path.write_bytes`，`tests/test_acquisition.py:204` 用「采集目录_澄迈」做了往返。全库没有 `cv2.imwrite`/`cv2.imread` 调用。例外是 `tests/test_calibration.py:207` 用 `np.fromfile` 并注释成「中文路径安全」——Windows 上这条并不安全，且该测试文件在 ASCII 的 pytest 临时目录，没踩到中文路径。删掉 `np.fromfile`，改用 `read_bytes`；闸门加一条禁止 `cv2.imwrite`/`np.fromfile` 的扫描。`make_aruco.py:78`、`oss_smoke.py:66`、`report/evidence.py:81` 各写了一份编码落盘，应收敛到 `imread_bgr`/`imwrite_bgr`。
- **[med]** `beaneye/acquisition/usb.py:105` — 相机构造时打开一次，`usb.py:138` 读失败只抛错，不释放、不重开，没有热插拔恢复。`usb.py:121` 设置分辨率/对焦/曝光后不读回，注释写「只记警告」但没有日志；UVC 忽略 3840×2160 时会静默停在默认分辨率。读失败时关闭并重开一次；`cap.get` 核对实际分辨率，不符即 `AcquisitionError`。

## E. 公开仓库卫生

- **[med]** `configs/taxonomy.yaml:37` — 上游项目名已收成 `poly12`/`grade4`，但 12 类原标签（`frozen`、`black_ear`、`triangle`、`longberry` 等）仍在产品配置里，`beaneye/taxonomy.py:13` 和 `tests/test_schemas.py:362` 直接引用。`scripts/gate_d2.py:63` 的模式表不包含这些标签，所以「零命中」并不表示映射只留在内部。公开树删除 `upstream_mapping`，映射只留在不随迁的内部文件；闸门模式补上这组标签。
- **[low]** `README.md:7` — 对外已写「符合 CQI 计数规则」，与 `verified: false` 的阈值和未核对的主/次归属并列出现。README 改为「内部计数规则，阈值核对前不作为 CQI 符合性声明」。

## F. 工程债 Top 5

| # | 风险 | 是否挡住素材库 / 合成器 / 分割 |
|---|---|---|
| 1 | Mock 与 `tray.yaml` 码位不一致，标定自洽门放行约 14% 尺度误差 | 不挡素材库。挡住合成器毫米真值和分割之后的毫米坐标 |
| 2 | 配对通过线建立在间距 16 mm 的稀盘上，密排点阵是未测失败模 | 不挡三段开工。挡住「合成稠密盘 → 配对」的验收 |
| 3 | 花豆位次吞掉次缺陷；`verified: false` 仍可判过；`sample_g` 不参与计数 | 不挡这三段。挡住定级，且 README 已对外声称符合 CQI |
| 4 | Roboflow key 未落地（已知） | 挡住真实单粒素材库，以及依赖该掩码的合成器纹理。不挡程序化 Mock、经典分割、Oracle 分割的接口 |
| 5 | 契约对类别、序位、代价、计数的约束不完整；单面/双面标定类型与 spec 不一致且组装未测试 | 不挡开工。合成器一旦按宽松契约写标签，错误会整批通过校验 |

素材库可以继续等 key，用程序化豆先做合成器骨架；码位几何、稠密配对用例、花豆计数这三处要先改再冻结布局。0.41 mm 与 P 0.995 只可当作当前合成夹具上的检测残差，不能写进标定或配对的精度结论。
