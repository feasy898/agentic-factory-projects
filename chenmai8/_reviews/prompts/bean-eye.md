# 任务（独立第二意见评审·只读）：澄迈大赛项目「啡眼咖啡豆质检」D1-D2 审查

背景：本项目由 AI 构建流水线按 spec+eval 逐模块开发，D1-D2 已全绿（scripts/gate_d1.py、gate_d2.py）。已完成：契约+taxonomy（54 测试）、ArUco 标定（中心反投影 0.08-0.41mm、ppm ≤0.06%）、匈牙利上下配对（含两遍中位数残差矫正，P 0.995）、严重度裁决（CQI 计数）、采集源（Mock/USB）。数据集下载被 Roboflow key 阻塞（已知）。你是独立评审，不信任我们的绿灯，专找盲区。当前工作树可能包含 D3 半成品。

请阅读（相对当前目录）：
1. ../plan/开发指令.md（内部规划：契约/各任务 spec/eval/通过线）
2. scripts/gate_d1.py、gate_d2.py、doctor.py、oss_smoke.py、download_datasets.py
3. beaneye/schemas.py、calibration/、pairing/、severity/、acquisition/、taxonomy.py
4. configs/（tray.yaml、taxonomy.yaml）

评审问题（逐条回答）：
A. 自证风险：
   1) 标定精度 0.41mm 是"用合成图测自己"——真实拍摄（光照/反光/亚克力折射/豆堆遮挡 ArUco）下的退化有没有量化或至少标注？
   2) 配对 P0.995 的 fixture 场景分布是否偏窄（真实盘 300+ 粒密集接触、上下视场差异、边缘透视畸变）？
   3) 严重度裁决的 taxonomy 序与 CQI 规则原文一致性（verified:false 字段的边界）？
B. 假绿灯风险：eval 容差是否过宽；测试是否覆盖失败路径（乱序/重复检测/亚像素框抖动）。
C. 契约一致性：SingleCalib/CalibResult 组装约定的实现与上报是否一致；schemas 不变式是否真的在构造时校验（而非仅测试里）。
D. Windows 原生坑：cv2 中文路径 imencode/imdecode 是否全面执行；USB 相机热插拔。
E. 公开仓库卫生：上游名残留（taxonomy.yaml 的映射是否只留在内部）。
F. 工程债 Top5（按风险排序，注明是否阻塞素材库/合成器/分割阶段）。

输出格式：问题清单，每项 = [high/med/low] 文件:行 — 问题一句话 — 修复建议一句话。最后给总体结论（可继续 / 需修后继续）。只读，不要修改任何文件。
