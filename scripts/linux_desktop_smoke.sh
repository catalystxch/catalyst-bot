#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 <executable> [log-file]" >&2
  exit 2
fi

exe="$1"
log="${2:-linux-desktop-smoke.log}"

rm -f "$log"

set +e
timeout 35s xvfb-run -a "$exe" >"$log" 2>&1
code=$?
set -e

cat "$log"

if grep -E \
  "No module named 'gi'|No module named 'qtpy'|No module named 'PyQt6'|You must have either QT or GTK|UnicodeEncodeError|CRASH:" \
  "$log"; then
  echo "Linux desktop smoke failed: GUI backend/tray crash detected" >&2
  exit 1
fi

if [[ "$code" -eq 124 ]]; then
  echo "Linux desktop smoke passed: app stayed alive until timeout"
  exit 0
fi

if [[ "$code" -eq 0 ]]; then
  echo "Linux desktop smoke passed: app exited cleanly"
  exit 0
fi

echo "Linux desktop smoke failed: executable exited with code $code" >&2
exit "$code"
