import json, glob, os
files = sorted(glob.glob("tmp/diff/crossqc/OB/*.report.json"))
print("OB reports:", len(files))
for p in files[:4]:
    try:
        d = json.load(open(p, encoding="utf-8"))
        f = d["facts"]["muteLoadTime"]
        print(os.path.basename(p), "checks=", len(d["checks"]), "audioPre=", f.get("audioRunningBeforeInteraction"))
    except Exception as e:
        print(os.path.basename(p), "ERR", e)
