-- ============================================================================
-- m5_trace_query.sql — M5 成片「门禁明细可追溯」查询 (SPECS §10)
-- 库: ~/cradle_m5/workdir/cradle.sqlite3  (sqlite3 CLI 或任意 SQLite 客户端)
-- 用法:
--   sqlite3 ~/cradle_m5/workdir/cradle.sqlite3 < reports/milestones/m5_trace_query.sql
--   单片追溯: sqlite3 ... -cmd "PARAM :video_id='t1_seeding_v1'" < m5_trace_query.sql
-- 依赖 JSON1(json_each/json_extract, SQLite ≥3.38 默认内建)。
-- ============================================================================

-- 1) 全部成片台账: 成片名 / 模板 / 文件 / 合成级 G6(逐字+CER)
SELECT video_id,
       template_id,
       path,
       json_extract(g6_json, '$.passed')                AS g6_passed,
       json_extract(g6_json, '$.detail.subtitle_exact') AS g6_subtitle_exact,
       json_extract(g6_json, '$.detail.cer')            AS g6_asr_cer,
       created_at
FROM m5_videos
ORDER BY video_id;

-- 2) 从成片名反查每镜头候选与六门禁分数 (核心追溯: video_id -> 每幕 -> 候选 -> G1..G6)
--    改 WHERE v.video_id = '...' 即可单片追溯。
SELECT v.video_id,
       json_extract(s.value, '$.scene_slot')           AS scene_slot,
       json_extract(s.value, '$.narrative_slot')       AS narrative_slot,
       json_extract(s.value, '$.shot_id')              AS shot_id,
       json_extract(s.value, '$.candidate_id')         AS candidate_id,
       json_extract(s.value, '$.verdict')              AS candidate_verdict,
       json_extract(s.value, '$.overall_score')        AS candidate_overall,
       c.path                                          AS candidate_file,
       json_extract(s.value, '$.gates.G1.passed')      AS G1_pass,
       json_extract(s.value, '$.gates.G1.score')       AS G1_score,
       json_extract(s.value, '$.gates.G2.passed')      AS G2_pass,
       json_extract(s.value, '$.gates.G2.score')       AS G2_score,
       json_extract(s.value, '$.gates.G3.passed')      AS G3_pass,
       json_extract(s.value, '$.gates.G3.score')       AS G3_score,
       json_extract(s.value, '$.gates.G4.passed')      AS G4_pass,
       json_extract(s.value, '$.gates.G4.score')       AS G4_score,
       json_extract(s.value, '$.gates.G5.passed')      AS G5_pass,
       json_extract(s.value, '$.gates.G5.score')       AS G5_score,
       json_extract(s.value, '$.gates.G6.passed')      AS G6_pass,
       json_extract(s.value, '$.gates.G6.score')       AS G6_score
FROM m5_videos v,
     json_each(v.shots_json) s
LEFT JOIN candidates c ON c.id = json_extract(s.value, '$.candidate_id')
WHERE v.video_id = 't1_seeding_v1'   -- ← 改成片名即可; 全部成片可注释掉本行
ORDER BY v.video_id, s.key;

-- 3) 生成参数追溯: 每镜头任务的 seed/steps/显存/重试轮次 (candidates.seed 可由文件名恢复, D-031)
SELECT t.shot_id,
       t.lane,
       t.narrative_slot,
       t.status,
       t.attempts,
       t.seed,
       t.steps,
       round(t.duration_s, 3)   AS gen_duration_s,
       round(t.vram_peak_mb, 1) AS vram_peak_mb,
       (SELECT COUNT(*) FROM candidates c WHERE c.shot_id = t.shot_id) AS n_candidates
FROM tasks t
ORDER BY t.shot_id;

-- 4) 候选级全表: 选中/判定/overall(六门禁均分口径, D-018)
SELECT c.shot_id,
       c.id          AS candidate_id,
       c.verdict,
       c.selected,
       c.overall_score,
       c.path
FROM candidates c
ORDER BY c.shot_id, c.id;

-- 5) 良率口径: 一次通过(0 重试即 accepted) vs 含降级交付
SELECT
       (SELECT COUNT(*) FROM tasks WHERE status IN ('accepted','fallback','composed')) AS reached_delivery,
       (SELECT COUNT(*) FROM tasks WHERE attempts = 0 AND status IN ('accepted','composed')) AS first_pass_accepted,
       (SELECT COUNT(*) FROM tasks WHERE status IN ('accepted','composed') AND
            (SELECT verdict FROM candidates WHERE shot_id = tasks.shot_id AND selected = 1)
              NOT IN ('fallback')) AS accepted_delivery,
       (SELECT COUNT(*) FROM tasks WHERE status = 'fallback') AS fallback_delivery,
       (SELECT COUNT(*) FROM tasks WHERE status = 'blocked')  AS blocked,
       (SELECT COUNT(*) FROM candidates WHERE verdict != 'fallback') AS wan_or_kb_candidates;
