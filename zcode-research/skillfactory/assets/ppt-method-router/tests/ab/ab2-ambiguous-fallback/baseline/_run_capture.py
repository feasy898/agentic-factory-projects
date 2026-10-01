# -*- coding: utf-8 -*-
"""ab2-ambiguous-fallback baseline runner.

Runs the ask's exact command:
    python package/scripts/route.py --input oracle/inputs/case11.txt
(cwd = skillfactory/assets/ppt-method-router)

Records stdout/stderr/returncode, runs 3 times to check fallback stability,
then extracts ONLY the "case11" entry from oracle/out/labels.json for the
comparison the ask names. Reads nothing else from oracle/, nothing from
package/, and not spec.md (fairness restriction).

Does NOT read the case11 input file itself (it lives in oracle/inputs/);
its content is taken from the ask's task material.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\workspace\zcode研究\skillfactory\assets\ppt-method-router")
OUT = ROOT / "tests" / "ab" / "ab2-ambiguous-fallback" / "baseline"
OUT.mkdir(parents=True, exist_ok=True)


def decode_auto(b: bytes):
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace"), "utf-8(replace)"


def run_once(tag: str):
    p = subprocess.run(
        [sys.executable, "package/scripts/route.py", "--input", "oracle/inputs/case11.txt"],
        cwd=str(ROOT),
        capture_output=True,
    )
    stdout_text, stdout_enc = decode_auto(p.stdout)
    stderr_text, stderr_enc = decode_auto(p.stderr)
    rec = {
        "tag": tag,
        "returncode": p.returncode,
        "stdout_encoding_detected": stdout_enc,
        "stdout_repr": repr(stdout_text),
        "stderr_repr": repr(stderr_text),
        "stripped": stdout_text.strip(),
        "single_line_nonempty": ("\n" not in stdout_text.strip()) and len(stdout_text.strip()) > 0,
    }
    parsed = None
    parse_error = None
    try:
        parsed = json.loads(stdout_text)
    except Exception as e:
        parse_error = f"{type(e).__name__}: {e}"
    rec["stdout_json_parses"] = parsed is not None
    rec["stdout_json_error"] = parse_error
    return rec, parsed, p


runs = []
parsed_outputs = []
primary_proc = None
for i, tag in enumerate(["primary", "repeat1", "repeat2"]):
    rec, parsed, proc = run_once(tag)
    runs.append(rec)
    if parsed is not None:
        parsed_outputs.append(parsed)
    if tag == "primary":
        primary_proc = proc

stability_identical = (
    len({r["stripped"] for r in runs}) == 1
    and len({r["returncode"] for r in runs}) == 1
)

# --- targeted extraction: ONLY the case11 entry of labels.json (named check in the ask) ---
labels_case11 = None
labels_note = None
try:
    raw = (ROOT / "oracle" / "out" / "labels.json").read_bytes()
    text, _ = decode_auto(raw)
    data = json.loads(text)
    if isinstance(data, dict):
        labels_case11 = data.get("case11")
        if labels_case11 is None:
            keys = [k for k in data.keys() if "case11" in str(k)]
            labels_note = f"no exact key 'case11'; keys containing 'case11': {keys}"
    else:
        labels_note = f"top-level JSON type is {type(data).__name__}, not dict"
except Exception as e:
    labels_note = f"extraction failed: {type(e).__name__}: {e}"

record = {
    "ask_command": "python package/scripts/route.py --input oracle/inputs/case11.txt",
    "cwd": str(ROOT),
    "python": sys.version,
    "runs": runs,
    "stability_all_identical_stdout_and_rc": stability_identical,
    "labels_case11_entry_only": labels_case11,
    "labels_note": labels_note,
}
(OUT / "capture_record.json").write_text(
    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
)
(OUT / "route-stdout-primary.txt").write_bytes(primary_proc.stdout)
(OUT / "route-stderr-primary.txt").write_bytes(primary_proc.stderr)
if parsed_outputs:
    (OUT / "route-output-parsed.json").write_text(
        json.dumps(parsed_outputs[0], ensure_ascii=False, indent=2), encoding="utf-8"
    )

print(json.dumps({
    "record_path": str(OUT / "capture_record.json"),
    "primary_returncode": runs[0]["returncode"],
    "primary_json_parses": runs[0]["stdout_json_parses"],
    "primary_single_line": runs[0]["single_line_nonempty"],
    "stability_all_identical": stability_identical,
}, ensure_ascii=False))
