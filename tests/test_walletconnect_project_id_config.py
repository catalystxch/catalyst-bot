from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import config as config_module


def test_walletconnect_project_id_is_optional_public_configuration(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "WALLETCONNECT_PROJECT_ID=public-reown-project-id\n",
        encoding="utf-8",
    )

    with (
        patch.object(config_module, "_ENV_PATH", str(env_path)),
        patch.dict(os.environ, {}, clear=False),
    ):
        config = config_module.Config()

    assert config.WALLETCONNECT_PROJECT_ID == "public-reown-project-id"


def test_example_config_documents_missing_id_as_signing_only_limitation():
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(
        encoding="utf-8"
    )

    assert "WALLETCONNECT_PROJECT_ID=" in example
    assert "Bootstrap remains usable" in example
