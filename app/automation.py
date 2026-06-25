import re
import threading
import time
from datetime import datetime
from playwright.sync_api import sync_playwright
from .browser_utils import lancar_browser, criar_contexto, sleep, resolver_tspd


OTIMUS_URLS = {
    "palhoca": "https://medimagempalhoca.otimusclinic.com/medimagempalhoca/servlet/app.entrar",
    "sao_jose": "https://medimagempalhoca.otimusclinic.com/medimagempalhoca/servlet/app.entrar",
}

def _otimus_url(unidade):
    url = OTIMUS_URLS.get(unidade)
    if not url:
        raise ValueError(f"Unidade '{unidade}' não possui URL do Otimus configurada")
    return url


def _logar_otimus(page, usuario, senha, url, timeout=15000):
    page.goto(url, wait_until="domcontentloaded")
    try:
        page.wait_for_selector("input#vLOGIN", timeout=timeout)
    except Exception:
        # Tentar recarregar se o campo de login não apareceu
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector("input#vLOGIN", timeout=timeout)
    page.fill("input#vLOGIN", usuario)
    page.wait_for_selector("input#vSENHA", timeout=timeout)
    page.fill("input#vSENHA", senha)
    page.click("input[name=BUTTON1]")
    page.wait_for_load_state("domcontentloaded")
    try:
        page.wait_for_selector("#SIDEBARDIV_MPAGE", timeout=15000)
    except Exception:
        texto = page.inner_text("body")
        erros = ["invalido", "incorreto", "negado", "erro"]
        for padrao in erros:
            if padrao in texto.lower():
                raise RuntimeError(f"Falha no login Otimus: credenciais inválidas")
        # Tentar recarregar e verificar novamente
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector("#SIDEBARDIV_MPAGE", timeout=15000)
        except Exception:
            raise RuntimeError(f"Falha no login Otimus: página de destino não encontrada")


def _navegar_para_faturamento(page, codigo_fatura, log_callback=None, max_retries=3):
    """Navega do menu principal do Otimus até a grid da fatura.
    Retorna True se conseguiu, False se falhou após todas as tentativas."""
    def _log(msg):
        if log_callback:
            log_callback(msg)

    for tentativa in range(max_retries):
        try:
            page.evaluate("""() => {
                const el = document.querySelector('a[href*="wwfaturamento"]');
                if (el) { el.click(); return; }
                const allLinks = document.querySelectorAll('a');
                for (const a of allLinks) {
                    if (a.textContent.trim() === 'Faturamento') {
                        a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                        return;
                    }
                }
            }()""")
            page.wait_for_timeout(2000)
            page.evaluate("""() => {
                const el = document.querySelector('a[href*="wwfaturamento"]');
                if (el) el.click();
            }()""")
            page.wait_for_selector("a:has-text('Visualizar Fatura')", timeout=20000)

            links = page.query_selector_all("a:has-text('Visualizar Fatura')")
            link_escolhido = None
            for link in links:
                codigo = link.evaluate("""el => {
                    const tr = el.closest('tr');
                    if (!tr) return null;
                    const span = tr.querySelector('span[id^="span_CAPADELOTEID"]');
                    return span ? span.textContent.trim() : null;
                }""")
                if codigo and codigo.strip() == codigo_fatura:
                    link_escolhido = link
                    break

            if not link_escolhido:
                _log(f"  AVISO (tentativa {tentativa+1}): Fatura {codigo_fatura} não encontrada no Otimus")
                if tentativa < max_retries - 1:
                    page.wait_for_timeout(2000)
                    continue
                return False

            page.evaluate("(el) => el.click()", link_escolhido)
            page.wait_for_selector('[id^="vEDITARGRID_"]', timeout=15000)
            return True

        except Exception as e:
            _log(f"  AVISO (tentativa {tentativa+1}): Falha ao navegar para faturamento: {e}")
            if tentativa < max_retries - 1:
                page.wait_for_timeout(2000)
                continue
            _log(f"  ERRO: Falha ao navegar para faturamento após {max_retries} tentativas")
            return False

    return False


def _encontrar_edit_buttons(page):
    imgs = page.query_selector_all('img[src*="ActionUpdate"]')
    if imgs:
        return imgs
    icones = page.query_selector_all("i.fa-pencil")
    if icones:
        return icones
    return page.query_selector_all('[id^="vEDITARGRID_"]')


