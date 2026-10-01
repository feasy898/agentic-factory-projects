#!/usr/bin/env bash
# Functional test of the corrected hook command's shell logic.
# jq is not installed on this machine; the `.tool_input.command` extraction step
# is replaced by an equivalent python one-liner. Everything after the pipe is
# byte-for-byte the corrected command's logic.

extract() {
  python -c "import sys,json;print(json.load(sys.stdin)['tool_input']['command'])"
}

run_case() {
  local label="$1" payload="$2"
  echo "=== $label ==="
  # The corrected command under test (extraction swapped in):
  printf '%s' "$payload" | { extract | grep -q 'rm -rf' && echo '危险命令，禁止' >&2 && exit 2 || true; }
  echo "exit_code=$?"
  echo
}

run_case "dangerous: rm -rf /" '{"tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/x"}}'
run_case "safe: ls -la" '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}'
run_case "dangerous: nested in compound cmd" '{"tool_name":"Bash","tool_input":{"command":"cd /var && rm -rf cache"}}'

echo "=== ORIGINAL command: where does the message go? ==="
printf '%s' '{"tool_input":{"command":"rm -rf /tmp/x"}}' | { extract | grep -q 'rm -rf' && echo '危险命令，禁止' && exit 2 || true; } 2>/dev/null
echo "original_exit_code=$?  (message above appeared on stdout, stderr was discarded)"
