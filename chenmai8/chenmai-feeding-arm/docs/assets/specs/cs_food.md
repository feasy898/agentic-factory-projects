# cs_food spec（感知层：勺上食物检查 + 选碗）

> 状态：**启发式基线 frozen**（接口冻结；学习型分类器延后、经同一 Protocol 无感替换）。
> 本页对照 `chengshao/cs_food/`（spoons.py / bowls.py / config.py / eval.py）逐行核验于 2026-09-29；
> **2026-09-30 回炉补遗**（首轮试验缺口 6 项：ArUco 检测参数与预处理 / food_hsv 六段端点 /
> 真实帧 eval 标注约定 / food_eval.json 报告字段 / conftest 定位 / cv2 5.0 ids 形态敏感点），
> 数值一律对照实现代码与当日实测（代码为权威）。

---

## 1. 职责与边界

**做**：勺区 BGR 裁剪 → `SpoonCheck`（HSV 启发式 MVP）；场景相机帧 → 基准码检测 → `bowl_sel`。

**不做**：不做位姿估计（碗位来自 config/workspace.json 的 bowls_m + 餐垫定位）；
不训练（训练资产在 chengshao/training/spoon_cls，延后）。

## 2. 冻结接口（spoons.py，开发指令 §3.2）

```python
@runtime_checkable
class SpoonClassifier(Protocol):
    def from_bgr(self, crop: np.ndarray) -> SpoonCheck: ...   # 签名不改，实现可无感替换
```

- 输入校验（spoons.py:41-51）：必须 numpy ndarray、HxWx3、uint8、非空——否则 ValueError
  （eval 与测试依赖该行为）。
- MVP 实现 `HeuristicSpoonClassifier(config_path=None, cam_ref=None, ts_ns_source=None)`：
  BGR→HSV，逐配置区间 `cv2.inRange` 取**并集掩码**；`score = 掩码均值(0-1)`；
  `has_food = score >= min_food_ratio`。**阈值偏保守（宁可重舀，不空勺到口）**。
- HSV 约定：8bit OpenCV，H∈[0,179]、S/V∈[0,255]；`h_lo > h_hi` 表示跨 0 环绕
  （红色系），生效域 [h_lo,179]∪[0,h_hi]（spoons.py:84-92）。
- **已知边界（设计内）**：低饱和白色系食物（椰子冻）与不锈钢勺/白瓷碗在纯 HSV 域不可分，
  缺省区间不覆盖白色系；缓解路径 = config 扩区间 + 限定勺位裁剪框，或延后分类器接手。

## 3. 选碗（bowls.py）

- 配置 `config/bowl_markers.json`：`cam_ref="scene_cam"`、`dictionary="DICT_4X4_50"`、
  `marker_to_bowl={"0":0,"1":1,"2":2}`（一码一碗，碗序号重复即配置错误）、
  `min_side_px=20`（过小码=过远/噪声，过滤）。
- `BowlSelector.detect(img)`：灰度化 → ArUco 检测 → 只留已登记码 → 码边长=四边均值 →
  按（边长降序，碗序升序）排序；**未登记码一律忽略**（他人干扰物不误选）。
- `select(img) -> int|None`：**最大可见码**（离得最近）对应碗序；无可选码返回 None
  （上层保持上一选择或下 tick 重扫）。

### 3.1 检测预处理与参数（代码为权威，2026-09-30 实测）

- **当前实现 = 仅灰度化 + 全缺省检测参数**：`ArucoDetector(dictionary,
  DetectorParameters())`（bowls.py:67-69），调用方**无**预二值化、无自适应窗口调整、
  无任何参数覆盖（OpenCV 检测器内部的 adaptive threshold 属其缺省预处理，非本仓代码）。
  安装版 cv2 5.0.0 缺省值实测：`minMarkerPerimeterRate=0.03`、
  `adaptiveThreshWinSizeMin/Max/Step = 3/23/10`。
- **首轮试验报告项处置**：报告称"灰底 120px 码漏检，需预二值化+自适应窗口+
  `minMarkerPerimeterRate=0.02`"——**该改动不在实现中**（代码无对应行）；且按仓库自身
  场景构造（同 eval.py `_make_bowl_scene`：DICT_4X4_50 120px 码贴灰底）以缺省参数
  复现尝试灰底 60/90/120/150/180/200 六档，全部 1/1 检出，**合成域未复现漏检**。
  真实帧行为待 `assets/spoon_frames/`（当前空，.gitkeep 占位）采集后复核。上述三项
  （预二值化 / 自适应窗口 / `minMarkerPerimeterRate=0.02`）登记为**真实帧漏检时的
  候选补救路径——未实现、未验证**；实施时须连 tests/test_food_interface.py 场景用例一起改。
