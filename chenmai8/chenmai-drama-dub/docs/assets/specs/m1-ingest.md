# M1 摄取与预处理 spec

> 状态：frozen。对照 `pipeline/m1_ingest.py` 逐行核验于 2026-09-29；
> **2026-09-30 回炉二稿**：首轮重生成试点（_regen/drama-pilot）暴露的缺口回填——收件命名 / probe.json 全
> schema / loudness 字段 / config 面 / 产物名模板 / CLI stdout / exit 2 承载 / `audio=skip` 位置修正，全部钉死。
> **2026-09-30 二轮裁定钉死**：_regen2/drama2 二轮盲重生成 7 条被迫裁定逐条收口——两处行为级
> （loudness_lufs falsy / 探针回退）已随 commit 134357d 入文；本次补钉 IngestError 消息全文（§3）、
> M1 重生成自含副本形态（§2.1）、`pipeline/__init__.py` 面归属 + 重生成 gate 形态 + 二轮输入面（§5）。
> 上游依赖：系统级 ffmpeg/ffprobe（PATH 可解析，硬依赖）；Python 侧仅 `pipeline/config.py` 的 YAML 读取
> （PyYAML，requirements.txt 未显式钉版、经依赖连带在库）——`m1_ingest`/`scaffold` 本体零第三方、零模型依赖。

## 1. 职责与边界

**做**：任意输入 → 规范化媒体三件 + probe.json + 原件收件（工作区自含）。只读写 `00_raw/` 与 `01_media/`。
**不做**：不分离（M3）、不识别（M4）、不做精响度两通归一（成片级归一属 M9；此处只做摄取级基础归一）。

**收件先行**：输入原件先 `shutil.copy2` 进 `00_raw/input.mp4`，此后**源探针与视频/音频两路处理一律以
收件副本为输入**（重放不依赖外部路径）。收件幂等：源路径与收件路径解析为同一下时跳过复制；
收件副本意外缺失时源探针回退探原路径（防御分支，二轮回填）。

## 2. 对外契约

### 2.1 配置事实源（configs/pipeline.yaml）

- M1 消费的键与键位**固定**（其余段落与本模块无关）：
  - `paths.jobs_dir`：默认 jobs 根，**相对 configs/ 目录解析**（仓内值 `../../jobs` → `<仓库根>/jobs`）；
  - `media.width` / `media.height` / `media.fps`（int）；`media.audio.asr_sr` / `media.audio.mix_sr`（int）——
    注意 `asr_sr`/`mix_sr` 在 `media.audio` **子字典**内，不在 media 顶层；
  - **顶层** `loudness_lufs`（float）——**不在 media 段内**。
- 缺省兜底（media 段或键缺失时）：`_DEFAULT_MEDIA = {width:1080, height:1920, fps:25,
  audio:{asr_sr:16000, mix_sr:48000}}`、`_DEFAULT_LUFS = -16.0`；合并语义 = media 段先浅合并、
  `audio` 子字典再合并（部分覆盖合法）；`loudness_lufs` 键缺失**或值为 0 等 falsy** 时取 -16.0
  （`cfg.get("loudness_lufs") or _DEFAULT_LUFS` 语义，二轮回填）。
- 编码参数**不是配置键**，是代码常量：libx264 **crf 18 / preset veryfast**；loudnorm 目标
  `TRUE_PEAK_DBTP = -1.5`、`LRA = 11.0`（模块级常量，M9 直接 import 复用）；容器内音轨 AAC 192k/48k/立体声。
- 读取助手行为契约（`pipeline/config.py`，冻结测试 import 面，逐名）：
  - `REPO_ROOT` = config.py 所在目录的上级（`parents[1]`，即仓库/工程根）；`CONFIG_DIR = <REPO_ROOT>/configs`；
  - `load_pipeline_config(configs_dir=None)`：读 `<CONFIG_DIR>/pipeline.yaml`（空文件视为 `{}`），并把
    `paths.*` 中的相对路径解析为绝对（相对 configs/ 目录锚定；绝对路径原样保留）后返回全 dict；
  - `jobs_dir(configs_dir=None)` = `Path(load_pipeline_config(configs_dir)["paths"]["jobs_dir"])`；
  - YAML 解析器不限实现（原实现 PyYAML safe_load），**冻结的是上述键位与解析语义**，不是解析库。
