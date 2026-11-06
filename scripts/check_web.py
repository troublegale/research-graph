"""Browser smoke test against a running demo server; creates/removes one request.

Run: uv run python scripts/check_web.py http://127.0.0.1:8001
Install browser first: uv run playwright install chromium
"""

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Browser, Route, expect, sync_playwright


def check_requests_pagination(browser: Browser, url: str) -> None:
    """The 101st request stays visible and selectable after loading another page."""
    page = browser.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    oldest = {
        "id": 1,
        "title": "Самая старая заявка",
        "budget": 1000000,
        "status": "open",
        "revision": 1,
    }
    recent = [
        oldest | {"id": identity, "title": f"Заявка {identity}"} for identity in range(101, 1, -1)
    ]

    def requests_route(route: Route) -> None:
        parsed = urlsplit(route.request.url)
        if parsed.path == "/api/requests":
            number = parse_qs(parsed.query).get("page", ["1"])[0]
            route.fulfill(json=recent if number == "1" else [oldest])
        elif parsed.path == "/api/requests/1":
            route.fulfill(json=oldest)
        elif parsed.path == "/api/requests/1/candidates":
            route.fulfill(json=[])
        else:
            route.continue_()

    page.route("**/api/requests**", requests_route)
    page.goto(url)
    expect(page.locator("#requests")).to_have_attribute("aria-busy", "false")
    expect(page.locator("#request-list [data-request]")).to_have_count(100)
    page.locator("[data-more-requests]").click()
    expect(page.locator("#request-list [data-request]")).to_have_count(101)
    page.locator('[data-request="1"]').click()
    expect(page.locator("#detail-title")).to_have_text("Самая старая заявка")
    expect(page.locator("#request-list [data-request]")).to_have_count(101)
    expect(page.locator("[data-more-requests]")).to_have_count(0)
    if errors:
        raise AssertionError(errors)
    page.close()


def main(url: str) -> None:
    expect.set_options(timeout=15000)
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        expect(page.locator("#requests")).to_have_attribute("aria-busy", "false")
        page.locator('#request-form [name="title"]').fill("Проверка интерфейса")
        page.locator('#request-form [name="budget"]').fill("2000000")
        page.get_by_role("button", name="Сохранить заявку", exact=True).click()
        expect(page.locator("#detail-title")).to_have_text("Проверка интерфейса")
        page.locator("#match").click()
        expect(page.locator("#matches .car-card").first).to_be_visible()
        page.locator("#matches [data-add]").first.click()
        expect(page.locator("#candidates tbody tr")).to_have_count(1)
        page.locator("#candidates [data-estimate]").click()
        expect(page.locator("#candidates tbody tr td").nth(2)).not_to_have_text("—")
        page.screenshot(path=str(output / "ui-desktop.png"), full_page=True)
        page.locator("#edit-request").click()
        page.locator('#request-form [name="budget"]').fill("2500000")
        page.get_by_role("button", name="Сохранить заявку", exact=True).click()
        expect(page.locator("#candidates")).to_contain_text("Требования изменились")
        page.locator("#status-request").click()
        expect(page.locator("#edit-request")).to_be_disabled()
        page.locator("#status-request").click()
        expect(page.locator("#edit-request")).to_be_enabled()
        page.on("dialog", lambda dialog: dialog.accept())
        page.locator("#delete-request").click()
        expect(page.locator("#request-detail")).to_be_hidden()
        page.locator('[data-tab="catalog"]').click()
        expect(page.locator("#catalog-items .car-card").first).to_be_visible()
        page.locator("#next-page").click()
        expect(page.locator("#page-label")).to_have_text("Страница 2")
        page.locator('[data-tab="analytics"]').click()
        expect(page.locator("#price-report tbody tr").first).to_be_visible()
        page.locator('[data-tab="model"]').click()
        page.get_by_role("button", name="Оценить автомобиль", exact=True).click()
        expect(page.locator("#manual-result")).to_contain_text("₽")
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "ui-mobile.png"), full_page=True)
        if page.evaluate("document.documentElement.scrollWidth > innerWidth"):
            raise AssertionError("page overflows mobile viewport")
        if errors:
            raise AssertionError(errors)
        check_requests_pagination(browser, url)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001")