- **ids 形态版本敏感点**：bowls.py:85 以 `zip(corners, ids.ravel())` 逐码迭代——实测
  cv2 5.0.0 的 `detectMarkers` 返回 `ids` 为**扁平 (N,) int32**（单码实测
  `array([1], dtype=int32)`）；OpenCV 4.x 系列为 (N,1) 列向量（文档口径，本机未装 4.x、
  未实测）。`.ravel()` 把两种形态都归一成"每码一元素"，跨版本安全；若改按二维索引
  （如 `ids[i][0]`）会在 5.0 扁平形态下错位。
- **版本钉注**：requirements.txt 同时钉 `opencv-contrib-python==5.0.0.93` /
  `opencv-python==5.0.0.93` / `opencv-python-headless==4.13.0.92` 三包——共存时实际
  import 的 cv2 以最后安装者为准（本机实测为 5.0.0、`cv2.aruco` 可用）；本文行为断言
  均为 5.0.0 实测，换 4.13 headless 须先复跑 §5 全部命令再下结论。

## 4. 配置装载与校验（config.py）

- 两个配置文件：`config/food_hsv.json`（cam_ref="wrist_cam"、`min_food_ratio=0.15`、
  6 段 HSV 区间覆盖橙黄/绿/青蓝/紫红/红环绕两段）与 `config/bowl_markers.json`。
- **food_hsv 六段端点数值（config/food_hsv.json 原值，2026-09-30 对照代码核验）**：
  JSON 每段只写 `h_lo/h_hi/s_lo/v_lo` 四端点，`s_hi/v_hi` 未写，由 config.py:129 缺省
  补 255；**`s_lo/v_lo` 未写缺省取域下界 0**——数据类缺省（`HSVRange` 字段
  `s_lo: int = 0` / `v_lo: int = 0`，config.py:40,42）与装载器缺省
  （config.py:129 `("s_lo", 0), …, ("v_lo", 0)`）两处一致（2026-09-30 钉死；二轮
  重生成件同日核对取值一致，重生成时须保持此缺省）。

  | 段 | H | S | V | 覆盖（eval.py:49-50 合成校验点） |
  |---|---|---|---|---|
  | 1 | 5–35 | 60–255 | 60–255 | 橙黄·南瓜粥类 (20,180,200) |
  | 2 | 35–85 | 50–255 | 40–255 | 绿·菜泥类 (60,160,150) |
  | 3 | 95–130 | 40–255 | 40–255 | 青蓝（无合成校验点） |
  | 4 | 130–165 | 40–255 | 40–255 | 紫红·芋泥类 (140,150,170) |
  | 5 | 0–15 | 50–255 | 30–255 | 红环绕低段·棕红肉泥类 (8,170,120) |
  | 6 | 170–179 | 50–255 | 30–255 | 红环绕高段（无合成校验点） |

  区间取**并集掩码**，端点重叠无碍（5–15 段 1/5 双覆盖）；85–95、165–170 无段覆盖
  （低饱和白色系本就不覆盖，见 §2 已知边界）。
- 校验失败一律抛 ValueError 且错误带字段名；**未声明键视为拼写漂移同样拒绝**
  （与 cs_schema extra="forbid" 同纪律）；`min_food_ratio` 必须 ∈(0,1] 数值；
  区间值必须整数且在域内（H∈[0,179]、S/V∈[0,255]）、s_lo≤s_hi、v_lo≤v_hi；
  dictionary 必须是 `cv2.aruco` 可用名。

## 5. eval（精确命令与通过线）

```bash
# ① 接口与配置装载（cwd=仓库根；conftest 自动落 food_interface_eval.json）
.venv/Scripts/python.exe -m pytest tests/test_food_interface.py -q
#   → exit 0；2026-09-30 回炉复跑 54 passed（含合成食物 4 正 4 负、3 碗码登记、
#     跨 0 环绕、配置负例）。
# ② 合成自检 eval（cwd=chengshao/ 包根；无硬件可跑）
../.venv/Scripts/python.exe -m cs_food.eval --report reports/food_eval.json
#   → exit 0；2026-09-30 回炉复跑 self_check=True：勺检 8 例（4 食物 4 空）全对、
#     3 码全检出、选碗命中、空图返回 None、未登记码忽略。
```

### 5.1 报告字段（food_eval.json，eval.py:185-196）

- 公共键：`module`("cs_food") / `date`(YYYY-MM-DD) / `cmd`(产生本报告的精确命令) /
  `source`("synthetic"|"real_frames") / `metrics` / `thresholds`；再按口径**互斥**带其一：
  合成集带 `self_check`(bool)，真实帧带 `pass`(bool)——**两者从不同时出现**
  （审查 B10：pass 只留给有人工标签的真实帧）。缺省落点 `chengshao/reports/food_eval.json`
  （eval.py:42）；满足 §10.2 / CONTRACTS C6（`checks` 可选键本模块未用）。
