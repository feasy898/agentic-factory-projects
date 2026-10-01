# 啡眼 BeanEye · 咖啡生豆 AI 质检台

面向海南罗布斯塔咖啡生豆的全开源桌面质检台：350g 样品铺盘双面拍摄，自动完成瑕疵豆识别计数、粒度色泽计量、按标准一键定级，输出带二维码验真的中 / 英 / 越三语质量护照，并由大模型给出加工环节溯因建议。

**核心能力**

- 双面成像逐粒分割，上下配对（每粒只计最严重缺陷，内部计数规则；标准阈值核对完成前不作为 CQI 符合性声明）
- ArUco 标定到毫米：目数分布、色差、粒数、估算重量
- 标准引擎：YAML 描述 CQI Fine Robusta / 国标 / 地标阈值，换标准不改代码
- 质量护照：每个缺陷附原图证据 + 二维码验真
- 溯因智能体：黑豆 / 酸豆 / 霉豆 / 虫蛀 → 采摘 / 发酵 / 干燥 / 仓储环节定位与改进建议（规则模板离线保底，LLM 后端为可选增强）
- 合成数据引擎：程序化豆素材 + 铺盘合成器，无真实样品阶段全程可演示、可回归

**精度与口径声明（重要）**

- 当前全部精度数字为**合成盘自洽口径**（合成真值 / oracle vs 管线输出），真机标定前
  不得对外引用为现场精度——见 `docs/calibration-error-budget.md`。
- 三套标准 YAML 均为**结构冻结 + 阈值占位**（`verified:false`），生豆到货后按
  `docs/collect_protocol.md` 采集回填（D7）；此前定级结果不作为标准符合性声明。
- 产品演示定位为「**AI 初检 + 人工复核**」辅助，最终质检结论以人工复核为准。

**仓库结构（现状）**

```
beaneye/          全部实现（Python 包）
  acquisition/    采集（Mock / USB / Synth 三源）
  calibration/    ArUco 标定与正射变换
  segment/        分割（ClassicSeg 经典 CV / OracleSeg 合成真值）
  classify/       分类（RulesV0 规则表驱动）
  pairing/        上下配对
  severity/       严重度裁决
  metrology/      计量（目数 / 色差 / 估重）
  standards/      标准引擎（YAML 规则）
  report/         质量护照生成与验真
  agent/          溯因智能体
  kb/             知识库检索（接口留桩）
  app/            FastAPI 应用、API 与单页演示 UI
  synth/          合成数据引擎（素材库 + 铺盘合成器）
configs/          托盘 / 相机 / 标准 / 规则 / 合成等 YAML 配置
docs/             自采协议（collect_protocol）、校准误差预算等
docs/assets/      资产包：manifest / CONTRACTS / REGENERATE / 逐模块 specs
scripts/          doctor 体检、验收门 gate_d1–d4、e2e 与演示脚本
tests/            逐模块 eval（508 用例）
```

> 逐模块规格、契约与整仓再生步骤见 `docs/assets/`（manifest + specs + REGENERATE）。
> 规划中（未开工）：NN 分类腿、AR 指选手选辅助、真机采集与阈值回填。
