# Automação SISREG

Automação RPA para cruzamento de guias médicas entre **Otimus Clinic** e **SISREG** (SUS).

## Funcionalidades

- Login automático no SISREG e Otimus Clinic
- Seleção de fatura por código (CAPADELOTEID)
- Processamento guia por guia:
  - Extrai CNS (matrícula) e número da guia
  - Consulta SISREG por CNS, UPS e operação "Confirma"
  - Compara procedimentos entre os sistemas
  - Registra confirmação automaticamente
- Logs em tempo real via WebSocket
- Histórico de execuções
- Credenciais criptografadas (Fernet)

## Executar Localmente

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Garantir que o Playwright tenha os browsers
playwright install chromium

# 3. Definir chave de criptografia (qualquer string)
# PowerShell:
$env:SECRET_KEY="sua-chave-secreta-aqui"
# CMD:
set SECRET_KEY=sua-chave-secreta-aqui

# 4. Rodar (modo headed - janela visível)
$env:HEADLESS="false"
uvicorn app.main:app --reload --port 8000

# 5. Acessar
http://localhost:8000
```

## Deploy no Easypanel

1. Crie um repositório no GitHub e faça push do código
2. No Easypanel: **New Service** → Selecione o repositório
3. Configure a **variável de ambiente** `SECRET_KEY` (valor qualquer, usado para criptografar as credenciais)
4. Deploy

## Credenciais Padrão

As credenciais padrão já vão preenchidas no formulário:

| Unidade | SISREG | UPS | Otimus |
|---|---|---|---|
| Palhoça | MED_LEIDE | 4090276 | gustavo.weingartner |
| São José | MED.LEIDE | 9385835 | gustavo.weingartner |

As senhas precisam ser informadas e salvas via interface.

## Estrutura do Projeto

```
automacao-sisreg/
├── app/
│   ├── __init__.py
│   ├── main.py          # Servidor FastAPI
│   ├── database.py      # SQLite + criptografia
│   ├── routes.py        # API REST + WebSocket
│   ├── automation.py    # Automação refatorada
│   ├── templates/
│   │   └── index.html   # Interface web
│   └── static/
│       ├── style.css
│       └── script.js
├── automacao_sisreg.py  # Script original (mantido)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