- 合成集 metrics 键：`spoon_cases / spoon_tp / spoon_tn / spoon_accuracy /
  aruco_registered_detected / aruco_detected_bowls / aruco_selected_bowl /
  aruco_select_correct / aruco_none_on_empty / aruco_ignore_unregistered`；thresholds 键：
  `synthetic_spoon_accuracy_min=1.0 / aruco_registered_detected_min=3 /
  aruco_select_bowl_expected=1 / aruco_none_on_empty=true / aruco_ignore_unregistered=true`
  （eval.py:160-166）。exit 0 ⇔ `self_check=true`。
- 真实帧 metrics 键：`frames / food_frames / food_frame_ratio / mean_score /
  mean_latency_ms / max_latency_ms`；thresholds 固定
  `{"heuristic_baseline":"record-only","classifier_accuracy_min":"deferred"}`
  （eval.py:181）。exit 0 ⇔ `pass=true` ⇔ 至少读入 1 帧。
- 接口测试报告 `food_interface_eval.json` 由 **tests/conftest.py 钩子**落盘：
  `{module,date,cmd,metrics{passed,failed,errors,exit_status},pass}` + thresholds
  `{all_green:true, synthetic_food_cases_min:4, synthetic_empty_cases_min:4,
  aruco_bowls_registered:3}`（conftest.py:23-29）。注意 `exit_status` 是**整个 pytest
  会话**的退出码——与其他失败模块同会话跑会记 1（pass 随之 False），独立跑该文件才是
  干净结论（CONTRACTS C6 / REGENERATE §8.5 坑）。

### 5.2 conftest 是否冻结件（2026-09-30 定位）

`tests/conftest.py` **不是冻结契约件**：CONTRACTS 冻结清单是 C1–C7（数据契约 / 下发纪律 /
黑板键 / 相机时序 / 看板 HTTP / 报告 schema / 目录配置），conftest 本体只是 pytest 根钩子
（sys.path 兜底 + 会话级报告落盘，conftest.py:1-29），全仓无任何"conftest 冻结"声明。
受冻结约束的是它的**产物**——报告须符合 C6 schema 并经 verify_g1_reports.py 独立复核；
改 conftest 自身不走契约变更流程，但改其报告字段结构等于改 C6 产物口径，须走 C6 流程。
钩子只在本次会话确实运行了对应用例时才写报告（conftest.py:48-49），不影响其他模块 eval。

### 5.3 真实帧 eval 与标注约定（2026-09-30 补）

- **启发式基线（`--data DIR`）不需要任何人工标注**：扫目录内 `.png/.jpg/.jpeg/.bmp`
  按文件名排序逐帧推理、只记录（键见 §5.1），读图一律走 `imread_u`（仓库路径含中文，
  cv2.imread 会静默返回空——eval.py:120-127）；`--data` 目录不存在 → exit 2，存在但
  0 帧 → ValueError（eval.py:121-122,176-178）。当前 `assets/spoon_frames/` 为空
  （.gitkeep 占位），真实帧条目为 D4 后事项。
- **标注约定属于延后的分类器数据集**（代码权威源 = `training/config/spoon_cls.json`
  `data` 节）：自动标注协议——**舀取完成帧→has_food=1、咬合结束帧→has_food=0**，
  各取前后 ±`context_frames`(=3) 帧；模糊帧丢弃（`blur_drop_var`=60.0）；
  train/val/test 按回合切分 70/15/15（`split_seed`=2026）防同回合泄漏；
  ≥3000 帧是目标值、非门禁硬线。
- **分类器硬线数值**（同文件 `thresholds` 节 + spoon_cls/eval.py:1）：`test_acc_min=0.95`、
  `miss_rate_max=0.03`（漏检=有食物判无=喂空勺，比误检严重，**硬线**）、
  `decision_threshold=0.35`（<0.5 偏向判有食物——宁可重舀）、`cpu_latency_ms_max=15.0`。
  与 training-plan §3、training-assets spec 一致。**注意**：cs_food/eval.py:12 模块
  docstring 写的"≥90%"是陈旧文案（该入口实际执行值是
  `"classifier_accuracy_min":"deferred"`，eval.py:181；将来启用时的评测执行件
  spoon_cls/eval.py 用 0.95/0.03）——以 spoon_cls 配置为准，eval.py docstring 待其
  下次代码改动时顺手订正。
- 训练资产（延后、只写不跑）：`chengshao/training/spoon_cls/`（prepare_data/train/export_onnx/
  eval；MobileNetV3-Small 干 + MLP 头，按回合切分 70/15/15 防同回合泄漏）——
  详见 [training-assets](training-assets.md)。
