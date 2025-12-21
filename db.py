import sqlite3
from datetime import datetime
from typing import List, Dict, Any
from config import DB_PATH

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            opening_hours_json TEXT NOT NULL,
            faq_json TEXT NOT NULL
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            client_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            draft_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (client_id, user_id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(client_id, date, time)
        )
        """)
        conn.commit()

def ensure_default_client(client_id: str):
    import json
    default_hours = {
        "mon": {"start": "09:00", "end": "18:00"},
        "tue": {"start": "09:00", "end": "18:00"},
        "wed": {"start": "09:00", "end": "18:00"},
        "thu": {"start": "09:00", "end": "18:00"},
        "fri": {"start": "09:00", "end": "18:00"},
        "sat": None,
        "sun": None
    }
    default_faq = {
        "horaires": "Nous sommes ouverts du lundi au vendredi de 9h à 18h.",
        "adresse": "Nous sommes en centre-ville. Dites-moi votre ville et je vous donne l’adresse exacte.",
        "tarifs": "Les tarifs dépendent de la demande. Dites-moi ce que vous cherchez et je vous renseigne."
    }

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM clients WHERE id = ?", (client_id,))
        if cur.fetchone():
            return
        cur.execute("""
            INSERT INTO clients (id, name, opening_hours_json, faq_json)
            VALUES (?, ?, ?, ?)
        """, (client_id, f"Client {client_id}", json.dumps(default_hours), json.dumps(default_faq)))
        conn.commit()

def get_client_config(client_id: str) -> Dict[str, Any]:
    import json
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("client_id inconnu")
        return {
            "id": row["id"],
            "name": row["name"],
            "opening_hours": json.loads(row["opening_hours_json"]),
            "faq": json.loads(row["faq_json"]),
        }

def save_message(client_id: str, user_id: str, role: str, content: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO messages (client_id, user_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (client_id, user_id, role, content, datetime.utcnow().isoformat()))
        conn.commit()

def get_recent_messages(client_id: str, user_id: str, limit: int = 8) -> List[Dict[str, str]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT role, content FROM messages
            WHERE client_id=? AND user_id=?
            ORDER BY id DESC
            LIMIT ?
        """, (client_id, user_id, limit))
        rows = cur.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

def upsert_session(client_id: str, user_id: str, stage: str, draft_json: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sessions (client_id, user_id, stage, draft_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(client_id, user_id)
            DO UPDATE SET stage=excluded.stage, draft_json=excluded.draft_json, updated_at=excluded.updated_at
        """, (client_id, user_id, stage, draft_json, datetime.utcnow().isoformat()))
        conn.commit()

def get_session(client_id: str, user_id: str) -> Dict[str, str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT stage, draft_json FROM sessions WHERE client_id=? AND user_id=?", (client_id, user_id))
        row = cur.fetchone()
        if not row:
            return {"stage": "idle", "draft_json": "{}"}
        return {"stage": row["stage"], "draft_json": row["draft_json"]}

def clear_session(client_id: str, user_id: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE client_id=? AND user_id=?", (client_id, user_id))
        conn.commit()

def appointment_exists(client_id: str, date: str, time: str) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM appointments WHERE client_id=? AND date=? AND time=? LIMIT 1", (client_id, date, time))
        return cur.fetchone() is not None

def insert_appointment(client_id: str, user_id: str, name: str, date: str, time: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO appointments (client_id, user_id, name, date, time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (client_id, user_id, name, date, time, datetime.utcnow().isoformat()))
        conn.commit()
