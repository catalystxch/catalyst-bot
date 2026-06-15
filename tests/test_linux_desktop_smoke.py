import os
import subprocess
from pathlib import Path

import pytest


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _bash_path(path: Path) -> str:
    value = path.resolve().as_posix()
    if os.name == "nt" and len(value) > 1 and value[1] == ":":
        return f"/mnt/{value[0].lower()}{value[2:]}"
    return value


def test_linux_desktop_smoke_waits_for_window_to_paint(tmp_path):
    if os.name == "nt":
        pytest.skip("Linux desktop smoke helpers require POSIX-executable temp files")

    repo = Path(__file__).resolve().parents[1]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    count_file = tmp_path / "xwd-count"
    proof_dir = tmp_path / "proof"
    log_file = tmp_path / "smoke.log"

    _write_executable(
        fake_bin / "xvfb-run",
        """#!/usr/bin/env bash
set -euo pipefail
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s)
      shift 2
      ;;
    -*)
      shift
      ;;
    *)
      exec "$@"
      ;;
  esac
done
""",
    )
    _write_executable(
        fake_bin / "xdotool",
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  search)
    echo 12345
    ;;
  getwindowgeometry)
    if [[ "${2:-}" == "--shell" ]]; then
      printf 'X=160\\nY=24\\nWIDTH=1600\\nHEIGHT=1000\\nSCREEN=0\\n'
    else
      printf 'Window 12345\\n  Position: 160,24 (screen: 0)\\n  Geometry: 1600x1000\\n'
    fi
    ;;
  windowactivate)
    ;;
esac
""",
    )
    _write_executable(
        fake_bin / "xwd",
        """#!/usr/bin/env bash
set -euo pipefail
out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -out)
      out="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
count=0
if [[ -f "$CATALYST_FAKE_XWD_COUNT" ]]; then
  count="$(cat "$CATALYST_FAKE_XWD_COUNT")"
fi
count=$((count + 1))
printf '%s' "$count" > "$CATALYST_FAKE_XWD_COUNT"
python3 - "$out" "$count" <<'PY'
import struct
import sys
from pathlib import Path

path = Path(sys.argv[1])
count = int(sys.argv[2])
values = [0] * 25
values[0] = 100
values[1] = 7
values[4] = 1920
values[5] = 1080
values[19] = 0
pixels = b"\\0" * 4096
if count > 1:
    pixels = bytes(range(256)) * 16
path.write_bytes(struct.pack(">25I", *values) + pixels)
PY
""",
    )
    _write_executable(
        fake_bin / "openbox",
        """#!/usr/bin/env bash
sleep 60
""",
    )
    fake_exe = tmp_path / "Catalyst"
    _write_executable(
        fake_exe,
        """#!/usr/bin/env bash
echo "CATalyst fake desktop"
while true; do sleep 1; done
""",
    )

    env = os.environ.copy()
    env["PATH"] = f"{_bash_path(fake_bin)}:/usr/bin:/bin:{env.get('PATH', '')}"
    env["CATALYST_FAKE_XWD_COUNT"] = _bash_path(count_file)
    env["CATALYST_GUI_PROOF_DIR"] = _bash_path(proof_dir)

    result = subprocess.run(
        [
            "bash",
            "scripts/linux_desktop_smoke.sh",
            _bash_path(fake_exe),
            _bash_path(log_file),
        ],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert int(count_file.read_text(encoding="utf-8")) >= 2
    assert "Linux desktop smoke passed" in output
