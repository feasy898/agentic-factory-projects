B0 的 4/4 PASS 不能当作 B1 的已验证基线。冒烟产物、M1 验收和 GPU 常驻环境都没有被门禁真正卡住；音频四件套的交接方式也还没冻结。结论是需修后继续。

## A. 冒烟结论的实证强度

`data/gpu_smoke_report.json` 里 4 条 `ok: true` 都写了远端路径（`/data/xdng/smoke/artifacts/dub-tts_fp32.wav`、`lip-fast_v15.mp4`、`alt-tts-b_zh.wav`、`asr-core_fp16_transcript.txt`），仓库里没有这些文件。`seconds` 是墙钟：dub-tts 5.35 秒对应一条 8 秒参考音，lip-fast 41 秒对应 2 秒/50 帧输入。报告里没有输出时长、文件大小、校验和，也没有 `nvidia-smi` 峰值显存。`summary.all_ok` 是 `false`（5 项里 fp16 失败）。

dub-tts「没有 fp16」这个判断成立，不是把参数名写错。上游 `indextts/infer_v2_5.py` 构造函数只有 `use_bf16`；`self.dtype` 为 `bfloat16` 或空，空则关闭 autocast，骨干停在 fp32。官方速度表只有 2.5 bf16 / 2.5 fp32 两列。冒烟里的 `TypeError: unexpected keyword argument 'use_fp16'` 与这个签名一致。同文件里的情绪子模块 `QwenEmotion` 写死 `torch_dtype="float16"`，那只覆盖情绪文本小模型，不给 GPT 骨干一个 fp16 开关。加载后手动 `.half()` 没人试过，那是省显存的未测路径，不推翻 fp32 定案。

asr-core 的独立 venv 在架构上走得通：`:9001` 单独进程，`gpu-services/asr_align/run_gpu.sh` 已指向 `/data/xdng/venv-asr`。它不会让 TTS 的 transformers 4.52 和 ASR 的 5.13 装进同一个解释器。阻塞点是这条常驻路径没有被冒烟过。报告写的是主 venv `/data/xdng/venv` 临时升到 5.13.0，随后降回 4.52.1。`gpu/setup_asr_venv.sh` 还依赖仓库里不存在的 `docs/gpu_asr_align_deps.md`，以及机器本地的 `/data/xdng/etc/model_ids.env`。

- [high] `scripts/gate_b0.py:209` — 冒烟门禁只要求 `items` 里至少 4 个不同的 `model` 字符串，失败项也算通过，不看 `ok`、产物路径、时长或校验和。把通过条件改成四个指定引擎各有一条 `ok: true`，并核对该条 `artifact_path` 的文件大小与时长（音频 ≥0.3 秒，视频帧数 >0）。
- [med] `data/gpu_smoke_report.json:65` — asr-core 的 PASS 样本是英语，转写文本没有落盘，而 `configs/models.yaml:45` 登记的语种只有 `zh`。用一段中文对白重跑，把转写文本和字级时间戳写进报告。
- [low] `data/gpu_smoke_report.json:35` — fp16 失败记录与上游签名一致，骨干没有公开的 fp16 开关；显存紧时唯一没做的是加载后 `.half()`。fp32 定案保持不变，把 `.half()` 标成未测备选，不要再开一轮「参数名写错」的复查。

## B. 契约是否盖住 B1 音频四件套

C1–C8 盖住的是融合之后的句级事实，没有盖住分离、ASR、对齐、说话人四段交接。

分离：规划把 `bgm.wav` 放在 M1 的 `01_media/`，M3 规格写 `vocals.wav` + `bgm.wav`，两边都没有人声文件的目录槽。`pipeline/scaffold.py` 的 `EXPECTED_FILES` 同样没有 `vocals.wav`。M4 该读混音 `audio_16k.wav` 还是人声，没有写死。

ASR / 对齐：`:9001` 的响应是整段一个 `text`、整段 `words`、能量 VAD 的 `segments`。三者没有共同键，也没有 `utt_id`。`words` 的时间从上传音频的 0 秒起算；C2 示例是全片绝对时间（12.40 秒）。契约不要求字级时间落在该句 `[start, end]` 内，也不要求单调。

