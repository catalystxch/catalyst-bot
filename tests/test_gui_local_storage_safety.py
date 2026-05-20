from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_save_config_bot_config_storage_is_guarded():
    gui = (ROOT / "bot_gui.html").read_text(encoding="utf-8")

    assert "safeLocalStorageSet('botConfig'" in gui
    assert "localStorage.setItem('botConfig'" not in gui
