# 数据集入库登记册（dataset_registry）

> **红线（最高优先级）**：本登记册与仓库内一切数据集文件**只用中性代号**
> （ext-main / ext-rseg / ext-rgreen / ext-scaa17）。真实来源 URL、workspace/
> project 坐标与平台账号信息**只登记在本机外部文件**
> `C:/devsetup/dataset_sources.txt`（不入库；含四集真实 URL、许可页链接、
> 备选源与风险警示，及 key 文件路径与认证环境变量名）。API key 绝不写入任何
> 入库文件或日志，运行时经外部登记文件记载的环境变量/`--key` 注入。
> 维护脚本：`scripts/download_datasets.py`（--only universe 为本批新增的
> 通用下载模式）。本登记册按 D-3 不随公开仓库分发。

**状态：PENDING_KEY（2026-10-02）** —— key 文件内当时为 Publishable Key
（31 位、rf_ 前缀），项目端点与账号端点、Bearer 头与 query 两条认证路径
均返回 401 "does not exist (or has been revoked)"。四集目录与映射表已就位，
数据下载待 Private Key 覆盖后执行（各集命令见下，逐条可直接复制）。

---

## 0. 目录与校验约定

```
data/datasets/<中性代号>/
├─ content/            导出解包内容（train/ valid/ test/ + _annotations.coco.json + 图片）
├─ _downloads/*.zip    原始归档（sha256 记入 manifest）
├─ mapping.yaml        本集 → taxonomy 13 类映射（train/prepare_coco.py --mapping-yaml 语义）
├─ manifest.json       来源/版本/许可/统计/类别直方图——universe 模式三集仅中性代号；
│                      ext-main 走 dcv 既有模式，manifest 额外含上游坐标（internal_name
│                      仍取目录名；manifest 位于 data/datasets/* 不入库，见 .gitignore）
└─ SHA256SUMS          `sha256sum -c SHA256SUMS` 可校验（在本集目录内执行）
```

离线体检：`.venv/Scripts/python.exe -m pytest tests/test_dataset_registry.py -q`
（校验目录结构 / 映射目标键 ∈ taxonomy 13 类 / manifest 图数与磁盘文件数一致
/ 登记册中性名——数据未下载的集自动跳过结构检查）。

## 1. ext-main —— 主源生豆缺陷集

| 项 | 值 |
|---|---|
| 中性代号 | `ext-main` |
| 来源平台与许可 | 公共 Universe 数据集托管平台（真实坐标见外部登记文件）；许可 **CC BY 4.0**（2026-10-02 项目页 LICENSE 节直接确认） |
| 预期量级 | 4038 图 / 12 类（**西语类名**，见下）/ 4 个已生成版本（页面确认） |
| **类型风险（先探测后下载）** | 页面标题/类型栏为 **Object Detection**，与「coco-segmentation 多边形」预期冲突（旧 README 的多边形说法出自论文描述）。key 就绪后先 `--list-versions` 探测（现打印 API `type`/`license`）：若 type 确为检测型，coco-segmentation 导出可能无多边形——下载器已有预检警告，且解包校验会在 total_poly==0 处硬失败（scripts/download_datasets.py validate 后置检查），故先回报决策再触发下载 |
| 类别（12，页面原样·西语） | agrio, broca, caracolillo, concha, elefante, helado, negro, normal, oreja, partido, seca, triangulo（缩略图 alt 标注同为西语，底层标注即西语；旧 README 英文名系翻译版本——其中 broca 被误译 brocade，实义虫蛀） |
| 图数/标注数/类别分布 | **PENDING**（下载后由 manifest.json `totals` + `category_histogram` 落数） |
| 绿豆占比核验 | 生豆数据集（项目主题即生豆缺陷），下载后抽验即可 |
| 映射决策（西语键 9 类） | agrio→sour；**broca→insect**（虫蛀，简报参考表）；caracolillo→peaberry；concha→shell；elefante→elephant；negro→black；normal→normal；partido→broken；seca→dried；**排除 3 类（null，简报：无对应类）**：helado（冻伤）、oreja（黑耳/耳形变异）、triangulo（形状变异）。注意本体系 brocade（花脸）在该集词表无对应来源（旧映射 broca→brocade 为误译产物，已纠正） |
| SHA256SUMS | `data/datasets/ext-main/SHA256SUMS`（**待生成**） |
| 下载命令 | `.venv/Scripts/python.exe scripts/download_datasets.py --only dcv --out data/datasets/ext-main`（带 --out 时 manifest internal_name=目录名 ext-main，与登记/测试一致） |

## 2. ext-rseg —— 罗布斯塔豆实例分割集

