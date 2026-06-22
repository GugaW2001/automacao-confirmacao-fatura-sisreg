import asyncio
import json
import threading
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from . import database as db
from . import automation

router = APIRouter(prefix="/api")

active_connections = {}
execution_threads = {}
suspend_events = {}
abort_events = {}
range_events = {}       # eventos para aguardar intervalo de guias
range_results = {}      # resultados do intervalo (guia_inicio, guia_fim)

_main_loop = None

SISREG_LOGIN_MAP = {
    "MED_LEIDE": ("palhoca", "4090276"),
    "MED.LEIDE": ("sao_jose", "9385835"),
}


class ExecutePayload(BaseModel):
    sisreg_user: str
    sisreg_pass: str
    otimus_user: str
    otimus_pass: str
    codigo_fatura: str
    guia_inicio: int = 1
    guia_fim: int | None = None


@router.post("/faturas")
def list_faturas(payload: dict):
    otimus_user = payload.get("otimus_user", "")
    otimus_pass = payload.get("otimus_pass", "")
    if not otimus_user or not otimus_pass:
        return {"success": False, "error": "Usuário e senha do Otimus são obrigatórios"}

    headless = os.environ.get("HEADLESS", "false").lower() == "true"

    collected_logs = []
    result = automation.listar_faturas(
        otimus_user=otimus_user,
        otimus_pass=otimus_pass,
        unidade="palhoca",
        log_callback=lambda msg: collected_logs.append(msg),
        headless=headless,
    )
    result["logs"] = collected_logs
    return result


def run_automation_thread(execution_id, unidade, codigo_fatura, sisreg_user, sisreg_pass, codigo_ups, otimus_user, otimus_pass, suspend_event=None, abort_event=None, guia_inicio=1, guia_fim=None):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    headless = os.environ.get("HEADLESS", "false").lower() == "true"

    range_event = threading.Event()
    range_events[execution_id] = range_event

    def log_callback(msg):
        db.add_execution_log(execution_id, msg)
        send_to_websockets(execution_id, msg)

    def range_callback():
        """Aguardar usuário definir intervalo de guias."""
        db.add_execution_log(execution_id, "⏸️ Total de guias identificado. Defina o intervalo para continuar...")
        db.add_execution_log(execution_id, "__RANGE_WAIT__")
        send_to_websockets(execution_id, "⏸️ Aguardando intervalo de guias...")
        send_to_websockets(execution_id, "__RANGE_WAIT__")
        range_event.wait()
        range_event.clear()
        if abort_event is not None and abort_event.is_set():
            return (1, 0)
        result = range_results.pop(execution_id, (1, None))
        return result

    db.add_execution_log(execution_id, f"Iniciando automação: {unidade} / Fatura {codigo_fatura}")

    try:
        result = automation.run_automation(
            unidade=unidade,
            codigo_fatura=codigo_fatura,
            sisreg_user=sisreg_user,
            sisreg_pass=sisreg_pass,
            codigo_ups=codigo_ups,
            otimus_user=otimus_user,
            otimus_pass=otimus_pass,
            log_callback=log_callback,
            headless=headless,
            suspend_event=suspend_event,
            abort_event=abort_event,
            guia_inicio=guia_inicio,
            guia_fim=guia_fim,
            range_callback=range_callback,
        )
        if result.get("abortado"):
            status = "aborted"
            db.add_execution_log(execution_id, "🛑 Execução abortada")
        else:
            status = "completed" if result.get("success") else "error"
        db.update_execution(
            execution_id,
            status=status,
            total_guias=result.get("total_guias", 0),
            sucessos=result.get("sucessos", 0),
            divergencias=0,
            erros=result.get("erros", 0),
            resultado_json=json.dumps(result, default=str),
        )
    except Exception as e:
        db.add_execution_log(execution_id, f"ERRO FATAL: {e}")
        db.update_execution(execution_id, status="error", resultado_json=json.dumps({"error": str(e)}))

    finally:
        if execution_id in suspend_events:
            del suspend_events[execution_id]
        if execution_id in abort_events:
            del abort_events[execution_id]
        if execution_id in range_events:
            del range_events[execution_id]
        if execution_id in range_results:
            del range_results[execution_id]

    send_to_websockets(execution_id, "__FIM__")

    if execution_id in active_connections:
        for ws in list(active_connections.get(execution_id, set())):
            try:
                asyncio.run_coroutine_threadsafe(ws.close(), _main_loop)
            except Exception:
                pass
        del active_connections[execution_id]

    if execution_id in execution_threads:
        del execution_threads[execution_id]


def set_main_loop(loop):
    global _main_loop
    _main_loop = loop

def send_to_websockets(execution_id, message):
    if execution_id not in active_connections or _main_loop is None:
        return
    for ws in list(active_connections[execution_id]):
        try:
            asyncio.run_coroutine_threadsafe(
                ws.send_json({"type": "log", "message": message}),
                _main_loop
            )
        except Exception:
            pass


