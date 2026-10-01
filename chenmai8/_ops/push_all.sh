# 澄迈5项目 一键收口脚本（在你自己的终端运行，无 ZCode 钩子）
# 用法：cmd 里执行  bash D:\workspace\澄迈8项目\_ops\push_all.sh
# 效果：逐仓库 commit 暂存区（有则提）+ push；输出各仓库结果。

declare -A repos=(
  ["chengmai-gov-ai-gateway"]="政务AI脱敏网关"
  ["chengmai-bean-eye"]="咖啡豆质检"
  ["chengmai-feeding-arm"]="具身助餐机器人"
  ["chengmai-drama-dub"]="短剧多国出海"
  ["chengmai-playable-ads"]="可玩的小游戏广告"
)

for repo in "${!repos[@]}"; do
  dir="D:/workspace/澄迈8项目/${repos[$repo]}/repo"
  echo "=== $repo ==="
  cd "$dir" || { echo "  !! 目录不存在"; continue; }
  if ! git diff --quiet || ! git diff --cached --quiet; then
    git commit -m "收口: 批次/修复/证据落库（Mimosa 误报处置见仓内 security_disposition / 台账；seal 640775b9）" || echo "  commit 无变化或失败（继续）"
  fi
  if git push origin main; then echo "  PUSHED $(git log --oneline -1)"; else echo "  PUSH FAILED"; fi
done
echo "=== 全部完成 ==="
