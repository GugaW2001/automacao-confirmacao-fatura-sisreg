import os
import sqlite3
from datetime import datetime


DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "app.db"))


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA encoding = 'UTF-8'")
    return conn


def init_db():
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                unidade TEXT NOT NULL,
                codigo_fatura TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                total_guias INTEGER DEFAULT 0,
                sucessos INTEGER DEFAULT 0,
                divergencias INTEGER DEFAULT 0,
                erros INTEGER DEFAULT 0,
                resultado_json TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id INTEGER NOT NULL,
                log TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (execution_id) REFERENCES executions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_logs_execution_id ON execution_logs(execution_id);
            CREATE INDEX IF NOT EXISTS idx_executions_started_at ON executions(started_at);
        """)
        conn.commit()
    finally:
        conn.close()


def create_execution(unidade, codigo_fatura):
    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO executions (unidade, codigo_fatura, status) VALUES (?, ?, 'running')",
            (unidade, codigo_fatura)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_execution(execution_id, **kwargs):
    allowed = {"status", "total_guias", "sucessos", "erros", "resultado_json", "finished_at"}
    sets = []
    values = []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k}=?")
            values.append(v)
    if not sets:
        return
    sets.append("finished_at=?")
    values.append(datetime.now().isoformat())
    values.append(execution_id)
    conn = _get_conn()
    try:
        conn.execute(f"UPDATE executions SET {', '.join(sets)} WHERE id=?", values)
        conn.commit()
    finally:
        conn.close()


def add_execution_log(execution_id, log_text):
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO execution_logs (execution_id, log) VALUES (?, ?)",
            (execution_id, log_text)
        )
        conn.commit()
    finally:
        conn.close()


def get_execution(execution_id):
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM executions WHERE id = ?", (execution_id,)).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def list_executions(limit=20):
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM executions ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_execution_logs(execution_id):
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT log, timestamp FROM execution_logs WHERE execution_id = ? ORDER BY id ASC",
            (execution_id,)
        ).fetchall()
        return [{"log": r["log"], "timestamp": r["timestamp"]} for r in rows]
    finally:
        conn.close()
