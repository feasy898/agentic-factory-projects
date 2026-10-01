# oss-manifest —— 上游开源项目清单（内部文件，勿入公开仓库）

> 核实日期：2026-09-28。核实方式：WebFetch GitHub/PyPI 官方页面 + WebSearch（标注见"备注"列）。
> 纪律：未来公开仓库内**不得出现本文件及任何上游项目名**；对外一律用中性内部名（cs_* / 澄勺）。
> 法务统一在赛前做一次全量扫描（见 开发指令.md §10）。

## 一、核心依赖（MVP 必装，本机 Windows 开发）

| 上游项目 | URL / 包名 | 许可证 | 我们用它什么 | 商用授权需求 | 替代备选 | 备注（核实结果） |
|---|---|---|---|---|---|---|
| LeRobot | https://github.com/huggingface/lerobot ，`pip install lerobot==0.6.1` | Apache-2.0 | **v3：单从臂电机控制适配（so101_follower）与标定**；数据集格式与 ACT 训练/推理入口（`lerobot-train --policy.type=act`）为延后用途；遥操作/采数暂不使用（无主臂） | 无需（宽松） | feetech 官方 SDK 直连（传输层回退，见 开发指令.md §9） | PyPI 0.6.1，2026-08-03 发布；Python≥3.12；extras：`core_scripts`（record/replay/calibrate）、`training`、`feetech`、`viz`(rerun)。Windows 下视频解码自动回退 pyav（无需 ffmpeg）；官方文档含 PowerShell venv 激活路径，但**真机 Feetech 控制在 Windows 属少见路径，D3 需实测**（风险见 开发指令.md §9） |
| SO-ARM100/SO-101（TheRobotStudio） | https://github.com/TheRobotStudio/SO-ARM100 | 仓库许可 **Apache-2.0**（概念文档猜测 CERN-OHL，**经核实为 Apache-2.0**，clone 后以 LICENSE 文件为准再复核一次） | 机械臂结构件 STL、URDF/仿真文件（repo 有 Simulation/ 目录，clone 时确认内容）、装配指南（HF docs so101）、量规 | 结构件自印/购买套件无额外限制；整机对外销售仍建议法务复核 Apache-2.0 的商标/署名条款 | 其他开源臂（Koch v1.1、Franka 太贵） | SO-101 为 SO-100 后继版（改进走线、免拆齿轮、leader 电机升级）；套件卖家列表含中国卖家 NeoBot、Seeed(AliExpress) 等 |
| MuJoCo | `pip install mujoco==3.14.0` | Apache-2.0 | 仿真、URDF 直接加载、可达空间与安全包络验证 | 无需 | PyBullet（维护差，不推荐） | PyPI 3.14.0 有 Windows wheel；库本体已捆绑，免下载二进制 |
| ikpy | https://github.com/Phylliade/ikpy ，`pip install ikpy` | **Apache-2.0**（已核实） | 逆运动学（URDF 加载，`Chain.from_urdf_file`），纯 Python 跨平台 | 无需 | placo（Rhoban，BSD-2，QP-based，C++/pybind，Windows wheel 需验证）；Pinocchio（BSD-2，重） | ikpy 近期加入 MJCF 支持与 JAX 后端，活跃；py≥3.10。主选 ikpy，placo 为可达性分析备选 |
| MediaPipe（Face Landmarker） | `pip install mediapipe`；模型 `face_landmarker.task`（float16 latest）下载自 `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task` | Apache-2.0（代码与官方 .task 模型） | 口部 478 三维关键点 + 52 blendshape（jawOpen/皱眉），张嘴/闭嘴/转头检测 | 无需 | OpenFace 类（难装）、3DDFA（许可需查） | 官方文档确认 478 点 + 52 blendshape；Python 支持以安装时实测为准（3.12 wheel 存在性 D1 验证，若不可用则给 venv 单独用 3.11，本机 3.12.10，另装 3.11 也允许） |
| pyorbbecsdk | `pip install pyorbbecsdk2`（**注意包名带 2**，import 名 `pyorbbecsdk`） | Apache-2.0 | 奥比中光 Gemini 系列深度相机驱动，取口部深度。**v3：不使用**（无深度相机，mono 为演示主路径）；D1 已装 2.0.18 留存无害，机构版高配线再启用 | 无需（底层 OrbbecSDK v2 随 wheel 分发，随仓库 Apache-2.0） | librealsense（`pyrealsense2`，Apache-2.0，Intel/RealSense 独立公司维护） | 官方 README 确认：Windows 10+ x64 有预编译 wheel，Python 3.8–3.13；对应 SDK v2.5.5（2025-10）。备查：届时选 Gemini 2 档即可，勿买 335 工业档 |
| py_trees | `pip install py-trees==2.6.0` | BSD-3-Clause | 行为树编排（选碗→舀取→检查→送达→咬合→撤回→记录） | 无需 | 自己写状态机（不推荐，行为树可视化利于答辩） | 2.6.0，2026-09-10 发布，py3.10/3.12/3.14；纯 Python 不依赖 ROS；README 注明 "YMMV with Windows"（纯 Python，风险低） |
| Rerun | `pip install rerun-sdk` | **Apache-2.0 OR MIT 双许可**（已核实） | 采数/调试可视化（图像流+关节数据流） | 无需 | Open3D、自绘 matplotlib | 开源核心免费（open-core，商业版为 Rerun Hub，我们不用） |
| FunASR + SenseVoiceSmall | `pip install "funasr>=1.3.26"`；权重从 ModelScope/HF 拉 | 代码 MIT；**SenseVoiceSmall 权重为 FunASR 模型许可**（官方明确允许商用，需遵守署名/模型名条件，微调衍生可不公开） | 中文语音识别（下一口/等一下/吃饱了/选菜），CPU 可跑 | 权重商用需保留许可条款（如不修改模型名） | sherpa-onnx + SenseVoice 量化版（更轻）；whisper（慢） | 已核实：非流式、单次≤30s、CPU 有 ONNX/sherpa-onnx 路径；Windows 主路径为 funasr+torch CPU（D1 实测） |
| OpenCV | `pip install opencv-python` | Apache-2.0 | 相机采集、ArUco/ChArUco 手眼标定、`cv2.calibrateHandEye` | 无需 | — | — |

