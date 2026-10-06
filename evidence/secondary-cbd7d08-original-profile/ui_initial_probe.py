import json
from pathlib import Path

from playwright.sync_api import sync_playwright


OUT = Path(__file__).resolve().parent


def main() -> None:
    console = []
    page_errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("console", lambda msg: console.append({"type": msg.type, "text": msg.text}))
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        response = page.goto("http://127.0.0.1:5000/", wait_until="networkidle", timeout=60_000)
        page.screenshot(path=OUT / "ui-initial.png", full_page=True)
        buttons = page.locator("button").evaluate_all(
            """els => els.map(e => ({
                id: e.id,
                text: (e.innerText || '').trim(),
                aria: e.getAttribute('aria-label'),
                disabled: !!e.disabled,
                visible: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)
            }))"""
        )
        result = {
            "http_status": response.status if response else None,
            "url": page.url,
            "title": page.title(),
            "body_text": page.locator("body").inner_text(),
            "buttons": buttons,
            "console": console,
            "page_errors": page_errors,
        }
        (OUT / "ui-initial.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        # PowerShell's host output is CP-1252 on this PC. Keep the saved JSON
        # human-readable UTF-8, but escape non-ASCII glyphs for console output.
        print(json.dumps(result, indent=2, ensure_ascii=True))
        browser.close()


if __name__ == "__main__":
    main()
