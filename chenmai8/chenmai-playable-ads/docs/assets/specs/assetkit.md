# M5 素材处理（assetkit，构建时素材管线）

> 状态：**frozen**（2026-09-29，commit `d03ac0e`）。`python/assetkit/` 已实现四能力并正规化进
> `python/pyproject.toml` 的 packages；`pfcore make` **默认接线**（`--no-assetkit` 逃生口，
> make.py `_run_assetkit`）。本页为模块边界与能力说明；逐项验收以
> `python -m assetkit selftest`（8 断言，exit 0）为门。

---

## 1. 职责（已实现）

读入 spec 声明且真实存在的素材（`assets.sprites/background/audio/fontSubset`，目录/文件皆可，
解析次序与模板构建脚本一致：spec 目录优先、仓库根兜底），产出可直接进包的优化素材：

- 压图：经 devDependency sharp 跑 Node 助手，四候选竞标（有损 WebP / 近无损 WebP /
  调色板量化 PNG / 常规 PNG；大图自动跳 PNG 候选省时）取最小；全部候选不小于原始则保留原图
  （永不增大）；可选 `--max-edge` 等比缩边（默认不缩）。
- 音频：ffmpeg（PATH 或 `PF_ASSETKIT_FFMPEG`）转 AAC 48kbps `.m4a`（剥元数据）；
  ffmpeg 缺席/单文件失败保留原始，如实记录、不阻塞。
- 字体子集：fontTools 按 spec `i18n.strings` 全语言字符 ∪ 标题 ∪ 数字子集化，
  woff2（依赖 brotli）/woff/ttf；如实报告字符覆盖率（字体缺字形不报错）。
- 图集：自研 shelf（next-fit 递减高）装箱 + 无损合成（WebP 无损/调色板 PNG 竞标），
  `atlas.json` = `pf-atlas/1` 帧表。

输出：`asset-optmap.json`（键 = spec 声明串或绝对路径 → 优化产物）与 `report.json`
（逐素材前后字节/候选明细/汇总降幅；`--min-reduction` 硬门不达 exit 1）。

素材纪律（红线，不变）：**素材仅来自公开授权（CC0/OFL）或用户提供**；每个素材包的许可文件随包留档
（`assets-cc0/` 目前为空目录，如实记录）。

## 2. pfcore make 接线（默认启用）

- make 在 validate 后对 spec 声明素材跑 assetkit，构建子进程经 `PF_ASSET_OPTMAP` 环境变量接线；
  模板构建脚本对声明串精确命中即内联优化产物（旁车 `<out>.assets.json` 如实记 `source=assetkit`），
  未命中回退原素材、行为同旧版。
- spec 无声明素材时**零开销空跑**（不发 node 子进程）；素材管线失败按流水线失败 exit 1
  （宁可失败不带病出包）；素材汇总进 `pipeline-report.json`。
- 验收（实测，2026-09-29）：demo 素材 `piece-0.png` 893B→402B（降 54.98%，
  `--min-reduction 30` exit 0）；`python -m pfcore make --spec specs-eval/demo-zh.json` 出包
  data URI 内联 + CHK10 像素对账通过。

## 3. selftest（冻结验收门）

`python -m assetkit selftest` → 8 断言全过 exit 0：合成全类型素材端到端、降幅 ≥30% 门、
照片走有损 WebP（实测 74.5%）、WAV→AAC 22094→4329B、中文/阿拉伯字体子集各 ≤40KB 且重载
cmap 全命中、图集帧两两不重叠在界内且图可解码、optmap 键一一对应。

如实说明：demo 包体 99.9% 为引擎 bundle（素材管线范围外）——素材级降幅折算到包体有限，
包体再降需引擎瘦身；四能力已在 selftest 就绪，待真实多素材主题接入。
