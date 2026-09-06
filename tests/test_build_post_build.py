import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_build_module():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("catalyst_build", root / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestBuildPostBuild(unittest.TestCase):
    def test_syncs_windows_metadata_from_runtime_version_before_build(self):
        build = _load_build_module()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version_dir = root / "src" / "catalyst"
            version_dir.mkdir(parents=True)
            (version_dir / "_version.py").write_text(
                '__version__ = "9.8.7"\n', encoding="utf-8"
            )
            (root / "version_info.txt").write_text(
                "filevers=(1, 0, 0, 0)\n", encoding="utf-8"
            )

            with patch.object(build, "HERE", str(root)):
                self.assertEqual(build._sync_build_metadata(), "9.8.7")

            metadata = (root / "version_info.txt").read_text(encoding="utf-8")
            self.assertIn("filevers=(9, 8, 7, 0)", metadata)
            self.assertIn("ProductVersion',   u'9.8.7'", metadata)

    def test_accepts_pyinstaller_internal_data_dir(self):
        build = _load_build_module()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "dist" / "Catalyst"
            internal = output / "_internal"
            internal.mkdir(parents=True)
            (output / ("Catalyst.exe" if os.name == "nt" else "Catalyst")).write_text(
                ""
            )
            (internal / "bot_gui.html").write_text("<html></html>", encoding="utf-8")
            env_example = root / ".env.example"
            env_example.write_text(
                "SAGE_RPC_URL=https://127.0.0.1:9257\n", encoding="utf-8"
            )

            buf = io.StringIO()
            with (
                patch.object(build, "OUTPUT_DIR", str(output)),
                patch.object(build, "ENV_EXAMPLE", str(env_example)),
                contextlib.redirect_stdout(buf),
            ):
                build._post_build()

            out = buf.getvalue()
            self.assertIn("HTML assets verified in bundle.", out)
            self.assertNotIn("bot_gui.html not found", out)
            self.assertEqual(
                (output / ".env.example").read_text(encoding="utf-8"),
                "SAGE_RPC_URL=https://127.0.0.1:9257\n",
            )


if __name__ == "__main__":
    unittest.main()
