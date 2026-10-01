import json, collections
from datetime import datetime, timezone, timedelta

CN = timezone(timedelta(hours=8))
OPEN = {"待处理", "处理中"}

def in_sep_2026(v):
    if v is None:
        return False
    if isinstance(v, (int, float)):            # 毫秒时间戳
        dt = datetime.fromtimestamp(v / 1000, tz=CN)
    else:                                       # RFC3339 或纯日期字符串
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CN)
    return (dt.year, dt.month) == (2026, 9)

cnt = collections.Counter(); total = 0; dropped = 0
with open("./sep-open-reqs.ndjson", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        total += 1
        st = r.get("状态")
        if isinstance(st, list):                # 单选 CellValue 为数组
            st = st[0] if st else None
        if st not in OPEN or not in_sep_2026(r.get("提交时间")):
            dropped += 1                        # 与服务端筛选口径不符，复核剔除
            continue
        owner = r.get("负责人")
        cnt[owner if isinstance(owner, str) and owner.strip() else "(负责人为空)"] += 1

print(f"文件总行数={total}  口径复核剔除={dropped}  未完结合计={sum(cnt.values())}")
print("Top3:")
for name, c in cnt.most_common(3):
    print(f"  {name}\t{c}")
print("全部负责人明细:")
for name, c in cnt.most_common():
    print(f"  {name}\t{c}")
