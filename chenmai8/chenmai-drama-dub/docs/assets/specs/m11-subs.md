# M11 字幕擦除 + 目标语渲染 spec

> 状态：frozen（T8）。对照 `pipeline/m11_subs.py`、`configs/pipeline.yaml`（label_zone/erase_band/erase/subs 段）、
> `configs/models.yaml cap-clean 条目` 核验于 2026-09-29。组件中性名：cap-ocr（输入）、cap-clean（重型擦除后端，
> 接口预留未安装）。

## 1. 职责与边界

只读 `01_media` 视频、`03_ocr/ocr_merged.jsonl`、`06_mt/translations.jsonl`、`04_dial/utterances.jsonl`；
**不写任何冻结契约**（C2/C4 一律只读）。
写入：`01_media/video_1080x1920_25fps_clean.mp4`（擦除基带）、`10_subs/{src.ass, tgt.<lang>.ass}`、
`12_out/<ep>.<lang>.mp4`。

## 2. 擦除（三后端）

- 区域计算：M2 字幕行 bbox（全片像素）→ 外扩 `erase_band.expand_px`=4 → 裁剪进 `erase_band`
  （y0=1440/y1=1780）→ **排除 label_zone**（AI 标识区，configs `label_zone`：top-center/top 60px/高 120px
  ——M11 与 M12 同源常量；按 y 剖分排除）→ 按行起止时间窗逐条擦除；越界/出带区域如实计入 summary 统计（不静默吞）。
- 后端（`erase.engine` 选择）：
  | 引擎 | 实现 | 定位 |
  |---|---|---|
  | `delogo`（默认） | ffmpeg delogo 滤镜按时间窗插值填充 | 轻量默认，本机离线可用；**产物用无损 x264（crf=0）**——擦除带外像素零改动，label_zone 哈希可判定 |
  | `inpaint` | cv2 inpaint 逐帧掩膜修复（TELEA） | 质量高一档、速度慢 |
  | `vsr` | models.yaml cap-clean 所指重型路线 | **接口预留、不安装——选中即如实报错并提示轻量路径，不静默降级**（cap-clean.runtime_notes 定案） |

## 3. 目标语渲染（ASS）

- 事件 = C2 句窗 × C4 选定译文（`(utt_id,tgt)` 行的 chosen 候选文本）；源语 `10_subs/src.ass` 由 C2 生成
  （人工审校回看口径）。
- 样式（configs `subs` 段 + `channels.<lang>.subs_align`）：font_size 62 / margin_h 60 / margin_v 220
  （底边距在字幕带 y0=1440 上方，对 PlayResY=1920）/ outline 3 / shadow 2；**en/es=左下(1)、ar=右下(3)**；
  字体候选 Noto Sans / 微软雅黑 / Noto Naskh Arabic 按 `resolve_font` 存在性取首个（找不到交 libass 兜底）。
- **RTL 责任边界**：ASS 文本以逻辑序直书，**不做预反转/预整形**——bidi 与 shaping 归渲染期
  libass+fribidi+harfbuzz（本机 ffmpeg 6.1.1 essentials 已核实含三者）。
- 文本清洗：`sanitize_ass_text` 换行/override 标签剥离。
- 压制：`burn_ass`（`ffmpeg -vf ass=`）；**ass= 只传相对文件名并以 `10_subs` 为 cwd**——
  绕开 Windows 滤镜串两级转义与非 ASCII 路径坑（同 M2 drawtext textfile 手法）；压制 CRF18/medium。
- `--skip-erase` 复用/回退基带不重擦；`--no-burn` 只生成 ASS。

## 4. eval

```bash
bash scripts/eval_m11.sh   # = pytest tests/test_m11.py -v（全离线零 GPU）
```

- 冻结线（§4 M11）：①擦除后重跑 M2 OCR **中文字符命中=0**（3 段合成素材各一遍：delogo×2 + inpaint×1；
  素材=drawtext 压中文硬字幕 + 顶部 AI 标识文本）；②**label_zone 裁剪区像素哈希前后一致**
  （无损基带 + delogo 窗外不动像素），且字幕带确被擦动（排除"什么都没做也哈希一致"）；
  ③ar：bidi 方向断言（孤立字母探针三簇，窄竖笔必在最右）+ shaping 连接断言（连写=1 簇 vs 空格断开=4 簇）
  + 截图目测；④CLI 真实子进程（全流程 / --skip-erase 不重擦 / --engine vsr 报错不装 / 各缺失 rc=1 可读提示 /
  -h 冻结形态）。
- 最近记录：自验收 24 用例 exit 0（墙钟 778s，T8 提交记录）；60s 素材擦除+渲染 CPU 耗时记录实测
  （≤40 分钟通过线）。
- 门禁：gate_b3 ②（并行批次）。

## 5. 重生成注意事项

- 与 M2 同源：`erase_band` 改动必须同时重跑 M2 与 M11 eval；label_zone 是 M12 的绘制位置常量——
  擦除掩码排除它 = 标识区永不被误擦。
- 重型后端（cap-clean 权重与 CLI）未安装是有意定案（默认 lama 系修复；条款复核后另行登记）——
  不要"顺手装上"而不改 models.yaml 与本 spec。
- 编排：M11 会被 M9 消费（`-c:v copy` 接入）；若 M11 在 M9 之后重跑，其 `-c:a copy` 会覆盖成片音轨
  （重跑后需重跑 M9 最终合成，见 m9 notes §5）。
