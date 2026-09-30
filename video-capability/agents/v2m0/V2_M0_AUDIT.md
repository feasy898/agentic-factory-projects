# V2-M0 审计报告(v2 状态恢复 + 夹具库 + G7 模型准备)

- 执行: V2-M0 子代理,2026-09-08
- 依据: `SPECS_V2.md`(569108a)§0 审计恢复/§2 夹具库、v1 DECISIONS D-019/D-021/D-022/D-025/D-029/D-037/D-038/D-041/D-050
- 结论速览: **v1 管线可运行(51s 全链六门禁全绿,pytest 226 全绿);磁盘治理 3.3G(avail 31G,红线 20G 无忧);回归夹具库 47 条入库(fail 15 四类全覆盖 + pass_structural 15 + pass_candidate 17 待人工确认);G7 模型 5/6 就绪并全部通过 Volta 自查。**

---

## 1. v1 状态清点

| 资产 | 实测 | 备注 |
|---|---|---|
| git | 13 commits(53b9881 bootstrap → 569108a SPECS_V2 落盘)+ tag **v1.0** | 会话开始时 worktree clean |
| 规格 | SPECS.md(v1,142 行)+ SPECS_V2.md(106 行,已入库) | 冲突以 v2 为准 |
| 主仓库 `workdir/cradle.sqlite3` | **12 任务 / 62 候选** / api_usage 59 / events 64 | 任务: 9 accepted + 3 fallback(S08/S09/S11);候选: 34 fail + 25 pass + 3 fallback |
| 沙箱库 `/root/cradle_m5/workdir/cradle.sqlite3` | **27 任务 / 60 候选** / api_usage 171 / events 124 / **m5_videos 9 成片台账** | 候选: 58 pass + 2 fail;含 10 条 AB(ABS01L/P..ABS11L/P) |
| output/ | **10 成片**: t1_seeding v1-v3(25s)/ t2_ambiance v1-v3(22s)/ t3_offer v1-v3(17s)/ m3_debug(25s)+ 9 个 .ass 字幕 | 与 m5_videos 台账一致 |
| 失败画廊 | **24 例 case.md**(typeA_g5_scene_bias 22 + typeB_g5_edge 2),mp4+grid 已随 v1.0 入库 | D-049 口径 |
| 候选池物理文件 | 主仓 candidates 目录 187 项 / 沙箱 180 项(.frames 缓存已清理,见 §2) | |
| 资产 | 11 张 832×1216 SDXL 主图 + manifest.json(D-029) | |
| 模型 | models/ 44G: Wan-Fun-InP 19G + LTX-2B 18G + SDXL fp16 6.5G + CLIP 0.9G + whisper 0.46G + yolo 6.3M | |
| API 消耗 | 两库合计 **230 次调用全部 route=local**(vlm 119 / tts 111),API 预算零消耗 | config/api.env 兜底链未实际用 API |
| 关键决策 | D-001..D-050 全部在册,墙钟硬停 2026-09-13 00:52 | |

v1 关键决策复核(仍有效): D-019(Wan2.1-Fun-1.3B-InP 替代主选)、D-021(下载源策略)、D-022(diffsynth 1.1.9 patchify 补丁)、D-025(卡面投影)、D-029(资产单源)、D-037/D-038(沙箱配方与 setsid nohup)、D-041(G5 双锚)——本轮全部沿用,无冲突。

## 2. 磁盘治理

前后: **67G used / 28G avail → 64G used / 31G avail**(红线 <20G 全程无风险)。

| 清理项 | 大小 | 依据 |
|---|---|---|
| /root/cradle_m4_sandbox + _sandbox2 | 208M | 演示沙箱,证据已在 reports/(任务面授权) |
| /tmp 残留(pytest-of-root、tmpu4enuep_ 等+散 PNG) | ~80M | 可再生测试/构建残留 |
| .frames 抽帧缓存(两库 candidates 下 121 处) | 609M | 门禁中间产物,可用 ffmpeg 再生 |
| ~/.cache/open_clip/ViT-L-14.pt | 890M | 冗余副本(md5 096db1af… 与 models/clip/ViT-L-14.pt 一致,删除前已校验) |
| ~/.cache/whisper/medium.pt | 1.5G | D-047 对比评测残留;生产用 models/whisper/small.pt |
| **合计** | **3.3G** | |