| 项 | 值 |
|---|---|
| 中性代号 | `ext-rseg` |
| 来源平台与许可 | 公共 Universe 数据集托管平台（真实坐标见外部登记文件）；许可 **CC BY 4.0**（2026-10-02 页面 LICENSE 节确认——即简报要求确认的许可结论） |
| 预期量级 | 418 图 / 4 类 / 实例分割多边形 / 3 个已生成版本（页面确认） |
| 图数/标注数/类别分布 | **PENDING**（下载后由 manifest 落数） |
| **绿豆占比核验** | **PENDING（关键核验项）**：该集所属工作区名称含 "Roasted"，其复数姊妹集带烘焙专属类（Quaker/Scorched）且图源同池——下载后必须抽样看图判定绿豆/烘焙豆占比：若烘焙豆为主 → 映射表全表作废改 null 并在此记录；若绿豆为主 → 按现表启用。抽样结论记于此：________ |
| 映射决策（预填，待核验启用） | Black→black；Broken/Chipped→broken；Good beans→normal；Insect damage→insect（虫蛀/破碎为物理表型，不随烘焙改变，但「Black/Good beans」是否绿生豆前提待看图判定） |
| 排除项 | 无独立烘焙类（与复数姊妹集不同；若核验发现烘焙内容，整集排除并记录） |
| SHA256SUMS | `data/datasets/ext-rseg/SHA256SUMS`（**待生成**） |
| 下载命令 | `.venv/Scripts/python.exe scripts/download_datasets.py --only universe --universe <工作区>/<项目> --out data/datasets/ext-rseg --format coco-segmentation`（真实坐标见外部登记文件 `[ext-rseg]` 节，含备选源） |

## 3. ext-rgreen —— 罗布斯塔绿豆检测集

| 项 | 值 |
|---|---|
| 中性代号 | `ext-rgreen` |
| 来源平台与许可 | 公共 Universe 数据集托管平台（真实坐标见外部登记文件）；许可 **CC BY 4.0**（2026-10-02 页面确认） |
| 预期量级 | 250 图 / 2 类 / Object Detection（bbox）/ 3 个版本（页面确认） |
| 图数/标注数/类别分布 | **PENDING**（下载后由 manifest 落数；检测导出无多边形属正常） |
| 绿豆占比核验 | 集名即"绿豆"，页面确认 Object Detection；下载后抽验即可（bbox 集，看图确认豆粒为生豆状态） |
| 映射决策 | full-black→black；partial-black→black（简报参考映射：full black/partial black → black）。单类补充集：仅给 black 供多样性 |
| 排除项 | 无（仅 2 类全映射） |
| SHA256SUMS | `data/datasets/ext-rgreen/SHA256SUMS`（**待生成**） |
| 下载命令 | `.venv/Scripts/python.exe scripts/download_datasets.py --only universe --universe <工作区>/<项目> --out data/datasets/ext-rgreen --format coco`（真实坐标见外部登记文件 `[ext-rgreen]` 节） |

## 4. ext-scaa17 —— SCAA 17 类缺陷集

| 项 | 值 |
|---|---|
| 中性代号 | `ext-scaa17` |
| 来源平台与许可 | 公共 Universe 数据集托管平台（真实坐标见外部登记文件）；许可 **CC BY 4.0**（2026-10-02 页面确认） |
| 预期量级 | 966 图 / 17 类（页面确认） |
| 图数/标注数/类别分布 | **PENDING**（下载后由 manifest 落数） |
| **下载风险（先探测再下载）** | 页面 "Dataset 0"（疑似无已生成版本）且类型栏曾显示 "Classification"，与「检测集」预期不符。key 就绪后**先跑该集的 `--list-versions` 探测**：有版本 → 正常下载；无版本/类型不符 → 回报等决策，不要自行换集（外部登记文件记有备选 fork） |
| 绿豆占比核验 | PENDING（类表为 SCAA 生豆缺陷词表，倾向生豆；下载后抽验） |
| 映射决策（预填 14 类） | Broken/Cut→broken；Dry Cherry/Withered→dried；Fade→faded；Full Black/Partial Black→black；Full Sour/Partial Sour→sour；Fungus Damange(页面原拼写)→mold；Severe Insect Damange/Slight Insect Damage→insect；Immature→immature；Shell→shell |
| 排除项（null，简报：本体系无对应类） | Floater（浮水豆，密度概念）、Husk（壳/果皮杂物）、Parchment（羊皮纸豆，工艺状态概念） |
| SHA256SUMS | `data/datasets/ext-scaa17/SHA256SUMS`（**待生成**） |
| 下载命令（先探测） | `.venv/Scripts/python.exe scripts/download_datasets.py --only universe --universe <工作区>/<项目> --out data/datasets/ext-scaa17 --list-versions` → 确认有版本后同命令去掉 `--list-versions` 加 `--format coco`（真实坐标见外部登记文件 `[ext-scaa17]` 节） |

