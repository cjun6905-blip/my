#!/bin/sh
set -eu

for dir in \
  /app/src/lobby \
  /app/src/guidance \
  /app/src/diary \
  /app/src/chat/features/games/blackjack-web
do
  echo "Building ${dir}"
  cd "${dir}"
  npm install --package-lock=false --no-audit --no-fund
  npm run build
done
