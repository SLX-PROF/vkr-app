"""Сквозная браузерная проверка; нужны запущенное приложение и seed_demo."""
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8765")


def main():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{BASE}/login/")
        page.fill("#id_username", "sb_demo")
        page.fill("#id_password", "SbDemo-2026")
        page.locator('form button[type="submit"]').click()
        page.wait_for_url(BASE + "/")
        page.fill('input[name="query"]', "0000000018")
        page.select_option("#profile", "demo")
        page.locator('form[action="/check/"] button').click()
        expect(page.get_by_role("heading", name="ООО «Тестстрой-1»")).to_be_visible()
        with page.expect_download() as download:
            page.get_by_role("link", name="Скачать PDF", exact=True).click()
        saved = ROOT / "docs" / "browser_report.pdf"
        download.value.save_as(saved)
        assert saved.read_bytes().startswith(b"%PDF-")
        page.get_by_role("link", name="Проверка документа", exact=True).click()
        for key, value in {"number": "smoke-17", "date": "2026-05-20", "inn": "0000000018",
                           "amount": "100", "signer_name": "Образцов П.С.",
                           "signer_position": "Генеральный директор"}.items():
            page.fill(f"#id_{key}", value)
        page.select_option("#id_doc_type", "upd")
        page.get_by_role("button", name="Сверить", exact=True).click()
        expect(page.get_by_text("Соответствует проверенным реквизитам")).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(ROOT / "docs" / "screenshots" / "14_mobile_result.png"), full_page=True)
        assert not errors, errors
        browser.close()
    (ROOT / "docs" / "browser_validation.json").write_text(
        json.dumps({"scenario": "login → INN → card → PDF → document", "passed": True,
                    "mobile_width": 390, "page_errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Браузерный сценарий и загрузка PDF пройдены, ошибок JavaScript нет.")


if __name__ == "__main__":
    main()
