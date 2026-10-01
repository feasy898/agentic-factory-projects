# M5 素材处理（assetkit，构建时素材管线）

> 状态：**已落地**（2026-09-30 成品切换批次）。规格源 = `repo/docs/assets/specs/assetkit.md`
> （frozen，commit `d03ac0e`）；本页为 factory 落位改写（oracle 语义 + 宿主差异登记）。
> 实现于 `packages/assetkit/`；`pf make` **默认接线**（`--no-assetkit` 逃生口，
> `pf/src/make-cmd.ts runAssetkitStep`）。逐项验收以 `npm run test:assetkit`
> （`node packages/assetkit/selftest.mjs`，9 断言，exit 0）为门。

---

## 1. 职责

读入 spec 声明且真实存在的素材（`assets.sprites/background/audio/fontSubset`，目录/文件皆可，
解析次序与模板构建脚本一致：spec 目录优先、仓库根兜底），产出可直接进包的优化素材：

- 压图：进程内 sharp（宿主适配：oracle 经 python→node 子进程助手
  `python/assetkit/node/optimize.mjs`，factory 单栈直接 import——四候选竞标语义逐条对齐：
  有损 WebP / 近无损 WebP / 调色板量化 PNG / 常规 PNG；原始 ≤3MB 才有 png-plain 候选；
  大图自动跳 PNG 候选省时）取最小；全部候选不小于原始则保留原图（永不增大）；
  可选 `--max-edge` 等比缩边（默认不缩）。
- 音频：ffmpeg（PATH 或 `PF_ASSETKIT_FFMPEG`）转 AAC 48kbps `.m4a`（剥元数据）；
  ffmpeg 缺席/单文件失败保留原始，如实记录、不阻塞。
- 字体子集：按 spec `i18n.strings` 全语言字符 ∪ 标题 ∪ 数字子集化，woff2 输出。
  宿主适配（登记）：oracle fontTools → subset-font（harfbuzzjs），cmap 覆盖率判定与
  子集复核用 fontkit；**TTC 集合取成员 0**（harfbuzzjs 不解析 ttcf 容器——oracle
  fontTools 经 fontNumber=0 取成员，factory 在 `fonts.ts fontBytesForSubset` 把成员 0
  重建为独立 sfnt，表目录偏移改写、4 字节对齐）。字体缺字形不报错：如实报告覆盖率。
- 图集：自研 shelf（next-fit 递减高）装箱 + 无损合成（WebP 无损/调色板 PNG 竞标），
  `atlas.json` = `pf-atlas/1` 帧表。

输出：`asset-optmap.json`（键 = spec 声明串或绝对路径 → 优化产物）与 `report.json`
（逐素材前后字节/候选明细/汇总降幅；`--min-reduction` 硬门不达 exit 1）。
CLI：`node packages/assetkit/cli.mjs run <素材...> --out <dir> [--spec ...]` /
`selftest`（oracle `python -m assetkit` 同表）。

素材纪律（红线，不变）：**素材仅来自公开授权（CC0/OFL）或用户提供**；许可文件随包留档。

## 2. pf make 接线（默认启用）

- make 在 validate 后对 spec 声明素材跑 assetkit，模板构建子进程经 `PF_ASSET_OPTMAP`
  环境变量接线；`tmpl-match3/build.mjs` 对声明串精确命中即内联优化产物（旁车
  `<out>.assets.json` 如实记 `source=assetkit`），未命中回退原素材、行为同旧版。
  **merge/pullpin/sort 三模板未接 optmap**（直读原素材内联）——oracle 原状（仅
  tmpl-match3 有接线），factory 如实登记于根 README 预留/未做。
- spec 无声明素材时零开销空跑（进程内直跑无子进程）；素材管线失败按流水线失败 exit 1
  （宁可失败不带病出包）；素材汇总进 `pipeline-report.json` 的 `assetkit` 键
  （`{dir, optmap, report, totals}`，键集不变）。
- 验收（实测，2026-09-30）：demo 素材 `piece-0.png` 893B→402B（降 54.98%，
  与 oracle 登记值逐位一致）；`node pf/pf.mjs make --spec specs-eval/demo-zh.json` 出包
  data URI 内联优化产物 + CHK10 像素对账通过。

## 3. selftest（冻结验收门）

`npm run test:assetkit` → 9 断言全过 exit 0：合成全类型素材端到端、降幅 ≥30% 门、
照片走有损 WebP（实测 83.8%）、WAV→AAC 22094→4334B、中文（msyh.ttc 经 TTC 成员 0 抽取，
14740B）/阿拉伯（arial.ttf，25596B）字体子集各 ≤40KB 且重载 cmap 全命中、图集帧两两
不重叠在界内且图可解码（640×512）、optmap 键一一对应。
2026-09-30 实测汇总：21,497,003B → 163,548B（降 99.24%；oracle 同表实测 99.23%）。

单测：`packages/assetkit/test/unit.test.mjs` 7 件（classify/声明序/字符集合成/NamePool/
packShelf 逐位对账 oracle 实算/压图竞标小样本/collect 去重），并入 `npm test`。

## 4. 如实说明

demo 包体 99.9% 为引擎 bundle（素材管线范围外）——素材级降幅折算到包体有限，包体再降需
引擎瘦身；演示 spec 声明素材面仅 1 张真实 sprite（demo-zh 的 piece-0），golden 系列声明的
`assets/theme-a/*` 在两仓均无对应文件（缺素材回退程序化贴图——构建脚本 design 如此，
告警不失败）；四能力已在 selftest 就绪，待真实多素材主题接入。
