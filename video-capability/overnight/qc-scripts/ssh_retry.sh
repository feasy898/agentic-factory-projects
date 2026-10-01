#!/usr/bin/env bash
# ssh_retry.sh — 网络瞬断重试包装: ssh_retry.sh "<remote command>"
# 用法在 Git Bash: bash ssh_retry.sh "tail -5 /data/night/logs/xxx.log"
KEY=C:/Users/Administrator/.ssh/wsl_key
HOST=anuser@203.0.113.41
for i in 1 2 3 4 5 6; do
  OUT=$(ssh -o ControlPath=none -o ConnectTimeout=20 -i "$KEY" "$HOST" "$@" 2>&1)
  RC=$?
  if [ $RC -eq 0 ]; then
    echo "$OUT"
    exit 0
  fi
  echo "[retry $i] ssh rc=$RC: $(echo "$OUT" | tail -1)" >&2
  sleep $((i * 20))
done
echo "SSH_FAILED after 6 attempts" >&2
exit 99
