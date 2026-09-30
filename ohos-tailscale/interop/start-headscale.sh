#!/usr/bin/env bash
# headscale 联调服务器启动脚本（WSL 内执行；setsid 脱离会话存活）
set -u
cd "$HOME/interop"
rm -f headscale.log
if pgrep -f "headscale serve" > /dev/null; then
  echo "already running"
  exit 0
fi
setsid nohup ./headscale serve --config headscale.yaml > headscale.log 2>&1 < /dev/null &
sleep 5
echo "--- log tail ---"
tail -8 headscale.log
echo "--- health ---"
curl -fsS --max-time 5 http://127.0.0.1:8080/health
echo
echo "--- key ---"
curl -fsS --max-time 5 http://127.0.0.1:8080/key | head -c 100
echo
