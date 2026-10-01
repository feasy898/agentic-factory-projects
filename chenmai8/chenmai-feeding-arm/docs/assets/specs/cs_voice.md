# cs_voice spec（交互层：VAD → 离线 ASR → 关键词意图 → TTS 播报）

> 状态：**frozen**（2026-09-29 eval 实测 20/20 全对、exit 0）。本页对照 `chengshao/cs_voice/`
>（vad.py / asr.py / intent.py / tts.py / link.py / _compat.py / eval.py）逐行核验于 2026-09-29；
> **2026-09-30 订正**：§6 优先级表述依代码订正——select 不在规则表内，实为规则表
> 全未命中后的兜底（全表最低优先级），旧文「done > select > pause > …」有误。

---

## 1. 职责与边界

**做**：麦克风常驻采集 → 能量 VAD 分段 → CPU 离线 ASR → 关键词意图解析 → 契约 `VoiceIntent`；
TTS 播报确认语；无麦克风/无声卡环境自动降级为注入模式（主链路可用）。

**不做**：不做流式识别（非流式，短句 ≤30s 场景）；不做复杂 NLU（关键词规则，
否定句局限见 §4）；不联网（模型本地缓存后全程离线）。

## 2. 冻结接口（link.py，开发指令 §3.2）

```python
class VoiceLink:
    def start(self) -> None        # 后台采集线程；麦克风不可用→降级注入模式（只打日志不抛错）
    def poll(self) -> VoiceIntent|None   # 非阻塞取最近意图：清空积压只留最新一条
    def say(self, text: str) -> None     # TTS 播报（异步语义见 §5）
# 注入接口（契约外只增，mock/e2e 用）：
inject_intent(intent) / inject_text(text) -> VoiceIntent / inject_audio(path) -> VoiceIntent
```

- 采集线程：`sounddevice` InputStream 16kHz 单声道 float32，blocksize 30ms、每次读 60ms；
  VAD 判静默时 `feed()` 继续，收口后 `take_utterance()` 整句送 ASR（link.py:113-138）。

## 3. VAD（vad.py，无 webrtcvad 依赖，纯 numpy）

| 参数 | 缺省值 |
|---|---|
| 帧长 | 30ms |
| 门限 | −38 dBFS（RMS 分贝）；自适应开启时 `max(−38, 噪声底+8dB)` |
| 噪声底跟踪 | 只取安静帧，慢速下漂 `0.995×旧+0.005×新` |
| hangover（语音后保持） | 400ms |
| pre-roll（预卷防句首截断） | 300ms |
| 最短有效语音 | 250ms（不足整句丢弃） |

- 收口时记录有效语音帧数（预卷/滞回不计入时长判定，vad.py:82-89）。
- `take_utterance()`：仍在说话返回 None；段结束返回含预卷的整段波形。

## 4. ASR（asr.py，双后端回退链）

```
AsrEngine(backend="auto") 加载顺序：funasr → sherpa-onnx（§9 回退）；全失败 RuntimeError。
```

- **主后端 funasr**：`AutoModel(model=本地缓存或 "iic/SenseVoiceSmall", device="cpu")`；
  模型 id 可经 env `CS_VOICE_ASR_MODEL` 覆盖；权重经 modelscope 首次拉取后读本地缓存
  （缓存布局两代都认：`<cache>/models/<org>--<name>/snapshots/<ref>/config.yaml` 或
  `<cache>/hub/<org>/<name>/config.yaml`，asr.py:80-103；命中本地则不联网校验）。
  **坑（64 核 Windows）**：torch 默认多线程互相争抢，实测 rtf 抖到 1.5+；单线程最稳最快
  （rtf≈0.25）——`torch.set_num_threads(env CS_VOICE_TORCH_THREADS 缺省 1)`，interop 线程设 1
  （每进程只允许一次，重复调用忽略）。
- **回退后端 sherpa-onnx**：env `CS_VOICE_ONNX_DIR` 指向同源 ONNX 模型目录
  （`model.int8.onnx` + `tokens.txt`，num_threads=2）；未配置则 RuntimeError。
- 识别细节：非 16k 输入先重采样（soxr，缺失时 scipy 兜底）；wav 经临时文件送推理；
  富标签 `<|zh|><|emo|>` 等统一剥除只留纯文本（asr.py:28-33）；`last_infer_s` 记录最近推理耗时。

