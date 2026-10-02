# 生咖啡标准对照矩阵（六标准）· BeanEye standards

> 维护：标准回填线（2026-10-02）。
> 数据可信度图例：**●** = 简报给定口径（已采纳为仓库基准）；**◐** = 2026-10-02
> 公开检索复核口径；**○** = 待核/占位（不得作为对外宣称依据）。
> 本文档只给标准名与文献号，不附链接；链接与原文取得方式由收账统一登记
> （中性名纪律：入库文件不出现上游数据集/项目名，上游一律用 `ext-*` 短代号）。

## 1. 六标准对照矩阵

| 维度 | CQI 精品罗布斯塔 | 越南 TCVN 4193:2014 | 巴西 COB IN 8/2003 | ISO 10470（=NY/T 1519-2007） | 乌干达 UCDA | 印度 Coffee Board |
|---|---|---|---|---|---|---|
| **样品基准** | ● 绿样 350 g；烘焙样 100 g（奎克豆计数）；杯测 5 杯 | ◐ 按批混合样，缺陷按质量百分比计 | ● 缺陷计数按 300 g 试样 | ◐ 缺陷参考图（配合 ISO 4149 目检/ISO 4150 筛分使用） | ◐ 出口批按 Screen 18/15/12 档验收 | ◐ 出口批经 curing works 分级（Robusta Cherry 系） |
| **缺陷分类法** | ● 主缺陷（Category 1，严重）与次缺陷（Category 2）二分 + 烘焙后奎克豆单列 | ◐ 缺陷分项按质量百分比（黑豆/破碎/虫蛀/外来杂质等分项限值） | ● 缺陷按类计数 × 等效因子折算为当量缺陷 | ◐ 每类缺陷给「质量损失系数 / 感官影响系数」双系数 | ◐ 否决项（霉变、活虫、异味、发酵痕迹）+ 按重量%的缺陷容差 | ◐ garbling 缺陷按重量%（PB/混入豆容差 1~2%） |
| **等效规则** | ● 1 粒 = 1（主/次二分）；奎克豆：烘焙样 100 g，精品 ≤3、优质 ≤5 | ◐ 质量百分比直算（无粒数当量表） | ● 黑豆 1=1、酸豆 2=1、未熟 5=1、虫蛀 2-5=1、贝壳 3=1（300 g 计数口径） | ● 黑豆 0/1、酸褐 0/1、破碎 0.5/0.5、虫蛀 0/0.5、未熟 0/0.5、霉臭 0/1（质量损失/感官影响，见 §2） | ◐ 按重量%计（无粒数当量表） | ◐ 按重量%计（garbling ≥98%~99% 为各档门槛） |
| **等级阈值** | ● 精品（Fine）= 0 严重缺陷 + 次缺陷 ≤5；优质（Premium 档）= 总缺陷 ≤12 | ◐ 一级：黑豆 ≤0.6%、破碎等总错 ≤14~16%；二级放宽至 2~3.5%（分项不同） | ◐ Type 系列按当量缺陷递增放宽（黑豆/酸豆/未熟等分项限值逐档放宽） | ○ 无等级体系（量化工具，供各标准引用） | ◐ Screen 18：≥92% 留 18 目、≤1% 低于 12 目；Screen 15 / Screen 12 同构递降 | ◐ Robusta Cherry PB/AB/C/A/AA/AAA（AAA=19 目档，AA≥90% 留 18 目） |
| **筛目体系** | ● 参考 16 号（乌干达实施口径） | ◐ 16 号 / 13 号筛档，90% 留存 | ◐ 13~18 号档（peneira，公称孔径见 ICO 表） | ○ 不自设（引用 ISO 4150 筛分法） | ◐ 18 / 15 / 12 三档（1/64 英寸口径） | ◐ 14 / 15 / 17 / 18 / 19 号（PB 为混筛） |
| **水分** | ◐ 常引 10~12%（协议文本待抄录核） | ● ≤12.5% | ○ 待核（出口口径常引 ≤12%~14%，未取正式文本） | ○ 不自设 | ◐ ≤12.5% | ○ 待核（ curing 口径常引 10.5%~11%） |

**与本仓三套 YAML 的关系**：CQI 列 → `configs/standards/cqi_fine_robusta.yaml`；
ISO 10470 列 → NY/T 1519-2007（中国等同/修改采用 ISO 10470 的缺陷参考图，
为 DB46/T 642—2024 附录 A 的引用基础之一）；DB46/T 642—2024 法定数值表
（杯品/理化双维度）已固化在 `configs/db46_t642_legal_2024.yaml`（每值带条款
号，文本层 + 位图双重复核），其与本仓引擎 v0 粒数口径的差异见该文件头注释；
NY/T 604 正式文本暂缺，`configs/standards/nyt_604.yaml` 阈值维持占位基线，
注释标注 TCVN/COB 折算锚点，待正式文本替换。

## 2. ISO 10470 系数表（质量损失 / 感官影响双系数）× 本仓 13 类 taxonomy

> ● 数值来自简报给定口径；「—」= 本仓体系无对应类；完整原表（含贝壳、
> 象豆、花豆等其余类别）待取得 ISO 10470 原文后补录（○）。
> 「本仓 kind」= `configs/taxonomy.yaml` 的 primary/secondary 计数归属；
> ISO 双系数是**量化工具**，与本仓「每粒只计最严重缺陷」的计数口径不同——
> v0 引擎不消费双系数，仅供折算与对照（升级位）。

