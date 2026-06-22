import random
import sys

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
]


def user_agent():
    return random.choice(USER_AGENTS)


ANTI_DETECTION_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-infobars",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-dev-shm-usage",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-first-run",
    "--disable-features=ChromeWhatsNewUI",
    "--disable-sync",
    "--disable-default-apps",
    "--disable-notifications",
    "--start-maximized",
]

ANTI_DETECTION_SCRIPT = """
const cores = 4 + Math.floor(Math.random() * 4);
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => cores
});

Object.defineProperty(navigator, 'deviceMemory', {
    get: () => [4, 8][Math.floor(Math.random() * 2)]
});

Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32'
});

Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};

Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const arr = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' }
        ];
        arr.item = i => arr[i];
        arr.namedItem = n => arr.find(p => p.name === n) || null;
        arr.refresh = () => {};
        return arr;
    }
});

Object.defineProperty(navigator, 'languages', {
    get: () => ['pt-BR', 'pt', 'en-US', 'en']
});

(() => {
    const spoof = (gl) => {
        const orig = gl.getParameter;
        gl.getParameter = function(p) {
            if (p === 37445) return 'Intel Inc.';
            if (p === 37446) return 'Intel(R) UHD Graphics 620';
            return orig.call(this, p);
        };
    };
    try { spoof(WebGLRenderingContext.prototype); } catch (e) {}
    try { spoof(WebGL2RenderingContext.prototype); } catch (e) {}
})();
"""

HEADERS = {
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


def lancar_browser(playwright, headless=True):
    canais = ["msedge", "chrome"]
    for canal in canais:
        try:
            browser = playwright.chromium.launch(
                channel=canal,
                headless=headless,
                args=ANTI_DETECTION_ARGS,
            )
            print(f"  Navegador: {canal}", flush=True)
            return browser
        except Exception as e:
            print(f"  {canal} não disponível ({e}), tentando próximo...", flush=True)

    print("  Navegador: Chromium padrão do Playwright", flush=True)
    return playwright.chromium.launch(
        headless=headless,
        args=ANTI_DETECTION_ARGS,
    )


def criar_contexto(browser):
    context = browser.new_context(
        user_agent=user_agent(),
        viewport={"width": 1920, "height": 1080},
        screen={"width": 1920, "height": 1080},
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        extra_http_headers=HEADERS,
    )
    context.add_init_script(ANTI_DETECTION_SCRIPT)
    return context


def sleep(page, min_ms=50, max_ms=150):
    page.wait_for_timeout(random.randint(min_ms, max_ms))


def resolver_tspd(page, context, timeout=30):
    """Aguarda o desafio TSPD do F5 completar.
    Se detectar pagina de rejeicao, clica Go Back e aguarda os cookies do F5.
    """
    import time
    start = time.time()

    while time.time() - start < timeout:
        cookies = context.cookies()
        nomes = [c["name"] for c in cookies]

        # Se jah temos o cookie TSPD_101, o desafio ja foi resolvido
        if any("TSPD_101" in n for n in nomes):
            return True

        body = page.inner_text("body").lower()

        # Se apareceu a pagina de rejeicao, clicar Go Back para liberar
        if "rejected" in body or "support id" in body:
            go_back = page.query_selector("a:has-text('Go Back'), a:has-text('go back'), a:has-text('Voltar')")
            if go_back:
                print("  TSPD: clicando Go Back...", flush=True)
                go_back.click()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                continue
            # Se nao tem Go Back, tentar recarregar a pagina
            print("  TSPD: recarregando pagina...", flush=True)
            page.goto(page.url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
            continue

        # Se tem o formulario de login mas ainda nao tem cookie TSPD,
        # o desafio pode estar rodando em background
        if page.is_visible("input#usuario", timeout=2000):
            print("  TSPD: aguardando desafio completar...", flush=True)
            page.wait_for_timeout(2000)
            continue

        page.wait_for_timeout(1000)

    return False
