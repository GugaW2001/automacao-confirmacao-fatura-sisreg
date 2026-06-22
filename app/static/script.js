let currentExecutionId = null;
let websocket = null;
let isSuspended = false;
let isAborted = false;
let wsReconnectAttempts = 0;
let wsReconnectTimer = null;
let pollTimer = null;
const MAX_WS_RECONNECT = 20;

// --- List faturas ---
document.getElementById('btn-listar-faturas').addEventListener('click', async () => {
    const otimus_user = document.getElementById('otimus-user').value.trim();
    const otimus_pass = document.getElementById('otimus-pass').value.trim();

    const resumoCard = document.getElementById('resumo-card');
    const erroCard = document.getElementById('erro-card');

    resumoCard.classList.add('hidden');
    erroCard.classList.add('hidden');

    if (!otimus_user) {
        showErro('Preencha o login do Otimus');
        return;
    }

    if (!otimus_pass) {
        showErro('Preencha a senha do Otimus');
        return;
    }

    const btn = document.getElementById('btn-listar-faturas');
    btn.disabled = true;
    btn.textContent = 'Buscando...';

    const logEl = document.getElementById('log-output');
    const logCard = document.getElementById('log-card');
    logCard.classList.remove('hidden');
    logEl.innerHTML = '<div class="log-info">Buscando faturas no Otimus...</div>\n';

    try {
        const res = await fetch('/api/faturas', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ otimus_user, otimus_pass }),
        });
        const data = await res.json();

        if (data.success && data.faturas) {
            if (data.logs) {
                data.logs.forEach(l => appendLog(l));
            }
            appendLog(`Encontradas ${data.faturas.length} faturas:`);
            data.faturas.forEach(f => {
                appendLog(`  [${f.codigo}] ${f.nome || '(sem nome)'} - ${f.convenio || '(sem convênio)'}`);
            });
        } else {
            appendLog(`ERRO: ${data.error || 'Nenhuma fatura encontrada'}`);
        }
    } catch (e) {
        appendLog(`Erro de conexão: ${e.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Listar Faturas';
    }
});

// --- Execute automation ---
document.getElementById('btn-executar').addEventListener('click', async () => {
    const sisreg_user = document.getElementById('sisreg-user').value.trim();
    const sisreg_pass = document.getElementById('sisreg-pass').value.trim();
    const otimus_user = document.getElementById('otimus-user').value.trim();
    const otimus_pass = document.getElementById('otimus-pass').value.trim();
    const codigo_fatura = document.getElementById('codigo-fatura').value.trim();

    if (!sisreg_user || !sisreg_pass) {
        showErro('Preencha login e senha do SISREG');
        return;
    }

    if (!otimus_user || !otimus_pass) {
        showErro('Preencha login e senha do Otimus');
        return;
    }

    if (!codigo_fatura) {
        showErro('Digite o código da fatura');
        return;
    }

    const btn = document.getElementById('btn-executar');
    const statusCard = document.getElementById('status-card');
    const logCard = document.getElementById('log-card');
    const logEl = document.getElementById('log-output');
    const resumoCard = document.getElementById('resumo-card');
    const erroCard = document.getElementById('erro-card');
    const statusText = document.getElementById('status-text');
    const spinner = document.getElementById('status-spinner');

    resumoCard.classList.add('hidden');
    erroCard.classList.add('hidden');
    document.getElementById('range-card').classList.add('hidden');

    logEl.innerHTML = '';
    logCard.classList.remove('hidden');
    statusCard.classList.remove('hidden');
    statusText.textContent = 'Iniciando...';
    spinner.classList.remove('hidden');
    btn.disabled = true;
    btn.textContent = 'Executando...';

    try {
        const res = await fetch('/api/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sisreg_user,
                sisreg_pass,
                otimus_user,
                otimus_pass,
                codigo_fatura,
            }),
        });
        const data = await res.json();

        if (!data.success) {
            statusText.textContent = 'Erro';
            spinner.classList.add('hidden');
            showErro(data.error);
            btn.disabled = false;
            btn.textContent = 'Executar Automação';
            return;
        }

        currentExecutionId = data.execution_id;
        isSuspended = false;
        statusText.textContent = 'Executando...';
        document.getElementById('suspend-actions').classList.remove('hidden');
        document.getElementById('btn-suspender').textContent = 'Suspender';
        document.getElementById('btn-suspender').className = 'btn btn-warning';
        connectWebSocket(currentExecutionId);

    } catch (e) {
        statusText.textContent = 'Erro de conexão';
        spinner.classList.add('hidden');
        showErro('Erro ao iniciar execução: ' + e.message);
        btn.disabled = false;
        btn.textContent = 'Executar Automação';
    }
});

// --- Suspend / Resume ---
document.getElementById('btn-suspender').addEventListener('click', async () => {
    if (!currentExecutionId) return;

    const btn = document.getElementById('btn-suspender');

    try {
        if (isSuspended) {
            const res = await fetch(`/api/executions/${currentExecutionId}/resume`, { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                isSuspended = false;
                btn.textContent = 'Suspender';
                btn.className = 'btn btn-warning';
                document.getElementById('status-text').textContent = 'Executando...';
            }
        } else {
            const res = await fetch(`/api/executions/${currentExecutionId}/suspend`, { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                isSuspended = true;
                btn.textContent = 'Retomar';
                btn.className = 'btn btn-resume';
                document.getElementById('status-text').textContent = 'Suspenso';
            }
        }
    } catch (e) {
        console.error('Erro ao suspender/retomar:', e);
    }
});

// --- Range confirmation ---
document.getElementById('btn-confirmar-range').addEventListener('click', async () => {
    if (!currentExecutionId) return;

    const guia_inicio = parseInt(document.getElementById('guia-inicio').value) || 1;
    const guia_fim = parseInt(document.getElementById('guia-fim').value) || null;

    const btn = document.getElementById('btn-confirmar-range');
    btn.disabled = true;
    btn.textContent = 'Confirmando...';

    try {
        const res = await fetch(`/api/executions/${currentExecutionId}/range`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ guia_inicio, guia_fim }),
        });
        const data = await res.json();
        if (data.success) {
            document.getElementById('range-card').classList.add('hidden');
        } else {
            appendLog(`Erro ao definir intervalo: ${data.error}`);
        }
    } catch (e) {
        appendLog(`Erro de conexão ao definir intervalo: ${e.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Confirmar Intervalo';
    }
});

