# cs_mouth spec（感知层：口部三维估计——mono 固定先验 / 腕部 IPD 双职 / depth 保留）

> 状态：**frozen（mono 主路径，bundled+synthetic 样本集）**；wrist-view 验收口子已冻结、
> 实拍样本 planned（缺失时 eval exit 2）；depth 后端延后保留（接口不变）。
> 本页对照 `chengshao/cs_mouth/`（estimator.py / prior.py / _schema.py / imgio.py / synth.py /
> bootstrap.py / eval.py）逐行核验于 2026-09-29。

---

## 1. 职责与边界

**做**：BGR 图（+可选深度图）→ 人脸 478 关键点 + blendshapes + 头姿 → 契约 `MouthPose`
（base 系）。三种距离来源按 `prior.mode` 与 `cam_pose` 切换。

**不做**：不开相机（帧源一律注入）；不做多脸（`num_faces=1`）；不加锁（单线程使用，
行为树 tick 内直调）。

## 2. 契约签名（estimator.py，v1.1 向后兼容扩展）

```python
MouthEstimator(backend="mono"|"depth", prior: MouthPrior|None=None,
               pose_provider: Callable[[], tuple]|None = None)
est.from_bgr(img, depth=None, *, cam_pose=None) -> MouthPose
```

- `pose_provider`：无参函数返回 `(T_base_flange, T_flange_cam)`（4×4）；提供后每次 `from_bgr`
  未显式传 `cam_pose` 时自动取用（行为树接 FK 用）。
- `cam_pose=(T_base_flange, T_flange_cam)`：单帧覆盖；提供该参数（或 pose_provider 生效）时
  走 IPD 估距且 `source="wrist"`。**两者皆 None 时行为与 v1.0 完全一致**（顶部固定先验）。
- `backend != "mono"` 时传 cam_pose 抛 ValueError（腕部双职仅支持 mono）。

## 3. 单帧管线（estimator.py:1-23 docstring + 实现）

```
BGR → 最长边缩放 prior.max_side=640（INTER_AREA；小图不动，estimator.py:162-172）
   → 人脸 478 关键点 + 头姿矩阵 + 52 blendshapes（模型字节流加载，绕开 Windows C 层
     非 ASCII 路径限制，estimator.py:184-197；关键点 <478 按失效帧处理）
   → 口中心像素 = 上下内唇关键点 13/14 的均值（_LIP_UPPER_INNER=13, _LIP_LOWER_INNER=14）
   → jaw_open = 几何口径比 gap/eye 线性映射（见 §4）
   → frown = blendshape mouthFrownLeft/Right 均值（browDown 微笑误报实测 0.68，弃用）
   → head yaw/pitch/roll = 面部变换矩阵欧拉分解 R = Ry(yaw)·Rx(pitch)·Rz(roll)
     （yaw 绕相机竖直轴=转头；estimator.py:219-232）
   → 距离（§5）→ cam→base（§6）→ MouthPose
```

## 4. 张嘴判定：几何口径比（关键实测坑）

- **ratio = |唇13-唇14| / |眼角33-眼角263|**，在归一化坐标下计算（尺度约简，与标定一致）。
- 线性映射（estimator.py:234-240）：`jaw_open = clip((ratio − calib_closed_ratio) /
  (calib_open_ratio − calib_closed_ratio), 0, 1)`，标定常数在 prior：
  **closed=0.11（实测闭嘴簇 ≈0.057–0.10）、open=0.23（实测张嘴簇 ≈0.226–0.30）**
  （prior.py:64-65；实测记录见 `chengshao/assets/face_samples/README.md`）。
- **坑**：静帧上 blendshape jawOpen **不区分张闭嘴**（实测张嘴 0.079–0.094 vs 闭嘴 0.093），
  故弃用 blendshape、改几何口径比。
- 行为阈值不在本模块：张嘴 `jaw_open>0.35`、转头 `|head_yaw|>25°`、皱眉 `frown>0.5`
  均为 cs_schema 冻结常量（单一事实来源）；**闭嘴（咬合完成）阈值 0.20 是编排层常量**
  `cs_orchestra.nodes.JAW_CLOSED_THRESHOLD`（schema 只定义张嘴阈值，闭嘴滞后属编排层，
  nodes.py:74-76）。

## 5. 距离三模式（estimator.py:249-298；prior.py）

### 5.1 mono fixed（顶部相机回退路径）

射线反演 × 固定先验距离：`ray = [(u-cx)/fx, (v-cy)/fy, 1]`，`pos_cam = ray × 0.42/|ray|`
（`distance_m=0.42`）。误差带 ±3–5cm（prior.error_band_m），由"勺停口前+用户前倾取食+
座位定位垫"设计吸收。

### 5.2 mono ipd（v1.1 腕部双职主模式）

```
ipd_px = |iris_R(468)×w − iris_L(473)×h|（像素距；虹膜中心关键点 468/473，
         canonical face mesh：468-472 右虹膜、473-477 左虹膜）
Z = fx × ipd_m / ipd_px        （ipd_m 缺省 0.063 m = 成人瞳距先验）
射线方向仍由口中心像素给出；pos_cam = ray × Z/|ray|
```

- **失效判定（返回 None → 失效帧）**：`ipd_px < IPD_PX_MIN=20.0`（过远/分辨率不足）；
  `Z ∉ [0.10, 0.80] m`（IPD_Z_RANGE_M 量程，prior.py:36-37）。
- 预期精度 ±2–4cm（近距 20–50cm 人脸占满画面；优于远距固定先验）。

### 5.3 depth（延后保留）