秒精度是对齐的。`pipeline/contracts.py:93` 的 `round(float, 3)` 是 1 毫秒。Qwen3-ForcedAligner 官方示例就是 `8.3f` 秒，样例落在 0.08 秒栅格上，三位小数能原样表达 0.080。M4 的验收条是 `|Δstart|≤100ms`。小数位不是缺口，时间零点才是。

说话人：`Utterance.speaker` 是可空字符串。`diar.jsonl` 只有文件名，没有 schema。`开发指令.md` 的 D2 含 M5，`workflow-proposal.md` 的 B1 批次没有 T7。说话人既没有中间契约，批次归属也不一致。

`utt_id` 唯一性不会锁住整文件重写。`dump_jsonl` 用 `"w"` 覆盖，同一批 id 再校验可以通过。它会锁住追加：同 id 再写一行，`UtteranceTable` / `SynthPlanTable` / `LipPlanTable` 直接 `ValidationError`，没有按 id 替换，也没有版本字段。C4 的键是 `(utt_id, tgt)`，同语种再追加同样失败。id 怎么从时间轴稳定生成，没有公式。

- [high] `pipeline/scaffold.py:34` — `01_media` 有 `bgm.wav`，没有 `vocals.wav`，M3 人声和 M4 输入音频没有冻结路径。在 `04_dial/` 增加 `vocals.wav`，并写明 M4 只读人声、不读 `audio_16k.wav`。
- [high] `gpu-services/asr_align/service.py:372` — 服务返回整段单文本、整段字级时间和能量分段，三者互不对齐，也生成不出 C2 的句。先冻结切句规则（OCR 时间段或 VAD 段）和「片段内时间 + 偏移 = 全片绝对时间」，再写客户端。
- [med] `pipeline/contracts.py:244` — `utt_id` 唯一性在整文件覆盖时放行，在同 id 追加时使 `validate` 失败，且没有替换原语。B1 写盘规定为按 `utt_id` 替换后整文件重写，id 用 `ep + 起始毫秒` 稳定生成。
- [med] `pipeline/contracts.py:220` — 说话人只是可空字符串，`diar.jsonl` 无 schema，D2 与 B1 批次对 M5 的归属不一致。B1 若含说话人，先补段级 schema（`start/end/speaker`）并决定 T7 是否进本批；若不含，从 B1 出口去掉说话人。
- [low] `pipeline/contracts.py:169` — 字级时间只检查 `e >= s` 且非负，不检查是否落在句区间内、是否单调。校验增加 `utt.start ≤ word.s ≤ word.e ≤ utt.end` 且按时间排序。

## C. 假绿灯

7 个 skipped 全是 `tests/test_m1.py` 模块级 `skipif`（`ffmpeg`/`ffprobe` 不在 PATH）。函数是 `test_ingest`、`test_probe_json_metadata`、`test_default_jobs_dir_resolution`、`test_cli_subprocess`、`test_cli_missing_input`、`test_video_only_input`、`test_audio_only_input`。契约 28 个加骨架 15 个等于报告里的 43。pytest 在「有跳过、无失败」时退出码仍是 0，门禁把这当成全绿。本轮没有重跑 pytest。

- [high] `scripts/gate_b0.py:164` — ① 只看 pytest 退出码，7 个 M1 测试被 `tests/test_m1.py:28` 整模块跳过仍判 PASS。输出里出现 `skipped` 即 FAIL，并检查 PATH 上的 ffmpeg。
- [high] `scripts/gate_b0.py:209` — ③ 在 `all_ok: false`、产物不在仓库内时仍 PASS，也不核对是不是 dub-tts / alt-tts-b / lip-fast / asr-core 这四个名字。与 ② 共用 `VOLTA_REQUIRED`，每条必须 `ok: true` 且 `volta_status` 为 `ok`。
- [med] `scripts/gate_b0.py:189` — ② 只要求 `fallback` 键存在、`volta_status` 非空字符串，`fail` 或 `pending` 也能过。四组件限定 `volta_status == ok`，并与冒烟的 dtype 一致（dub-tts 必须是 fp32）。
- [med] `scripts/gate_b0.py:295` — ④ 在台账缺失或附录 A 解析出 0 行时仍 PASS，只在备注里写一句。台账不可读或 0 行改为 FAIL，禁止静默降级。