def _coletar_guias(page):
    return page.evaluate("""() => {
        const data = [];
        const seen = new Set();
        let scrollEl = [...document.querySelectorAll('div')].find(
            e => e.scrollHeight > e.clientHeight &&
                 e.scrollHeight > 500 &&
                 e.querySelector('tr[id^="Grid1ContainerRow_"]')
        );
        if (!scrollEl) {
            scrollEl = [...document.querySelectorAll('div')].find(
                e => e.scrollHeight > e.clientHeight && e.scrollHeight > 1000
            );
        }
        if (!scrollEl) scrollEl = document.documentElement;
        let lastPos = 0, attempt = 0;
        const MAX_ATTEMPTS = 10;
        return new Promise(resolve => {
            function scrollAndCollect() {
                document.querySelectorAll('tr[id^="Grid1ContainerRow_"]').forEach(tr => {
                    const cells = tr.querySelectorAll('td');
                    const guiaNum = (cells[4]?.innerText || '').trim();
                    if (guiaNum && !seen.has(guiaNum)) {
                        seen.add(guiaNum);
                        data.push({
                            row: tr.getAttribute('data-gxrow'),
                            guia: guiaNum,
                            paciente: (cells[8]?.innerText || '').trim(),
                            servico: (cells[11]?.innerText || '').trim(),
                        });
                    }
                });
                const newCount = data.length;
                if (newCount > lastPos) {
                    lastPos = newCount;
                    attempt = 0;
                } else {
                    attempt++;
                }
                if (attempt >= MAX_ATTEMPTS || newCount >= 10000) {
                    resolve(data);
                    return;
                }
                scrollEl.scrollTop = scrollEl.scrollTop + scrollEl.clientHeight * 0.6;
                setTimeout(scrollAndCollect, 800);
            }
            scrollAndCollect();
        });
    }""")


def _scroll_para_linha(page, idx, total):
    page.evaluate("""({ idx, total }) => {
        let scrollEl = [...document.querySelectorAll('div')].find(
            e => e.scrollHeight > e.clientHeight &&
                 e.scrollHeight > 500 &&
                 e.querySelector('tr[id^="Grid1ContainerRow_"]')
        );
        if (!scrollEl) {
            scrollEl = [...document.querySelectorAll('div')].find(
                e => e.scrollHeight > e.clientHeight && e.scrollHeight > 1000
            );
        }
        if (!scrollEl) scrollEl = document.documentElement;
        if (total <= 1) return;
        const fraction = idx / (total - 1);
        scrollEl.scrollTop = fraction * (scrollEl.scrollHeight - scrollEl.clientHeight);
    }""", {"idx": idx, "total": total})


def _encontrar_slot_da_guia(page, numero_guia):
    return page.evaluate("""(numero_guia) => {
        const rows = document.querySelectorAll('tr[id^="Grid1ContainerRow_"]');
        for (const tr of rows) {
            const cells = tr.querySelectorAll('td');
            const guia = (cells[4]?.innerText || '').trim();
            if (guia === numero_guia) {
                return tr.getAttribute('data-gxrow');
            }
        }
        return null;
    }""", numero_guia)


def _micro_ajuste_scroll(page, numero_guia, passos=20, incremento=100):
    """Faz scroll incremental pequeno apos o scroll proporcional para compensar
    imprecisoes do DOM virtual do GeneXus."""
    for passo in range(1, passos + 1):
        page.evaluate(f"""() => {{
            const el = [...document.querySelectorAll('div')].find(
                e => e.scrollHeight > e.clientHeight && e.scrollHeight > 3000
            );
            if (el) el.scrollBy(0, {passo * incremento});
        }}""")
        page.wait_for_timeout(50)
        row_num = _encontrar_slot_da_guia(page, numero_guia)
        if row_num:
            return row_num
    return None


def _restaurar_grid_otimus(page, codigo_fatura, log_callback=None):
    """Apos uma falha de edicao, tenta voltar a grid do Otimus.
    Retorna True se conseguiu restaurar, False caso precise de relogin."""
    def _log(msg):
        if log_callback:
            log_callback(msg)
        print(msg, flush=True)

    try:
        voltar_btn = page.query_selector("input[name=BUTTON26]")
        if voltar_btn:
            page.evaluate("(el) => el.click()", voltar_btn)
            page.wait_for_selector('[id^="vEDITARGRID_"]', timeout=10000)
            _log("  Grid Otimus restaurada (clicou Voltar)")
            return True
    except Exception:
        pass

    try:
        cancel_btn = page.query_selector("input[name=BUTTON_CANCEL]")
        if cancel_btn:
            page.evaluate("(el) => el.click()", cancel_btn)
            page.wait_for_selector('[id^="vEDITARGRID_"]', timeout=10000)
            _log("  Grid Otimus restaurada (clicou Cancelar)")
            return True
    except Exception:
        pass

    return False


