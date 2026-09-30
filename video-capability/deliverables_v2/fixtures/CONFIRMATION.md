# pass_candidate 人工确认清单 —— **本轮唯一人工动作**

> **怎么回复(一句话即可)**: 「这些算过」; 或「第 X 个(fixture 号)有问题」; 对 B 组另可回复「杀得对/杀过头」。
> - **A 组 13 条**: G7 终版全部判过 —— 请确认画面可用。
> - **B 组 4 条**: G7 终版判杀(FX-C001/C002/C003/C010) —— 按"宁可误杀"原则主动杀的, **请你复核杀得对不对**。
> - 看图: 每条附首/中/尾三联拼图(`workdir/fixtures/strips/<id>.jpg`, 已入 git); 看动态: 同行 mp4(已入 git, 克隆即看)。

## 判读基准(与 G7e 豁免条款同源, `src/gates/g7_vlm_prompt.txt`)

- 液体/蒸汽/雾/光影等"软"本体的运动、沸腾、高光变化 **不算缺陷**;
- 要看的是: 硬物体(食物主体/容器/建筑/人物)的**形状保持、数量一致、无凭空出现/分裂/融合/液化**。

## A. 系统判过, 请确认 (13 条)

| # | fixture | 源候选 | 内容 | 三联拼图 | 动态 mp4 | G7 终版 score | a / d 余弦 |
|---|---|---|---|---|---|---|---|
| A01 | FX-C004 | SB_S10_39 | 全景餐桌,碗碟结构保持,锅内沸腾豁免 | [strips](../../workdir/fixtures/strips/FX-C004.jpg) | `workdir/fixtures/pass_candidate/FX-C004.mp4` | 0.9280 | a 0.8560 / d 0.8560 |
| A02 | FX-C005 | SB_S10_40 | 全景餐桌,结构保持 | [strips](../../workdir/fixtures/strips/FX-C005.jpg) | `workdir/fixtures/pass_candidate/FX-C005.mp4` | 0.9420 | a 0.8841 / d 0.8841 |
| A03 | FX-C006 | SB_ABS11L_9 | 走廊背影行走,人物位移为正常运动,结构保持;AB横版 | [strips](../../workdir/fixtures/strips/FX-C006.jpg) | `workdir/fixtures/pass_candidate/FX-C006.mp4` | 0.9318 | a 0.8636 / d 0.8636 |
| A04 | FX-C007 | SB_S14_51 | 饮料杯,液体飞溅与果块滚动属液体豁免,杯体保持 | [strips](../../workdir/fixtures/strips/FX-C007.jpg) | `workdir/fixtures/pass_candidate/FX-C007.mp4` | 0.9330 | a 0.8660 / d 0.8660 |
| A05 | FX-C008 | SB_S05_25 | 糕点盘,块形与数量保持,酱汁延展豁免 | [strips](../../workdir/fixtures/strips/FX-C008.jpg) | `workdir/fixtures/pass_candidate/FX-C008.mp4` | 0.9275 | a 0.8530 / d 0.8579 |
| A06 | FX-C009 | SB_S05_23 | 糕点盘,块形与数量保持 | [strips](../../workdir/fixtures/strips/FX-C009.jpg) | `workdir/fixtures/pass_candidate/FX-C009.mp4` | 0.9477 | a 0.8954 / d 0.8954 |
| A07 | FX-C011 | SB_S06_26 | 饮料杯,液体飞溅豁免,杯体与果块保持 | [strips](../../workdir/fixtures/strips/FX-C011.jpg) | `workdir/fixtures/pass_candidate/FX-C011.mp4` | 0.9913 | a 0.9811 / d 0.9848 |
| A08 | FX-C012 | SB_S13_47 | 虾仁盘,虾形完好数量一致 | [strips](../../workdir/fixtures/strips/FX-C012.jpg) | `workdir/fixtures/pass_candidate/FX-C012.mp4` | 0.9896 | a 0.9792 / d 0.9792 |
| A09 | FX-C013 | SB_ABS08P_8 | 夜景店面竖版,结构保持;AB竖版 | [strips](../../workdir/fixtures/strips/FX-C013.jpg) | `workdir/fixtures/pass_candidate/FX-C013.mp4` | 0.9975 | a 0.9944 / d 0.9957 |
| A10 | FX-C014 | SB_ABS08L_7 | 夜景店面横版,结构保持;AB横版 | [strips](../../workdir/fixtures/strips/FX-C014.jpg) | `workdir/fixtures/pass_candidate/FX-C014.mp4` | 0.9714 | a 0.9353 / d 0.9540 |
| A11 | FX-C015 | MAIN_S10_30 | LTX调试片,餐桌全景首尾一致 | [strips](../../workdir/fixtures/strips/FX-C015.jpg) | `workdir/fixtures/pass_candidate/FX-C015.mp4` | 0.9980 | a 0.9947 / d 0.9978 |
| A12 | FX-C016 | MAIN_S04_11 | LTX调试片,肥牛卷+倒油,首尾一致 | [strips](../../workdir/fixtures/strips/FX-C016.jpg) | `workdir/fixtures/pass_candidate/FX-C016.mp4` | 0.9977 | a 0.9951 / d 0.9958 |
| A13 | FX-C017 | MAIN_S03_7 | LTX调试片,虾仁盘首尾一致,虾形完好 | [strips](../../workdir/fixtures/strips/FX-C017.jpg) | `workdir/fixtures/pass_candidate/FX-C017.mp4` | 0.9216 | a 0.8432 / d 0.8432 |

