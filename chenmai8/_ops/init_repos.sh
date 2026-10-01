#!/usr/bin/env bash
# Init local repo skeletons under each project's repo/ dir and push to GitHub.
set -e
BASE="D:/workspace/澄迈8项目"
TOKEN=$(sed -n 's|^https://feasy898:\([^@]*\)@github.com.*|\1|p' /c/Users/Administrator/.git-credentials | head -1)
[ -n "$TOKEN" ] || { echo "no token"; exit 1; }

init_one() { # $1=projdir $2=repo $3=readme-file
  local dir="$BASE/$1/repo"
  mkdir -p "$dir/docs"
  cp "$BASE/_ops/readmes/$3" "$dir/README.md"
  cp "$BASE/_ops/readmes/gitignore.txt" "$dir/.gitignore"
  cd "$dir"
  git init -b main -q
  git add -A
  git -c user.name="feasy898" -c user.email="feasy898@users.noreply.github.com" commit -q -m "init: project skeleton" || true
  git remote remove origin 2>/dev/null || true
  git remote add origin "https://github.com/feasy898/$2.git"
  git push -q "https://feasy898:$TOKEN@github.com/feasy898/$2.git" main
  echo "PUSHED $2"
}

init_one "具身助餐机器人" chengmai-feeding-arm feeding-arm.md
init_one "可玩的小游戏广告" chengmai-playable-ads playable-ads.md
init_one "咖啡豆质检" chengmai-bean-eye bean-eye.md
init_one "政务AI脱敏网关" chengmai-gov-ai-gateway gov-gateway.md
init_one "短剧多国出海" chengmai-drama-dub drama-dub.md
