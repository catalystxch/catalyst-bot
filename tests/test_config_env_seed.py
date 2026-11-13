import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config


def test_transient_windows_env_replace_is_retried():
    attempts = []

    def write(*args):
        attempts.append(args)
        if len(attempts) < 3:
            raise PermissionError(13, "sharing violation")

    with patch.object(config.os, "name", "nt"), patch.object(config, "set_key", side_effect=write), patch.object(config.time, "sleep"):
        config._set_key_with_windows_retry("config.env", "MAX_POSITION_XCH", "73.7")

    assert len(attempts) == 3


class TestEnvExampleDiscovery(unittest.TestCase):
    def test_finds_template_from_source_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_dir = root / "src" / "catalyst"
            install_dir.mkdir(parents=True)
            expected = root / ".env.example"
            expected.write_text(
                "SAGE_RPC_URL=https://127.0.0.1:9257\n", encoding="utf-8"
            )

            self.assertEqual(
                config._find_env_example_path(str(install_dir)),
                str(expected),
            )

    def test_finds_template_from_pyinstaller_onedir_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp) / "Catalyst"
            install_dir = app_dir / "_internal"
            install_dir.mkdir(parents=True)
            expected = app_dir / ".env.example"
            expected.write_text(
                "SAGE_RPC_URL=https://127.0.0.1:9257\n", encoding="utf-8"
            )

            self.assertEqual(
                config._find_env_example_path(str(install_dir)),
                str(expected),
            )


if __name__ == "__main__":
    unittest.main()