def _extrair_procedimento(row_text):
    if not row_text:
        return ""
    match = re.search(r'(?:Faturar|Guia)\s+(.+?)(?:\s{2,}|$)', row_text)
    if match:
        return match.group(1).strip()
    match = re.search(r'\d{2}:\d{2}\s+(.+?)(?:\s{2,}|$)', row_text)
    if match:
        return match.group(1).strip()
    CONHECIDOS = ["MAMOGRAFIA", "TOMOGRAFIA", "RESSONANCIA", "ULTRASSON",
                   "RAIO-X", "RX", "ARTICULACAO", "ELETROCARDIOGRAMA",
                   "DENSITOMETRIA", "DOPPLER", "ECO", "HOLTER"]
    partes = re.split(r'\s{2,}', row_text)
    for p in partes:
        p = p.strip()
        if len(p) > 5 and any(k in p.upper() for k in CONHECIDOS):
            return p
    partes = row_text.split()
    for i, p in enumerate(partes):
        if p.upper() in CONHECIDOS:
            return " ".join(partes[i:i+3])
    return row_text[:80].strip()


def listar_faturas(otimus_user, otimus_pass, unidade="palhoca", log_callback=None, headless=True):
    def log(msg):
        if log_callback:
            log_callback(msg)
        print(msg, flush=True)

    log("Otimus: Abrindo navegador e acessando sistema...")
    p = sync_playwright().start()
    browser = lancar_browser(p, headless=headless)
    context = criar_contexto(browser)
    otimus = context.new_page()
    otimus.on("dialog", lambda d: d.accept())

    try:
        _logar_otimus(otimus, otimus_user, otimus_pass, _otimus_url(unidade))

        otimus.evaluate("""() => {
            const el = document.querySelector('a[href*="wwfaturamento"]');
            if (el) { el.click(); return; }
            const allLinks = document.querySelectorAll('a');
            for (const a of allLinks) {
                if (a.textContent.trim() === 'Faturamento') {
                    a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                    return;
                }
            }
        }()""")
        otimus.wait_for_timeout(2000)
        otimus.evaluate("""() => {
            const el = document.querySelector('a[href*="wwfaturamento"]');
            if (el) el.click();
        }()""")
        otimus.wait_for_selector("a:has-text('Visualizar Fatura')", timeout=20000)

        links = otimus.query_selector_all("a:has-text('Visualizar Fatura')")
        faturas = []

        if not links:
            log("Nenhuma fatura encontrada!")
            return {"success": False, "error": "Nenhuma fatura disponível"}

        log(f"Encontradas {len(links)} faturas. Extraindo dados...")
        for link in links:
            codigo = link.evaluate("""el => {
                const tr = el.closest('tr');
                if (!tr) return null;
                const span = tr.querySelector('span[id^="span_CAPADELOTEID"]');
                return span ? span.textContent.trim() : null;
            }""")
            if codigo and codigo.strip():
                convenio = link.evaluate("""el => {
                    const tr = el.closest('tr');
                    if (!tr) return '';
                    const span = tr.querySelector('span[id^="span_CATEGORIACATNOME_"]');
                    return span ? span.textContent.trim() : '';
                }""")
                nome = link.evaluate("""el => {
                    const tr = el.closest('tr');
                    if (!tr) return '';
                    const span = tr.querySelector('span[id^="span_CAPADELOTEFATURA_"]');
                    return span ? span.textContent.trim() : '';
                }""")
                faturas.append({"codigo": codigo.strip(), "nome": (nome or "").strip(), "convenio": (convenio or "").strip()})
                log(f"  Fatura [{codigo.strip()}] - {convenio.strip() if convenio else '(sem convênio)'}")

        log(f"Total de faturas disponíveis: {len(faturas)}")
        return {"success": True, "faturas": faturas}

    except Exception as e:
        log(f"Erro ao listar faturas: {e}")
        return {"success": False, "error": str(e)}

    finally:
        browser.close()
        p.stop()
        log("Otimus: Navegador fechado.")


