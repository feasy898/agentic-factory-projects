import os, subprocess, sys
HERE = r"D:\new-workspace\agent-asset\afp-clone\zcode-research\skillfactory\v5\assets\speaker-mapping"
os.chdir(HERE)
old_name = "out/student_run1/partial__m_partial.json"
new_name = "out/student_run1/partial__m_partial.txt"
if os.path.exists(old_name):
    os.rename(old_name, new_name)
# re-run map to overwrite with right content + stderr sidecar
r = subprocess.run(
    [sys.executable, "oracle/map_speakers.py", "--transcript", "oracle/fixtures/partial.txt",
     "--mapping", "oracle/fixtures/m_partial.json", "--out", new_name],
    capture_output=True, text=True
)
print("rc=", r.returncode)
print("stdout:", r.stdout[-300:])
print("stderr:", r.stderr[-300:])
files = sorted(os.listdir("out/student_run1"))
print("file count:", len(files))
print("files:", files)