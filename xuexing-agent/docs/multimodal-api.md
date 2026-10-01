# 阶跃星辰 API 能力矩阵（2026-09-29 实测，v0.3.0 wave3 依据）

> 凭据只从环境变量读（`STEPFUN_API_KEY`，见 `.env`，已 gitignore）。端点白名单：域名 `api.stepfun.com`，仅 https，DNS 解析后阻断私网/环回/链路本地 IP。此约束与 `mimosa` 安全扫描对齐，必须带进所有调用代码。

## 端点与实测结论

| 能力 | 端点 | 模型 | 实测 |
|---|---|---|---|
| 文本对话 | `https://api.stepfun.com/step_plan/v1/chat/completions` | step-3.7-flash / step-router-v1 / step-3.5-flash | ✅ 200（"Hi there!"） |
| **图像理解** | 同上 chat/completions，content 段 `{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}` | **step-5-preview** | ✅ 识别纯红图为"红色" |
| 图像理解（备用） | 同上 | step-3.7-flash | ⚠️ 收图但返回空 content（max_tokens≥30 也空），仅备用 |
| 语音合成 | `step_plan/v1/audio/speech` | stepaudio-2.5-tts，**voice=linjiajiejie**，response_format=mp3 | ✅ 19496 字节/句 |
| 语音识别 | `https://api.stepfun.com/v1/audio/transcriptions`（**注意不在 step_plan 路径下**） | stepaudio-2.5-asr，multipart: model+file | ✅ 格式正确（正弦波返回 "no speech found" 属预期） |
| 模型清单 | `step_plan/v1/models` | 10 个模型 | ✅ |

## 模型清单（/models 实测）

step-3.7-flash, step-router-v1, stepaudio-2.5-chat, stepaudio-2.5-tts, stepaudio-2.5-asr,
stepaudio-2.5-realtime, step-image-edit-2, step-3.5-flash-2603, step-3.5-flash, step-5-preview

## 本项目用法（冻结约定）

- 文本/视觉主力：`step-5-preview`（vision 实测唯一可用）；大批量内容生成：`step-3.7-flash` 或 `step-router-v1`（路由自动选型）。
- 所有客户端进 `src/xuexing/mm_client.py`：端点白名单常量、key 只从 `XX_LLM_API_KEY` 或 `STEPFUN_API_KEY` 读、同族 `LLMError`。
- 冒烟测试：仅当 `XX_MM_SMOKE=1` 时真调 API（默认 mock，CI/契约测试零网络）。
- MiniMax Design：本机 `AppData/Local/Programs/MiniMax Design` 为空壳目录（应用本体不存在），本地无可用的 minimax 服务；如需启用需用户提供入口。
