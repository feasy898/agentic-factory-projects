# asr_align —— GPU 服务（:9001，M4）

识别 + 字级对齐 + 情绪/事件 + 说话人预分段。组件对应 `configs/models.yaml`：
`asr-core` / `align-core`（阿语降级 `align-proportional`）/ `emo-tag`。

## GPU 机部署（一次性）

```bash
# 1) 独立 venv + 权重（transformers>=5.13 与 TTS/口型组的 4.52.x 不共存，
#    实测依据 data/gpu_smoke_report.json 第 4 项）
scp gpu/setup_asr_venv.sh <gpu>: /data/xdng/
#    模型/框架分发名对照见 docs/gpu_asr_align_deps.md，运行时注入 /data/xdng/etc/model_ids.env
ssh <gpu> 'nohup bash /data/xdng/setup_asr_venv.sh > /data/xdng/logs/setup_asr_venv.log 2>&1 &'

# 2) 代码部署 + 启动（nohup 常驻，日志 /data/xdng/logs/asr_align.log）
scp -r gpu-services/asr_align <gpu>: /data/xdng/asr_align
ssh <gpu> 'bash /data/xdng/asr_align/run_gpu.sh start'
```

## 接口

| 方法/路径 | 说明 |
|---|---|
| `GET /health` | 装载状态 / 设备 / 版本 |
| `POST /v1/asr_align` | multipart：`file`(wav)，`lang`(默认 zh，`ar` 走比例内插)，`text`(校对文本重对齐)，`do_align`，`do_emo` |

响应核心字段：`text`、`words[{w,s,e}]`（逐字时间戳）、`segments[{i,start,end}]`（说话人
预分段，M5 回填 speaker 的单元）、`emo{label,score}`、`events[]`、`nonverbal_hint`、
`aligner`（align-core \| align-proportional）、`timing`。

## 本机访问

服务只监听 GPU 机 127.0.0.1（该机有公网出口，不对外暴露）。本机：

```bash
bash ops/tunnel_gpu.sh start        # ssh -L 9001:127.0.0.1:9001，幂等可重跑
curl http://127.0.0.1:9001/health
python -m pipeline.m4_asr --ep ep01  # 客户端（C2 出口），或 pytest tests/test_m4.py
```
