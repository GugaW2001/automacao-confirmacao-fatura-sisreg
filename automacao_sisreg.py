from playwright.sync_api import sync_playwright
import time
import sys
import re
from datetime import datetime
from app.browser_utils import lancar_browser, criar_contexto, sleep, resolver_tspd

# ============================================================
# FUNÇÕES AUXILIARES - VERIFICAÇÃO DE SESSÃO
# ============================================================
def sisreg_logado():
    try:
        return "cons_agendas" in sisreg.url
    except Exception:
        return False

def _tem_erro_login():
    try:
        texto = sisreg.inner_text("body")
        erros = ["sessao", "invalida", "finalizada", "logon novamente",
                 "operador invalido", "operador nao cadastrado",
                 "senha invalidos", "usuario invalido",
                 "requested url was rejected", "support id",
                 "was rejected"]
        for padrao in erros:
            if padrao in texto.lower():
                linhas = [l.strip() for l in texto.split('\n') if padrao in l.lower()]
                return linhas[0][:120] if linhas else padrao
        return ""
    except Exception:
        return ""


def relogin_sisreg():
    sisreg.goto("https://sisregiii.saude.gov.br/cgi-bin/index?logout=1")
    sisreg.wait_for_selector("input#usuario", timeout=15000)
    sisreg.fill("input#usuario", usuario)
    sisreg.fill("input#senha", senha)
    sisreg.click("input[name=entrar]")
    sisreg.wait_for_load_state("domcontentloaded")
    erro = _tem_erro_login()
    if erro:
        print(f"  ERRO LOGIN SISREG: {erro}")
        sys.stdout.flush()
        raise RuntimeError(f"Falha no login SISREG: {erro}")
    sisreg.goto("https://sisregiii.saude.gov.br/cgi-bin/cons_agendas")
    sisreg.wait_for_selector("input[name=cns_paciente]", timeout=15000)
    print("  SISREG: Re-logado")
    sys.stdout.flush()

def otimus_logado():
    try:
        return otimus.query_selector('[id^="vEDITARGRID_"]') is not None
    except Exception:
        return False

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
        const MAX_ATTEMPTS = 5;
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
                if (attempt >= MAX_ATTEMPTS || newCount >= 5000) {
                    resolve(data);
                    return;
                }
                scrollEl.scrollTop = scrollEl.scrollTop + scrollEl.clientHeight * 0.8;
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
        page.wait_for_timeout(100)
        row_num = _encontrar_slot_da_guia(page, numero_guia)
        if row_num:
            return row_num
    return None


def _restaurar_grid_otimus():
    """Apos uma falha de edicao, tenta voltar a grid do Otimus.
    Retorna True se conseguiu restaurar, False caso precise de relogin."""
    try:
        voltar_btn = otimus.query_selector("input[name=BUTTON26]")
        if voltar_btn:
            otimus.evaluate("(el) => el.click()", voltar_btn)
            otimus.wait_for_selector('[id^="vEDITARGRID_"]', timeout=10000)
            print("  Grid Otimus restaurada (clicou Voltar)")
            sys.stdout.flush()
            return True
    except Exception:
        pass

    try:
        cancel_btn = otimus.query_selector("input[name=BUTTON_CANCEL]")
        if cancel_btn:
            otimus.evaluate("(el) => el.click()", cancel_btn)
            otimus.wait_for_selector('[id^="vEDITARGRID_"]', timeout=10000)
            print("  Grid Otimus restaurada (clicou Cancelar)")
            sys.stdout.flush()
            return True
    except Exception:
        pass

    return False


