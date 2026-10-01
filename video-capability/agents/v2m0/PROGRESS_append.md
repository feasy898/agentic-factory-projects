
## V2-M0 完成 (2026-09-08, v2 状态恢复 + 回归夹具库 + G7 模型准备)
- [audit] v1 状态审计(SPECS_V2 §0):git 13 commits + tag v1.0;主仓库 12 任务/62 候选(34 LTX fail + 25 pass + 3 fallback);沙箱库 27 任务/60 候选(58 pass + 2 fail)+ m5_videos 9 成片台账;output 10 片;画廊 24 例;api_usage 230 次全部 route=local(API 预算零消耗)。全文: reports/V2_M0_AUDIT.md
- [disk] 治理 3.3G(used 67→64G, avail 28→31G):m4 演示沙箱 208M + /tmp 残留 80M + .frames 缓存 609M + open_clip 冗余副本 890M + whisper medium 评测残留 1.5G;8G 目标不可达,范围裁定记 D-051
- [verify] v1 最小任务全链 51s 全绿:m0v 沙箱(D-037 配方)S12 ken_burns 走 initdb→ingest→run,六门禁 G1 1.0/G2 0.926/G3 0.970/G4 0.995/G5 0.770/G6 deferred;**pytest 226 passed**;记 D-055
- [fixtures] **回归夹具库 47 条入库**(指标全达标):fail 15(fluid_melt 8/split_merge 3/count_drift 2/object_flow 2,四类全覆盖;8 条曾 verdict=pass、6 条曾 selected)+ pass_structural 15(v1 真产物 4 + kenburns 确定性再生成 11)+ pass_candidate 17(G7e 预审,**待人工确认**)。方法: DINOv2 粗筛 122/122(median 0.972)→ 26 条嫌疑三联帧逐条目检;可分性 fail≤0.845 vs pass_structural≥0.962 零重叠。入库: 主仓库 fixtures 表 + workdir/fixtures/(媒体 32.1MB 随 git 入库,D-053)+ reports/fixtures/INDEX.md + dino_scan_hist.png。口径记 D-052
- [models] G7 模型 5/6 就绪且 Volta 自查通过(D-054):DINOv2 ViT-L/14 1.22G(ModelScope, fp16 OK)/ grounding-dino-tiny 689M(**fp32+autocast-fp16 口径**, 纯 .half() 有 dtype bug)/ SAM ViT-B 375M(fp16 OK)/ RAFT-small 4M(fp32 OK, FX-F001 光流 P95=128px)/ Depth-Anything-V1-Small 99M(fp16 OK);pip matplotlib+lap 就绪;MobileSAM 备份下载失败不阻塞
- git: "V2-M0: audit + fixture library + G7 model prep"