## 二、参考项目（只读设计参考，不安装不构建）

| 上游项目 | URL | 许可证 | 我们借鉴什么 | 商用授权需求 | 替代备选 | 备注 |
|---|---|---|---|---|---|---|
| ada_feeding（华盛顿大学） | https://github.com/personalrobotics/ada_feeding | **BSD-3-Clause**（已核实） | 安全设计：急停看门狗（必须点击一次才算在线）、力矩传感器监控、失败状态机；动作选择库（acquisition_library.yaml 的思路）；评测方法 | 仅借鉴思想，不复制代码，无需授权 | 康奈尔 FLAIR 论文（无代码依赖） | ROS2 Humble 专属，Windows 不可运行 → **只 clone 阅读**，不进构建 |
| ACT（tonyzhaozh/act） | https://github.com/tonyzhaozh/act | MIT（clone 时复核） | 参考原论文超参；实际训练走 LeRobot 内置 `policy.type=act`，不直接用此仓 | 无需 | diffusion policy（lerobot[diffusion]） | LeRobot 已集成 ACT，此仓仅备查 |
| SmolVLA | LeRobot 内置 `pip install 'lerobot[smolvla]'` | Apache-2.0 | 可选：语言条件策略（"我想吃芋泥"直接进策略）。V100S-32GB 理论可 LoRA，**延后不进 MVP** | 无需 | openpi π0.5（Apache-2.0，LoRA 需 22.5GB+ 显存，V100 2×32G 或可拆分，风险大，不进 MVP） | 概念文档的三个"最新接口待核实"之一：已核实为 lerobot extras 集成方式 |

## 三、数据集（有许可证陷阱，重点标注）

| 数据集 | URL | 许可证 | 用途 | 商用授权需求 | 替代备选 | 备注 |
|---|---|---|---|---|---|---|
| 自采示教数据（LeRobotDataset 格式） | 本地/自有 | 自有，无限制 | ACT 舀取训练 | 无 | — | 采集协议见 training-plan.md |
| 自采勺上帧 + 自动标注 | 本地/自有 | 自有 | 勺上检测分类器 | 无 | — | 标注协议见 training-plan.md |
| FoodSeg103 | HF `aimagelab/FoodSeg103` 等 | **仅限研究/非商用**（经核实，多源综述确认；下载前以 dataset card 原文为准） | 仅用于**研究性训练与评测**勺上检测分类器的补充数据 | **不可商用交付**：用其训练的权重不得作为商业产品交付；参赛演示属研究范畴可用，但商用版需自建数据重训 | 自采数据为主，FoodSeg103 仅作数据增强/预训练 | 如实记录；训练产物若商用需重训（已在 training-plan.md 标注） |
| UEC-FoodPIX Complete | 九州大学 Food Image Recognition 站点 | **仅限研究/非商用**（经核实） | 同上（备选，可不用） | 同上 | 同上 | 优先级低于 FoodSeg103 |
| LeRobot Hub 社区 SO-100/101 数据 | HF hub | 逐数据集不同（多为 Apache-2.0/MIT，逐个核对） | 可选：预训练/对照，不进 MVP | 若引用需逐个记录 | — | MVP 不依赖 |

