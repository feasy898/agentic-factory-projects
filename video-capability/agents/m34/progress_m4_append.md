
## M4 完成 (2026-09-08, 端到端 + 崩溃恢复)
- [e2e] 全新沙箱 /root/cradle_m4_sandbox (CRADLE_ROOT 隔离, models 只读软链, D-037 配方) 一键出片
  PASS: `bash scripts/m4_e2e_demo.sh` = initdb → ingest 6 卡(S01/S03/S05/S02/S07 + S12 ken_burns,
  D-037) → run --task-file --once 不动点全链 → 自动 compose。总墙钟 **340s**;
  终态 composed=6/6, 候选 pass=16, yield_accepted=1.0 / with_fallback=1.0, unfinished=0 blocked=0;
  成片 output/product_seeding_25s.mp4 (h264 1088×1920+aac, 25.000s, 5.6MB);
  报告 reports/milestones/m4_e2e_demo.md (含踩坑: 沙箱缺 models 软链时 gater 回落 HF hub 被墙卡死)
- [recover] **kill -9 崩溃恢复演示 PASS** (M4 核心验收点): 沙箱 /root/cradle_m4_sandbox2,
  05:47:38 于 gating=1∧generating=1 混合孤儿窗口 kill -9 (watcher 1s 轮询自动命中);
  05:48:02 重启 → `recover(): 重置 1 个孤儿任务` (generating S02→pending;
  gating S01 有 3 候选**保留不重生成**, id/mtime 佐证: 重启后 verdict pending→pass 而
  文件 mtime 仍为 kill 前 05:47:34-38) → 05:53:20 6/6 composed + 自动合成成片(25.000s) +
  主循环干净退出, 全库 16 候选无重复无冗余生成;
  报告 reports/milestones/m4_recovery_demo.md (prekill 快照/时间轴/候选对照表)
- [tool] scripts/m4_start_orch.sh + m4_kill_when_mixed.sh (演示可复现, 入 git)
- [test] pytest 209 passed 复核(M4 无管线代码改动, 复用 M3 合成层升级)
- 决策追加 D-037; commit "M4: e2e CLI + crash recovery demo"