def relogin_otimus():
    otimus.goto("https://medimagempalhoca.otimusclinic.com/medimagempalhoca/servlet/app.entrar")
    otimus.fill("input#vLOGIN", "gustavo.weingartner")
    otimus.fill("input#vSENHA", "gustavo1@")
    otimus.click("input[name=BUTTON1]")
    otimus.wait_for_selector("text=Faturamento", timeout=20000)

    otimus.click("text=Faturamento")
    otimus.wait_for_timeout(1000)
    otimus.click('a[href*="wwfaturamento"]')
    otimus.wait_for_selector("a:has-text('Visualizar Fatura')", timeout=20000)

    links = otimus.query_selector_all("a:has-text('Visualizar Fatura')")
    for link in links:
        codigo = link.evaluate("""el => {
            const tr = el.closest('tr');
            if (!tr) return null;
            const span = tr.querySelector('span[id^="span_CAPADELOTEID"]');
            return span ? span.textContent.trim() : null;
        }""")
        if codigo and codigo.strip() == codigo_desejado:
            otimus.evaluate("(el) => el.click()", link)
            break
    otimus.wait_for_selector('[id^="vEDITARGRID_"]', timeout=15000)
    print(f"  Otimus: Re-logado e fatura {codigo_desejado} re-selecionada")
    sys.stdout.flush()

    # Reaplicar "mostrar todas" e clicar Pesquisar
    try:
        ultima_opcao = otimus.evaluate("""() => {
            const select = document.querySelector('#vQTDREGISTROS');
            const options = select ? Array.from(select.options) : [];
            return options.length ? options[options.length - 1].value : '0';
        }""")
        otimus.select_option("#vQTDREGISTROS", ultima_opcao)
        otimus.wait_for_timeout(1000)
        pesq_btn = otimus.query_selector('input[value="Pesquisar"]')
        if pesq_btn:
            otimus.evaluate("(el) => el.click()", pesq_btn)
            otimus.wait_for_selector('[id^="vEDITARGRID_"]', timeout=15000)
    except Exception as e:
        print(f"  AVISO relogin: erro ao reaplicar 'mostrar todas': {e}")
        sys.stdout.flush()

p = sync_playwright().start()
browser = lancar_browser(p, headless=False)
context = criar_contexto(browser)

# Escolha da unidade
print("Selecione a unidade:")
print("  [1] Palhoça")
print("  [2] São José")
opcao = input("Digite 1 ou 2: ").strip()

if opcao == "1":
    usuario, senha = "MED_LEIDE", "Med1115@"
    codigo_ups = "4090276"
elif opcao == "2":
    usuario, senha = "MED.LEIDE", "Med@1115"
    codigo_ups = "9385835"
else:
    print("Opção inválida! Encerrando.")
    sys.stdout.flush()
    browser.close()
    p.stop()
    sys.exit(1)

# ============================================================
# 1. SISREG - LOGIN
# ============================================================
sisreg = context.new_page()
sisreg.on("dialog", lambda d: d.accept())
sisreg.goto("https://sisregiii.saude.gov.br/cgi-bin/index?logout=1")
resolver_tspd(sisreg, context)
sisreg.fill("input#usuario", usuario)
sisreg.fill("input#senha", senha)
sisreg.click("input[name=entrar]")
resolver_tspd(sisreg, context)
erro = _tem_erro_login()
if erro:
    print(f"ERRO NO LOGIN SISREG: {erro}")
    sys.stdout.flush()
    browser.close()
    p.stop()
    sys.exit(1)
sisreg.goto("https://sisregiii.saude.gov.br/cgi-bin/cons_agendas")
sisreg.wait_for_selector("input[name=cns_paciente]", timeout=15000)
print("SISREG: Logado")
sys.stdout.flush()

# ============================================================
# 2. OTIMUS - LOGIN E SELEÇÃO DE FATURA
# ============================================================
otimus = context.new_page()
otimus.on("dialog", lambda d: d.accept())
otimus.goto("https://medimagempalhoca.otimusclinic.com/medimagempalhoca/servlet/app.entrar")
otimus.fill("input#vLOGIN", "gustavo.weingartner")
otimus.fill("input#vSENHA", "gustavo1@")
otimus.click("input[name=BUTTON1]")
otimus.wait_for_selector("text=Faturamento", timeout=20000)

otimus.click("text=Faturamento")
otimus.wait_for_timeout(1000)
otimus.click('a[href*="wwfaturamento"]')
otimus.wait_for_selector('[id^="vEDITARGRID_"], a:has-text("Visualizar")', timeout=20000)

# Coletar faturas disponíveis
links = otimus.query_selector_all("a:has-text('Visualizar Fatura')")
faturas = []
for link in links:
    codigo = link.evaluate("""el => {
        const tr = el.closest('tr');
        if (!tr) return null;
        const span = tr.querySelector('span[id^="span_CAPADELOTEID"]');
        return span ? span.textContent.trim() : null;
    }""")
    if codigo and codigo.strip():
        texto = link.evaluate("el => el.closest('tr')?.innerText?.trim() || ''")
        faturas.append((codigo.strip(), link, texto))

if not faturas:
    print("Nenhuma fatura encontrada na página!")
    sys.stdout.flush()
    browser.close()
    p.stop()
    sys.exit(1)

