# M2 硬字幕 OCR + OCR↔ASR 校对 spec（含两条 Windows 硬约束）

> 状态：frozen。对照 `pipeline/m2_ocr.py`、`pipeline/ocr_wrap.py`、`docs/setup_windev.md §3`、
> `tests/test_ocr_wrap.py` 逐行核验于 2026-09-29。上游组件中性名 **cap-ocr**（真名对照仅登记于
> requirements.txt 依赖安装记录；代码内拼接构造动态加载）。

## 1. 职责与边界

**做**：字幕带采样 OCR → 帧级/行级两件产物 → 与 ASR 投票融合 → C2 出口（upsert）。
**不做**：不切镜头（M5）、不擦除（M11 只消费本模块 bbox）、不做句级去重的最后裁决（跨行冲突归 M5/M14 融合批次，
`merge_ocr_asr` docstring 已知边界）。

## 2. 冻结常量（§4 M2 原文口径；改行为先改 eval，m2_ocr.py:73-92）

| 常量 | 值 | 出处 |
|---|---|---|
| `OCR_SAMPLE_INTERVAL_S` | 0.2s 采样 | §4 M2 |
| `OCR_HIGH_CONF` | 0.9（≥ 则以 OCR 为准） | §4 M2 |
| `ASR_OVERLAP_MIN` | 0.6（重叠率 ≥60% 才配对，分母=OCR 行时长） | §4 M2 |
| `_REC_SCORE_MIN` | 0.30（帧内检出框置信门，滤台标/时间码） | 实测 |
| `_SAMPLE_SCALE` | 0.5（字幕带降采样推理；实测 1.7s/帧 vs 全尺寸 5.5s/帧，0.5 档质量不降） | T6 |
| `_MERGE_GAP_STEPS` | 2（合并允许 ≤2 个采样步断裂，桥单帧抖动） | 实测 |
| `_ROW_SPLIT_RATIO` | 0.7（帧内多框按 y 中心聚行的行距阈值） | 实测 |
| `PLACEHOLDER_SHOT` | "s0000"（M5 就绪前占位，与 M4 同值） | B1 |

字幕区 = configs/pipeline.yaml `erase_band`（y0=1440/y1=1780，与 M11 擦除带**同源**）；
`--full-frame` 可扫全画幅。采样**顺序解码**（grab 全帧、命中才 retrieve），时间戳=帧号/fps，
不经 seek（H.264 seek 抖动会污染字幕行起止，`sample_band` docstring）。

## 3. 行为规格

- 帧级 → 行级（`merge_frames_to_lines`）：相邻采样帧归一化文本相同且断裂 ≤2 步 → 合并一行；
  行起止 = 首/末命中采样时刻 ∓ 半步（0.2s 粒度下的中心化修正，实测误差 ≤0.1s，通过线 0.3s）；
  行 bbox = 多帧并集（全片像素坐标）；行置信 = 各帧均值；帧置信 = 各框最小值。
- 文本归一（`normalize_text`）：去空白 + 中英文标点（全角/CJK 标点表 + 曲引号 + ASCII 标点），
  仅留实义字符——OCR↔ASR 一致性比较口径。`cer()` 供 M15 回听指标复用。
- 投票（`vote_text` 纯函数）：OCR 置信 ≥0.9 且非空 → OCR；否则 ASR；ASR 空兜底回 OCR；
  `agree` = 双方归一化文本一致（ASR 缺席 → False）。
- 融合（`merge_ocr_asr` 纯函数）：全部 (行,句) 对中重叠率 ≥0.6 者，按重叠率降序贪心 1:1 配对；
  命中句按 OCR 区间重切句窗、字级时间戳夹取（契约字级校验保持成立）、文本经投票定稿、
  `ocr` 事实落 C2；未命中行生成纯 OCR 新句（`utt_id=make_utt_id(ep, 行起点)`，`agree=False`）；
  未命中句原样保留。出口按起点排序经 `upsert_jsonl` 原子写 C2。
- ASR 缺席（utterances.jsonl 不存在/空 或 `--no-asr`）→ 退化为纯 OCR（agree=False）。

## 4. 两条 Windows 硬约束（可执行落点 = `pipeline/ocr_wrap.py`，B1 修订）

| # | 约束 | 实测现象（docs/setup_windev.md §3） | 代码落点 |
|---|---|---|---|
| 1 | **同进程先 `import torch` 再加载 paddle 系** | 先 paddle 后 torch → `OSError: [WinError 127] … torch\lib\shm.dll`（两者捆绑的同名 `libiomp5md.dll` Intel OpenMP 运行时冲突，paddle 先加载自己的副本，torch shm.dll 解析到它缺新符号） | `ocr_wrap.bootstrap()`（幂等先 import torch，ocr_wrap.py:27-34）+ `assert_torch_first()` 守护（sys.modules 插入序 paddle 系不得早于 torch，:37-49） |
| 2 | **OCR 构造必须 `enable_mkldnn=False`** | 默认（mkldnn 开）`predict()` → `NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support`（PIR/oneDNN 执行器不支持） | `ocr_kwargs()` 强制注入且**外部同名覆盖一律忽略**（:52-59）；`create_ocr()` = 唯一许可入口（先保序再构造，真名拼接动态加载 :62-73） |

- M2 一律经 `create_ocr` 构造引擎，**禁止绕过本模块自行 import OCR 分发后构造**（m2_ocr 模块 docstring）。
- 守护测试：`tests/test_ocr_wrap.py`（3 用例：保序/强制参数/拼接构造）。
- 代价与定案：mkldnn 关闭后为原生 CPU kernel 速度略降 → 以 0.5 降采样补吞吐（T6 实测 1.7s/帧），
  本阶段冻结此约束。

## 5. eval

```bash
bash scripts/eval_m2.sh   # = pytest tests/test_m2.py -v（合成 drawtext 中文字幕视频 → M1 → M2 → 断言）
```

- 通过线（冻结）：抽取行语料级 **CER ≤5%**；字幕起止时间误差 **≤0.3s 且 ≥90% 命中**；C2 契约出口校验。
- 最近记录：T13 门 ③ 12 passed 365.36s（含真引擎推理）。
- 已知边界：一条 OCR 行横跨多条 ASR 句且对任何单句重叠率都 <0.6 时三方共存（OCR 新句+原 ASR 句）——
  句级去重归 M5/M14 融合批次（CONTRACTS §3 痛点 2）。

## 6. 重生成注意事项

- 依赖：paddle 系运行时 3.3.1 + OCR 引擎封装 3.7.0（真实发行名见 requirements.txt；py3.12 有 cp312
  win_amd64 轮子，未触发 rapidocr 降级——requirements.txt 偏差说明）；引擎默认模型 PP-OCRv6 medium det/rec（本机官方仓缓存 `~/.paddlex`，离线可用，
  models.yaml cap-ocr 条目）。引擎首次调用自动下载走国内源。
- 关 3 个无用前置（`use_doc_orientation_classify/use_doc_unwarping/use_textline_orientation=False`，
  m2_ocr `_ensure`）。
- 与 M11 同源：改 `erase_band` 必须**同时**重跑 M2 与 M11 eval（擦除带=采样带）。