// --- Abort ---
document.getElementById('btn-abortar').addEventListener('click', async () => {
    if (!currentExecutionId) return;

    if (!confirm('Tem certeza que deseja ABORTAR a execução atual?')) return;

    const btn = document.getElementById('btn-abortar');
    btn.disabled = true;
    btn.textContent = 'Abortando...';

    try {
        const res = await fetch(`/api/executions/${currentExecutionId}/abort`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            appendLog('🛑 Abortamento solicitado. Aguardando parada...');
        } else {
            appendLog(`Erro ao abortar: ${data.error}`);
        }
    } catch (e) {
        appendLog(`Erro de conexão ao abortar: ${e.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Abortar';
    }
});

// --- WebSocket com reconexão automática ---
function connectWebSocket(executionId) {
    if (websocket) {
        websocket.close();
    }

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${window.location.host}/api/ws/${executionId}`;
    websocket = new WebSocket(wsUrl);
    wsReconnectAttempts = 0;
    isAborted = false;

    // Iniciar polling de fallback concorrente
    startPollFallback(executionId);

    websocket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'log') {
            appendLog(data.message);
        }
    };

    websocket.onclose = () => {
        document.getElementById('suspend-actions').classList.add('hidden');
        // Tentar reconectar se a execução ainda estiver rodando
        scheduleWsReconnect(executionId);
        setTimeout(() => fetchResumo(executionId), 2000);
    };

    websocket.onerror = () => {
        // reconexão será tratada pelo onclose
    };
}

function scheduleWsReconnect(executionId) {
    if (wsReconnectAttempts >= MAX_WS_RECONNECT) return;
    if (isAborted) return;

    wsReconnectAttempts++;
    if (wsReconnectTimer) clearTimeout(wsReconnectTimer);

    wsReconnectTimer = setTimeout(() => {
        if (isAborted) return;
        console.log(`WS reconectando (${wsReconnectAttempts}/${MAX_WS_RECONNECT})...`);
        connectWebSocket(executionId);
    }, 3000);
}

function startPollFallback(executionId) {
    if (pollTimer) clearInterval(pollTimer);

    pollTimer = setInterval(async () => {
        if (isAborted) {
            clearInterval(pollTimer);
            pollTimer = null;
            return;
        }
        try {
            const res = await fetch(`/api/executions/${executionId}`);
            if (res.ok) {
                const data = await res.json();
                if (data.status !== 'running') {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    // Se o WebSocket não pegou, buscar logs e resumo
                    if (!websocket || websocket.readyState !== WebSocket.OPEN) {
                        const logsRes = await fetch(`/api/executions/${executionId}/logs`);
                        if (logsRes.ok) {
                            const logsData = await logsRes.json();
                            logsData.logs.forEach(l => appendLog(l.log));
                        }
                        showResumo(data);
                        finalizarExecucao(data);
                    }
                }
            }
        } catch (e) {
            // Silencioso - rede pode estar fora
        }
    }, 10000);
}

function finalizarExecucao(data) {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
    document.getElementById('status-spinner').classList.add('hidden');
    document.getElementById('btn-executar').disabled = false;
    document.getElementById('btn-executar').textContent = 'Executar Automação';
    document.getElementById('suspend-actions').classList.add('hidden');
    document.getElementById('range-card').classList.add('hidden');

    if (data && data.abortado) {
        document.getElementById('status-text').textContent = 'Abortado';
        showResumo(data);
    } else if (data && data.status === 'completed') {
        document.getElementById('status-text').textContent = 'Concluído';
    } else if (data && data.status === 'error') {
        document.getElementById('status-text').textContent = 'Erro';
    } else {
        document.getElementById('status-text').textContent = 'Finalizado';
    }
}

function appendLog(msg) {
    const logEl = document.getElementById('log-output');

    if (msg === '__FIM__') {
        finalizarExecucao();
        return;
    }

    // Aguardando intervalo de guias
    if (msg === '__RANGE_WAIT__') {
        document.getElementById('range-card').classList.remove('hidden');
        document.getElementById('guia-fim').value = '';
        document.getElementById('guia-fim').placeholder = 'Total de guias';
        document.getElementById('status-text').textContent = 'Aguardando intervalo...';
        document.getElementById('status-spinner').classList.add('hidden');
        return;
    }

    // Fallback: se o replay do banco trouxe "Total de guias identificado" sem o __RANGE_WAIT__
    if (!document.getElementById('range-card').classList.contains('hidden')) return;
    if (msg.includes('Total de guias identificado')) {
        document.getElementById('range-card').classList.remove('hidden');
        document.getElementById('guia-fim').value = '';
        document.getElementById('guia-fim').placeholder = 'Total de guias';
        document.getElementById('status-text').textContent = 'Aguardando intervalo...';
        document.getElementById('status-spinner').classList.add('hidden');
        return;
    }

    // Auto-detectar suspensão/retomada via log
    if (msg.includes('suspensa')) {
        isSuspended = true;
        document.getElementById('btn-suspender').textContent = 'Retomar';
        document.getElementById('btn-suspender').className = 'btn btn-resume';
        document.getElementById('status-text').textContent = 'Suspenso';
    } else if (msg.includes('retomada')) {
        isSuspended = false;
        document.getElementById('btn-suspender').textContent = 'Suspender';
        document.getElementById('btn-suspender').className = 'btn btn-warning';
        document.getElementById('status-text').textContent = 'Executando...';
    } else if (msg.includes('abortada') || msg.includes('ABORTADO')) {
        isAborted = true;
        isSuspended = false;
        document.getElementById('status-text').textContent = 'Abortado';
        document.getElementById('status-spinner').classList.add('hidden');
        document.getElementById('btn-suspender').textContent = 'Suspender';
        document.getElementById('btn-suspender').className = 'btn btn-warning';
        document.getElementById('btn-abortar').disabled = true;
    }

    let cssClass = 'log-info';
    if (msg.startsWith('ERRO') || msg.startsWith('  ERRO')) cssClass = 'log-error';
    else if (msg.includes('SUCESSO')) cssClass = 'log-success';
    else if (msg.startsWith('>>>') || msg.startsWith('---') || msg.startsWith('===')) cssClass = 'log-success';
    else if (msg.includes('RESUMO') || msg.includes('Total:') || msg.includes('Sucessos:') || msg.includes('Erros:') || msg.includes('Divergências:')) cssClass = 'log-success';
    else if (msg.includes('abortada') || msg.includes('ABORTADO')) cssClass = 'log-error';

    const line = document.createElement('div');
    line.className = cssClass;
    line.textContent = msg;
    logEl.appendChild(line);
    logEl.scrollTop = logEl.scrollHeight;
}

async function fetchResumo(executionId) {
    try {
        const res = await fetch(`/api/executions/${executionId}`);
        if (!res.ok) return;
        const data = await res.json();
        showResumo(data);
    } catch (e) {
        // silent
    }
}

async function pollResumo(executionId) {
    let attempts = 0;
    while (attempts < 30) {
        await new Promise(r => setTimeout(r, 2000));
        try {
            const res = await fetch(`/api/executions/${executionId}`);
            if (!res.ok) continue;
            const data = await res.json();
            if (data.status !== 'running') {
                if (data.logs) {
                    data.logs.forEach(l => appendLog(l.log));
                }
                showResumo(data);
                finalizarExecucao(data);
                return;
            }
        } catch (e) {
            // silent
        }
        attempts++;
    }
}

function showResumo(data) {
    const card = document.getElementById('resumo-card');
    const content = document.getElementById('resumo-content');

    let html = '<div class="resumo-grid">';
    html += `<div class="resumo-item total"><div class="valor">${data.total_guias || 0}</div><div class="rotulo">Total Guias</div></div>`;
    html += `<div class="resumo-item sucesso"><div class="valor">${data.sucessos || 0}</div><div class="rotulo">Sucessos</div></div>`;

    html += `<div class="resumo-item erro"><div class="valor">${data.erros || 0}</div><div class="rotulo">Erros</div></div>`;
    html += '</div>';

    if (data.resultado_json) {
        try {
            const r = typeof data.resultado_json === 'string' ? JSON.parse(data.resultado_json) : data.resultado_json;
            if (r.falhas && Object.keys(r.falhas).length > 0) {
                html += '<div class="falhas-lista"><h4>Falhas por Guia</h4><ul>';
                for (const [guia, motivo] of Object.entries(r.falhas)) {
                    html += `<li><strong>Guia ${guia}:</strong> ${motivo}</li>`;
                }
                html += '</ul></div>';
            }

        } catch (e) {}
    }

    content.innerHTML = html;
    card.classList.remove('hidden');
}

function showErro(msg) {
    const card = document.getElementById('erro-card');
    const content = document.getElementById('erro-content');
    content.textContent = msg;
    card.classList.remove('hidden');
}

// --- Clear log ---
document.getElementById('btn-clear-log').addEventListener('click', () => {
    document.getElementById('log-output').innerHTML = '';
});