**目标偏差(记 D-051)**: 任务面"腾出 ≥8G"不可达——授权清理项合计不足 1G,扩大到可再生缓存也仅 3.3G。不动 models/(44G,再生产物+D-037 沙箱只读软链依赖)、不动 LTX fp32 布局(D-020 记载的加载路径)、不动 .venv(唯一环境)。新增 G7 模型 ~2.4G 后 avail 仍 ~29G,对 M1-M5 充裕。

## 3. v1 管线可运行性验证

**最小任务**(SPECS_V2 §0-3): 新建 `/root/cradle_m0v` 沙箱,完整 D-037 配方(models/templates 只读软链 + assets 拷贝 + `CRADLE_CLIP_WEIGHTS` + `HF_HUB_OFFLINE=1`),S12 ken_burns 卡(生产口径 480×832/5s)走完整链:

```
initdb → schema v2 就绪
ingest → S12 task#1 lane=ken_burns
run    → 事件链: 22:09:28 pending → 22:09:29 generating → 22:10:02 gating → 22:10:22 accepted (51s)
status → accepted 1 / 候选 pass=1
```

候选 `S12_a0_0.mp4` 六门禁全绿: G1 1.0(ffprobe 480×832/16fps/5s h264)、G2 0.926、G3 0.970(阈值 0.65)、G4 0.995(阈值 0.85)、G5 0.770(阈值 0.70)、G6 deferred(合成阶段逐字校验,D-036 设计)。DB: `/root/cradle_m0v/workdir/cradle.sqlite3`。

**pytest 复跑**: `226 passed, 1 warning in 10.35s`(log: workdir/logs/v2m0_pytest.log)。

**结论: v1 管线(initdb→ingest→run→gates)与测试资产完好,可进入 v2 开发。**

## 4. 回归夹具库(SPECS_V2 §2 核心交付)

### 4.1 构建方法与口径(D-052)

1. **粗筛**: DINOv2 ViT-L/14(fp16)对**全候选池 122 条**(主仓 62 + 沙箱 60)抽首/尾帧算余弦相似度,122/122 成功。分布: min 0.352 / p10 0.722 / **median 0.972** / p75 0.995。`<0.80` 嫌疑 17 条,`0.80-0.88` borderline 9 条。分布图: `reports/fixtures/dino_scan_hist.png`;原始数据: `workdir/logs/v2m0_dino_scan.json`。
2. **精筛**: 26 条嫌疑候选逐条抽首/中/尾三联帧,由本代理目检(G7e 对读协议: 形状保持/数量一致/无液化/无分裂),按四类归类;把握不足的 3 条按不对称原则(宁可误杀,不可漏网)收录并标 borderline。
3. **画廊 24 例不整体混入**(它们是 G5 启发式偏差型,画面正常);仅目检确认真形变的 SB_S15_52(红油溢锅)收录为 FX-F005。MAIN 34 条 LTX 拒绝候选目检抽查(最低分 MAIN_S08_23 = 夜景正常雾气)证实均为启发式偏差而非形变,零收录——这与 D-041/D-049 结论互证。
4. **pass_structural**: v1 S12 真产物 + 3 条 fallback 渲染(`route.py`: fallback 车道=ken_burns,故为程序产物)+ 对 11 张 v1 资产用 `src/gen/kenburns.py` 确定性再生成(motion 轮转,480×832/5s/16fps,zoompan 无 RNG,单条 ~300KB/5.0s 实测)。
5. **pass_candidate**: G1-G6 全绿且经 G7e 对读预审无明显形变者,全部标注**待人工确认**。

### 4.2 统计自检(硬性指标)

| 指标 | 要求 | 实际 | |
|---|---|---|---|
| fail 夹具 | ≥15 | **15** | fluid_melt 8 / split_merge 3 / count_drift 2 / object_flow 2(四类全覆盖) |
| pass_structural | ≥10 | **15** | v1 真产物 4 + 确定性再生成 11 |
| pass_candidate | ≥10 | **17** | 全部"待人工确认" |
| 总计 | ≥35(M0 验收) | **47** | |

**可分性佐证**(G7a/D 首尾 DINO 单子项): fail 15 条 ∈ [0.352, 0.845],pass_structural v1 产物 ∈ [0.962, 0.984]——两组间隔 0.117,零重叠;pass_candidate ∈ [0.760, 0.998] 与 fail 组重叠,印证 SPECS_V2 诊断"仅靠首尾相似度不够,需 G7b/c/e 组合"。

