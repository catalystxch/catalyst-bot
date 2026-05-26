from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "bot_gui.html"


def _function_body(name: str) -> str:
    html = GUI.read_text(encoding="utf-8")
    marker = f"function {name}()"
    start = html.index(marker)
    brace_start = html.index("{", start)
    depth = 0
    for index in range(brace_start, len(html)):
        char = html[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return html[brace_start + 1 : index]
    raise AssertionError(f"Could not parse {name} body")


def test_offer_filter_targets_stable_buy_and_sell_sections():
    body = _function_body("v4ApplyOfferFilter")

    assert "getElementById('buyOffersSection')" in body
    assert "getElementById('sellOffersSection')" in body
    assert "#activeTab .offers-section:first-child" not in body
    assert "#activeTab .offers-section:last-child" not in body
