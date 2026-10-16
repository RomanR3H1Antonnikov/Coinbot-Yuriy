"""One-time helper: open a VISIBLE Chrome with the scraper's persistent profile on avito.ru.

Use it when the scraper reports "Avito BLOCKED": click "Продолжить" / pass the check yourself in the window,
make sure the Avito page loads normally, then press Enter in this terminal. The cookies are saved in
.avito_profile and the scraper reuses them.
Run:  .venv/Scripts/python.exe avito_unblock.py  (or .venv' Scripts python)
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, ".avito_profile")
BLOCK_FILE = os.path.join(BASE_DIR, "logs", "avito_blocked_until.txt")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE_DIR, channel="chrome", headless=False, locale="ru-RU",
        timezone_id="Europe/Moscow", viewport={"width": 1400, "height": 900},
        args=["--disable-blink-features=AutomationControlled", "--lang=ru-RU"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.avito.ru/rossiya/kollektsionirovanie/monety-ASgBAgICAkSSA8YQ?q=%D0%B1%D1%80%D0%B0%D0%BA&s=104")
    print("В открывшемся Chrome пройди проверку Авито (кнопка «Продолжить» / галочка), дождись обычной страницы с объявлениями.")
    input("Когда страница с объявлениями открылась — нажми Enter здесь... ")
    ctx.close()

try:
    os.remove(BLOCK_FILE)
except OSError:
    pass
print("Готово. Профиль сохранён, пауза после блокировки сброшена.")