### 4.3 fail 夹具清单(全部目检确证)

| fixture_id | 类别 | 源候选(库/判定/分) | dino | 现象 |
|---|---|---|---|---|
| FX-F001 | fluid_melt | SB_S17_60 (pass/0.923) | 0.3523 | 虾仁约9只清晰可数→融为虾味糊浆,个体形状完全消失(并发count_drift) |
| FX-F002 | fluid_melt | SB_S17_58 (pass/0.938) | 0.4185 | 虾仁溶解成酱糊,仅零星残形 |
| FX-F003 | fluid_melt | SB_S03_18 (pass/0.938) | 0.4355 | 整盘虾仁化为浓稠炖糊,数量不可辨识 |
| FX-F004 | split_merge | SB_ABS03P_4 (pass/0.930, **sel=1**) | 0.5156 | 盘中凭空出现无定形橙色酱糊团并扩大,与虾仁融合 |
| FX-F005 | object_flow | SB_S15_52 (fail/0.888) | 0.5493 | 红油与锅内物溢出锅沿流淌到桌面成滩(typeB画廊案例,目检确认真形变) |
| FX-F006 | fluid_melt | SB_S17_59 (pass/0.940, **sel=1**) | 0.5605 | 虾仁肿胀融浆,尾帧仅2只依稀可辨 |
| FX-F007 | fluid_melt | SB_ABS03L_3 (pass/0.914, **sel=1**) | 0.5752 | 虾仁膨胀融连成糊状团块 |
| FX-F008 | fluid_melt | SB_S02_14 (pass/0.939) | 0.5898 | 锅内红油长出凝胶状红色团块并增大 |
| FX-F009 | fluid_melt | SB_S15_53 (pass/0.909) | 0.6040 | 锅面化为浓稠红泥浆,周边配菜碗内容变形 |
| FX-F010 | split_merge | SB_S02_16 (pass/0.941, **sel=1**) | 0.6235 | 红油表面凝胶膜增厚蔓延,辣椒被裹入融合 |
| FX-F011 | split_merge | SB_S15_54 (pass/0.927, **sel=1**) | 0.7627 | 锅内凭空隆起巨大红肉状物,配菜碗内容变异 |
| FX-F012 | count_drift | SB_S03_17 (pass/0.938) | 0.8110 | 勺舀虾滑入场,盘内虾仁 9→15+ 只堆满 |
| FX-F013 | fluid_melt | SB_S02_15 (pass/0.939) | 0.6646 | borderline: 汤体变稠胶化+辣椒肿胀(轻),按不对称原则收录 |
| FX-F014 | count_drift | SB_S03_19 (pass/0.949, **sel=1**) | 0.7827 | borderline: 虾仁膨胀密堆观感数量增多,个体形状尚保持 |
| FX-F015 | object_flow | SB_S04_20 (pass/0.922) | 0.8447 | borderline: 油瓶中尾帧呈融状黑团(主食物肥牛保持) |

要点: **15 条 fail 中 8 条 verdict=pass、6 条曾 selected 进入成片/AB**——正是"通过 v1 全部门禁但人类判定不可用"的活体证据,与 SPECS_V2 §0 描述的人类审片发现(虾仁流体化、锅体流动)逐类对上。

### 4.4 pass_candidate 待人工确认清单(17 条,唯一人工动作)

Wan 生产: FX-C001 SB_S01_11 / FX-C002 SB_S01_12 / FX-C003 SB_S01_13(毛肚特写,主体保持)/ FX-C004 SB_S10_39 / FX-C005 SB_S10_40(全景餐桌)/ FX-C007 SB_S14_51(饮料,液体豁免)/ FX-C008 SB_S05_25 / FX-C009 SB_S05_23(糕点)/ FX-C010 SB_S08_32(夜景)/ FX-C011 SB_S06_26(饮料)/ FX-C012 SB_S13_47(虾仁盘,虾形完好);
AB: FX-C006 ABS11L_9(走廊背影)/ FX-C013 ABS08P_8 / FX-C014 ABS08L_7(夜景横竖版);
LTX 调试: FX-C015 MAIN_S10_30 / FX-C016 MAIN_S04_11 / FX-C017 MAIN_S03_7。
逐条说明见 `reports/fixtures/INDEX.md`;请用户对每条回复"确认/否决"。