口中心 5×5 窗口中值查深：整型图或 `z>50` 判毫米→米；量程 [0.05, 3.0] m 出界失效；
像素反演 `(u-cx)z/fx, (v-cy)z/fy, z`。

### 5.4 相机内参与位姿

- 内参缺省标称（prior.py:67-73）：fx=fy=460、cx=320、cy=240，对应 ref 640×480；
  `intrinsics_for(w,h)` 按图像尺寸等比缩放（sx=w/640, sy=h/480）。真机标定后覆盖 config。
- cam→base：`T_base_cam` 缺省摆位（prior.py:47-52）——旋转行 cam_z→base_x、cam_x→−base_y、
  cam_y→−base_z；平移 (0.05, −0.20, 0.30)（底盘前方 0.05m、右 0.20m、高 0.30m）。
  腕部模式：`T_base_cam = T_base_flange(FK) × T_flange_cam(手眼外参)`
  （`MouthPrior.compose_cam_pose`，两输入都必须 4×4）。
  腕部手眼外参名义值在 cs_orchestra.core.NOMINAL_T_FLANGE_CAM（cam_z 沿 flange +X、
  cam_x 沿 flange −Y、cam_y 沿 flange −Z；光心在 flange 前方 2cm、上方 5cm），
  `config/calib/handeye_wrist.npz`（key=`T_flange_cam`）标定后覆盖（core.py:88-111）。

## 6. 失效帧行为与置信度（契约 §3.1）

- 失效帧（未检出人脸 / IPD 不可靠 / 深度缺失）：`valid=False, confidence=0, jaw=frown=head=0`，
  x/y/z **沿用上一有效值**；无历史时用名义位姿 `[distance_m, 0, mouth_height_m]=[0.42,0,0.25]`
  （estimator.py:315-334）。
- 启发式置信度（仅排序用，estimator.py:305-313）：mono 0.90 / depth 0.85；
  贴边（3% 边带内）−0.15；`eye_px<12`（脸过小）−0.30；clip [0,1]。

## 7. 配置与模型文件

- `config/mouth_prior.json`（mode 缺省 "fixed"；字段与 `MouthPrior` dataclass 一一对应；
  `_note` 记录标定簇与口径）。`MouthPrior.load()`：文件缺失/损坏/字段非法一律回退代码缺省
  （工程容错不抛异常，prior.py:106-116）；`mode` 只接受 fixed|ipd。
- 人脸关键点模型 `models/face_landmarker.task`（**权重不入库**：.gitignore 含 `*.task` 与
  `models/`）——`python chengshao/scripts/fetch_models.py` 一次性下载（URL 在 prior
  `DEFAULT_MODEL_URL`）；路径解析顺序：绝对 → cwd 相对 → 包根相对（prior.py:122-131）；
  未找到时抛 FileNotFoundError 并提示 fetch 命令。

## 8. 样本集与导入工具

- `assets/face_samples/`：`seeds/` 公版真人种子 5 张 + `bundled/` 确定性变体（每种子 8 变体，
  共 40 帧，labels.json 人工核定标签）+ `labels.json` + README（来源/许可证/实测记录）；
  `face_demo_carousel.mp4` 演示轮播。
- `synth.py`：运行时程序合成卡通脸（检出/时延负载）与无脸场景（拒识路径），不入库，
  `--skip-synth` 关闭。
- `bootstrap.py ensure_bundled()`：变体缺失时从 seeds 重建（幂等）。
- `scripts/import_face_samples.py`：真机手机视频 → 抽帧 + 半自动标签初稿入库（`--wrist` 入
  wrist_view 子集，样本 planned）。
- `imgio.py`：`imread_u/imwrite_u`（np.fromfile+cv2.imdecode / imencode+tofile）、
  `open_video_u`（直接开失败则复制到 ASCII 临时文件再开）——**中文路径坑的统一规避层**，
  本模块一切图像/视频 IO 必须经它（cv2 原生 imread/imwrite/VideoCapture 在非 ASCII 路径静默失败）。

## 9. eval（精确命令与通过线）

```bash
# cwd = chengshao/（包根）
../.venv/Scripts/python.exe -m cs_mouth.eval --input assets/face_samples --report reports/mouth_eval.json
#   → exit 0。2026-09-29 空载实测：detect=1.000 reject=1.000 jaw_acc=1.000 jaw_auc=1.000
#     turn=1.000 lat_p95=39.7ms → PASS。
```

| 指标 | 通过线 | 说明 |
|---|---|---|
| 正面人脸检出率 | ≥95% | bundled+synthetic 全帧 |
| 无脸帧拒识率（附加内部门槛） | ≥95% | 报告注明 |
| 张嘴/闭嘴与人工标签一致率 | ≥90%（或 AUC≥0.9） | 几何口径比信号 |
| 转头帧触发率 | 100% | \|head_yaw\|>25° 双向 |
| CPU 单帧时延 p95 | ≤70ms | 含缩放与推理，不含文件解码 |

- **坑（负载敏感）**：latency 阈值 70ms 在**并发重负载下会假失败**——2026-09-29 实测同机
  并行全量 pytest 时 lat_p95=75.1ms FAIL，空载复跑 39.7ms PASS。验收时避免与其他重活并行。
- `--wrist-view`：对 `assets/face_samples/wrist_view/` 跑 ipd 模式（检出率 ≥95%、
  带实测距离标签帧的估距误差 ≤4cm）；**目录/标签缺失 → exit 2（接口先冻结、样本后补，
  非失败）**（eval.py:287-325）。
- `--static-distance`：读 config/static_distance.json（卷尺三点实测 0.35/0.45/0.55m），
  输出 |先验−实测|；**文件缺失 exit 2**；记录项不阻塞（超线只修 mouth_prior.json）。
