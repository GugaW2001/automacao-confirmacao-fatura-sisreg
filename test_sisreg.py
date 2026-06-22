from playwright.sync_api import sync_playwright
import time
from app.browser_utils import lancar_browser, criar_contexto

with sync_playwright() as p:
    browser = lancar_browser(p, headless=False)
    context = criar_contexto(browser)
    page = context.new_page()
    page.goto("https://sisregiii.saude.gov.br/cgi-bin/index?logout=1")
    print(f"Título: {page.title()}")
    print("Navegador aberto. Pressione Ctrl+C para fechar.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Fechando navegador...")
    finally:
        browser.close()
