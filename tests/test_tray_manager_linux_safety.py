import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "catalyst"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _FakeMenu:
    SEPARATOR = "-"

    def __init__(self, *items):
        self.items = items


class _FakeMenuItem:
    def __init__(self, text, action=None, **kwargs):
        self.text = text
        self.action = action
        self.kwargs = kwargs

    def __str__(self):
        return self.text


def test_tray_tooltips_and_menu_labels_are_x11_latin1_safe(monkeypatch):
    fake_pystray = types.SimpleNamespace(
        Icon=object,
        Menu=_FakeMenu,
        MenuItem=_FakeMenuItem,
    )
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)
    sys.modules.pop("tray_manager", None)

    import tray_manager

    tray = tray_manager.TrayManager(app_name="CATalyst", app_version="1.2.36")
    tray.update_tray_state("running", cat_name="MZ")

    labels = [tray._build_tooltip()]
    labels.extend(str(item) for item in tray._build_menu().items)

    for label in labels:
        label.encode("latin-1")