## 5. TTS（tts.py，Windows SAPI；工程坑驱动的双通道设计）

- **合成（synth_to_wav）**：pyttsx3 `save_to_file` 走**进程级单例工作线程**串行
  （pyttsx3.init() 是进程级缓存单例且 runAndWait 事件循环不可并发/复用——同线程第 2 次或
  跨线程会互相挂起；单线程顺序 runAndWait 实测可反复执行）；同步等待，超时 60s；
  产物校验文件存在且 >44 字节（+0.3s 落盘抖动兜底）。无声卡/CI 环境也能验证 TTS 通路。
- **播放（say）**：**不碰 pyttsx3**——一次性线程内原生 SAPI COM（win32com `SAPI.SpVoice`）
  异步播报（SVSFlagsAsync），轮询 `Status.RunningState==1`，10s 硬超时；线程先
  `CoInitialize`（COM 组件非主线程必须初始化公寓）；`say()` 最多阻塞 `timeout_s`（缺省 15s）
  等真实成败回传。中文语音挑选 hints：huihui/zh-cn/chinese（缺省回退第一个）。
- 语速 `rate=190` → SAPI Rate = `(rate−190)//15` clip [−10,10]。
- TTS 不可用（缺 SAPI/无中文语音）→ `available=False` 降级记录，**绝不阻塞主链路**。

## 6. 意图解析（intent.py，关键词规则、离线可解释）

- 归一化：只去空白与标点（保留全部汉字）。
- **优先级（真实语义，2026-09-30 依代码订正）**：规则表 `_RULES`（intent.py:34-40）只含
  **五条**、顺序即优先级：`done > pause > next > resume > greet`——同句命中多条时按表序
  取最优先（`_match` 命中即返回，intent.py:89-94）。**select 不在规则表内**：仅当规则表
  五条全部未命中时才进菜名匹配（intent.py:68-78 else 分支），即 select 是**全表最低的
  兜底优先级**，不是次高。反例：同句含『暂停』『芋泥』（如「暂停，我想吃芋泥」）判
  **pause**（规则表先命中）而非 select。关键词表：
  - done：吃饱了/吃饱/吃不下了/不吃了/饱了
  - pause：等一下/暂停/等一等/等等/停一下/别动/慢一点
  - next：下一口/再来一口/来一口/喂我/接着喂下一口
  - resume：继续/接着来/可以了/接着喂
  - greet：你好/您好/在吗/嗨
  - select（兜底）：规则表全未命中后菜名命中即触发（槽位只取预注册表
    DEFAULT_DISH_REGISTRY=芋泥/南瓜粥/椰子冻，config 可扩展）；
    触发词（我想吃/想吃/来点/要吃/换个/换）仅用于置信度分档。
- 置信度常数（无校准信号，保守固定）：命中 0.95；select 带触发词 0.90 / 无触发词 0.75；
  unknown 0.30。
- **已知局限（文档化）**：否定句/复杂从句不在关键词规则能力内（"我不想吃芋泥了"会解析为
  select），由行为树确认策略兜底。

## 7. eval（精确命令与通过线）

```bash
# cwd = chengshao/（包根）
../.venv/Scripts/python.exe -m cs_voice.eval --input assets/voice_samples --report reports/voice_eval.json
#   → exit 0。2026-09-29 实测：correct=20/20 acc=1.00 max_lat=0.736s tts_ok=True
#     offline_ok=True（backend=funasr）。
```

| 指标 | 通过线 | 实测 |
|---|---|---|
| 意图正确数 | ≥18 / 20（4 条×4 类 + 4 条干扰噪声） | 20/20 |
| 单条响应时延 | ≤2.5s（CPU，含 ASR） | max 0.736s |
| 全离线 | 程序化证据 = eval 期间零外联尝试；拔网线复测属人工步骤 | outbound=0 |

- **坑**：ASR 首次加载模型耗时长（实测 model_load_s≈172s 冷缓存；本地缓存命中后秒级）——
  eval/演示前先暖一次；`torch 单线程`与 `MODELSCOPE_CACHE` 布局见 §4。
- 样本：`assets/voice_samples/`（next/pause/select/done/noise 各 4 条 wav + labels.json），
  由 `scripts/gen_voice_samples.py` 用 TTS 合成入库（离线可复生）。
