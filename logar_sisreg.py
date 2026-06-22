import sys
import time
from playwright.sync_api import sync_playwright
from app.browser_utils import lancar_browser, criar_contexto, resolver_tspd

USUARIO = sys.argv[1] if len(sys.argv) > 1 else "MED.LEIDE"
SENHA = sys.argv[2] if len(sys.argv) > 2 else "Med@1115"

erros = ["sessao", "invalida", "finalizada", "logon novamente",
         "operador invalido", "operador nao cadastrado",
         "senha invalidos", "usuario invalido"]

def tem_erro_login(page):
    try:
        texto = page.inner_text("body")
        for padrao in erros:
            if padrao in texto.lower():
                linhas = [l.strip() for l in texto.split('\n') if padrao in l.lower()]
                return linhas[0][:120] if linhas else padrao
        return ""
    except Exception:
        return ""

p = sync_playwright().start()
browser = lancar_browser(p, headless=False)
context = criar_contexto(browser)
page = context.new_page()

print(f"Logando em SISREG como {USUARIO}...")
page.goto("https://sisregiii.saude.gov.br/cgi-bin/index?logout=1")
resolver_tspd(page, context)

page.fill("input#usuario", USUARIO)
page.fill("input#senha", SENHA)
page.click("input[name=entrar]")
resolver_tspd(page, context)

erro = tem_erro_login(page)
if erro:
    print(f"ERRO NO LOGIN: {erro}")
else:
    print("LOGIN BEM-SUCEDIDO!")
    page.goto("https://sisregiii.saude.gov.br/cgi-bin/cons_agendas")
    page.wait_for_timeout(3000)
    print(f"URL atual: {page.url}")

sys.stdout.flush()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    browser.close()
    p.stop()