@router.post("/execute")
def execute_automation(payload: ExecutePayload):
    sisreg_user = payload.sisreg_user.strip().upper()

    if sisreg_user not in SISREG_LOGIN_MAP:
        return {"success": False, "error": f"Login SISREG '{sisreg_user}' não reconhecido. Use MED_LEIDE (Palhoça) ou MED.LEIDE (São José)"}

    unidade, codigo_ups = SISREG_LOGIN_MAP[sisreg_user]

    execution_id = db.create_execution(unidade, payload.codigo_fatura)

    suspend_event = threading.Event()
    suspend_events[execution_id] = suspend_event

    abort_event = threading.Event()
    abort_events[execution_id] = abort_event

    thread = threading.Thread(
        target=run_automation_thread,
        args=(execution_id, unidade, payload.codigo_fatura, payload.sisreg_user, payload.sisreg_pass, codigo_ups, payload.otimus_user, payload.otimus_pass, suspend_event, abort_event, payload.guia_inicio, payload.guia_fim),
        daemon=True,
    )
    execution_threads[execution_id] = thread
    thread.start()

    return {"success": True, "execution_id": execution_id}


@router.post("/executions/{execution_id}/suspend")
def suspend_execution(execution_id: int):
    event = suspend_events.get(execution_id)
    if not event:
        return {"success": False, "error": "Execução não encontrada ou já finalizada"}
    event.set()
    db.add_execution_log(execution_id, "⏸️ Usuário solicitou suspensão...")
    send_to_websockets(execution_id, "⏸️ Usuário solicitou suspensão...")
    return {"success": True}


@router.post("/executions/{execution_id}/resume")
def resume_execution(execution_id: int):
    event = suspend_events.get(execution_id)
    if not event:
        return {"success": False, "error": "Execução não encontrada ou já finalizada"}
    event.clear()
    db.add_execution_log(execution_id, "▶️ Usuário retomou a execução!")
    send_to_websockets(execution_id, "▶️ Usuário retomou a execução!")
    return {"success": True}


@router.post("/executions/{execution_id}/abort")
def abort_execution(execution_id: int):
    event = abort_events.get(execution_id)
    if not event:
        return {"success": False, "error": "Execução não encontrada ou já finalizada"}
    event.set()
    # Também limpa suspensão se estiver suspenso
    susp_event = suspend_events.get(execution_id)
    if susp_event:
        susp_event.clear()
    # Libera range event se estiver aguardando
    range_event = range_events.get(execution_id)
    if range_event:
        range_event.set()
    db.add_execution_log(execution_id, "🛑 Usuário solicitou abortamento!")
    send_to_websockets(execution_id, "🛑 Usuário solicitou abortamento...")
    return {"success": True}


@router.post("/executions/{execution_id}/range")
def set_execution_range(execution_id: int, payload: dict):
    event = range_events.get(execution_id)
    if not event:
        return {"success": False, "error": "Execução não está aguardando intervalo ou já finalizada"}
    guia_inicio = payload.get("guia_inicio", 1)
    guia_fim = payload.get("guia_fim")
    range_results[execution_id] = (guia_inicio, guia_fim)
    event.set()
    db.add_execution_log(execution_id, f"Intervalo definido: guias {guia_inicio} a {guia_fim or 'fim'}")
    send_to_websockets(execution_id, f"Intervalo definido: guias {guia_inicio} a {guia_fim or 'fim'}")
    return {"success": True}


@router.websocket("/ws/{execution_id}")
async def websocket_logs(websocket: WebSocket, execution_id: int):
    await websocket.accept()

    # Replay logs do banco para não perder nada que foi gerado antes da conexão
    existing_logs = db.get_execution_logs(execution_id)
    for log_entry in existing_logs:
        await websocket.send_json({"type": "log", "message": log_entry["log"]})

    if execution_id not in active_connections:
        active_connections[execution_id] = set()
    active_connections[execution_id].add(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if execution_id in active_connections:
            active_connections[execution_id].discard(websocket)
            if not active_connections[execution_id]:
                del active_connections[execution_id]


@router.get("/executions")
def list_executions():
    return db.list_executions()


@router.get("/executions/{execution_id}")
def get_execution_detail(execution_id: int):
    exec_data = db.get_execution(execution_id)
    if not exec_data:
        return {"error": "Execução não encontrada"}, 404
    logs = db.get_execution_logs(execution_id)
    exec_data["logs"] = logs
    return exec_data


@router.get("/executions/{execution_id}/logs")
def get_execution_logs_endpoint(execution_id: int):
    logs = db.get_execution_logs(execution_id)
    return {"logs": logs, "execution_id": execution_id}
