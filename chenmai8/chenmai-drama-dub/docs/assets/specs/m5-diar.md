# M5 镜头切分 + 说话人聚类 + 正脸近景判定 spec

> 状态：frozen（T7）。对照 `pipeline/m5_diar.py`、`pipeline/_scdet_net.py`、`pipeline/_voxdia_net.py`、
> `pipeline/_facemesh_face.py`、`configs/models.yaml`（shot-cut/voxdia/facemesh/actspk 条目）核验于 2026-09-29。
> 组件中性名：shot-cut / voxdia / facemesh / actspk。

## 1. 职责与边界（四链路，全本机 CPU）

1. **镜头切分**（shot-cut）：视频逐帧 48x27 RGB → 单帧转场概率 → >0.5 局部峰为切点 + 0.8s 最小镜头守卫 →
   C1 `shots.json`（`faces` = 镜内最大并发脸数）+ `02_shots/frontal_closeups.json` 正脸近景镜头表
   （C1 schema 冻结不含正脸字段，故独立落盘）。架构自实现（`_scdet_net.py` 中性名自实现，
   state_dict 键严格对应 strict=True 装载），末帧补齐 100 帧倍数、单前向全片概率。
2. **说话人嵌入聚类**（voxdia）：说话段窗口（**B1 规则 10：窗口切分归 M4/VAD，本模块不重切**；
   无 diar.jsonl 时能量 VAD 兜底：帧 25ms/hop 10ms/间隙 ≤0.30s 桥接/最短段 0.40s，过短标 unknown）→
   16k 人声切片 → 192 维嵌入（kaldi 口径 fbank 纯 torch 复刻 + CMN + L2）→ 余弦亲和谱聚类 →
   回填 `04_dial/diar.jsonl` 的 `speaker`（spkN）。说话人数 = kNN 稀疏图（k=⌈√n⌉−1）拉普拉斯特征值间隙估计，
   上限 = 登记角色数+1；平均余弦 <0.30 判全 unknown。
3. **人脸/正脸近景**（facemesh）：478 点网格 + 头部姿态（几何代理 ∨ 4x4 姿态矩阵 RQDecomp3x3 欧拉，
   **逐轴取 |较大|**——矩阵法对整图透视编辑过钝，T7 实测 45° 错切 yaw 仅 ~12°）；
   正脸 = |yaw|/|pitch| ≤25°（configs/pipeline.yaml `lip.frontal_yaw_deg`，lip 段唯一事实源）；
   近景 = 框高 ≥1/4 画幅（`lip.min_face_height_ratio`）；IoU 贪心轨迹关联。
4. **主动说话人**（actspk MVP）：轨迹嘴部开合比在说话窗内打分；单轨迹直接绑定、多轨迹取嘴动最大；
   合成静帧无信号时如实退化为"无在说话人脸"（模型化 ASD 集成列后续批次，models.yaml actspk.runtime_notes）。
5. **C2 回填**（`upsert_jsonl` 原子替换）：`speaker`/`char_id`（经 `05_cast/speaker_map.json` 绑定表）/
   `overlap`（段窗两两时间交叠 >0.2s 才判真）/`face`（覆盖 ≥50% 窗口的轨迹多数票+中位框）/
   `shot_id`（句中点回填真实镜头）。
6. **voicebank 子命令**：`voice add --cast ep01 --char char_nan --wav ref.wav`（复制参考音频入
   `jobs/<cast>/05_cast/voicebank` + 登记 configs/voices.yaml + C3 CastBook 强校验回写 + 参考时长 10–15s
   越界 WARN）/`voice list`/`voice bind --spk spk0 --char char_id`。

## 2. 线程帽与实测（models.yaml runtime_notes 摘要）

- voxdia **torch 线程帽 8**：64 核默认全开互踩，7.4s 句嵌入 49.6s → 8 线程 0.25s（同 m3 threads=16 教训）。
- fbank 数值对拍 GPU 机参照实现 max_abs≈2.1e-4，参照固化为 `tests/fixtures/fbank_ref.npy` 回归件
  （torchaudio 官方轮子与本仓 torch 2.14 不兼容故手写）。
- 嵌入区分度实测：同人余弦 0.95+ / 跨人 0.23。
- shot-cut CPU 16 线程 1500 帧块前向。

## 3. Windows 路径坑（复述，重建必踩）

- facemesh 运行时 C++ 层打不开非 ASCII 模型路径 → `_facemesh_face.py` 复制到 `%TEMP%` ASCII 副本装载
  （T7 实测 FileNotFoundError）。
- cv2.imread 不支持非 ASCII 路径 → `np.fromfile + cv2.imdecode`；`cv2.VideoCapture` 不受影响。

## 4. eval

```bash
.venv/Scripts/python.exe -m pytest tests/test_m5.py    # → 13 passed（T13 记录 72.84s）
```

冻结线（§4 M5）：①diar 一致率（时长加权最优映射）≥0.85（合成双人轮替样本实测 1.000，聚类数=2）；
②切分召回 ≥0.8（±0.4s，实测 8/8）；③正脸近景逐镜一致 ≥80%（实测 9/9）；④C2 回填 speaker/face/shot_id
逐句核验；⑤纯函数/姿态分解/谱聚类/VAD 单测；⑥fbank parity 对拍（参照缺失 skip，非冻结线）；
⑦facemesh 真人像推理冒烟 + voicebank CLI 子进程。
已知边界：eval 素材为合成人脸场景（真脸仅静态公版人像）；全片真人口播素材的 ASD/正脸逐镜一致率待自拍素材验收。

## 5. 重生成注意事项

- 依赖钉版（requirements.txt）：facemesh 运行时 1.0.1（仅 tasks API）、scikit-learn==1.9.1
  （谱聚类）、scipy==1.18.1（特征值间隙）。真名与安装源只登记 requirements.txt；运行时经拼接构造动态加载。
- 权重：`models/shot-cut`（HF 镜像直下 sha256 前缀登记）、`models/voxdia`（ModelScope 直下）、
  `models/facemesh`（运行时 + face_landmarker task 包）；均不入公开仓。
- voicebank 的 `05_cast/speaker_map.json` 是 spkN→char_id 绑定表（模块工作产物，非冻结契约）。