## 四、间接依赖（跟随 pip，公开前法务全扫）

| 包 | 许可证（常见，安装时以 METADATA 为准） | 备注 |
|---|---|---|
| torch / torchvision | BSD-3 | Windows 默认 CPU wheel；GPU 机装 cu126/cu128 Linux wheel（V100 = sm_70，受支持） |
| fastapi / uvicorn | MIT / BSD-3 | 看板后端 |
| pyserial / pynput / deepdiff（lerobot[hardware]） | BSD / **LGPL-3.0(pynput，以 METADATA 为准)** / — | 遥操作键鼠映射；pynput 许可证在法务扫描清单中单独确认 |
| numpy / scipy / pydantic | BSD-3 / BSD-3 / MIT | — |
| pyav | BSD-3 类（以 METADATA 为准） | lerobot 在 Windows 的视频解码回退 |
| TTS：pyttsx3（Windows SAPI 离线）/ 备选 piper | MPL-2.0(pyttsx3，以 METADATA 为准) / MIT(piper 权重逐个看) | CosyVoice（Apache-2.0 代码，权重另计）延后，MVP 不用 |
| sqlite3（stdlib）、Chart.js（前端 vendor 本地） | 公有领域(stdlib) / MIT(Chart.js) | Chart.js 单文件下载后放 `cs_dashboard/static/`，离线可用，保留其 MIT 头部注释 |

## 五、待复核清单（诚实标注，D1 复核）

1. ~~SO-ARM100 仓库 LICENSE 原文~~ **已复核（2026-09-28，D1，读 `_vendor/SO-ARM100/LICENSE` 原文）**：确认为 **Apache-2.0**，概念文档的 CERN-OHL 猜测不成立，以原文为准。
2. mediapipe 对 Python 3.12 的 Windows wheel：**已验证可用（2026-09-28 实装 mediapipe==1.0.1 于 py3.12.10 venv，import 成功）**。
3. lerobot 单从臂 Feetech 控制（so101_follower）在原生 Windows 的可用性——官方文档有 Windows venv 说明但示例偏 Linux/macOS/WSL；**回退**： feetech 官方 Windows SDK 直连舵机（FeetechArm 只换传输层，接口不变）；USB 相机/语音/看板不受影响。
4. LeRobotDataset 具体格式版本号（0.6.x 生成的格式以 `lerobot-dataset-viz` 能加载为准，训练/评测脚本不硬编码版本号）。
5. pynput/pyttsx3/pyav 的许可证原文（法务扫描项）。

## 六、上游克隆锁定 commit（D1 实测，2026-09-28）

克隆位置：`repo/_vendor/`（gitignore，不入公开仓库）。方式：hk-gateway 中转 `git clone --depth 1`，
克隆后 `git rev-parse HEAD` 锁定，本地副本 commit 已逐一核对一致。
中性对应关系见公开仓库 `chengshao/reports/upstream_lock.md`。

| 上游项目 | 锁定 commit | 许可证（本地 LICENSE 原文复核） | 备注 |
|---|---|---|---|
| huggingface/lerobot | `e595b7902714ba51f91e47523f66f89c5181b649` | Apache-2.0 | pip 同步装 0.6.1（实装成功，含 core_scripts/training/feetech extras） |
| TheRobotStudio/SO-ARM100 | `5f6d2b876a53a4872e405b991dd925556c9e38a4` | Apache-2.0 | 克隆内确认存在 `Simulation/` 目录（§5.1 回退链第一级成立） |
| personalrobotics/ada_feeding | `0e91e8d33836ef675217ced4690e1e913dbbedda` | BSD-3-Clause（LICENSE.md） | 只读参考，不安装不构建 |
| tonyzhaozh/act | `742c753c0d4a5d87076c8f69e5628c79a8cc5488` | MIT（Copyright (c) 2023 Tony Z. Zhao） | 只读超参对照 |

同日环境实装记录（Python 3.12.10 venv，清华 PyPI 镜像，`pip check` 干净）：
mujoco==3.14.0、py-trees==2.6.0、mediapipe==1.0.1、funasr==1.4.16（满足 >=1.3.26）、
lerobot==0.6.1、torch==2.11.0+cpu、torchvision==0.26.0、pyorbbecsdk2==2.0.18（import 名 `pyorbbecsdk`）、
opencv-python==5.0.0.93、numpy==2.2.6、scipy==1.18.1、ikpy==4.1.0、rerun-sdk==0.33.1、
fastapi==0.141.1、uvicorn==0.54.0、pydantic==2.13.5、pyttsx3==2.99、pytest==9.1.1。
