#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 <executable> [log-file]" >&2
  exit 2
fi

exe="$1"
log="${2:-linux-desktop-smoke.log}"
proof_dir="${CATALYST_GUI_PROOF_DIR:-$(mktemp -d)}"
screenshot="${CATALYST_GUI_PROOF_SCREENSHOT:-$proof_dir/linux-desktop-smoke.xwd}"
runner="$(mktemp)"

mkdir -p "$(dirname "$log")" "$(dirname "$screenshot")"
rm -f "$log" "$screenshot"

cat >"$runner" <<'RUNNER'
#!/usr/bin/env bash
set -euo pipefail

exe="$1"
log="$2"
screenshot="$3"

if ! command -v xdotool >/dev/null 2>&1; then
  echo "Linux desktop smoke failed: xdotool is required to prove window visibility" >&2
  exit 1
fi

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export QT_OPENGL="${QT_OPENGL:-software}"
export QT_QUICK_BACKEND="${QT_QUICK_BACKEND:-software}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:---no-sandbox --disable-gpu --disable-dev-shm-usage}"
export FONTCONFIG_PATH="${FONTCONFIG_PATH:-/etc/fonts}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/catalyst-runtime-$(id -u)}"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR" || true

wm_pid=""
if command -v openbox >/dev/null 2>&1; then
  openbox >/tmp/catalyst-openbox-smoke.log 2>&1 &
  wm_pid=$!
  sleep 1
fi

"$exe" >"$log" 2>&1 &
app_pid=$!

cleanup() {
  if kill -0 "$app_pid" >/dev/null 2>&1; then
    kill "$app_pid" >/dev/null 2>&1 || true
    wait "$app_pid" >/dev/null 2>&1 || true
  fi
  if [[ -n "$wm_pid" ]] && kill -0 "$wm_pid" >/dev/null 2>&1; then
    kill "$wm_pid" >/dev/null 2>&1 || true
    wait "$wm_pid" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

window_id=""
geometry=""
for _ in $(seq 1 35); do
  if ! kill -0 "$app_pid" >/dev/null 2>&1; then
    app_code=0
    wait "$app_pid" || app_code=$?
    echo "Linux desktop smoke failed: executable exited before visible window proof (code $app_code)" >&2
    exit 1
  fi

  for candidate in $(xdotool search --name "CATalyst" 2>/dev/null || true); do
    candidate_geometry="$(xdotool getwindowgeometry --shell "$candidate" 2>/dev/null || true)"
    width="$(printf '%s\n' "$candidate_geometry" | awk -F= '$1 == "WIDTH" {print $2}')"
    height="$(printf '%s\n' "$candidate_geometry" | awk -F= '$1 == "HEIGHT" {print $2}')"
    if [[ "${width:-0}" -ge 800 && "${height:-0}" -ge 600 ]]; then
      window_id="$candidate"
      geometry="$(xdotool getwindowgeometry "$window_id" 2>/dev/null || true)"
      break
    fi
  done
  if [[ -n "$window_id" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$window_id" ]]; then
  echo "Linux desktop smoke failed: CATalyst window was not visible at desktop size within 35s" >&2
  exit 1
fi

echo "$geometry"

if ! command -v xwd >/dev/null 2>&1; then
  echo "Linux desktop smoke failed: xwd is required to capture the visible desktop" >&2
  exit 1
fi

mkdir -p "$(dirname "$screenshot")"
xwd -silent -root -out "$screenshot"

python3 - "$screenshot" <<'PY'
import struct
import sys
from pathlib import Path

path = Path(sys.argv[1])
raw = path.read_bytes()
if len(raw) < 256:
    raise SystemExit("Linux desktop smoke failed: screenshot file is too small")

header = None
for endian in (">", "<"):
    try:
        values = struct.unpack(endian + "25I", raw[:100])
    except Exception:
        continue
    header_size = values[0]
    version = values[1]
    width = values[4]
    height = values[5]
    ncolors = values[19]
    data_offset = header_size + (ncolors * 12)
    if version == 7 and 100 <= header_size < len(raw) and data_offset < len(raw):
        header = (width, height, data_offset)
        break

if header is None:
    raise SystemExit("Linux desktop smoke failed: could not parse XWD screenshot")

width, height, data_offset = header
if width < 800 or height < 600:
    raise SystemExit(
        f"Linux desktop smoke failed: screenshot too small for desktop GUI: {width}x{height}"
    )

pixels = raw[data_offset:]
step = max(1, len(pixels) // 200000)
sample = pixels[::step]
unique_values = len(set(sample))
nonzero = sum(1 for value in sample if value != 0)
if unique_values < 4 or nonzero < max(128, len(sample) // 100):
    raise SystemExit("Linux desktop smoke failed: screenshot is blank or nearly blank")

print(f"Linux desktop smoke screenshot nonblank: {path} ({width}x{height})")
PY

echo "Linux desktop smoke passed: visible CATalyst window captured"
RUNNER
chmod +x "$runner"

set +e
timeout 55s xvfb-run -a -s "-screen 0 1920x1080x24" bash "$runner" "$exe" "$log" "$screenshot"
code=$?
set -e

rm -f "$runner"

cat "$log"

if grep -E \
  "No module named 'gi'|No module named 'qtpy'|No module named 'PyQt6'|You must have either QT or GTK|UnicodeEncodeError|CRASH:" \
  "$log"; then
  echo "Linux desktop smoke failed: GUI backend/tray crash detected" >&2
  exit 1
fi

if [[ "$code" -eq 0 ]]; then
  exit 0
fi

if [[ "$code" -eq 124 ]]; then
  echo "Linux desktop smoke failed: GUI proof timed out" >&2
  exit 1
fi

echo "Linux desktop smoke failed: executable exited with code $code" >&2
exit "$code"
