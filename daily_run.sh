#!/bin/zsh
# Daily local run: both trackers + commit/push. Invoked by launchd
# (com.alexlauks.flight-tracker) each morning; the claude.ai routine then
# reads the pushed outputs and decides the email.
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$(dirname "$0")"

LOG=daily_run.log
exec > >(tee -a "$LOG") 2>&1
echo "=== daily_run $(date '+%F %T') ==="
echo "(cada tracker tarda 5-15 min; el progreso va apareciendo por búsqueda)"

git pull --rebase origin main || echo "WARN: git pull failed, running on local state"

.venv/bin/python run_tracker.py
jp=$?
echo "japan exit=$jp"

.venv/bin/python run_tracker.py --config config_balkans.json
bk=$?
echo "balkans exit=$bk"

if [ "$jp" -eq 0 ] || [ "$bk" -eq 0 ]; then
  git add prices*.json report*.md alert*.json
  git commit -m "prices: $(date +%F)" && git push origin main
else
  echo "both trackers returned no data; nothing committed"
fi
echo "=== done $(date '+%F %T') ==="
