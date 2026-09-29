# webui/ — M10 网页壳（批次 3）

node:http 单进程（FastAPI→node:http）；API 形状对齐（health/meta/build/jobs/qr/静态/负向 400）；
multipart 自写最小解析器并加负向测试；防 SSRF 纪律照抄（零出站请求；质检是裁判）。
selftest 语义移植：`node webui/selftest.mjs`（`python -m webui.selftest` 迁移，决策 §2.2）。
