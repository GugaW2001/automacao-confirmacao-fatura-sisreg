from playwright.sync_api import sync_playwright
import time
import sys
from app.browser_utils import lancar_browser, criar_contexto

p = sync_playwright().start()
browser = lancar_browser(p, headless=False)
context = criar_contexto(browser)
page = context.new_page()
page.goto("https://sisregiii.saude.gov.br/cgi-bin/index?logout=1")
print(f"Título: {page.title()}")
print("Navegador aberto. Feche-o manualmente para encerrar.")
sys.stdout.flush()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    browser.close()
    p.stop()