- **M1 重生成自含副本形态**（二轮裁定钉死）：重生成范围内 `configs/pipeline.yaml` 允许**只写 M1 消费段落**——
  `schema_version: 1` + `paths.jobs_dir: ../../jobs` + `media` 段（width 1080 / height 1920 / fps 25 /
  audio.asr_sr 16000 / audio.mix_sr 48000）+ 顶层 `loudness_lufs: -16`；其余段落（clips_dir / models_dir /
  label_zone / erase / subs / speed_window / m8 / m9 等）不属 M1 面，可不复制（spec 上文已明言
  「其余段落与本模块无关」）。M1 消费键的仓内值即上列字面值（configs/pipeline.yaml），
  二轮重生成副本（_regen2/drama2）逐键一致。

### 2.2 产物命名（冻结）

- 视频：**`video_{W}x{H}_{fps}fps.mp4` 模板，文件名随 targets 联动**（默认 targets 下即
  `video_1080x1920_25fps.mp4`，与 scaffold `EXPECTED_FILES` 槽位一致；targets 改变则名字随之改变）。
- 音频两路固定名：`audio_48k.wav`（混音底座）、`audio_16k.wav`（识别用）。
- 收件：`00_raw/input.mp4` **固定名**——任意输入容器一律此名（AVI/m4a 输入也叫 input.mp4，不保留原扩展名）。
- probe.json：`01_media/probe.json`。

### 2.3 规范化目标

- 视频 = mp4/H.264，滤镜链**逐字**（W/H/fps 代入）：
  `scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,fps={fps},setsar=1,format=yuv420p`
  ＋ `-c:v libx264 -preset veryfast -crf 18 -movflags +faststart`、`-map 0:v:0`（等比缩放 + 黑边 pad + 恒定 fps + 方像素 + yuv420p）。
- 音频两路：
  - **混音底座** `audio_48k.wav`：`-vn -af loudnorm=I={lufs}:TP={TP}:LRA={LRA}:print_format=summary
    -ar {mix_sr} -ac 2 -c:a pcm_s16le`——loudnorm **动态单通**基础归一；输入实测响度从该步 **stderr 的
    summary** 正则抓取；
  - **识别用** `audio_16k.wav`：**由 48k 产物降采样派生**（非从源直转，保证两路同源同增益）：
    `-ar {asr_sr} -ac 1 -c:a pcm_s16le`。
- 视频产物**容器内音轨**：仅统一容器编码 AAC 192k/48k/立体声（`-map 0:a:0 -c:a aac -b:a 192k -ar 48000 -ac 2`），
  **不做响度处理**——该轨最终被 M9 混音替换；源无音轨时 `-an`。
- 容错：
  - **纯音频输入**（无视频轨）→ 第二输入 `-f lavfi -i color=black:s={W}x{H}:r={fps}` 补黑底视频轨
    （`-map 1:v:0`），时长以音频为准 `-t {源时长+0.05:.3f}`（+50ms 余量防切尾帧）；音轨照常出双路产物。
  - **无音轨**（纯视频输入）→ 跳过两路音频产物（`01_media/` 不出现 audio_48k/16k.wav）；
    probe.json 如实记录 `outputs.audio_mix=null`、`outputs.audio_asr=null`、`loudness=null`；
    **`audio=skip(源无音轨)` 字样出现在 CLI stdout，probe.json 里没有这个字段**。
  - 既无视频也无音轨 → IngestError（exit 1）。
- 流型判定：ffprobe 流清单先剔除封面图（`codec_type=video` 且 `disposition.attached_pic` 非零），
  再判定 has_video/has_audio；probe.json 记录的 streams 均为剔除后的真实流。

### 2.4 probe.json schema（工作产物，非冻结契约；M3 输入回退 / M9 master 时长的口径根）

- 顶层键（8 个）：`ep`、`module`（恒 `"m1_ingest"`）、`schema_version`（恒 `1`）、`targets`、`source`、
  `outputs`、`loudness`、`durations`。
- `targets` = `{width, height, fps, asr_sr, mix_sr, loudness_lufs}`（本步实际生效值，非配置回显）。
- `source` = `{path（源绝对路径 str）, container（format.format_name）, duration_s, has_video, has_audio,
  streams（剔除封面后的真实流清单）, format（ffprobe format 原始 dict）}`。
