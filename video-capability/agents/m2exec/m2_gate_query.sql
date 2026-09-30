-- M2 门禁明细溯源 SQL (reports/milestones/m2_gate_query.sql)
-- 用法: sqlite3 workdir/cradle.sqlite3 < reports/milestones/m2_gate_query.sql
-- 配套聚合脚本: m2_gate_query.py

-- 1) 任务状态总览
SELECT status, COUNT(*) AS n FROM tasks GROUP BY status ORDER BY n DESC;

-- 2) 每镜头: 状态/尝试数/候选数/通过数/选中候选
SELECT t.shot_id, t.status, t.lane, t.attempts,
       COUNT(c.id) AS n_cands,
       SUM(c.verdict = 'pass') AS n_pass,
       SUM(c.verdict = 'fail') AS n_fail,
       SUM(c.selected) AS n_selected
FROM tasks t LEFT JOIN candidates c ON c.shot_id = t.shot_id
GROUP BY t.shot_id ORDER BY t.shot_id;

-- 3) 每候选六门禁结果(平铺; 1=passed)
SELECT c.shot_id, c.id AS cand_id, c.verdict, c.overall_score,
       json_extract(c.gate_json, '$.G1.passed') AS G1,
       json_extract(c.gate_json, '$.G2.passed') AS G2,
       json_extract(c.gate_json, '$.G3.passed') AS G3,
       json_extract(c.gate_json, '$.G4.passed') AS G4,
       json_extract(c.gate_json, '$.G5.passed') AS G5,
       json_extract(c.gate_json, '$.G6.passed') AS G6,
       json_extract(c.gate_json, '$.G3.detail.min_similarity') AS g3_min_sim,
       json_extract(c.gate_json, '$.G4.detail.min_adjacent_similarity') AS g4_min_adj,
       json_extract(c.gate_json, '$.G5.detail.overall_score') AS g5_overall,
       json_extract(c.gate_json, '$.G5.detail.main_issue') AS main_issue
FROM candidates c WHERE c.verdict IN ('pass','fail')
ORDER BY c.shot_id, c.id;

-- 4) 各门禁通过率
SELECT 'G1' AS gate, SUM(json_extract(gate_json,'$.G1.passed'))*1.0/COUNT(*) AS pass_rate, COUNT(*) AS evaluated
FROM candidates WHERE verdict IN ('pass','fail') AND json_extract(gate_json,'$.G1.passed') IS NOT NULL
UNION ALL
SELECT 'G2', SUM(json_extract(gate_json,'$.G2.passed'))*1.0/COUNT(*), COUNT(*)
FROM candidates WHERE verdict IN ('pass','fail') AND json_extract(gate_json,'$.G2.passed') IS NOT NULL
UNION ALL
SELECT 'G3', SUM(json_extract(gate_json,'$.G3.passed'))*1.0/COUNT(*), COUNT(*)
FROM candidates WHERE verdict IN ('pass','fail') AND json_extract(gate_json,'$.G3.passed') IS NOT NULL
UNION ALL
SELECT 'G4', SUM(json_extract(gate_json,'$.G4.passed'))*1.0/COUNT(*), COUNT(*)
FROM candidates WHERE verdict IN ('pass','fail') AND json_extract(gate_json,'$.G4.passed') IS NOT NULL
UNION ALL
SELECT 'G5', SUM(json_extract(gate_json,'$.G5.passed'))*1.0/COUNT(*), COUNT(*)
FROM candidates WHERE verdict IN ('pass','fail') AND json_extract(gate_json,'$.G5.passed') IS NOT NULL
UNION ALL
SELECT 'G6', SUM(json_extract(gate_json,'$.G6.passed'))*1.0/COUNT(*), COUNT(*)
FROM candidates WHERE verdict IN ('pass','fail') AND json_extract(gate_json,'$.G6.passed') IS NOT NULL;

-- 5) 失败候选明细(失败画廊选材入口; mp4 保留在 workdir/candidates/)
SELECT shot_id, id AS cand_id, path, overall_score,
       json_extract(gate_json, '$.G5.detail.main_issue') AS main_issue
FROM candidates WHERE verdict = 'fail' ORDER BY shot_id, id;

-- 6) 生成记账(seed/steps/耗时/显存, SPECS §5.3)
SELECT shot_id, seed, steps, duration_s, vram_peak_mb, error FROM tasks ORDER BY shot_id;

-- 7) 事件日志(路由/降级/恢复痕迹)
SELECT ts, level, msg FROM events ORDER BY id DESC LIMIT 100;
