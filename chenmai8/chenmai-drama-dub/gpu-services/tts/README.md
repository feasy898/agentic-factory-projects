# tts —— GPU 服务（:9002，M7）

情绪迁移合成：**音色参考与情绪参考分离**（音色=角色干净人声样本，情绪=原片该句
人声——两者可来自不同说话人，这是情绪迁移的核心用法）。组件对应
`configs/models.yaml`：`dub-tts`（主力，fp32 D1 定案）/ 备选链 `dub-tts-base` →
`alt-tts-a` → `alt-tts-b`（按 `routing.tts` 语种链依序尝试；权重未部署的链节点如实
记 skip，不伪装成功）。

## GPU 机部署（一次性）

```bash
# 1) 前置核验（主 venv torch/transformers 断言 + 权重/引擎仓核验 + 依赖补装）
scp gpu/setup_tts_service.sh <gpu>: /data/xdng/
ssh <gpu> 'bash /data/xdng/setup_tts_service.sh'
#    模型/框架分发名对照见 docs/tts_service_deps.md

# 2) 代码部署 + 启动（nohup 常驻，日志 /data/xdng/logs/tts.log）
scp -r gpu-services/tts <gpu>: /data/xdng/tts
ssh <gpu> 'bash /data/xdng/tts/run_gpu.sh start'
```

显存互斥（B2 预算表提示）：备选 B 引擎按 models.yaml 落 cuda:1，与 lip-pro 互斥
——lip-pro 启动前先停本服务。

## 接口

| 方法/路径 | 说明 |
|---|---|
| `GET /health` | 引擎装载状态 / 路由表 / 权重就位 / 每卡空闲显存 |
| `POST /v1/tts` | multipart：`text`，`lang`(默认 en)，`voice_ref`(wav 必填)，`emo_ref`(wav 可空)，`emo_alpha`[0,1]，`duration_factor`[0.5,2.0]，`engine`(auto=语种链)，`utt_id`(日志追踪)，`dry_run` |

响应核心字段：`engine`（实际命中的引擎）、`chain`+`attempts`（路由与逐节点成败）、
`wav_b64`+`sr`、**`duration_s`（产出实测时长，C 出口）**、`request.emo_ref_used`
（情绪参考是否被引擎消费——备选引擎无情绪通道时如实 false）、`timing`、`versions`。

## 本机访问

服务只监听 GPU 机 127.0.0.1（该机有公网出口，不对外暴露）。本机：

```bash
TUNNEL_LOCAL_PORT=9002 TUNNEL_REMOTE_PORT=9002 bash ops/tunnel_gpu.sh start
curl http://127.0.0.1:9002/health
python -m pipeline.tts_client --text "What do you actually want?" \
    --voice-ref voice.wav --emo-ref emo.wav --lang en --out u0007.wav
pytest tests/test_m7_tts.py        # 或 bash scripts/eval_m7.sh
```