def run_automation(
    unidade,
    codigo_fatura,
    sisreg_user,
    sisreg_pass,
    codigo_ups,
    otimus_user,
    otimus_pass,
    log_callback=None,
    headless=True,
    suspend_event=None,
    abort_event=None,
    guia_inicio=1,
    guia_fim=None,
    range_callback=None,
):
    def log(msg):
        if log_callback:
            log_callback(msg)
        print(msg, flush=True)

    sucessos = 0
    erros = 0
    guias_futuras = 0
    falhas = {}

    p = sync_playwright().start()
    browser = lancar_browser(p, headless=headless)
    context = criar_contexto(browser)

    log(f"=== AUTOMAÇÃO SISREG - Unidade: {unidade} ===")
    log(f"Fatura: {codigo_fatura} | UPS: {codigo_ups}")
    log("")

    def sisreg_logado(page):
        try:
            return "cons_agendas" in page.url
        except Exception:
            return False

    def _sisreg_tem_erro_login(page):
        try:
            texto = page.inner_text("body")
            erros = ["sessao", "invalida", "finalizada", "logon novamente",
                     "operador invalido", "operador nao cadastrado",
                     "senha invalidos", "usuario invalido",
                     "requested url was rejected", "support id",
                     "was rejected"]
            for padrao in erros:
                if padrao in texto.lower():
                    linhas = [l.strip() for l in texto.split('\n') if padrao in l.lower()]
                    motivo = linhas[0][:120] if linhas else padrao
                    return True, motivo
            return False, ""
        except Exception:
            return False, ""

    def _logar_sisreg(page):
        page.goto("https://sisregiii.saude.gov.br/cgi-bin/index?logout=1")
        resolver_tspd(page, context)
        page.wait_for_selector("input#usuario", timeout=15000)
        page.fill("input#usuario", sisreg_user)
        page.wait_for_selector("input#senha", timeout=10000)
        page.fill("input#senha", sisreg_pass)
        page.click("input[name=entrar]")
        resolver_tspd(page, context)
        tem_erro, motivo = _sisreg_tem_erro_login(page)
        if tem_erro:
            raise RuntimeError(f"Falha no login SISREG: {motivo}")

    def relogin_sisreg(page):
        _logar_sisreg(page)
        page.goto("https://sisregiii.saude.gov.br/cgi-bin/cons_agendas")
        page.wait_for_selector("input[name=cns_paciente]", timeout=15000)
        log("  SISREG: Re-logado")

    def otimus_logado(page):
        try:
            return len(_encontrar_edit_buttons(page)) > 0
        except Exception:
            return False

    def relogin_otimus(page, cod_desejado):
        _logar_otimus(page, otimus_user, otimus_pass, _otimus_url(unidade))

        if not _navegar_para_faturamento(page, cod_desejado, log_callback=log_callback):
            log(f"  ERRO relogin: não foi possível re-selecionar fatura {cod_desejado}")
            raise RuntimeError(f"Falha ao re-selecionar fatura {cod_desejado} no relogin")
        log(f"  Otimus: Re-logado e fatura {cod_desejado} re-selecionada")

        # Reaplicar "mostrar todas" e clicar Pesquisar
        try:
            melhor_opcao = page.evaluate("""() => {
                const select = document.querySelector('#vQTDREGISTROS');
                if (!select) return '0';
                const options = Array.from(select.options);
                // 1. Preferir opção "Todas" (value "0"/"-1" ou texto que contenha "Todas"/"All")
                const todas = options.find(o =>
                    o.value === '0' || o.value === '-1' ||
                    o.text.toLowerCase().includes('toda') ||
                    o.text.toLowerCase().includes('todas') ||
                    o.text.toLowerCase().includes('all')
                );
                if (todas) return todas.value;
                // 2. Fallback: maior valor numérico
                const nums = options.map(o => parseInt(o.value)).filter(n => !isNaN(n) && n > 0);
                if (nums.length > 0) return String(Math.max(...nums));
                // 3. Último recurso: última opção
                return options[options.length - 1].value;
            }""")
            page.select_option("#vQTDREGISTROS", melhor_opcao)
            page.wait_for_timeout(500)
            pesq_btn = page.query_selector('input[value="Pesquisar"]')
            if pesq_btn:
                page.evaluate("(el) => el.click()", pesq_btn)
                page.wait_for_function("""() => {
                    const container = [...document.querySelectorAll('div')].find(
                        e => e.scrollHeight > e.clientHeight && e.scrollHeight > 500
                    );
                    if (!container) return false;
                    const ratio = container.scrollHeight / container.clientHeight;
                    return ratio > 1.5 && document.querySelectorAll('tr[id^="Grid1ContainerRow_"]').length > 0;
                }""", timeout=20000)
                page.wait_for_timeout(2000)
        except Exception as e:
            log(f"  AVISO relogin: erro ao reaplicar 'mostrar todas': {e}")

    # ============================================================
    # 1. SISREG - LOGIN
    # ============================================================
    log("--- [1/4] SISREG: Fazendo login ---")
    sisreg = context.new_page()
    sisreg.on("dialog", lambda d: d.accept())
    try:
        _logar_sisreg(sisreg)
        sisreg.goto("https://sisregiii.saude.gov.br/cgi-bin/cons_agendas")
        sisreg.wait_for_selector("input[name=cns_paciente]", timeout=15000)
        log("SISREG: Logado com sucesso")
    except Exception as e:
        log(f"ERRO NO LOGIN SISREG: {e}")
        browser.close()
        p.stop()
        return {"success": False, "error": f"Falha no login SISREG: {e}"}

    # ============================================================
    # 2. OTIMUS - LOGIN E SELEÇÃO DE FATURA
    # ============================================================
    log(f"\n--- [2/4] Otimus: Fazendo login e selecionando fatura {codigo_fatura} ---")
    otimus = context.new_page()
    otimus.on("dialog", lambda d: d.accept())
    try:
        _logar_otimus(otimus, otimus_user, otimus_pass, _otimus_url(unidade))

        if not _navegar_para_faturamento(otimus, codigo_fatura, log_callback=log_callback):
            msg = f"Fatura {codigo_fatura} não encontrada no Otimus após tentativas!"
            log(f"ERRO: {msg}")
            browser.close()
            p.stop()
            return {"success": False, "error": msg}

        log(f"Otimus: Fatura {codigo_fatura} selecionada")

        # Exibir todas as guias no grid — priorizar "Todas", senão maior valor numérico
        melhor_opcao = otimus.evaluate("""() => {
            const select = document.querySelector('#vQTDREGISTROS');
            if (!select) return '0';
            const options = Array.from(select.options);
            // 1. Preferir opção "Todas" (value "0"/"-1" ou texto que contenha "Todas"/"All")
            const todas = options.find(o =>
                o.value === '0' || o.value === '-1' ||
                o.text.toLowerCase().includes('toda') ||
                o.text.toLowerCase().includes('todas') ||
                o.text.toLowerCase().includes('all')
            );
            if (todas) return todas.value;
            // 2. Fallback: maior valor numérico
            const nums = options.map(o => parseInt(o.value)).filter(n => !isNaN(n) && n > 0);
            if (nums.length > 0) return String(Math.max(...nums));
            // 3. Último recurso: última opção
            return options[options.length - 1].value;
        }""")
        otimus.select_option("#vQTDREGISTROS", melhor_opcao)
        otimus.wait_for_timeout(500)

        # Clicar Pesquisar para recarregar grid com todas as guias
        pesq_btn = otimus.query_selector('input[value="Pesquisar"]')
        if pesq_btn:
            otimus.evaluate("(el) => el.click()", pesq_btn)
            otimus.wait_for_function("""() => {
                const container = [...document.querySelectorAll('div')].find(
                    e => e.scrollHeight > e.clientHeight && e.scrollHeight > 500
                );
                if (!container) return false;
                const ratio = container.scrollHeight / container.clientHeight;
                return ratio > 1.5 && document.querySelectorAll('tr[id^="Grid1ContainerRow_"]').length > 0;
            }""", timeout=20000)
            otimus.wait_for_timeout(2000)
        else:
            log("  AVISO: Botao Pesquisar nao encontrado, continuando sem recarregar grid")
    except Exception as e:
        log(f"ERRO NO LOGIN/SELEÇÃO OTIMUS: {e}")
        browser.close()
        p.stop()
        return {"success": False, "error": f"Falha no Otimus: {e}"}

    # ============================================================
    # 3. PROCESSAR CADA GUIA
    # ============================================================
    log("\n--- [3/4] Processando guias ---")

    # Coletar guias via scroll programático (contorna virtual DOM que só renderiza ~101 linhas)
    guias = _coletar_guias(otimus)
    total_guias = len(guias)
    log(f"Guias encontradas na fatura: {total_guias}")

    # Se tem range_callback, aguardar usuário definir intervalo
    if range_callback:
        guia_inicio, guia_fim = range_callback()
        if guia_fim == 0:  # abortou durante aguarda
            log("🛑 Execução abortada durante definição de intervalo!")
            browser.close()
            p.stop()
            return {
                "success": False,
                "abortado": True,
                "unidade": unidade,
                "codigo_fatura": codigo_fatura,
                "total_guias": total_guias,
                "sucessos": 0,
                "erros": 0,
                "falhas": {},
            }

    # Aplicar intervalo de guias
    if guia_fim is None or guia_fim > total_guias:
        guia_fim = total_guias
    guia_inicio = max(1, guia_inicio)
    if guia_inicio > 1 or guia_fim < total_guias:
        guias = guias[guia_inicio - 1:guia_fim]
        log(f"Processando guias {guia_inicio} a {guia_fim} (de {total_guias})")

    for idx, guia in enumerate(guias):
        # Verificar abortamento
        if abort_event is not None and abort_event.is_set():
            log("🛑 Execução abortada pelo usuário!")
            break

        # Verificar suspensão
        if suspend_event is not None:
            while suspend_event.is_set():
                if abort_event is not None and abort_event.is_set():
                    log("🛑 Execução abortada pelo usuário!")
                    break
                log("⏸️ Execução suspensa. Aguardando retomada...")
                time.sleep(3)
            if abort_event is not None and abort_event.is_set():
                break
            if idx > 0:
                log("▶️ Execução retomada!")

        i = idx + 1
        numero_guia_alvo = guia["guia"]
        log(f"\n--- GUIA {i}/{total_guias} (guia #{numero_guia_alvo}) ---")

        # ----- VERIFICAR SESSÃO OTIMUS -----
        if not otimus_logado(otimus):
            log(f"  GUIA {i}: Sessão Otimus expirada. Re-logando...")
            relogin_otimus(otimus, codigo_fatura)
            guias = _coletar_guias(otimus)
            total_guias = len(guias)
            if idx >= total_guias:
                log(f"  ERRO: Guia {i} nao encontrada apos relogin")
                erros += 1
                continue
            numero_guia_alvo = guias[idx]["guia"]

        # ----- EXTRAIR PROCEDIMENTO DA GRID -----
        procedimento_otimus = guia.get("servico", "")
        if procedimento_otimus:
            log(f"  Procedimento Otimus: {procedimento_otimus}")

        # ----- SCROLL ATÉ A LINHA E CLICAR EDITAR -----
        tem_vMATRICULAGUIA = False
        try:
            _scroll_para_linha(otimus, idx, total_guias)
            otimus.wait_for_timeout(200)
            row_num = _encontrar_slot_da_guia(otimus, numero_guia_alvo)
            if not row_num:
                row_num = _micro_ajuste_scroll(otimus, numero_guia_alvo)
            if not row_num:
                raise Exception(f"Guia {numero_guia_alvo} nao encontrada no DOM apos scroll")
            for _ in range(30):
                if otimus.query_selector(f'[id="vEDITARGRID_{row_num}"]'):
                    break
                otimus.wait_for_timeout(100)
            edit_btn = otimus.query_selector(f'[id="vEDITARGRID_{row_num}"]')
            if not edit_btn:
                raise Exception(f"Botao vEDITARGRID_{row_num} nao encontrado apos scroll")
            edit_btn.evaluate("(el) => { el.scrollIntoViewIfNeeded(); el.click(); el.dispatchEvent(new Event('click', { bubbles: true })) }")
            otimus.wait_for_selector("#vMATRICULAGUIA", timeout=15000)
            tem_vMATRICULAGUIA = True
        except Exception as e:
            erro_edicao = str(e)
            try:
                otimus.wait_for_timeout(500)
                _scroll_para_linha(otimus, idx, total_guias)
                otimus.wait_for_timeout(200)
                row_num = _encontrar_slot_da_guia(otimus, numero_guia_alvo)
                if not row_num:
                    row_num = _micro_ajuste_scroll(otimus, numero_guia_alvo)
                if not row_num:
                    raise Exception(f"Guia {numero_guia_alvo} nao encontrada na segunda tentativa")
                for _ in range(30):
                    if otimus.query_selector(f'[id="vEDITARGRID_{row_num}"]'):
                        break
                    otimus.wait_for_timeout(100)
                edit_btn = otimus.query_selector(f'[id="vEDITARGRID_{row_num}"]')
                if edit_btn:
                    edit_btn.evaluate("(el) => { el.scrollIntoViewIfNeeded(); el.click(); el.dispatchEvent(new Event('click', { bubbles: true })) }")
                    otimus.wait_for_selector("#vMATRICULAGUIA", timeout=15000)
                    tem_vMATRICULAGUIA = True
                else:
                    raise Exception("Botao nao encontrado na segunda tentativa")
            except Exception as e2:
                log(f"  ERRO: {erro_edicao}")
                erros += 1
                # Restaurar grid Otimus antes de prosseguir
                try:
                    restaurado = _restaurar_grid_otimus(otimus, codigo_fatura, log_callback=log_callback)
                    if not restaurado:
                        raise Exception("Falha ao restaurar via botoes")
                except Exception:
                    log(f"  AVISO: Re-logando Otimus para restaurar grid...")
                    relogin_otimus(otimus, codigo_fatura)
                    guias = _coletar_guias(otimus)
                    total_guias = len(guias)
                    if idx < total_guias:
                        numero_guia_alvo = guias[idx]["guia"]
                continue

        # ----- EXTRAIR MATRÍCULA -----
        matricula = ""
        try:
            mat_input = otimus.query_selector("#vMATRICULAGUIA")
            if mat_input:
                matricula = mat_input.get_attribute("value") or ""
            if not matricula:
                log(f"  ERRO: Matricula nao encontrada apos clicar editar guia {i}")
                erros += 1
                continue
            log(f"  CNS (matricula): {matricula}")
        except Exception as e:
            log(f"  ERRO: Falha ao extrair campo matricula: {e}")
            erros += 1
            continue

        # ----- EXTRAIR NÚMERO DA GUIA -----
        numero_guia = ""
        try:
            guia_input = otimus.query_selector("#vGUIAPRINCIPALRESUMO")
            if guia_input:
                numero_guia = guia_input.get_attribute("value") or ""
            if not numero_guia:
                log(f"  ERRO: Numero da guia nao encontrado apos editar guia {i}")
                erros += 1
                continue
            log(f"  Número guia: {numero_guia}")
        except Exception as e:
            log(f"  ERRO: Falha ao extrair numero da guia: {e}")
            erros += 1
            continue

        # ----- CLICAR VOLTAR -----
        try:
            voltar_btn = otimus.query_selector("input[name=BUTTON26]")
            if voltar_btn:
                otimus.evaluate("(el) => el.click()", voltar_btn)
                otimus.wait_for_selector('[id^="vEDITARGRID_"]', timeout=15000)
            else:
                log(f"  ERRO: Botao VOLTAR nao encontrado apos editar guia {i}")
                erros += 1
                continue
        except Exception as e:
            log(f"  ERRO: Falha ao clicar em VOLTAR: {e}")
            erros += 1
            continue

        # ----- VERIFICAR SESSÃO SISREG -----
        if not sisreg_logado(sisreg):
            log(f"  GUIA {i}: Sessão SISREG expirada. Re-logando...")
            relogin_sisreg(sisreg)

        # ----- CONSULTAR NO SISREG -----
        try:
            for tentativa_sisreg in range(2):
                try:
                    sisreg.goto("https://sisregiii.saude.gov.br/cgi-bin/cons_agendas", wait_until="domcontentloaded", timeout=20000)
                    break
                except Exception:
                    if tentativa_sisreg == 0:
                        log(f"  GUIA {i}: SISREG lento, re-logando...")
                        relogin_sisreg(sisreg)
                    else:
                        raise
            sisreg.wait_for_selector("input[name=cns_paciente], input#usuario", timeout=15000)
            if sisreg.query_selector("input#usuario"):
                log(f"  GUIA {i}: Sessão SISREG expirada, re-logando...")
                relogin_sisreg(sisreg)

            sisreg.fill("input[name=cns_paciente]", matricula)
            sleep(sisreg, 50, 150)
            sisreg.select_option("select[name=ups]", codigo_ups)
            sleep(sisreg, 50, 150)
            sisreg.select_option("select[name=cmbTipoOperacao]", "Confirma")
            sleep(sisreg, 50, 150)

            chk = sisreg.query_selector("input[name=chkboxExibirProcedimentos]")
            if chk and not chk.is_checked():
                sisreg.click("input[name=chkboxExibirProcedimentos]")
                sleep(sisreg, 50, 150)

            ok_btn = sisreg.query_selector("input[name=btnOK]")
            if ok_btn:
                sisreg.click("input[name=btnOK]")
                try:
                    sisreg.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                sisreg.wait_for_timeout(500)
            else:
                log(f"  ERRO: Botao OK nao encontrado no SISREG para CNS {matricula}")
                erros += 1
                continue

            # ----- VERIFICAR RESULTADOS -----
            body_text = sisreg.inner_text("body")
            if "Nenhum" in body_text or "não encontrado" in body_text.lower():
                motivo = f"SISREG não retornou resultados para CNS {matricula}"
                log(f"  ERRO: {motivo}")
                falhas[numero_guia] = motivo
                erros += 1

            elif "Procedimento(s)" in body_text:
                hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                solic_tables = sisreg.query_selector_all('[id^="tblConfirmacao"]')
                solicitacoes_preencher = []

                for tbl in solic_tables:
                    tbl_id = tbl.get_attribute("id") or ""
                    idx_match = re.search(r'tblConfirmacao(\d+)', tbl_id)
                    if not idx_match:
                        continue
                    idx = int(idx_match.group(1))
                    texto = tbl.inner_text()

                    date_match = re.search(r"Data/Hora:[^\n]*\n?\s*(\d{2})/(\d{2})/(\d{4})", texto)
                    if not date_match:
                        continue
                    data_sisreg = datetime(int(date_match.group(3)), int(date_match.group(2)), int(date_match.group(1)))
                    data_str = f"{date_match.group(1)}/{date_match.group(2)}/{date_match.group(3)}"

                    if data_sisreg > hoje:
                        log(f"  GUIA {i}: Agendamento futuro ({data_str}), pulando")
                        guias_futuras += 1
                        continue

                    chave_input = sisreg.query_selector(f'input[name="Chave{idx}"]')
                    if not chave_input or chave_input.get_attribute("disabled") is not None:
                        log(f"  GUIA {i}: Chave{idx} não disponível, pulando")
                        continue

                    solicitacoes_preencher.append({'idx': idx, 'data_str': data_str})

                if not solicitacoes_preencher:
                    if not solic_tables:
                        motivo = "Nenhuma solicitação encontrada na agenda SISREG"
                        log(f"  ERRO: {motivo}")
                        falhas[numero_guia] = motivo
                        erros += 1
                    else:
                        log(f"  GUIA {i}: Nenhuma solicitação com Chave disponível, pulando")
                else:
                    for sol in solicitacoes_preencher:
                        try:
                            sisreg.fill(f'input[name="Chave{sol["idx"]}"]', numero_guia)
                            sleep(sisreg, 50, 150)
                        except Exception:
                            log(f"  ERRO: Falha ao preencher Chave{sol['idx']}")

                    try:
                        confirm_btn = sisreg.query_selector("input[name=btnConfirmar]")
                        if confirm_btn:
                            sisreg.click("input[name=btnConfirmar]")
                            try:
                                sisreg.wait_for_load_state("networkidle", timeout=15000)
                            except Exception:
                                pass
                            sisreg.wait_for_timeout(500)
                            sucessos += 1
                            log(f">>> GUIA {i}: SUCESSO - Guia {numero_guia} registrada em {len(solicitacoes_preencher)} solicitação(ões) <<<")
                        else:
                            log(f"  ERRO: Botão Confirmar não encontrado")
                            falhas[numero_guia] = "Botão Confirmar não encontrado"
                            erros += 1
                    except Exception:
                        log(f"  ERRO: Falha ao confirmar agenda no SISREG (guia {numero_guia})")
                        falhas[numero_guia] = "Falha ao confirmar agenda"
                        erros += 1

            elif matricula in body_text:
                sucessos += 1
                log(f">>> GUIA {i}: SUCESSO - CNS encontrado nos resultados! <<<")
            else:
                motivo = f"Retorno SISREG não reconhecido para CNS {matricula}"
                log(f"  ERRO: {motivo}")
                log(f"  DEBUG body_text[:500]: {body_text[:500]}")
                falhas[numero_guia] = motivo
                erros += 1

        except Exception as e:
            motivo = f"Exceção no bloco SISREG: {e}"
            log(f"  ERRO: {motivo}")
            falhas[numero_guia] = motivo
            erros += 1

    # ============================================================
    # 4. RESUMO
    # ============================================================
    abortado = abort_event is not None and abort_event.is_set()

    log(f"\n{'='*50}")
    log(f"RESUMO DO PROCESSAMENTO")
    log(f"{'='*50}")
    log(f"Unidade: {unidade}")
    log(f"Fatura: {codigo_fatura}")
    log(f"Total de guias: {total_guias}")
    log(f"Sucessos: {sucessos}")
    log(f"Guias com data futura (não confirmadas): {guias_futuras}")
    log(f"Erros: {erros}")
    if abortado:
        log(f"Status: ABORTADO pelo usuário")
    if falhas:
        log(f"\nFalhas por guia:")
        for guia, motivo in falhas.items():
            log(f"  Guia {guia}: {motivo}")
    log(f"{'='*50}")
    if abortado:
        log("Processo abortado!")
    else:
        log("Processo concluído!")

    browser.close()
    p.stop()

    return {
        "success": not abortado,
        "abortado": abortado,
        "unidade": unidade,
        "codigo_fatura": codigo_fatura,
        "total_guias": total_guias,
        "sucessos": sucessos,
        "erros": erros,
        "falhas": falhas,
    }
