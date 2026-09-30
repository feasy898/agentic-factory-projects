# M4 kill -9 崩溃恢复演示 (m4_recovery_demo)

- 日期: 2026-09-08 05:47-05:53 (服务器时间)
- 沙箱: `/root/cradle_m4_sandbox2` (CRADLE_ROOT 隔离, 与 e2e 沙箱/真实 workdir 互不影响; 6 卡已 ingest)
- 结论: **PASS** — kill -9 留下混合孤儿态(gating+generating), 重启后 recover() 精确区分两类孤儿:
  **generating→pending 重生成**、**gating(有候选)→保留候选继续门禁不重生成**, 最终 6/6 composed
  并**自动合成成片**, 主循环干净退出。

## 1. 时间轴(全部有日志/DB 佐证)

| 时刻 | 事件 | 佐证 |
|---|---|---|
| 05:47:14 | run1 启动 (PID 3183131, nohup, 日志 m4_run1.log) | `RUN1 START` + ps |
| 05:47:18 | watcher 轮询: `{'generating': 1, 'pending': 5}` (S01 生成中/LTX 加载) | watcher 输出 |
| 05:47:38 | watcher 命中窗口 `{'gating': 1, 'generating': 1, 'pending': 4}` → **kill -9 3183131** | watcher `KILL9 pid=3183131 at 2026-09-08 05:47:38` |
| 05:47:38+ | 进程确认死亡; **prekill 快照**落盘 m4_prekill_snapshot.txt | §2 |
| 05:48:02 | run2 启动 (PID 3183692, 日志 m4_run2.log) | run2 log 首行 |
| 05:48:02 | **`recover(): 重置 1 个孤儿任务`** — 仅 S02(generating→pending); S01(gating, 有候选)原样保留 | run2 log + DB |
| 05:49:22-26 | S02 重生成 3 候选(新文件 mtime) | 候选表 mtime |
| ~05:49-05:53 | S01 既有候选继续门禁(pass, 未重生成); S03/S05/S07/S12 正常推进 | 候选表+log |
| 05:53:20 | **`成片完成: product_seeding_25s -> 沙箱/output/product_seeding_25s.mp4`** | run2 log |
| 05:53:20 | **`全部任务到达终态, 主循环退出`** (无进程残留, nvidia-smi 0MiB) | run2 log + ps |

## 2. kill 时孤儿态快照 (m4_prekill_snapshot.txt, kill -9 前一瞬)

```
-- tasks --
S01 gating      attempts=0   <- 孤儿 A: 门禁中(3 候选已生成, verdict=pending)
S02 generating  attempts=0   <- 孤儿 B: 生成中(候选 0 个, kill 落在首候选完成前)
S03/S05/S07/S12 pending
-- candidates --
id=1 S01_a0_0.mp4 verdict=pending mtime=05:47:34 size=120234
id=2 S01_a0_1.mp4 verdict=pending mtime=05:47:36 size=143758
id=3 S01_a0_2.mp4 verdict=pending mtime=05:47:38 size=118011
```

## 3. 恢复行为证据 (重启后最终候选表, 与 §2 对照)

| 候选 | id | 文件 mtime | 最终 verdict | selected | 说明 |
|---|---|---|---|---|---|
| S01_a0_0 | **1** | **05:47:34 (kill 前)** | pass (0.9307) | 0 | **未重生成**: id/mtime 不变, 仅 verdict pending→pass(重启后继续门禁) |
| S01_a0_1 | **2** | **05:47:36 (kill 前)** | pass (0.9200) | 0 | 同上 |
| S01_a0_2 | **3** | **05:47:38 (kill 前)** | pass (0.9335) | **1** | 同上, 被 select 进成片 |
| S02_a0_0 | 4 | 05:49:22 (重启后) | pass (0.9554) | **1** | **重生成**: recover 孤儿 generating→pending 后重新生成 |
| S02_a0_1 | 5 | 05:49:24 | pass (0.9542) | 0 | 同上 |
| S02_a0_2 | 6 | 05:49:26 | pass (0.9537) | 0 | 同上 |

- 全库候选总数 16 = 5 LTX×3 + S12 kenburns×1, **无重复行/无多余生成** (S02 死时 0 候选, 干净重生成)
- 最终任务态: **composed×6**, attempts 全 0; 成片 ffprobe: h264 1088×1920 + aac, 25.000s, 5.6MB

## 4. 恢复语义依据

`src/orchestrator.py recover()` (D-012): 孤儿 generating→pending 重生成; gating 且无候选→pending;
**gating 且有候选→保持 gating**, 由 `_gate_candidates` 对既有 verdict=pending 候选续评(幂等)。
本次演示覆盖前两类中"generating"与"gating 有候选"两种实际发生的孤儿形态。

## 5. 产物

- 成片: `/root/cradle_m4_sandbox2/output/product_seeding_25s.mp4` (25.0s, 1088×1920, 自动合成)
- 日志: `沙箱/workdir/logs/m4_run1.log`(崩溃前) / `m4_run2.log`(重启+recover+收敛)
- 快照: `沙箱/workdir/logs/m4_prekill_snapshot.txt`
- 演示工具(入 git): `scripts/m4_start_orch.sh`(exec 保证 PID 可追), `scripts/m4_kill_when_mixed.sh`(1s 轮询 DB, 命中 gating≥1∧generating≥1 窗口即 kill -9 + 落快照)
