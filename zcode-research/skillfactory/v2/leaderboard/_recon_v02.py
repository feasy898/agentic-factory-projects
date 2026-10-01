import json, os

base = r'D:\workspace\zcode研究\skillfactory\v2\evalbench-v02'
req = ['slug', 'name', 'assetType', 'tasks', 'baselineMean', 'treatmentMean',
       'delta', 'winRate', 'reverseTasks', 'accepted', 'driftNote', 'taskAggs']

for slug in ['lark-cli', 'meeting-minutes', 'hooks-mastery']:
    p = os.path.join(base, slug, 'ab_summary.json')
    raw = open(p, 'rb').read()
    bom = raw[:3] == b'\xef\xbb\xbf'
    d = json.loads(raw.decode('utf-8'))  # 解析失败会抛异常 => 合法 JSON、无注释
    missing = [k for k in req if k not in d]
    ta = d['taskAggs']
    n = len(ta)
    bm = sum(t['baseMean'] for t in ta) / n
    tm = sum(t['treatMean'] for t in ta) / n
    ids_ok = [t['id'] for t in ta] == ['t%d' % (i + 1) for i in range(d['tasks'])]
    reps_ok = all(len(t['repNotes']) == 2 for t in ta)
    nbase = sum(1 for t in ta if t['majority'] == 'baseline')
    ntie = sum(1 for t in ta if t['majority'] == 'tie')
    ntreat = sum(1 for t in ta if t['majority'] == 'treatment')
    rev36 = sum(1 for t in ta if t['treatMean'] < t['baseMean'] or t['treatMean'] == 0)
    hi = sum(1 for t in ta if t['treatMean'] > t['baseMean'])
    eq = sum(1 for t in ta if t['treatMean'] == t['baseMean'])
    print(slug)
    print('  BOM=%s missing=%s tasks_field=%s n_aggs=%d ids_seq=%s reps2=%s'
          % (bom, missing, d['tasks'], n, ids_ok, reps_ok))
    print('  recomputed base=%.6f treat=%.6f delta=%.6f' % (bm, tm, tm - bm))
    print('  delivered  base=%s treat=%s delta=%s winRate=%s reverseTasks=%s accepted=%s'
          % (d['baselineMean'], d['treatmentMean'], d['delta'], d['winRate'],
             d['reverseTasks'], d['accepted']))
    print('  majority: baseline=%d tie=%d treatment=%d | vs means: treat>base=%d equal=%d lower=%d | rev_per_spec36=%d'
          % (nbase, ntie, ntreat, hi, eq, n - hi - eq, rev36))
    print('  check: base~rec=%s treat~rec=%s delta~rec=%s reverseTasks==cnt(majority=baseline)=%s'
          % (abs(bm - d['baselineMean']) < 1e-9, abs(tm - d['treatmentMean']) < 1e-9,
             abs((tm - bm) - d['delta']) < 1e-9, nbase == d['reverseTasks']))
