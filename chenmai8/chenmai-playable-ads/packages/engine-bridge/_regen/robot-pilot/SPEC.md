# cs_food spec（感知层：勺上食物检查 + 选碗）

> 状态：**启发式基线 frozen**（接口冻结；学习型分类器延后、经同一 Protocol 无感替换）。
> 本页对照 `chengshao/cs_food/`（spoons.py / bowls.py / config.py / eval.py）逐行核验于 2026-09-29。

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

## 4. 配置装载与校验（config.py）

- 两个配置文件：`config/food_hsv.json`（cam_ref="wrist_cam"、`min_food_ratio=0.15`、
  6 段 HSV 区间覆盖橙黄/绿/青蓝/紫红/红环绕两段）与 `config/bowl_markers.json`。
- 校验失败一律抛 ValueError 且错误带字段名；**未声明键视为拼写漂移同样拒绝**
  （与 cs_schema extra="forbid" 同纪律）；`min_food_ratio` 必须 ∈(0,1] 数值；
  区间值必须整数且在域内、s_lo≤s_hi、v_lo≤v_hi；dictionary 必须是 `cv2.aruco` 可用名。

## 5. eval（精确命令与通过线）

```bash
# ① 接口与配置装载（cwd=仓库根；conftest 自动落 food_interface_eval.json）
.venv/Scripts/python.exe -m pytest tests/test_food_interface.py -q
#   → exit 0；2026-09-29 独立复跑 54 passed（含合成食物 4 正 4 负、3 碗码登记、
#     跨 0 环绕、配置负例）。
# ② 合成自检 eval（cwd=chengshao/ 包根；无硬件可跑）
../.venv/Scripts/python.exe -m cs_food.eval --report reports/food_eval.json
#   → exit 0；2026-09-29 实测 self_check=True：勺检 8 例（4 食物 4 空）全对、
#     3 码全检出、选碗命中、空图返回 None、未登记码忽略。
```

- 真实帧 eval（`--data assets/spoon_frames`，脚本舀取运行采集的腕部帧）为 D4 后条目：
  **启发式基线准确率仅记录不设硬线**；学习型分类器 test acc ≥95% 且漏检（有食物判无）<3%
  才算过（漏检=喂空勺，比误检严重——阈值向 has_food 偏置）。当前 `assets/spoon_frames/`
  为空（.gitkeep 占位）。
- 训练资产（延后、只写不跑）：`chengshao/training/spoon_cls/`（prepare_data/train/export_onnx/
  eval；MobileNetV3-Small 干 + MLP 头，按回合切分 70/15/15 防同回合泄漏）——
  详见 [training-assets](training-assets.md)。
