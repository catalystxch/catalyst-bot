import json
from pathlib import Path

from playwright.sync_api import sync_playwright


OUT = Path(__file__).resolve().parent
EXPECTED_ASSET = "b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105"
NAV = [
    ("Dashboard", "dashboard"),
    ("Offers", "offers"),
    ("Profit and loss", "pnl"),
    ("Market intelligence", "market-intel"),
    ("Settings", "settings"),
    ("Logs", "logs"),
    ("Data reset", "data-reset"),
]


def main() -> None:
    console: list[dict] = []
    page_errors: list[str] = []
    api_failures: list[dict] = []
    views: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("console", lambda msg: console.append({"type": msg.type, "text": msg.text}))
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on(
            "response",
            lambda response: api_failures.append(
                {"method": response.request.method, "url": response.url, "status": response.status}
            )
            if "/api/" in response.url and response.status >= 400
            else None,
        )
        page.goto("http://127.0.0.1:5000/", wait_until="networkidle", timeout=60_000)
        page.locator("#startupOverlay").wait_for(state="hidden", timeout=30_000)
        page.locator("#catSelector option").nth(1).wait_for(state="attached", timeout=30_000)

        pair = page.locator("#catSelector")
        options = pair.locator("option").evaluate_all(
            "els => els.map(e => ({value: e.value, text: (e.textContent || '').trim(), selected: e.selected}))"
        )
        values = [option["value"] for option in options]
        if EXPECTED_ASSET not in values:
            raise RuntimeError(f"Exact MZ asset missing from pair selector: {values}")
        pair.select_option(EXPECTED_ASSET)
        page.wait_for_timeout(2_500)
        if pair.input_value() != EXPECTED_ASSET:
            raise RuntimeError(f"Pair identity mismatch after selection: {pair.input_value()}")

        for accessible_name, slug in NAV:
            page.get_by_role("button", name=accessible_name, exact=True).click()
            page.wait_for_timeout(900)
            page.screenshot(path=OUT / f"ui-view-{slug}.png", full_page=True)
            views.append(
                {
                    "name": accessible_name,
                    "slug": slug,
                    "body_text": page.locator("body").inner_text(),
                }
            )

            if accessible_name == "Settings":
                for selector, subslug in [
                    ("#settingsSubtabLive", "settings-live"),
                    ("#settingsSubtabSetup", "settings-setup"),
                ]:
                    button = page.locator(selector)
                    if button.count() and button.is_visible():
                        button.click()
                        page.wait_for_timeout(600)
                        page.screenshot(path=OUT / f"ui-view-{subslug}.png", full_page=True)

            if accessible_name == "Logs":
                doctor = page.locator("#logsRunDoctorBtn")
                doctor.wait_for(state="visible", timeout=10_000)
                doctor.click()
                page.get_by_text("Doctor Report", exact=True).wait_for(
                    state="visible", timeout=30_000
                )
                page.screenshot(path=OUT / "ui-doctor-report.png", full_page=True)
                views.append(
                    {
                        "name": "Doctor Report",
                        "slug": "doctor",
                        "body_text": page.locator("body").inner_text(),
                    }
                )
                close = page.get_by_role("button", name="Close", exact=True).last
                if close.count() and close.is_visible():
                    close.click()

        help_button = page.get_by_role("button", name="Help", exact=True).last
        help_button.click()
        page.wait_for_timeout(500)
        page.screenshot(path=OUT / "ui-help.png", full_page=True)
        views.append({"name": "Help", "slug": "help", "body_text": page.locator("body").inner_text()})
        help_close = page.get_by_role("button", name="Close help", exact=True)
        if help_close.count() and help_close.is_visible():
            help_close.click()

        about_button = page.get_by_role("button", name="About this app", exact=True)
        about_button.click()
        page.wait_for_timeout(500)
        page.screenshot(path=OUT / "ui-about.png", full_page=True)
        views.append({"name": "About", "slug": "about", "body_text": page.locator("body").inner_text()})

        result = {
            "expected_asset": EXPECTED_ASSET,
            "pair_value": pair.input_value(),
            "pair_options": options,
            "views": views,
            "console": console,
            "page_errors": page_errors,
            "api_failures": api_failures,
        }
        (OUT / "ui-traverse-result.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        summary = {
            "pair_value": result["pair_value"],
            "view_names": [view["name"] for view in views],
            "console_error_count": sum(1 for item in console if item["type"] == "error"),
            "page_errors": page_errors,
            "api_failures": api_failures,
        }
        print(json.dumps(summary, indent=2, ensure_ascii=True))
        browser.close()


if __name__ == "__main__":
    main()