| 本仓 taxonomy key | 中文名 | 本仓 kind | ISO 10470 缺陷（英） | 质量损失系数 | 感官影响系数 |
|---|---|---|---|---|---|
| black | 黑豆 | primary | black | 0 | 1 |
| sour | 酸豆 | primary | sour (brown/ferment) | 0 | 1 |
| broken | 破碎 | secondary | broken | 0.5 | 0.5 |
| insect | 虫蛀 | primary | insect-damaged | 0 | 0.5 |
| immature | 未熟 | secondary | immature | 0 | 0.5 |
| mold | 霉豆 | primary | mouldy / stinker | 0 | 1 |
| faded | 褪色/白化 | secondary | faded / bleached（待核 ○） | ○ | ○ |
| dried | 干瘪/僵豆 | primary | withered / dry（待核 ○） | ○ | ○ |
| brocade | 花脸 | secondary | （无直接对应，○ 待核） | ○ | ○ |
| shell | 贝壳豆 | secondary | shell（○ 待补） | ○ | ○ |
| elephant | 象豆 | secondary | elephant（○ 待补） | ○ | ○ |
| peaberry | 花豆/胡椒粒豆 | secondary（不计缺陷） | peaberry（○ 待补；本仓计量不计缺陷） | ○ | ○ |
| normal | 好豆 | normal | （非缺陷） | — | — |

## 3. 筛目/毫米对照（大中小筛段 · 轨2）

- 筛段（`configs/size_bands.yaml`）：大 = screen ≥17；中 = 15~16；小 = ≤14
  （1/64 英寸筛号，与 `Measurements.sieve_hist` 同口径；连续目数域左闭右开，
  16.99 → 中、17.00 → 大）。
- ICO 筛径表（公称孔径 mm）：13=5.00 / 14=5.60 / 15=6.00 / 16=6.30 /
  17=6.70 / 18=7.10。来源注：越南罗豆出口惯例 18/16/13 档 + ICO 筛径表，
  **待真实豆标定修正**。
- 引擎内部 `screen_mm(s) = s/64×25.4` 为精确孔径（如 17 目 = 6.747 mm），
  与 ICO 公称值并存、用途不同（计算 vs 对照）。

## 4. 附录：taxonomy ↔ ISO 10470 ↔ 上游类映射参考（内部参考，中性短代号）

> 上游数据集/项目一律用中性短代号（与 `data/datasets/*mapping.yaml` 一致）：
> `ext-main`（主源生豆缺陷分割集，12 类）、`ext-rseg`（罗豆实例分割集，4 类，
> 绿豆占比核验项）、`ext-rgreen`（罗豆绿豆检测集，2 类 bbox）、
> `ext-scaa17`（17 类缺陷集，966 图，3 类不映射）。
> `null` = 明确不映射；真实 URL 与上游原名只登记在收账侧，不入库。

| 本仓 key | ISO 10470 缺陷 | ext-main | ext-rseg | ext-rgreen | ext-scaa17 |
|---|---|---|---|---|---|
| normal | （非缺陷） | normal | Good beans（核验项） | — | — |
| broken | broken | broken | Broken/Chipped | — | Broken; Cut |
| faded | faded/bleached（○） | — | — | — | Fade |
| brocade | （无直接对应 ○） | brocade | — | — | — |
| immature | immature | — | — | — | Immature |
| peaberry | peaberry（○ 待补） | peaberry | — | — | — |
| shell | shell（○ 待补） | shell | — | — | Shell |
| elephant | elephant（○ 待补） | elephant | — | — | — |
| insect | insect-damaged | — | Insect damage（核验项） | — | Severe Insect Damange; Slight Insect Damage |
| dried | withered/dry（○） | dry | — | — | Dry Cherry; Withered |
| sour | sour/brown（○） | sour | — | — | Full Sour; Partial Sour |
| mold | mouldy/stinker | — | — | — | Fungus Damange（页面原拼写） |
| black | black | black | Black（核验项） | full-black; partial-black | Full Black; Partial Black |
| （无对应） | frozen / black_ear / triangle / Floater / Husk / Parchment | frozen; black_ear; triangle → null | — | — | Floater; Husk; Parchment → null |

## 5. 变更与核对记录

| 日期 | 事项 | 依据 |
|---|---|---|
| 2026-10-02 | DB46/T 642—2024 印刷稿 PDF 文本层抽取 + 表 1/表 2 页（6/7 页）位图人工复核，法定数值固化至 `configs/db46_t642_legal_2024.yaml` | 标准印刷稿（15 页） |
| 2026-10-02 | CQI 精品罗布斯塔口径复核：350 g、0 主/次 ≤5、Premium 档总缺陷 ≤12、奎克 100 g 样 ≤3/≤5 —— 与简报给定口径一致 | 公开检索（2026-10-02） |
| 2026-10-02 | TCVN 4193:2014 口径复核：水分 ≤12.5%、一级/二级分档与黑豆 ≤0.6% 一致 | 公开检索（2026-10-02） |
| 2026-10-02 | UCDA Screen 18/15/12（≥92% 留档、≤1% 低于 12 目、水分 ≤12.5%）、印度 Robusta Cherry 筛档与 garbling 容差入表 | 公开检索（2026-10-02） |
| 待办 | ISO 10470 全系数表抄录、巴西 IN 8/2003 与印度水分正式文本、CQI 协议原文水分条款 | ○ 待取得原文 |