# Exibir faturas
print("\n=== FATURAS DISPONÍVEIS ===")
for cod, _, txt in faturas:
    desc = txt[:120].strip().replace('\n', ' | ')
    print(f"  [{cod}] {desc}")
print()

sys.stdout.flush()

# Solicitar código ao usuário
codigo_desejado = input("Digite o código CAPADELOTEID da fatura: ").strip()

# Encontrar e clicar
link_escolhido = None
for cod, link, _ in faturas:
    if cod == codigo_desejado:
        link_escolhido = link
        break

if not link_escolhido:
    print(f"Código {codigo_desejado} não encontrado!")
    sys.stdout.flush()
    browser.close()
    p.stop()
    sys.exit(1)

otimus.evaluate("(el) => el.click()", link_escolhido)
otimus.wait_for_selector('[id^="vEDITARGRID_"]', timeout=15000)
print(f"Otimus: Fatura {codigo_desejado} selecionada")
sys.stdout.flush()

# Exibir todas as guias no grid
ultima_opcao = otimus.evaluate("""() => {
    const select = document.querySelector('#vQTDREGISTROS');
    const options = select ? Array.from(select.options) : [];
    return options.length ? options[options.length - 1].value : '0';
}""")
otimus.select_option("#vQTDREGISTROS", ultima_opcao)
otimus.wait_for_timeout(1000)

# Clicar Pesquisar para recarregar grid com todas as guias
pesq_btn = otimus.query_selector('input[value="Pesquisar"]')
if pesq_btn:
    otimus.evaluate("(el) => el.click()", pesq_btn)
    otimus.wait_for_function("""() => {
        const rows = document.querySelectorAll('tr[id^="Grid1ContainerRow_"]');
        return rows.length > 0;
    }""", timeout=15000)
    otimus.wait_for_timeout(1000)
else:
    print("  AVISO: Botao Pesquisar nao encontrado, continuando sem recarregar grid")
    sys.stdout.flush()

# ============================================================
# 3. PROCESSAR CADA GUIA
# ============================================================
sucessos = 0
erros = 0
guias_futuras = 0
falhas = {}  # numero_guia -> motivo_erro

print("\n--- INICIANDO PROCESSAMENTO ---")
sys.stdout.flush()

# Coletar guias via scroll programático (contorna virtual DOM que só renderiza ~101 linhas)
guias = _coletar_guias(otimus)
total_guias = len(guias)
print(f"Guias encontradas na fatura: {total_guias}")
sys.stdout.flush()

