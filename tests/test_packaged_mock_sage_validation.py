"""Package probes must use Sage-valid synthetic identity, not host credentials."""
import importlib.util
from pathlib import Path
from urllib.parse import urlsplit

import pytest

import sage_node
from sage_node import validate_sage_cert_pair


def _script(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["packaged_api_smoke", "packaged_sage_rpc_smoke"])
def test_generated_mock_identity_passes_real_sage_certificate_selection(tmp_path, name):
    script = _script(name)
    server, thread, cert, key = script._start_mock_sage(tmp_path)
    try:
        valid, reason, selected_cert, selected_key = validate_sage_cert_pair(
            str(cert), str(key), extra_data_dirs=[str(tmp_path / "sage-data")])
        assert valid is True, reason
        assert Path(selected_cert) == cert
        assert Path(selected_key) == key
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_probe_cannot_inherit_host_sage_discovery_roots(tmp_path):
    script = _script("packaged_api_smoke")
    keys = ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "SAGE_HOME", "SAGE_ALLOWED_CERT_ROOTS")
    env = script._build_env(
        base_env={key: "outside-test-wallet-root" for key in keys},
        temp_dir=tmp_path, sage_rpc_url="https://127.0.0.1:19257",
        client_cert=tmp_path / "sage-data/ssl/wallet.crt",
        client_key=tmp_path / "sage-data/ssl/wallet.key",
        flask_port=15234, local_token="test-token",
    )
    for key in keys:
        assert Path(env[key]).is_relative_to(tmp_path), key


@pytest.mark.parametrize("authenticated", [False, None, "true"])
def test_api_probe_rejects_unauthenticated_wallet_even_when_keys_exist(authenticated):
    script = _script("packaged_api_smoke")
    check = next(c for c in script._endpoint_checks() if c.path == "/api/wallet/sage-running")
    with pytest.raises(script.SmokeFailure, match="authenticated"):
        script._validate_payload(check, {
            "running": True, "rpc_port_listening": True, "rpc_authenticated": authenticated})


def test_mock_sage_version_satisfies_real_startup_requirement(monkeypatch):
    script = _script("packaged_api_smoke")
    version = script._mock_sage_payload("/get_version")["version"]
    monkeypatch.setattr(sage_node, "_load_current_sage_version", lambda: version)
    assert sage_node.get_sage_version_requirement()["supported"] is True


def test_package_api_probe_keeps_exchange_diagnostics_off_public_network(tmp_path):
    script = _script("packaged_api_smoke")
    env = script._build_env(
        base_env={"DEXIE_API_BASE": "https://public-provider.invalid", "SPLASH_ENABLED": "true"},
        temp_dir=tmp_path, sage_rpc_url="https://127.0.0.1:19257",
        client_cert=tmp_path / "sage-data/ssl/wallet.crt",
        client_key=tmp_path / "sage-data/ssl/wallet.key",
        flask_port=15234, local_token="test-token",
    )
    assert urlsplit(env["DEXIE_API_BASE"]).hostname == "127.0.0.1"
    assert env["SPLASH_ENABLED"] == "false"


def test_package_api_probe_persists_network_isolation_across_config_reload(tmp_path, monkeypatch):
    """The app's on-disk config must not replace loopback with public Dexie."""
    import config

    script = _script("packaged_api_smoke")
    env = script._build_env(
        base_env={"DEXIE_API_BASE": "https://public-provider.invalid"},
        temp_dir=tmp_path, sage_rpc_url="https://127.0.0.1:19257",
        client_cert=tmp_path / "sage-data/ssl/wallet.crt",
        client_key=tmp_path / "sage-data/ssl/wallet.key",
        flask_port=15234, local_token="test-token",
    )
    profile = Path(env["CMM_DATA_DIR"]) / ".env"
    assert profile.is_file(), "Probe must persist its synthetic profile before launch"
    monkeypatch.setattr(config, "_ENV_PATH", str(profile))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # Exercise actual config reload, even after process values have changed.
    monkeypatch.setenv("DEXIE_API_BASE", "https://public-provider.invalid")
    monkeypatch.setenv("SPLASH_ENABLED", "true")
    loaded = config.Config()
    loaded.reload()
    assert loaded.DEXIE_API_BASE == "http://127.0.0.1:1"
    assert loaded.SPLASH_ENABLED is False
    assert loaded.SAGE_RPC_URL == "https://127.0.0.1:19257"
    assert loaded.SAGE_FINGERPRINT == "123456789"


def test_package_api_probe_profile_does_not_copy_host_secrets(tmp_path):
    from dotenv import dotenv_values

    script = _script("packaged_api_smoke")
    env = script._build_env(
        base_env={"SPACESCAN_API_KEY": "do-not-copy-host-secret"},
        temp_dir=tmp_path, sage_rpc_url="https://127.0.0.1:19257",
        client_cert=tmp_path / "sage-data/ssl/wallet.crt",
        client_key=tmp_path / "sage-data/ssl/wallet.key",
        flask_port=15234, local_token="test-token",
    )
    profile = Path(env["CMM_DATA_DIR"]) / ".env"
    assert profile.is_file(), "Probe must persist its synthetic profile before launch"
    settings = dotenv_values(profile)
    assert "SPACESCAN_API_KEY" not in settings
    assert settings["CAT_ASSET_ID"] == "0" * 64


@pytest.mark.parametrize("dexie,splash", [
    ("https://api.dexie.space", False),
    ("http://127.0.0.1:1", True),
    ("http://127.0.0.1:1", "false"),
])
def test_package_api_probe_rejects_runtime_network_isolation_drift(dexie, splash):
    script = _script("packaged_api_smoke")
    check = script.EndpointCheck("GET", "/api/config", ("DEXIE_API_BASE", "SPLASH_ENABLED"))
    with pytest.raises(script.SmokeFailure, match="network isolation"):
        script._validate_payload(check, {"DEXIE_API_BASE": dexie, "SPLASH_ENABLED": splash})


def test_package_api_probe_reads_isolation_before_doctor():
    script = _script("packaged_api_smoke")
    paths = [check.path for check in script._endpoint_checks()]
    assert "/api/config" in paths
    assert paths.index("/api/wallet/begin-startup") < paths.index("/api/config")
    assert paths.index("/api/config") < paths.index("/api/doctor?force=true")
