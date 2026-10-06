import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


OUT = Path(__file__).resolve().parent
EXPECTED_FINGERPRINT = "3702373391"


def visible(page, selector: str) -> bool:
    locator = page.locator(selector)
    return locator.count() > 0 and locator.first.is_visible()


def snapshot(page, name: str, events: list[dict]) -> None:
    page.screenshot(path=OUT / f"{name}.png", full_page=True)
    payload = {
        "url": page.url,
        "title": page.title(),
        "body_text": page.locator("body").inner_text(),
        "visible_buttons": page.locator("button").evaluate_all(
            """els => els.filter(e => e.offsetWidth || e.offsetHeight || e.getClientRects().length)
                .map(e => ({id: e.id, text: (e.innerText || '').trim(),
                            aria: e.getAttribute('aria-label'), disabled: !!e.disabled,
                            fingerprint: e.dataset.fingerprint || null}))"""
        ),
        "events": events,
    }
    (OUT / f"{name}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> None:
    events: list[dict] = []
    console: list[dict] = []
    page_errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("console", lambda msg: console.append({"type": msg.type, "text": msg.text}))
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on(
            "response",
            lambda response: events.append(
                {"method": response.request.method, "url": response.url, "status": response.status}
            )
            if "/api/" in response.url
            else None,
        )

        page.goto("http://127.0.0.1:5000/", wait_until="networkidle", timeout=60_000)
        continue_btn = page.locator("#startupDisclaimerContinueBtn")
        continue_btn.wait_for(state="visible", timeout=15_000)
        continue_btn.click()

        connect_btn = page.get_by_role("button", name="Connect to Sage", exact=True)
        connect_btn.wait_for(state="visible", timeout=15_000)
        snapshot(page, "ui-risk-acknowledged", events)
        connect_btn.click()

        deadline = time.monotonic() + 60
        cards = page.locator("#startupFpCards .fp-card")
        while time.monotonic() < deadline:
            if cards.count() > 0 and cards.first.is_visible():
                break
            if visible(page, "#startupChangeAddressSection"):
                break
            if page.locator("#startupOverlay").evaluate(
                "e => e.classList.contains('hidden') || getComputedStyle(e).display === 'none'"
            ):
                break
            page.wait_for_timeout(500)

        snapshot(page, "ui-wallet-choice", events)
        available = cards.evaluate_all("els => els.map(e => e.dataset.fingerprint)")
        if available:
            if EXPECTED_FINGERPRINT not in available:
                raise RuntimeError(
                    f"Fingerprint identity mismatch: expected {EXPECTED_FINGERPRINT}, got {available}"
                )
            exact = page.locator(
                f'#startupFpCards .fp-card[data-fingerprint="{EXPECTED_FINGERPRINT}"]'
            )
            exact.click()
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                overlay_hidden = page.locator("#startupOverlay").evaluate(
                    "e => e.classList.contains('hidden') || getComputedStyle(e).display === 'none'"
                )
                if overlay_hidden or visible(page, "#startupChangeAddressSection"):
                    break
                page.wait_for_timeout(1000)

        snapshot(page, "ui-wallet-selected", events)
        result = {
            "expected_fingerprint": EXPECTED_FINGERPRINT,
            "available_fingerprints": available,
            "overlay_hidden": page.locator("#startupOverlay").evaluate(
                "e => e.classList.contains('hidden') || getComputedStyle(e).display === 'none'"
            ),
            "change_address_prompt_visible": visible(page, "#startupChangeAddressSection"),
            "splash_gate_visible": visible(page, "#splashGateOverlay"),
            "spacescan_gate_visible": visible(page, "#spacescanGateOverlay"),
            "console": console,
            "page_errors": page_errors,
            "events": events,
        }
        (OUT / "ui-connect-result.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(json.dumps(result, indent=2, ensure_ascii=True))
        browser.close()


if __name__ == "__main__":
    main()
