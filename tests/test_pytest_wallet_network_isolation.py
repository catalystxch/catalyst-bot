"""The ordinary unit suite must never default to the operator's Sage wallet."""

import os
from pathlib import Path


def test_pytest_session_uses_isolated_sage_defaults():
    data_dir = Path(os.environ["CMM_DATA_DIR"]).resolve()
    sage_home = Path(os.environ["SAGE_HOME"]).resolve()

    assert os.environ["SAGE_RPC_URL"] == "https://127.0.0.1:1"
    assert sage_home.is_relative_to(data_dir)
    assert Path(os.environ["SAGE_ALLOWED_CERT_ROOTS"]).resolve() == sage_home
    assert Path(os.environ["SAGE_CERT_PATH"]).resolve().is_relative_to(sage_home)
    assert Path(os.environ["SAGE_KEY_PATH"]).resolve().is_relative_to(sage_home)
    assert os.environ.get("_CATALYST_PRESERVE_PROCESS_ENV") != "1"