## B. 系统判杀, 请你复核 (4 条)

| # | fixture | 源候选 | 内容 | 三联拼图 | 动态 mp4 | G7 终版 score | 触发子项 | 判杀原因(系统口径) |
|---|---|---|---|---|---|---|---|---|
| B01 | FX-C001 | SB_S01_11 | 毛肚特写,主体形状保持,汤面波动属液体豁免 | [strips](../../workdir/fixtures/strips/FX-C001.jpg) | `workdir/fixtures/pass_candidate/FX-C001.mp4` | 0.8926 | a+d | 毛肚沸腾特写, 首尾画面剧烈演化 → a/d 真实低余弦(0.785 < 0.82/0.84), 按不对称原则主动误杀 |
| B02 | FX-C002 | SB_S01_12 | 毛肚特写,主体保持,液面高光变化 | [strips](../../workdir/fixtures/strips/FX-C002.jpg) | `workdir/fixtures/pass_candidate/FX-C002.mp4` | 0.8840 | a+d | 同上(a/d 0.768), 同一镜头相邻候选 |
| B03 | FX-C003 | SB_S01_13 | 毛肚特写,主体保持 | [strips](../../workdir/fixtures/strips/FX-C003.jpg) | `workdir/fixtures/pass_candidate/FX-C003.mp4` | 0.9116 | d | 同上(d 0.8235 < 0.84; a 0.8229 未触发), 同一镜头相邻候选 |
| B04 | FX-C010 | SB_S08_32 | 夜景店面,灯笼门脸结构保持 | [strips](../../workdir/fixtures/strips/FX-C010.jpg) | `workdir/fixtures/pass_candidate/FX-C010.mp4` | 0.9486 | b | 夜景灯笼 GDINO 检测闪烁 → churn>12; d 余弦 0.982 很高, **可能属误杀**, 请重点复核 |

## 裁定后的动作

- A 组全确认 + B 组"杀得对" → 夹具库定版, thresholds_v2.yaml 不动;
- 若某条 B 组被裁定"杀过头" → 该条转正为可用候选参考, 阈值是否放宽由 owner 另行决定(G7_CALIBRATION §2 显示再放宽会挤压拦截稳健性);
- 若 A 组发现问题 → 请指出 fixture 号, 该条转入失败画廊并在下一轮夹具库修订中改标。

