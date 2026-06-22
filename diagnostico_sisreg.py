import sys, json
from playwright.sync_api import sync_playwright

USUARIO = sys.argv[1] if len(sys.argv) > 1 else "MED_LEIDE"
SENHA = sys.argv[2] if len(sys.argv) > 2 else "Med1115@"

p = sync_playwright().start()
browser = p.chromium.launch(headless=False, args=[
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-infobars",
])

context = browser.new_context()
page = context.new_page()

requests_log = []

def on_request(request):
    if "sisregiii" in request.url:
        h = dict(request.headers)
        info = {
            "method": request.method,
            "url": request.url,
            "headers": {k: v for k, v in sorted(h.items())},
            "post_data": request.post_data,
        }
        requests_log.append(info)
        print(f"\n>>> {request.method} {request.url[:100]}", flush=True)
        for k, v in sorted(h.items()):
            print(f"  {k}: {v[:120]}", flush=True)
        if request.post_data:
            print(f"  body: {request.post_data[:300]}", flush=True)

def on_response(response):
    if "sisregiii" in response.url:
        print(f"<<< {response.status} {response.url[:100]}", flush=True)
        h = dict(response.headers)
        for k, v in sorted(h.items()):
            if "cookie" in k.lower() or "set-cookie" in k.lower() or "ts" in k.lower() or k in ("content-type", "location"):
                print(f"  {k}: {v[:120]}", flush=True)

page.on("request", on_request)
page.on("response", on_response)

print("=== CARREGANDO PAGINA INICIAL ===", flush=True)
page.goto("https://sisregiii.saude.gov.br/cgi-bin/index?logout=1", wait_until="domcontentloaded", timeout=20000)
page.wait_for_timeout(5000)

print("\n=== PREENCHENDO FORMULARIO ===", flush=True)
print("  Preenchendo usuario...", flush=True)
page.fill("input#usuario", USUARIO)
page.wait_for_timeout(800)
print("  Preenchendo senha...", flush=True)
page.fill("input#senha", SENHA)
page.wait_for_timeout(600)

print("\n=== CLICANDO ENTRAR ===", flush=True)
page.click("input[name=entrar]")
page.wait_for_load_state("domcontentloaded", timeout=15000)
page.wait_for_timeout(3000)

body = page.inner_text("body")
print(f"\n=== RESULTADO ===", flush=True)
print(f"URL: {page.url}", flush=True)
print(f"Body: {body[:500]}", flush=True)

browser.close()
p.stop()

print("\n\n=== RESUMO DAS REQUISICOES ===", flush=True)
for r in requests_log:
    print(f"\n{r['method']} {r['url'][:90]}", flush=True)
    if r["method"] == "POST":
        ctype = r["headers"].get("content-type", "")
        print(f"  content-type: {ctype}", flush=True)
        print(f"  content-length: {r['headers'].get('content-length', '?')}", flush=True)
        print(f"  origin: {r['headers'].get('origin', 'AUSENTE')}", flush=True)
        print(f"  referer: {r['headers'].get('referer', 'AUSENTE')}", flush=True)
        print(f"  cookie: {r['headers'].get('cookie', 'AUSENTE')[:100]}", flush=True)
        if r["post_data"]:
            print(f"  body: {r['post_data'][:500]}", flush=True)