### 4.5 入库物理与索引

- 物理文件: `workdir/fixtures/{fail,pass_structural,pass_candidate}/`(47 mp4 合计 28.4MB)+ 三联帧证据 `workdir/fixtures/strips/`(47 张,3.7MB);合计 32.1MB < 50MB 门槛(D-049 先例)→ 全量随 git 入库(D-053);
- DB: 主仓 `workdir/cradle.sqlite3` 新表 `fixtures(fixture_id, path, label, category, human_source, notes)`,47 行;
- 索引: `reports/fixtures/INDEX.md`(M5 终版)+ `workdir/fixtures/fixtures_manifest.json`。

## 5. G7/M3 模型下载与 Volta 自查(D-054, D-021 源策略)

| 模型 | 大小 | 来源(实测通道) | 耗时 | Volta 自查 |
|---|---|---|---|---|
| DINOv2 ViT-L/14 | 1.22G | ModelScope `AI-ModelScope/dinov2-large`(curl 直连) | ~2min | **fp16 OK**: 加载 1.6s,self-cos 1.0,同视频首尾帧 cos 0.9722,CLS norm 45.3 |
| Grounding DINO (SwinT tiny) | 689M+tokenizer | ModelScope `IDEA-Research/grounding-dino-tiny` | <1min | 纯 `.half()` ✗(transformers 4.49 dtype bug)→ **fp32权重+autocast-fp16 OK**: 2.5s/帧,检出 shrimp×13 + bowl×1,纯 PyTorch 零编译 |
| SAM ViT-B | 375M | ModelScope `facebook/sam-vit-base` | <1min | **fp16 OK**: 0.4s,点提示 mask 3.9% |
| RAFT-small | 4.0M | download.pytorch.org(curl 通道,D-021) | ~10s | **fp32 OK**: flow (1,2,832,480),FX-F001 首尾帧 mean 27.6px / **P95 128.2px**(融浆巨形变量级,佐证 G7c 判据);fp16 未启用防 overflow |
| Depth-Anything-V1-Small | 99M | hf-mirror `LiheYoung/depth-anything-small-hf` | ~1min | **fp16 OK**: 0.4s,depth ∈ [0.35, 20.70] |
| MobileSAM(备份 40M) | **失败**(两次 github 截断至 3.5MB;ModelScope 无仓) | — | — | 备份不可用,不阻塞(主选 SAM ViT-B 已过;M1 前可重试) |
| pip: matplotlib 3.11.1 / lap | — | aliyun pypi | ~40s | import OK(ByteTrack 依赖就绪) |

落盘: `models/{dinov2-large, grounding-dino-tiny, sam-vit-base, raft, depth-anything-small-hf}`(gitignore 内)。自查原始数据: `workdir/logs/v2m0_model_smokes*.json`、`v2m0_gdino_autocast.json`。**M1 实现注意**: Grounding DINO 必须用 fp32 权重+autocast(fp16) 口径。

## 6. 未达成/偏差清单

1. 磁盘治理 8G 目标 → 实际 3.3G(授权与可再生范围内已穷尽,D-051);
2. MobileSAM 备份下载失败(github 大文件通道不稳,ModelScope 无仓)——主选 SAM ViT-B 可用,不阻塞 G7c(D-054);
3. pass_candidate 17 条为机器预审,按规格保持"待人工确认"状态,不视为已完成确认;
4. INDEX.md 为雏形版(本轮),M5 终版(规格 §7-3)。

## 7. 产物索引

- 本报告: `reports/V2_M0_AUDIT.md`
- 夹具索引: `reports/fixtures/INDEX.md` + `reports/fixtures/dino_scan_hist.png`
- 脚本(全部幂等可重跑): `scripts/v2m0_dl_dinov2.sh` / `v2m0_dl_rest.sh` / `v2m0_dino_scan.py` / `v2m0_sheets.py` / `v2m0_model_smokes.py` / `v2m0_model_smokes2.py` / `v2m0_build_fixtures.py` / `v2m0_gen_index.py`
- 数据: `workdir/logs/v2m0_dino_scan.json`、`workdir/fixtures/fixtures_manifest.json`、`workdir/logs/v2m0_pytest.log`
- 决策增量: D-051..D-055(见 DECISIONS.md)
- 验证沙箱留档: `/root/cradle_m0v`(51s 全链证据)
