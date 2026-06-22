from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto("https://www.google.com")
    print(f"Título: {page.title()}")
    input("Pressione Enter para fechar o navegador...")
    browser.close()
