"""An unavailable data directory must never select the install profile."""

import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_unavailable_data_dir_does_not_use_install_profile(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    requested = blocked / "Catalyst"
    monkeypatch.setenv("CMM_DATA_DIR", str(requested))

    install = tmp_path / "install"
    install.mkdir()
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "src" / "catalyst" / "user_paths.py",
        install / "user_paths.py",
    )
    (install / ".env").write_text("WALLET_TYPE=sage\n", encoding="utf-8")
    (install / "bot.db").write_bytes(b"legacy profile")

    paths = runpy.run_path(str(install / "user_paths.py"))
    for resolve in ("data_dir", "env_file", "database_file"):
        with pytest.raises(OSError, match="data directory"):
            paths[resolve]()

    assert not (install / ".migration_complete").exists()
    assert not requested.exists()


@pytest.mark.parametrize("module", ["config", "database"])
def test_unavailable_data_dir_blocks_profile_module_import(tmp_path, module):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    source = Path(__file__).resolve().parents[1] / "src" / "catalyst"
    env = os.environ.copy()
    env["CMM_DATA_DIR"] = str(blocked / "Catalyst")
    env["PYTHONPATH"] = os.pathsep.join((str(source), env.get("PYTHONPATH", "")))

    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "data directory is unavailable" in result.stderr
