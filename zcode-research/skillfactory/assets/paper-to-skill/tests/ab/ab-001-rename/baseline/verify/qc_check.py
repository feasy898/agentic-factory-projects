#!/usr/bin/env python3
"""QC checks for baseline/SKILL.md (ab-001): front-matter spec, script identity, structure."""
import io
import re

skill = io.open("SKILL.md", encoding="utf-8").read()
ref = io.open("verify/rename_files.py", encoding="utf-8").read()
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# --- front-matter (QC-1 / QC-2) ---
m = re.match(r"^---\n(.*?)\n---\n", skill, re.S)
check("front-matter block exists", bool(m))
fm = m.group(1)
nm = re.search(r"^name:\s*(.+)$", fm, re.M)
name = nm.group(1).strip()
dm = re.search(r"^description:\s*(.+)$", fm, re.M)
desc = dm.group(1).strip()
print(f"  name = {name!r} (len={len(name)})")
check("name regex ^[a-z0-9]+(-[a-z0-9]+)*$", re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) is not None)
check("name <= 64 chars", len(name) <= 64)
check("no leading/trailing/double hyphen", not name.startswith("-") and not name.endswith("-") and "--" not in name)
check("description <= 1024 chars", len(desc) <= 1024, f"(len={len(desc)})")
check("description mentions trigger scenario", ("批量重命名" in desc and "整理目录内文件名" in desc))
try:
    import yaml
    parsed = yaml.safe_load(fm)
    check("front-matter parses as YAML", isinstance(parsed, dict)
          and parsed.get("name") == name and parsed.get("description") == desc)
except ImportError:
    print("[SKIP] pyyaml not installed; YAML parse not run")

# --- embedded script identity (QC-3) ---
blocks = re.findall(r"```python\n(.*?)```", skill, re.S)
check("exactly one python code block", len(blocks) == 1)
if blocks:
    emb = blocks[0]
    check("embedded script == verify/rename_files.py", emb.rstrip("\n") == ref.rstrip("\n"),
          f"(embedded {len(emb)} chars vs file {len(ref)} chars)")

# --- steps / pitfalls / sections (QC-4) ---
steps = re.findall(r"^### 步骤 (\d+)：(.+)$", skill, re.M)
check(">=3 numbered steps", len(steps) >= 3, f"({len(steps)} steps)")
body = "\n".join(s[1] for s in steps)
for kw in ("pattern", "模板", "dry-run", "apply"):
    check(f"steps cover '{kw}'", kw in body)
pits = re.findall(r"^\d+\. \*\*", skill[skill.index("## 常见坑"):skill.index("## 安全红线")], re.M)
check(">=2 pitfalls", len(pits) >= 2, f"({len(pits)} pitfalls)")
check("安全红线 section", "## 安全红线" in skill)
check("red line: dry-run 先行", "先 dry-run 后 apply" in skill)
check("red line: 重名跳过绝不覆盖", "重名跳过，绝不覆盖" in skill)
src = skill[skill.index("## 来源与依据"):]
check("来源 section with 5-element label", "名称、类型/出处、日期、位置、引用内容与验证方式" in src)
check("来源 cites brief", "batch-rename-brief.md" in src)
check("来源 cites mv/os.rename behavior", ("mv" in src and "os.rename" in src))
for bad in ("os.replace(src, dst)", "--recursive", "--undo", "--rollback", "--start"):
    check(f"no fabricated feature: {bad!r} absent", bad not in skill)
# 'mv -f' must only appear as a prohibition (禁止 mv -f), never as an endorsed usage
mvf_lines = [ln for ln in skill.splitlines() if "mv -f" in ln]
check("'mv -f' only in prohibition list", len(mvf_lines) == 1 and "禁止" in mvf_lines[0],
      f"({mvf_lines[0].strip()[:40]}...)")

# --- content.md carries full text ---
cm = io.open("content.md", encoding="utf-8").read()
cemb = re.findall(r"```python\n(.*?)```", cm, re.S)
check("content.md embeds identical script", any(b.rstrip("\n") == ref.rstrip("\n") for b in cemb))
sentinels = ["### 步骤 3：dry-run 预览（每次 apply 前必须执行）", "## 安全红线", "## 来源与依据", "触发词：batch rename"]
check("content.md contains SKILL.md sentinel lines", all(s in cm for s in sentinels))
print("\nRESULT:", "ALL PASS" if ok else "SOME FAIL")