## D. GPU 机配置

`/data/xdng/venv` 的脚本不是实测栈的重放。`gpu/setup_gpu.sh` 在 torch 已能 import 时直接保留；全新安装先装 `torch==2.4.1`，失败再降到 `2.4.1+cu118`，并写明「最新带 sm_70 的 cu118 是 2.4.1，因此 transformers<5」。冒烟和 `configs/models.yaml:227` 的实测是 `torch 2.5.1+cu118`。alt-tts-b 需要 `torch>=2.5`。已装好 2.5.1 的机器重跑会留下 2.5.1，再装 `transformers<5`（主 venv 这步是对的）；空机器重跑得到的是 2.4.1，冒烟栈复现不出来。

两套 transformers 的共存只在 ASR 侧写清楚了：主 venv 4.52.x 给定 TTS/口型，`/data/xdng/venv-asr` 定 5.13 给识别/对齐，两边都用 torch 2.5.1+cu118。`setup_gpu.sh:105` 的注释与此相反。除 `run_gpu.sh` 点名 `venv-asr` 外，没有一张「服务 → 解释器」表。tts/lip/mt 服务还没落地。

32GB×2 的常驻分配没有数字。规划是 `#0 = asr+mt+tts`，`#1 = 口型独占 18GB`。散落估计只有 ASR 0.6B/1.7B 约 4–8GB、mt-core 约 5GB、IndexTTS 官方 bf16 路径约 6GB（fp32 更大，冒烟没量）。`service.py` 启动即把 asr-core、align-core、emo-tag 一起载入 `cuda:0`。B1 只有这三件，单卡 32GB 放得下。asr 与 dub-tts 同时常驻在 `#0` 没有预算；`alt-tts-b` 被标到 `cuda:1`，和 lip-pro 的 18GB 独占叠在同一张卡上。

- [high] `gpu/setup_gpu.sh:88` — 全新执行安装 torch 2.4.1，与实测 2.5.1+cu118 和 alt-tts-b 的 `torch>=2.5` 不一致，脚本不能重放出冒烟环境。默认改为 `torch==2.5.1+cu118` 并在装完后断言版本与 `sm_70`。
- [high] `gpu/setup_asr_venv.sh:28` — 缺 `model_ids.env` 直接 FATAL，对照文档 `docs/gpu_asr_align_deps.md` 不在仓库；已有任意 torch 或非空权重目录就跳过，残缺安装会被一直保留。把对照文档纳入依赖安装记录，版本不符时重装，权重以文件清单校验而不是「目录非空」。
- [med] `configs/models.yaml:51` — 双 venv 方案只写在 ASR 注释里，主安装脚本仍按 2.4.1 + `transformers<5` 叙述。在 `models.yaml` 顶部加一张服务→venv→torch→transformers 表，并改掉 `setup_gpu.sh:105` 的过期理由。
- [med] `configs/models.yaml:7` — `#0` 同时放 asr、翻译、合成，`#1` 同时放 alt-tts-b 和 18GB 的 lip-pro，没有任何显存数字或互斥规则。B2 常驻 TTS 之前写下每卡预算和「lip-pro 起来时 alt-tts-b 必须退出」。

## E. Windows 两条硬约束

两条都停在文档和注释里。`requirements.txt:5` 和 `docs/setup_windev.md:52` 写了「先 torch 后 paddle」和 `enable_mkldnn=False`。`pipeline/__init__.py:4` 的做法是包导入时两边都不引，避免在 import 期踩 DLL。`cli.py` 没有先 `import torch`。全仓库 Python 里没有 `enable_mkldnn`。GPU 侧 `service.py:34` 先 import torch，但那个进程不加载 paddle。B1 的 T6（M2 OCR）会第一次在本机进程里 import paddleocr，两条都会被踩到。