for idx, guia in enumerate(guias):
    i = idx + 1
    numero_guia_alvo = guia["guia"]
    print(f"\n--- GUIA {i}/{total_guias} (guia #{numero_guia_alvo}) ---")
    sys.stdout.flush()

    # ----- VERIFICAR SESSÃO OTIMUS -----
    if not otimus_logado():
        print(f"  GUIA {i}: Sessão Otimus expirada. Re-logando...")
        sys.stdout.flush()
        relogin_otimus()
        guias = _coletar_guias(otimus)
        total_guias = len(guias)
        if idx >= total_guias:
            print(f"  ERRO: Guia {i} nao encontrada apos relogin")
            sys.stdout.flush()
            erros += 1
            continue
        numero_guia_alvo = guias[idx]["guia"]

    # ----- EXTRAIR PROCEDIMENTO DA GRID -----
    procedimento_otimus = guia.get("servico", "")
    if procedimento_otimus:
        print(f"  Procedimento Otimus: {procedimento_otimus}")
        sys.stdout.flush()

    # ----- SCROLL ATÉ A LINHA E CLICAR EDITAR -----
    try:
        _scroll_para_linha(otimus, idx, total_guias)
        otimus.wait_for_timeout(800)
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
        otimus.evaluate("(el) => { el.scrollIntoViewIfNeeded(); el.click(); el.dispatchEvent(new Event('click', { bubbles: true })) }", edit_btn)
        otimus.wait_for_selector("#vMATRICULAGUIA", timeout=15000)
    except Exception as e:
        erro_edicao = str(e)
        try:
            otimus.wait_for_timeout(2000)
            _scroll_para_linha(otimus, idx, total_guias)
            otimus.wait_for_timeout(800)
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
                otimus.evaluate("(el) => { el.scrollIntoViewIfNeeded(); el.click(); el.dispatchEvent(new Event('click', { bubbles: true })) }", edit_btn)
                otimus.wait_for_selector("#vMATRICULAGUIA", timeout=15000)
            else:
                raise Exception("Botao nao encontrado na segunda tentativa")
        except Exception:
            print(f"  ERRO Guia {i}: {erro_edicao}")
            sys.stdout.flush()
            erros += 1
            # Restaurar grid Otimus antes de prosseguir
            try:
                restaurado = _restaurar_grid_otimus()
                if not restaurado:
                    raise Exception("Falha ao restaurar via botoes")
            except Exception:
                print(f"  AVISO: Re-logando Otimus para restaurar grid...")
                sys.stdout.flush()
                relogin_otimus()
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
            print(f"  ERRO Guia {i}: Matricula nao encontrada apos clicar editar #{row_num}")
            sys.stdout.flush()
            erros += 1
            continue
    except Exception:
        print(f"  ERRO Guia {i}: Falha ao extrair campo matricula #{row_num}")
        sys.stdout.flush()
        erros += 1
        continue

    # ----- EXTRAIR NÚMERO DA GUIA -----
    numero_guia = ""
    try:
        guia_input = otimus.query_selector("#vGUIAPRINCIPALRESUMO")
        if guia_input:
            numero_guia = guia_input.get_attribute("value") or ""
        if not numero_guia:
            print(f"  ERRO Guia {i}: Numero da guia (vGUIAPRINCIPALRESUMO) nao encontrado #{row_num}")
            sys.stdout.flush()
            erros += 1
            continue
    except Exception:
        print(f"  ERRO Guia {i}: Falha ao extrair numero da guia #{row_num}")
        sys.stdout.flush()
        erros += 1
        continue

    # ----- CLICAR VOLTAR -----
    try:
        voltar_btn = otimus.query_selector("input[name=BUTTON26]")
        if voltar_btn:
            otimus.evaluate("(el) => el.click()", voltar_btn)
            otimus.wait_for_selector('[id^="vEDITARGRID_"]', timeout=15000)
        else:
            print(f"  ERRO Guia {i}: Botao VOLTAR (BUTTON26) nao encontrado apos editar #{row_num}")
            sys.stdout.flush()
            erros += 1
            continue
    except Exception:
        print(f"  ERRO Guia {i}: Falha ao clicar em VOLTAR (BUTTON26) #{row_num}")
        sys.stdout.flush()
        erros += 1
        continue

    # ----- VERIFICAR SESSÃO SISREG -----
    if not sisreg_logado():
        print(f"  GUIA {i}: Sessão SISREG expirada. Re-logando...")
        sys.stdout.flush()
        relogin_sisreg()

    # ----- CONSULTAR NO SISREG -----
    try:
        for tentativa_sisreg in range(2):
            try:
                sisreg.goto("https://sisregiii.saude.gov.br/cgi-bin/cons_agendas", wait_until="domcontentloaded", timeout=20000)
                break
            except Exception:
                if tentativa_sisreg == 0:
                    print(f"  GUIA {i}: SISREG lento, re-logando...")
                    sys.stdout.flush()
                    relogin_sisreg()
                else:
                    raise
        sisreg.wait_for_selector("input[name=cns_paciente], input#usuario", timeout=15000)
        if sisreg.query_selector("input#usuario"):
            print(f"  GUIA {i}: Sessão SISREG expirada, re-logando...")
            sys.stdout.flush()
            relogin_sisreg()
        sisreg.fill("input[name=cns_paciente]", matricula)
        sleep(sisreg, 200, 500)
        sisreg.select_option("select[name=ups]", codigo_ups)
        sleep(sisreg, 200, 500)
        sisreg.select_option("select[name=cmbTipoOperacao]", "Confirma")
        sleep(sisreg, 300, 600)

        chk = sisreg.query_selector("input[name=chkboxExibirProcedimentos]")
        if chk and not chk.is_checked():
            sisreg.click("input[name=chkboxExibirProcedimentos]")
            sleep(sisreg, 300, 600)

        ok_btn = sisreg.query_selector("input[name=btnOK]")
        if ok_btn:
            sisreg.click("input[name=btnOK]")
            sleep(sisreg, 1500, 2500)
        else:
            print(f"  ERRO Guia {i}: Botao OK (btnOK) nao encontrado no SISREG para CNS {matricula}")
            sys.stdout.flush()
            erros += 1
            continue

        # ----- VERIFICAR PROCEDIMENTO -----
        body_text = sisreg.inner_text("body")
        if "Nenhum" in body_text or "não encontrado" in body_text.lower():
            motivo = f"SISREG não retornou resultados para CNS {matricula}"
            print(f"  ERRO Guia {i}: {motivo}")
            sys.stdout.flush()
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

                date_match = re.search(r"Data/Hora:[^\n]*\n\s*(\d{2})/(\d{2})/(\d{4})", texto)
                if not date_match:
                    continue
                data_sisreg = datetime(int(date_match.group(3)), int(date_match.group(2)), int(date_match.group(1)))
                data_str = f"{date_match.group(1)}/{date_match.group(2)}/{date_match.group(3)}"

                if data_sisreg > hoje:
                    print(f"  GUIA {i}: Agendamento futuro ({data_str}), pulando")
                    sys.stdout.flush()
                    guias_futuras += 1
                    continue

                chave_input = sisreg.query_selector(f'input[name="Chave{idx}"]')
                if not chave_input or chave_input.get_attribute("disabled") is not None:
                    print(f"  GUIA {i}: Chave{idx} não disponível, pulando")
                    sys.stdout.flush()
                    continue

                solicitacoes_preencher.append({'idx': idx, 'data_str': data_str})

            if not solicitacoes_preencher:
                if not solic_tables:
                    motivo = "Nenhuma solicitação encontrada na agenda SISREG"
                    print(f"  ERRO Guia {i}: {motivo}")
                    sys.stdout.flush()
                    falhas[numero_guia] = motivo
                    erros += 1
                else:
                    print(f"  GUIA {i}: Nenhuma solicitação com Chave disponível, pulando")
                    sys.stdout.flush()
            else:
                for sol in solicitacoes_preencher:
                    try:
                        sisreg.fill(f'input[name="Chave{sol["idx"]}"]', numero_guia)
                        sleep(sisreg, 300, 600)
                    except Exception:
                        print(f"  ERRO: Falha ao preencher Chave{sol['idx']}")
                        sys.stdout.flush()

                try:
                    confirm_btn = sisreg.query_selector("input[name=btnConfirmar]")
                    if confirm_btn:
                        sisreg.click("input[name=btnConfirmar]")
                        sleep(sisreg, 2000, 3000)
                        sucessos += 1
                        print(f">>> GUIA {i}: SUCESSO - Guia {numero_guia} registrada em {len(solicitacoes_preencher)} solicitação(ões) <<<")
                        sys.stdout.flush()
                    else:
                        print(f"  ERRO Guia {i}: Botão Confirmar (btnConfirmar) não encontrado")
                        sys.stdout.flush()
                        falhas[numero_guia] = "Botão Confirmar não encontrado"
                        erros += 1
                except Exception:
                    print(f"  ERRO Guia {i}: Falha ao confirmar agenda no SISREG (guia {numero_guia})")
                    sys.stdout.flush()
                    falhas[numero_guia] = "Falha ao confirmar agenda"
                    erros += 1
        elif matricula in body_text:
            sucessos += 1
            print(f">>> GUIA {i}: SUCESSO - CNS encontrado nos resultados! <<<")
        else:
            motivo = f"Retorno SISREG não reconhecido para CNS {matricula}"
            print(f"  ERRO Guia {i}: {motivo}")
            print(f"    body_text[:300] = {body_text[:300]}")
            sys.stdout.flush()
            falhas[numero_guia] = motivo
            erros += 1

    except Exception as e:
        motivo = f"Exceção no bloco SISREG: {e}"
        print(f"  ERRO Guia {i}: {motivo}")
        sys.stdout.flush()
        falhas[numero_guia] = motivo
        erros += 1

    sys.stdout.flush()

# ============================================================
# 4. RESUMO
# ============================================================
print(f"\n{'='*50}")
print(f"RESUMO DO PROCESSAMENTO")
print(f"{'='*50}")
print(f"Total de guias: {total_guias}")
print(f"Sucessos: {sucessos}")
print(f"Guias com data futura (não confirmadas): {guias_futuras}")
print(f"Erros: {erros}")
if falhas:
    print(f"\nFalhas por guia:")
    for guia, motivo in falhas.items():
        print(f"  Guia {guia}: {motivo}")
print(f"{'='*50}")
print("Processo concluído! Pressione Ctrl+C para fechar.")
print(f"{'='*50}")
sys.stdout.flush()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    browser.close()
    p.stop()
