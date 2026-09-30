# 架构摘要 · ztough926/video-understanding（纯代码视频理解前处理）

> 研究：CloudCrane 视频能力迭代 worker-B ｜ 日期 2026-10-01 ｜ 配套接入方案：`ztough926_接入方案.md`
> 取证：GitHub API `repos/ztough926/video-understanding`（HTTP 200，description「视频/gif理解」，public，GPL-3.0）；
> 全量树 `git/trees/HEAD?recursive=1`（truncated=false）共 5 个 blob + 2 个 tree。
> 四件套原文存档：`research/ztough926_src/`（sha256 见文末）。

## 1. 输入 / 输出

- **输入**：本地视频 / GIF 文件（mp4 等，ffmpeg 可解码即可；≤8 帧的短 GIF 全保留）。
- **输出**（三件，全部确定性产物，零语义结论）：
  1. `overview.jpg` × N——关键帧总览图（网格、左→右上→下=时间顺序、每格下方 `#序号 时间戳`，无元数据条）；
  2. `frames/kf_XXX_时间戳.jpg`——单帧原图（文件名带时间戳，供细节补读）；
  3. `keyframes.json`——尺寸/时长/帧率/每帧帧号·时间戳·diff 分值/总览图路径列表。

## 2. 核心思想：纯代码桥接「视频」与「多模态模型」

**它自己不看懂任何东西**——全程零模型调用，只做确定性压缩；「看懂」交给具备视觉能力的
多模态大模型。分工边界（README 明示，是其设计第一原则）：

| 环节 | 谁做 | 做什么 |
| --- | --- | --- |
| 压缩与呈现 | 本工具（纯图像算法） | 挑出画面真正变化的帧，排成时序总览图，保证每格文字在模型眼里可读 |
| 看懂与表达 | 多模态大模型 | 识别场景/主体/动作/文字，综合成理解 |

三条支撑性设计判断：

1. **自适应帧差选帧**：逐帧差异双角度取 max——全局平均差异（抓转场换色）+ 8×8 分块最剧烈块
   差异（抓角落小动作；只看全局时小动作 0.004 会被未变像素稀释到噪声量级，分块后 0.06，区分度干净）。
   阈值 = 差异中位数（≈底噪）× 灵敏度 k（默认 4.0），夹在 [0.008, 0.08]，免手调。
2. **「等它变完」选帧**：画面变化中不选帧，等变化结束后的第一个稳定帧才入选（避免元素淡入淡出
   的空白中间态）；持续运动每 1.5s 强制补一张；相邻关键帧最小间隔 0.30s。抽太多时用抽稀而不是调高阈值
   （调高阈值会在渐进动画中途误判稳定，抽到空白中间态——README 给了 0.03 阈值下「一多半空白帧」的实测反例）。
3. **模型可读分张纪律**（为 VLM 视觉编码器的长边 ~1568px 压缩而调，不是为人眼）：
   每格能分到的像素只取决于「一张图里多少格」，与图做多大基本无关。
   硬规则：每张 ≤12 格（至多 16）、列数 ≤4、图宽 ≤2400（1600 为安全+够清落点）、JPEG 4:4:4 +
   LANCZOS 保文字；帧多自动按时间顺序均匀分张（每张格数差 ≤1）。

**工程细节值得抄的**：不用 ffmpeg `select='eq(n,x)+...'` 滤镜（关键帧上百后超 ffmpeg 表达式解析上限），
改为 Python 侧按帧号筛选、只完整解码一遍；分析阶段让 ffmpeg 直接输出 200px 灰度裸帧流逐帧算差异。

## 3. 关键模块与依赖（`scripts/extract_keyframes.py`，1029 行）

| 模块（行号） | 职责 |
| --- | --- |
| `probe`（L134） | ffprobe 读尺寸/帧率/时长，处理 rotation 元数据 |
| `diff_score`（L196） | 双角度差异：全局均值 vs 8×8 分块最大块均值，取 max |
| `compute_threshold`（L227） | 中位数×k 夹 [0.008, 0.08]（常量 L57-58：`DEFAULT_ABS_FLOOR/CEIL`，`BLOCK_GRID=8` L55） |
| `select_keyframes`（L250） | 等它变完 + 运动补帧 + 最小间隔 + 尾帧兜底；≤8 帧全留 |
| `_iter_video_gray`（L314） | ffmpeg rawvideo 灰度流单遍解码 |
| `_export_video`（L407） | 第二遍 RGB 解码按帧号存图（Python 侧筛选） |
| `build_overview_sheets`（L534） | 网格拼图、LANCZOS、格标签、自动分张 |

依赖面极小：Python 3.8+、系统 ffmpeg/ffprobe、numpy、Pillow。打包形态是 **Agent Skill**：
`SKILL.md` 带 frontmatter（name/description）+「隐式调用铁律」（对话中出现视频就先抽帧再作答）+
固定档位 `--cols 3 --sheet-max-cells 12 --sheet-width 1600` + 三步协议（读总览→逐张读完→补读单帧）+
输出约束（自然语言理解，不写时间轴/文件参数）。

## 4. 性能与 License

- 性能（README 自述，declared）：3 分钟 1080p 全流程 ~22s；推荐档位 4分42秒视频 ~45s。
- **License：GPL-3.0**（全文随仓库）。允许商用/修改，但**分发衍生作品须同证开源**——
  因此本项目的落地路径是「思想引用 + 独立实现」，不复制其代码（见接入方案 §合规）。

## 存档文件 sha256（下载于 2026-10-01，raw.githubusercontent.com/HEAD）

```
048254053946940a66ce862a39ed9d236b818fa1a95bd0e525878a7640ae47e8  README.md
09815cacd4af84fdba1e7a11f71eb1b1a2a0aac9689a1f8c8db6735d0ca58c50  SKILL.md
bb36f0a14777a115ce41162ff37556cc48f1ff5a0c0e0827c717bd274de747eb  references/parameters.md
3fbea8c9759c3b774d8a7a51ff50a1b9f487fd23c9c6ff4f5e0d15db0161f6de  scripts/extract_keyframes.py
```