- `outputs.video / outputs.audio_mix / outputs.audio_asr` = 产物 ffprobe 摘要（无音轨时 audio_mix/audio_asr
  为 `null`）：`{path, duration_s, width, height, fps, video_codec, audio_tracks, audio_codec, sample_rate,
  channels, n_streams, streams, format}`（width/height/fps/video_codec 取首条视频流；sample_rate/channels/
  audio_codec 取首条音轨；无对应流时为 `null`）。
- `loudness` = `null`（源无音轨）或 `{input_integrated_lufs, input_true_peak_dbtp, input_lra,
  input_threshold_lufs, mode: "loudnorm-single-pass", target_lufs, true_peak_dbtp: -1.5, lra: 11.0}`；
  四个 `input_*` 从 loudnorm stderr summary 按标签 `Input Integrated / Input True Peak / Input LRA /
  Input Threshold` 正则抓取，**取不到或值为 `-inf`/`nan` 时该字段为 `null`**（静音输入如实 null，不报错）。
- `durations` = `{source_s, video_s, audio_mix_s, audio_asr_s, max_abs_delta_s}`；
  时长口径 = `format.duration`（round 3 位小数），缺失时取各流 duration 最大值（仍无则 0.0）；
  `max_abs_delta_s` = 各产物与源 |Δ| 的最大值（round 3，无音频产物时只算 video；无任何产物时 `null`）。
- 写盘：`json.dumps(..., ensure_ascii=False, indent=2) + "\n"`（utf-8；probe.json 不走契约写盘原语）。

## 3. CLI（冻结形态）与退出码

```
python -m pipeline.m1_ingest --ep ep01 --in clips/ep01_raw.mp4 [--jobs-dir <dir>]
```

- 退出码：**0** 成功；**1** 媒体处理失败（IngestError，消息携工具 stderr 尾 2000 字符；「输入不存在」
  与「既无视频轨也无音轨」同为 IngestError）；**2** 用法错误——由 **argparse 承载**：缺 `--ep`/`--in` 时
  `parse_args` 直接 `SystemExit(2)`，`main()` 不捕获（`python -m` 下进程退出码 2）。
- stdout 成功**两行**（冻结测试断言含 `OK m1_ingest {ep}` 前缀）：
  - 第一行 `OK m1_ingest {ep}: ` + 逗号拼接的 parts，**parts 顺序**：`video {dur}s {W}x{H}@{fps}` →
    `audio_48k {sr}Hz/{ch}ch` → `audio_16k {sr}Hz/{ch}ch` → `audio=skip(源无音轨)`（仅无音轨时）→
    `loudness in={实测}→{目标} LUFS`（仅实测非 null 时）；后三项按存在性追加；
  - 第二行 `   probe.json → <01_media 绝对路径>`（三个前导空格）。
- stdout 失败一行：`FAIL m1_ingest: {IngestError 消息}`，exit 1。
- IngestError 消息全文**冻结为以下五种**（二轮裁定钉死；与 `pipeline/m1_ingest.py:73/80/83/264/281` 逐字一致，
  其余文案措辞不得自由发挥）：`未找到可执行文件 {exe!r}（请确认 ffmpeg 已安装并在 PATH）`（which 落空，:73）；
  `{exe} 超时（>{timeout_s:.0f}s）: {cmd 前 6 个 token}...`（TimeoutExpired，:80）；
  `{exe} 退出码 {rc}: {cmd 全量}` + 换行 + `{stderr 尾 2000 字符}`（:83）；
  `输入不存在: {src}`（src 为 resolve 后绝对路径，:264）；`输入既无视频轨也无音轨: {src}`（:281）。
- 子进程纪律：统一 utf-8 解码（errors=replace）+ timeout（媒体步默认 1800s，ffprobe 300s）；
  `shutil.which` 找不到 ffmpeg/ffprobe 即 IngestError。
