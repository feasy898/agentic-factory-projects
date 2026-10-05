# Hardware —— 硬件需求结论

## 结论：无需采购任何物理硬件（写"无"）

- 开发与构建：windev-01（本机，无 GPU 需求——训练延后、推理走远程 OpenAI 兼容 API；Playwright/ffmpeg/esbuild 均原生跑）。
- 训练/私有化推理（交付后）：anolis-gpu-01（2×V100S-32GB，tailnet 100.64.0.7）已有，见 training-plan.md 时数估算（≤16 GPU·时）。
- 大模型推理（若演示当天要展示自部署）：Qwen3-VL-8B fp16 单卡 V100S-32GB 可跑 vLLM（备选，不依赖；演示默认远程 API + 预录兜底）。

## 演示现场建议（非采购必需，清单备查）

| 项 | 建议 | 说明 |
|---|---|---|
| 演示手机 | 任意安卓真机 1 部（或评委自带） | 扫码玩；iOS Safari 亦可但备安卓为主 |
| 网络 | 自备便携 Wi-Fi 路由器（LAN） | 兜底：二维码指向局域网地址，无外网也能演示路径 A |
| 大屏 | HDMI 转 LCD/投影 | 5 分钟出包演示 |
| 兜底 | demo-prebuilt 静态包 + 录屏视频 | 断网/断电双保险（artifacts\demo-prebuilt，10-08 前定稿） |
| 打印 | 二维码打印纸 2 份 | 评委扫码最快路径 |
