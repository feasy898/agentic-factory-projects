# sorting_log — HN-Robusta v0.1 分堆台账

> 每堆分完**立即**记一行（协议 §2.3：堆名/粒数/分拣人/日期；当天不补记）。
> 「≥20」列填 是/否——不足 20 粒的类照实记否（manifest 标 WARN，只用于人工
> 核对，不用于阈值回填）；「净重g」蓝牙秤到货后补称回填（操作卡 §8）。
> 拿不准的粒子入待议堆并在此登记；归类争议另记 `disputes.md`。
> 「主/次」列合法取值只有 5 个：`primary`（★主缺陷 5 类）/ `secondary`
> （次缺陷类；peaberry 也填 secondary，「计量不计缺陷」写进疑难点）/ `normal`
> （好豆堆）/ `size_tray`（大中小分型堆）/ `pending`（待议堆）——定义见操作卡 §5。

| 日期 | 操作人 | 类key | 中文类名 | 主/次 | 粒数 | ≥20 | 净重g | 疑难点 |
|------|--------|-------|----------|-------|------|-----|-------|--------|
| 2026-10-03 | 张三 | black | 黑豆 | primary | 23 | 是 | | 3 粒局部发黑疑似 sour，已移待议堆（示例行，可删） |
| | | normal | 好豆 | normal | | | | |
| | | broken | 破碎 | secondary | | | | |
| | | faded | 褪色/白化 | secondary | | | | |
| | | brocade | 花脸 | secondary | | | | |
| | | immature | 未熟 | secondary | | | | |
| | | peaberry | 花豆/胡椒粒豆 | secondary | | | | 计量不计缺陷（counts_as_defect=false） |
| | | shell | 贝壳豆 | secondary | | | | |
| | | elephant | 象豆 | secondary | | | | |
| | | insect | 虫蛀 | primary | | | | |
| | | dried | 干瘪/僵豆 | primary | | | | |
| | | sour | 酸豆 | primary | | | | |
| | | mold | 霉豆 | primary | | | | |
| | | black | 黑豆 | primary | | | | |
| | | （大粒堆） | 大粒分型 | size_tray | | | | 全盘照见 images/size_trays/ |
| | | （中粒堆） | 中粒分型 | size_tray | | | | |
| | | （小粒堆） | 小粒分型 | size_tray | | | | |
| | | （待议堆） | 待议 | pending | | | | 不入 v0.1；复核后归堆或剔除 |

## 2026-10-04 夸克实拍照（raw_quark/，26 张）坏堆谱系确认（owner 口述）

| 日期 | 操作人 | 堆/类key | 中文 | 主/次 | 依据 | 疑难点 |
|------|--------|----------|------|-------|------|--------|
| 2026-10-04 | owner（口述） | 坏堆→broken | 缺口/不成形（畸形） | secondary | 「豆子缺口、不成形」 | 不成形豆归 broken（畸形家族；与 shell 边界待细标） |
| 2026-10-04 | owner（口述） | 坏堆→black | 发黑 | primary | 「发黑」 | — |
| 2026-10-04 | owner（口述） | 坏堆→sour | 发黑红 | primary | 「发黑红」（酸豆典型外观即黑红褐） | 与 black 的边界按色调深浅，细标时确认 |
| 2026-10-04 | owner（口述） | — | 无虫蛀/无霉 | — | 「没有虫蛀和发霉」 | **真实坏堆不含 insect/mold**——这两类真实样本靠公开数据集（ext-main broca/fungus 等） |
| 2026-10-04 | owner（口述） | 大/中/小堆→normal | 好豆（按尺寸三档） | normal | 分堆定义 | 兼作轨2（大≥17/中15-16/小≤14）尺寸标定素材 |

> 批5真实照片探针解读口径更新：坏堆「合理缺陷预测」= {broken, black, sour} 三类，
> 预测为 mold/insect/dried 等视为误判类（该堆无此缺陷）。