---

## 附录 A · key 就绪后的执行序（本机）

```bash
cd <仓库根>
# 认证环境变量注入（变量名与 key 文件路径见 C:/devsetup/dataset_sources.txt 红线节；
# 必须是 Private API Key——Publishable Key 下载导出会 401，2026-10-02 实测）
export <认证环境变量>="$(cat <key文件路径>)"
# ① 两个风险集先探测（--list-versions 会打印 API 自报 type/license/images）
.venv/Scripts/python.exe scripts/download_datasets.py --only universe \
  --universe <ext-scaa17工作区>/<项目> --out data/datasets/ext-scaa17 --list-versions
.venv/Scripts/python.exe scripts/download_datasets.py --only dcv --out data/datasets/ext-main --list-versions
#    → ext-scaa17：无版本或类型不符 → 回报等决策，不要自行换集
#    → ext-main：type=object-detection 时 coco-segmentation 导出可能无多边形
#      （下载器会打预检警告；解包校验 total_poly==0 硬失败）→ 回报决策再下载
# ② 四集下载（坐标见 C:/devsetup/dataset_sources.txt；ext-main 用 --only dcv）
.venv/Scripts/python.exe scripts/download_datasets.py --only dcv --out data/datasets/ext-main
# ③ 逐集校验
cd data/datasets/ext-main && sha256sum -c SHA256SUMS && cd ../../..
# ④ 离线体检（映射/结构/登记册）
.venv/Scripts/python.exe -m pytest tests/test_dataset_registry.py -q
```

## 附录 B · 全量合成 + 外部集合并（GPU 机执行，留给训练线）

```bash
# 全量合成（10000 对 + holdout 500）+ ext-main 合并进 train/（一根命令；
# 完整参数语义见 train/README.md 与 train/prepare_coco.py --help）
.venv/Scripts/python.exe train/prepare_coco.py \
  --train-pairs 10000 --holdout-pairs 500 --seg-format polygon \
  --ext-coco-json data/datasets/ext-main/content/train/_annotations.coco.json \
  --ext-image-root data/datasets/ext-main/content/train \
  --mapping-yaml data/datasets/ext-main/mapping.yaml --mapping-source ext-main \
  --out train/runs/datasets/v1
# 其余三集换对应 --ext-coco-json/--ext-image-root/--mapping-yaml/--mapping-source
# 即同法合并；注意当前 CLI 一次只吃一个外部集，多集合并需训练线扩展或分批
# （合并 stats.skipped_categories 会显式列出未映射跳过的类别，供核对映射表）。
# 产物校验：cd train/runs/datasets/v1 && sha256sum -c SHA256SUMS
# 上传 GPU 机走 COS 中转（跨机不直传）。
```

## 5. 映射总原则（四集通用）

- 目标键 = `configs/taxonomy.yaml` 的 13 类；映射文件语义对齐
  `train/prepare_coco.py --mapping-yaml`（顶层键=中性代号，--mapping-source 同值）。
- 同义归并按简报参考表：agrio/full sour/partial sour→sour；broca/insect bored→insect；
  caracolillo/peaberry→peaberry；concha/shell→shell；elefante→elephant；
  partido/broken/cut/chipped→broken；dry/withered/dry cherry→dried；
  negro/full black/partial black→black；fade/spotted→faded；fungus/moldy→mold；
  normal/good/premium→normal。
- **longberry→null**（尺寸概念走计量轨、不走分类）——本批四集词表均未出现
  longberry，故各 mapping.yaml 无此行；若未来入库集出现该类，按 null 排除并注明本条。
- 映射未命中的类别在合并 stats 的 `skipped_categories` 显式暴露（不静默）；
  `tests/test_dataset_registry.py` 会在数据就位后校验「实际类别 ⊆ 映射表键」。

## 附录 C · 冒烟验证记录（2026-10-02）

