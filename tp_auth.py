"""
tp_auth.py
Login con Playwright a TrainingPeaks — mismo flujo exacto que usa el
Comments Bot (tp-bot/bot.py), reutilizado tal cual para mantener consistencia.

Variables de entorno esperadas:
    TP_EMAIL     - email de la cuenta de coach en TrainingPeaks
    TP_PASSWORD  - contraseña de esa cuenta
"""
import os
import random
import time

TP_LOGIN_URL = "https://home.trainingpeaks.com/login"


def _human_delay(a=1.0, b=3.0):
    time.sleep(random.uniform(a, b))


def login_and_get_page(playwright_instance):
    """
    Abre un browser, hace login en TrainingPeaks (mismo flujo que bot.py),
    y devuelve (page, browser) ya autenticado.

    Uso:
        with sync_playwright() as p:
            page, browser = login_and_get_page(p)
            ftp = get_athlete_ftp(page, athlete_id)
            ...
            browser.close()
    """
    email = os.environ["TP_EMAIL"]
    password = os.environ["TP_PASSWORD"]

    browser = playwright_instance.chromium.launch(
        headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()

    page.goto(TP_LOGIN_URL, wait_until="networkidle")
    _human_delay(2, 4)
    try:
        page.locator("#onetrust-accept-btn-handler").click()
        _human_delay(1, 2)
    except Exception:
        pass

    page.fill('input[name="Username"]', email)
    _human_delay(0.5, 1)
    page.fill('input[name="Password"]', password)
    _human_delay(0.5, 1)
    page.click('button[type="submit"]')
    _human_delay(5, 8)

    if "login" in page.url:
        raise Exception("Login a TrainingPeaks falló")

    page.goto("https://app.trainingpeaks.com/#/coach/athletes/list", wait_until="networkidle")
    _human_delay(6, 10)

    return page, browser
