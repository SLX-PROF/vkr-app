"""Скриншоты основных экранов для главы 3 ВКР → docs/screenshots/.

Нужны dev-зависимости и браузер:  pip install -r requirements-dev.txt && playwright install chromium
Перед запуском выполните `python manage.py seed_demo`. Если сервер на BASE_URL не отвечает, скрипт сам
запускает `manage.py runserver` на порту 8765 и останавливает его в конце.

Запуск:  python scripts/take_screenshots.py
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8765")
# Учётные записи из seed_demo (только для разработки, см. README)
SECURITY = ("sb_demo", "SbDemo-2026")
ACCOUNTING = ("buh_demo", "BuhDemo-2026")
ADMIN = ("admin_demo", "AdminDemo-2026")


def server_up() -> bool:
    try:
        urllib.request.urlopen(f"{BASE_URL}/login/", timeout=2)
        return True
    except Exception:  # noqa: BLE001
        return False


def start_server():
    port = BASE_URL.rsplit(":", 1)[-1]
    proc = subprocess.Popen([sys.executable, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if server_up():
            return proc
        time.sleep(0.2)
    proc.terminate()
    raise SystemExit("Сервер не запустился: проверьте БД и миграции")


def shot(page, name):
    OUT.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(900)  # анимация графика и вкладок
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print("сохранён", name)


def login(browser, credentials):
    context = browser.new_context(viewport={"width": 1200, "height": 800}, locale="ru-RU")
    page = context.new_page()
    page.goto(f"{BASE_URL}/login/")
    page.fill("#id_username", credentials[0])
    page.fill("#id_password", credentials[1])
    page.click("button[type=submit]")
    page.wait_for_url(f"{BASE_URL}/")
    return context, page


def open_card(page, name):
    page.goto(f"{BASE_URL}/")
    page.click(f"a:has-text('{name}')")
    page.wait_for_selector("#risk-chart")


def tab(page, title):
    page.click(f"button[role=tab]:has-text('{title}')")


def submit_document(page, signer, doc_date="2026-05-20"):
    page.goto(f"{BASE_URL}/documents/verify/")
    page.select_option("#id_doc_type", "upd")
    page.fill("#id_number", "17")
    page.fill("#id_date", doc_date)
    page.fill("#id_inn", "0000000018")
    page.fill("#id_amount", "1200000")
    page.fill("#id_signer_name", signer)
    page.fill("#id_signer_position", "Генеральный директор")
    page.click("button:has-text('Сверить')")  # не button[type=submit]: первой в навбаре идёт кнопка «Выйти»
    page.wait_for_selector(".alert")


def main():
    proc = None if server_up() else start_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            anon = browser.new_context(viewport={"width": 1200, "height": 800}, locale="ru-RU").new_page()
            anon.goto(f"{BASE_URL}/login/")
            shot(anon, "01_login")

            context, page = login(browser, SECURITY)
            shot(page, "02_dashboard")
            open_card(page, "Тестстрой-8")
            shot(page, "03_card_overview")
            tab(page, "ЕГРЮЛ")
            shot(page, "04_card_egrul")
            tab(page, "Риски")
            shot(page, "05_card_risks")
            open_card(page, "Тестстрой-1")
            tab(page, "Документы")
            shot(page, "06_card_documents")
            submit_document(page, "Образцов П.С.")
            shot(page, "07_document_ok")
            submit_document(page, "Иванов Иван Иванович")
            shot(page, "08_document_warning")
            submit_document(page, "Образцов П.С.", doc_date="2010-01-15")
            shot(page, "09_document_error")
            page.goto(f"{BASE_URL}/documents/verify/")
            shot(page, "10_document_form")
            context.close()

            context, page = login(browser, ACCOUNTING)
            shot(page, "11_dashboard_accountant")
            open_card(page, "Тестстрой-8")
            tab(page, "Риски")
            shot(page, "12_card_accountant_risks_hidden")
            context.close()

            context, page = login(browser, ADMIN)
            page.goto(f"{BASE_URL}/admin/")
            shot(page, "13_admin")
            context.close()
            browser.close()
    finally:
        if proc:
            proc.terminate()


if __name__ == "__main__":
    main()