- 程序化 import 面（冻结测试逐名依赖）：`pipeline.m1_ingest.FFMPEG` / `FFPROBE`（值即 `"ffmpeg"`/`"ffprobe"`，
  PATH 解析）、`IngestError`、`ffprobe_json(path) -> dict`（`ffprobe -v error -show_format -show_streams
  -print_format json`，timeout 300s）、`ingest(ep, src, jobs_dir, cfg=None) -> probe dict`、
  `main(argv) -> int`；`pipeline.config.REPO_ROOT`、`pipeline.config.jobs_dir()`。

## 4. eval

```bash
.venv/Scripts/python.exe -m pytest tests/test_m1.py    # → 7 passed
```

7 用例：`test_ingest` / `test_probe_json_metadata` / `test_default_jobs_dir_resolution` /
`test_cli_subprocess` / `test_cli_missing_input` / `test_video_only_input` / `test_audio_only_input`。
**模块级 skipif**：`shutil.which(FFMPEG)` 或 `shutil.which(FFPROBE)` 解析不到即整模块 7 skipped——
门禁必须保证 PATH 可解析 ffmpeg/ffprobe（本机在 `D:/tools/bin`；gate_b0 ① 有 FFMPEG_FALLBACK_DIRS 兜底注入）。
通过线（§4 M1 冻结）：输出存在；ffprobe 断言分辨率/fps/采样率；时长差 ≤0.2s。
注意 `test_default_jobs_dir_resolution` 会写真实共享 `jobs_dir()/ep02` 工作区并在结束时自清理。

## 5. 重生成注意事项

- `durations.max_abs_delta_s` 是 M3（输出时长=输入）与 M9（master 时长基准）的口径根。
- 中文路径：ffmpeg 子进程经 argv 直传路径在本机实测可用；但 cv2/facemesh 系不行（见 m2/m5 spec）。
- M1 依赖 `pipeline/scaffold.py` 的 `create_workspace(ep, jobs_dir)`（幂等建 13 层骨架，不预生成任何文件）
  与 `ep_dir(ep, jobs_dir)`（集 ID 白名单校验，`^[A-Za-z0-9][A-Za-z0-9._-]*$`）——13 层布局与
  EXPECTED_FILES 全表见 [contract-io §3](contract-io.md)。
- 白名单外 ep：`ep_dir` 抛未捕获 `ValueError`（不在 IngestError 之列，进程 exit 1 带 traceback）；
  校验发生在建任何目录之前。
- 素材与工作区：`clips/`、`jobs/` 不入公开仓（.gitignore）；测试素材由 pytest 自备（ffmpeg lavfi 合成 3s）。
- `pipeline/__init__.py` **不属 M1 冻结面**（二轮裁定钉死）：M1 重生成范围只要求包标记（import 期零重型依赖、
  零 M1 符号）；仓内现值为 contracts 轻量再导出面（`from pipeline import contracts` +
  34 符号 `__all__` + `__version__="0.1.0"`，pipeline/__init__.py:8/45/47），归 contract-io / m2-ocr
  spec 面所有——「torch 先于 paddle」的进程级 bootstrap 在 `pipeline/m2_ocr.py:27` 的 `bootstrap()`
  （m2-ocr spec §4），**不在 `__init__.py`**，勿误置入。
- 重生成门（gate）**形态钉死**（二轮裁定钉死，_regen2/drama2/gate.py 即此形态）：①冻结测试 sha256 运行前后
  各检一次（tests/test_m1.py = `00e54b184e4e8ddcf2cd8ab5f45089cb879668446c239d6fd08334cb6577b205`，
  变动即 FAIL）；②PATH 前置 `D:/tools/bin` 后 `shutil.which` 预检 ffmpeg/ffprobe（落空即 FAIL）；
  ③pytest 结束后校验输出无 skipped 行——**skipped 即 FAIL**，防「有跳过、无失败」假绿；
  spec §4 命令逐字复跑在 gate 之外另行执行。
- **二轮盲重生成输入面**（二轮裁定披露钉死）：回炉后 spec + 冻结测试（逐字节复制 + sha256 前后核）+
  configs / 契约文档；实现期间禁读原仓实现代码与试点实现代码。同一 agent 先回炉后实现无法达成跨 agent
  意义的全盲，纪律底线 = 二轮实现期间**不重读任何实现代码**（原仓 `pipeline/*.py` 与 `_regen/drama-pilot`
  实现均不得打开）——这是本模块重生成时对「盲」的操作性定义。