- [high] `pipeline/__init__.py:4` — torch→paddle 的顺序和 `enable_mkldnn=False` 没有进入可执行代码，也没有测试守护。加一个本机 bootstrap：进程内先 import torch，OCR 构造只走封装函数并强制 `enable_mkldnn=False`，用测试锁住这两条。
- [med] `requirements.txt:28` — `ffmpeg==系统安装` 和 `pydub==不使用` 不是合法 pip 行，文档中的 `pip install -r requirements.txt` 无法重放 T0。删掉这两行，ffmpeg 检查放到独立脚本。

## F. 公开仓库卫生

附录 A 的 19 行在台账可读时都被 `BANNED_TOKENS` 的子串盖住（`qwen`、`forcedaligner`、`musetalk`、`voxcpm`、`c2pa toolchain`、`dubmt` 等都能命中对应单元格）。覆盖机制本身是通的。

漏检在三处：台账缺失时门禁放行；`tests/test_skeleton.py:191` 只扫 `pipeline/`、`configs/`、`tests/`、`README.md`、`conftest.py`，不扫 `gpu/`、`gpu-services/`、`scripts/`、`data/`；下划线变体能躲开无下划线 token。

- [med] `gpu-services/asr_align/service.py:238` — `prepare_forced_aligner_inputs` / `decode_forced_alignment` 含 `forced_aligner`，token `forcedaligner` 匹配不到。token 同时禁下划线与连字符变体，并把 `gpu-services/`、`scripts/`、`data/` 纳入 `test_skeleton.py` 的扫描面。
- [low] `data/gpu_smoke_report.json:26` — 公开报告写了附录 A 之外的传递依赖名：bigvgan、WeTextProcessing、pynini、diffusers、mmpose、mmcv、mmdet、S3FD。这些名字改成中性描述，或把该文件列入与 `docs/` 相同的依赖记录豁免并在台账补行。
- [med] `scripts/gate_b0.py:295` — 附录 A 覆盖校验在台账不可读时降级为 PASS，独立克隆发现不了 token 表脱节。独立克隆改为 FAIL 或要求提交一份只含中性名的覆盖清单。

## G. 工程债 Top 5

1. [high] 门禁假绿（pytest 跳过算过、冒烟只数名字）。阻塞把 B0 当基线派发；不改的话 B1 会沿用同一验收口径。
2. [high] 分离 / ASR / 对齐没有冻结交接（无人声路径、`:9001` 不是句级、字级时间零点不明）。阻塞 B1 的 C2 出口。契约 `extra="forbid"`，子代理不能自行加字段。
3. [high] GPU 安装脚本重放不到 2.5.1+cu118，asr 常驻 venv 没有按 `:9001` 冒烟，还缺模型 ID 文档。阻塞 T5 拉起服务。不阻塞本机先写 M1/M3。
4. [high] 先 torch 后 paddle、`enable_mkldnn=False` 只在文档里。阻塞 T6 OCR。不阻塞 GPU 上的 ASR 进程。
5. [med] `utt_id` 追加即自锁，没有稳定 id 和替换写盘。不阻塞第一次整文件写出。阻塞同句重跑和以后的断点续跑。

显存预算不在这五条里：B1 只常驻 ASR 三模型，32GB 够用。它在 B2 让 TTS 与 ASR 同时常驻之前变成阻塞项。

## 总体结论

**需修后继续。**

派发 B1 之前要先改四件事：门禁把跳过和「只数模型名」判失败；写死 `vocals.wav` 路径、切句规则和字级时间零点；在 GPU 上用 `venv-asr` 把 `:9001` `/health` 跑通，并把 `setup_gpu.sh` 对齐到 torch 2.5.1+cu118；OCR 封装落地两条 Windows 硬约束。fp32 定案和「2.5 公开 API 没有 fp16」可以保持，不必重开冒烟结论。
