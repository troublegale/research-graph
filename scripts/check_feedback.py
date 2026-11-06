"""Check visible feedback and duplicate protection with delayed browser responses."""

import sys
from pathlib import Path

from playwright.sync_api import Request, expect, sync_playwright


def main(url: str) -> None:
    expect.set_options(timeout=15000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(15000)
        errors: list[str] = []
        requests: list[Request] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request))
        # Delay delivery rather than blocking the browser automation thread.
        page.add_init_script("""const originalFetch = window.fetch;
            window.fetch = async (...args) => {
                const response = await originalFetch(...args);
                await new Promise(resolve => setTimeout(resolve, 1200));
                return response;
            };""")
        page.goto(url)
        expect(page.locator("#activity")).to_be_visible()
        expect(page.locator("#requests")).to_have_attribute("aria-busy", "false")
        page.locator('#request-form [name="title"]').fill("Проверка обратной связи")
        page.locator('#request-form [name="budget"]').fill("2000000")
        submit = page.locator('#request-form button[type="submit"]')
        submit.click()
        expect(submit).to_be_disabled()
        expect(submit).to_have_text("Сохраняем заявку…")
        expect(page.locator("#activity")).to_contain_text("Сохраняем заявку…")
        # Even programmatic repeated submit events cannot create duplicates.
        page.locator("#request-form").evaluate(
            "form => {form.requestSubmit(); form.requestSubmit();}"
        )
        expect(page.locator("#message")).to_contain_text("Заявка сохранена")
        expect(submit).to_be_enabled()
        creates = [
            request
            for request in requests
            if request.method == "POST" and request.url.endswith("/api/requests")
        ]
        if len(creates) != 1:
            raise AssertionError(f"Expected one create request, got {len(creates)}")
        page.locator("#match").click()
        expect(page.locator("#activity")).to_contain_text("Подбираем автомобили…")
        expect(page.locator("#match")).to_be_disabled()
        expect(page.locator("#message")).to_contain_text("Подбор завершён")
        expect(page.locator("#match")).to_be_enabled()
        page.locator("#matches [data-add]").first.click()
        expect(page.locator("#activity")).to_contain_text("Сохраняем автомобиль…")
        expect(page.locator("#message")).to_contain_text("Автомобиль добавлен")
        page.locator("#candidates [data-estimate]").click()
        expect(page.locator("#activity")).to_contain_text("Оцениваем автомобиль…")
        expect(page.locator("#message")).to_contain_text("Оценка готова")
        # Toast remains visible even far down a long page of matching cars.
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        box = page.locator("#message").bounding_box()
        if box is None or box["y"] < 0 or box["y"] + box["height"] > 900:
            raise AssertionError("Completion message is outside the viewport")
        page.locator("#status-request").click()
        expect(page.locator("#message")).to_contain_text("Заявка закрыта")
        expect(page.locator("#edit-request")).to_be_disabled()
        page.locator("#status-request").click()
        expect(page.locator("#message")).to_contain_text("Заявка открыта повторно")
        page.on("dialog", lambda dialog: dialog.accept())
        page.locator("#delete-request").click()
        expect(page.locator("#message")).to_contain_text("Заявка удалена")
        page.locator('[data-tab="catalog"]').click()
        expect(page.locator("#activity")).to_contain_text("Загружаем каталог…")
        expect(page.locator("#message")).to_contain_text("Каталог загружен")
        expect(page.locator("#previous-page")).to_be_disabled()
        page.locator("#next-page").click()
        expect(page.locator("#activity")).to_contain_text("Загружаем объявления…")
        expect(page.locator("#page-label")).to_have_text("Страница 2")
        expect(page.locator("#activity")).to_be_hidden()
        page.locator('[data-tab="analytics"]').click()
        expect(page.locator("#activity")).to_contain_text("Формируем аналитические отчёты…")
        expect(page.locator("#message")).to_contain_text("Аналитические отчёты готовы")
        page.locator('[data-tab="model"]').click()
        expect(page.locator("#model")).to_have_attribute("aria-busy", "false")
        manual = page.locator("#manual-form button")
        # Errors release the form; the next attempt can succeed.
        page.route(
            "**/predict",
            lambda route: route.fulfill(
                status=503, json={"error": {"message": "Сервис временно недоступен"}}
            ),
            times=1,
        )
        manual.click()
        expect(manual).to_be_disabled()
        expect(page.locator("#activity")).to_contain_text("Рассчитываем стоимость автомобиля…")
        expect(page.locator("#message")).to_contain_text("Сервис временно недоступен")
        expect(manual).to_be_enabled()
        expect(page.locator("#model")).to_have_attribute("aria-busy", "false")
        expect(page.locator("#activity")).to_be_hidden()
        manual.click()
        expect(page.locator("#message")).to_contain_text("Оценка готова")
        expect(page.locator("#manual-result")).to_contain_text("₽")
        page.route("**/predict", lambda route: route.abort("failed"), times=1)
        manual.click()
        expect(page.locator("#message")).to_contain_text("Не удалось связаться с сервисом")
        expect(manual).to_be_enabled()
        expect(page.locator("#activity")).to_be_hidden()
        page.locator('#upload-form input[type="file"]').set_input_files("artifacts/model.zip")
        page.locator("#upload-form button").click()
        expect(page.locator("#activity")).to_contain_text("Загружаем и проверяем модель…")
        expect(page.locator("#upload-form button")).to_be_disabled()
        expect(page.locator("#message")).to_contain_text("Модель загружена и готова к работе")
        csv = b"brand,name,location,price\nToyota,Corolla,Moscow,1000000\n"
        page.locator('#csv-form input[type="file"]').set_input_files(
            {"name": "cars.csv", "mimeType": "text/csv", "buffer": csv}
        )
        page.locator("#csv-form button").click()
        expect(page.locator("#activity")).to_contain_text("Обрабатываем CSV")
        expect(page.locator("#download-predictions")).to_be_hidden()
        expect(page.locator("#message")).to_contain_text("Обработка CSV завершена. Строк: 1")
        expect(page.locator("#download-predictions")).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        manual.click()
        expect(page.locator("#activity")).to_be_visible()
        Path("artifacts").mkdir(exist_ok=True)
        page.screenshot(path="artifacts/ui-feedback-mobile.png")
        expect(page.locator("#activity")).to_be_hidden()
        if page.evaluate("document.documentElement.scrollWidth > innerWidth"):
            raise AssertionError("Feedback overflows mobile viewport")
        if errors:
            raise AssertionError(errors)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001")