- **brief 原命令（--emit-sample 独占模式实证）**：

  ```
  .venv/Scripts/python.exe train/prepare_coco.py \
    --emit-sample out/smoke-merge/brief-literal-sample --limit-pairs 5 \
    --ext-coco-json data/datasets/ext-main/content/train/_annotations.coco.json \
    --ext-image-root data/datasets/ext-main/content/train \
    --mapping-yaml data/datasets/ext-main/mapping.yaml --mapping-source ext-main \
    --out out/smoke-merge/brief-literal
  ```

  实测 exit 0，只产出合成小样本（2 图/12 标注）；**--ext-coco-json/--mapping-yaml
  在该模式下不被读取**（train/prepare_coco.py 真实分支在 emit-sample 后提前
  return）——即 brief 原命令验证的是合成小样本链路，不是合并链路；且数据未就位
  （ext-main 导出路径当时不存在）也不报错，不能作为合并验证依据。

- **合并链路（merge_ext_coco）冒烟 PASS × 4（四集各一遍，合成替身）**：
  每集用按其页面已核验类别表构造的替身 COCO（**明确非真实数据**）+ 该集真实
  mapping.yaml，同款命令 `--limit-pairs 1 --holdout-pairs 2 --mapping-yaml
  data/datasets/<代号>/mapping.yaml --mapping-source <代号>`（--ext-coco-json/
  --ext-image-root 指向 out/smoke-merge/synth-<代号>/ 替身）。实测（2026-10-02）：

  | 代号 | 并入标注 | 跳过（null/未知） | skipped_categories | 输出 categories |
  |---|---|---|---|---|
  | ext-main | 9 | 3 | helado, oreja, triangulo | == taxonomy 13 类 |
  | ext-rseg | 4 | 0 | （空） | == taxonomy 13 类 |
  | ext-rgreen | 2 | 0 | （空） | == taxonomy 13 类 |
  | ext-scaa17 | 14 | 4（3 null + 1 故意未知类） | Floater, Husk, Parchment, TotallyUnknownClass | == taxonomy 13 类 |

  映射命中/跳过均显式可见（不静默）；`ext_` 前缀防撞名生效；四份 mapping.yaml
  均通过 prepare_coco 真实加载器解析（非 null 目标键全部 ∈ 13 类）。

- **第二轮复核修订（2026-10-02）**：①ext-main 映射键按页面实抓改为**西语原样**
  （旧键为旧 README 英译，11/12 键不命中；broca 由误配 brocade 纠正为 insect，
  简报参考表 broca→insect），替身与合并冒烟已按西语键重跑（上表 ext-main 行）；
  ②dcv 模式带 --out 时 manifest internal_name 改取目录名（tests 新增回归
  test_dcv_mode_internal_name_follows_out_dir）；③下载器 dcv/universe 两路径
  现打印 API 自报项目 type，并对「分割格式 × 检测型项目」在下载前打预检警告；
  ④登记册 §0/§1/附录 A 已按 ext-main 页面类型差异（Object Detection vs 多边形
  预期）补记先探测后下载流程。

- **真实数据四集冒烟：PENDING_KEY**——key 就绪后按附录 A 下载，随后对每集跑
  同款 `--limit-pairs 1 --holdout-pairs 2` 小样本合并（换成各集真实
  --ext-coco-json/--ext-image-root/--mapping-yaml/--mapping-source），核对
  stats 与 13 类键后把结论记回本文件第 1-4 节。


---

## 2026-10-03 下载实录（key 就绪后执行）

| 代号 | 结果 | 实测规模 | 备注 |
|---|---|---|---|
| ext-main | ✅ v8 bbox COCO | **8728 图 / 10779 标注（含多边形 8340）/ 13 类** | 主源所有版本均 320×320 预处理——适合喂裁剪分类腿（224-320px），对 1024 分割腿贡献有限；bbox 导出意外含多边形，T3 合并时可作分割源；新增容器类 coffee-beans（null 映射） |
| ext-rseg | ✅ 备选源 coco-segmentation | **1002 图 / 5 类** | 主源无版本，走备选 robusta-coffee-bean-defects；实测键名 Broken-Chipped（连字符），新增 defects 粗标桶（null）；**绿豆占比抽样核验仍 PENDING**（烘焙工作区风险，T3 并入前必须完成） |
| ext-rgreen | ✅ coco bbox | **250 图 / 3 类** | 实测多一个 defect-coffee 粗标桶（null 映射） |
| ext-scaa17 | ✅ 备选 fork coco bbox | **1500 图 / 15 类** | 主源 gcb 无已生成版本，走预案备选 fork；fork 将 Full/Partial Black/Sour 简并、含 objects 容器类（null）；映射表已按 fork 实测类名重写 |

合计 **11480 图**。全四集 mapping/manifest/SHA256SUMS 齐备并通过 tests/test_dataset_registry.py 20/20。
过程修复：download_datasets.py resolve_version 兼容 REST 全路径字符串版本 id（"ws/proj/N"）；
ext-main 需 `--format coco`（项目类型 object-detection，无分割导出）。
