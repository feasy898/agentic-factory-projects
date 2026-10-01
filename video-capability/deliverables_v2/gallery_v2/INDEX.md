# gallery_failures_v2 — v2 期失败/误杀案例索引 (V2-M5)

> 构建脚本 `tools/m5v2_build_gallery_v2.py`(幂等); 媒体全部已在 git 库内(夹具 D-053 / overlay M3 入库), 案例目录引用相对路径不复制文件。

## 0. 本轮漏网 = 0 (如实声明)

v2 全程**未发生任何形变漏网**: 校准集 fail 夹具拦截 **15/15 = 100%**; 生产 25/25 候选 G7 全过(0 触发, score ∈ [0.9758, 0.9983]) + 21 帧目检 0 形变 + 主控 VLM 抽帧终检通过(v2_t1_seeding_v2)。

因此本目录不是"漏网画廊", 而是**不对称原则(宁误杀, 不漏网)的代价侧档案** —— 系统拒收了什么、为什么拒、拒得对不对。素材来源说明: 生产首轮 100% 良率 → 产线零被杀样本, 本目录案例全部来自 **overlay 素材审计** 与 **G7 校准期夹具运行**, 而非生产期。

## 1. overlay 审计 FAIL (4 例; 审计 FAIL 判定共 5 次/物理失败文件 3 个)

| 案例 | 素材类型 | 审计分 d' (阈 0.84) | 一句话归因 |
|---|---|---|---|
| [ov_steam_dense](overlay_audit_fail/ov_steam_dense/case.md) | 蒸汽(浓) | 0.5176 | 浓雾光渗透真实抬亮暗底, screen 混合将污染产品图底 —— 正确保护 |
| [ov_fog_low](overlay_audit_fail/ov_fog_low/case.md) | 雾(贴地) | 0.8265 | 贴地浓雾整幅渗透, c' 低纹理伪光流已豁免但 d' 背景语义漂移超阈 |
| [ov_bokeh_dust](overlay_audit_fail/ov_bokeh_dust/case.md) | 光斑(暗粒子) | 0.5499 → 0.71(亮化重生后) | 暗粒子低于亮度阈值动态区不可分 + 粒子本性动; 重生仍不达标即停 |
| [ov_mist_cool_v1](overlay_audit_fail/ov_mist_cool_v1/case.md) | 雾(首版) | 0.7272 → 重生后 **0.9427 PASS** | 唯一重生成功对照: prompt 限域收敛可行; 原件已被替换无独立视频 |

物理解释(D-066/D-069): 蒸汽/浓雾类的"雾光渗透"不是检测器误报 —— screen 混合模式下素材亮区会叠加到产品底图上, 底片暗区被真实抬亮属**物理污染**; 暗色粒子类则是审计口径的已知可分性局限(低于亮度阈值的本体无法与背景分离), 两者都不以放宽阈值解决(不对称原则)。

## 2. G7 校准期判杀的 pass_candidate (4 例, 误杀率 4/17=23.5% 带内)

| 案例 | 源候选 | G7 score | 触发子项 | 一句话归因 |
|---|---|---|---|---|
| [FX-C001](g7_calibration_killed/FX-C001/case.md) | SB_S01_11 | 0.8926 | a+d | 毛肚沸腾特写首尾剧烈演化, a/d 真实低余弦 —— 主动"宁误杀" |
| [FX-C002](g7_calibration_killed/FX-C002/case.md) | SB_S01_12 | 0.8840 | a+d | 同上相邻候选(a/d 0.768) |
| [FX-C003](g7_calibration_killed/FX-C003/case.md) | SB_S01_13 | 0.9116 | d | 同上(d 0.8235 触发, a 未触发) |
| [FX-C010](g7_calibration_killed/FX-C010/case.md) | SB_S08_32 | 0.9486 | b | 夜景 GDINO 检测闪烁 churn>12; d=0.982 很高, 误杀可能性最大 |

4 条均为 v1 六门禁全绿的真实生产候选; 前 3 条(毛肚)属画面真实剧烈演化、系统按不对称原则主动杀, FX-C010 属检测器噪声触发。**是否杀过头由用户裁定** → [CONFIRMATION.md](../fixtures/CONFIRMATION.md) B 组(本轮唯一人工动作)。

## 3. 与 v1 画廊的关系

- v1 画廊 [../gallery_failures/](../gallery_failures/)(24 例) = **G5 启发式偏差型**(画面正常被判拒, CLIP 口径局限的实证);
- 本目录 = **G7 物体恒存口径的拒绝侧**(overlay 素材审计 + 校准期主动误杀), 两目录互补, 共同构成门禁完整行为档案;
- v1 的 15 条真形变已收编为夹具库 fail 组(`workdir/fixtures/fail/`), 不在本目录重复列出。

