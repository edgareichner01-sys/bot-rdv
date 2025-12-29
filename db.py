import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

# --- GESTION DES IMPORTS ET CONFIG ---
try:
    from config import DATABASE_URL
except ImportError:
    DATABASE_URL = os.getenv("DATABASE_URL")

def get_conn():
    """Détecte automatiquement si on utilise SQLite (local) ou Postgres (Render)."""
    if DATABASE_URL.startswith("sqlite"):
        import sqlite3
        conn = sqlite3.connect("app.db", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_conn()
    is_sqlite = DATABASE_URL.startswith("sqlite")
    id_type = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    
    queries = [
        """CREATE TABLE IF NOT EXISTS clients (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, 
            opening_hours_json TEXT NOT NULL, faq_json TEXT NOT NULL, 
            google_credentials TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS messages (
            id {id_type}, client_id TEXT NOT NULL, user_id TEXT NOT NULL, 
            role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sessions (
            client_id TEXT NOT NULL, user_id TEXT NOT NULL, 
            stage TEXT NOT NULL, draft_json TEXT NOT NULL, updated_at TEXT NOT NULL, 
            PRIMARY KEY (client_id, user_id))""",
        f"""CREATE TABLE IF NOT EXISTS appointments (
            id {id_type}, client_id TEXT NOT NULL, user_id TEXT NOT NULL, 
            name TEXT NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL, 
            created_at TEXT NOT NULL, UNIQUE(client_id, date, time))"""
    ]
    try:
        cur = conn.cursor()
        for q in queries: cur.execute(q)
        conn.commit()
    finally: conn.close()

def ensure_default_client(client_id: str):
    conn = get_conn()
    cur = conn.cursor()
    p = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    try:
        cur.execute(f"SELECT id FROM clients WHERE id = {p}", (client_id,))
        if cur.fetchone(): return
        
        # FIX : Horaires incluant le Samedi
        hours = {"mon":{"start":"08:00","end":"18:00"}, "tue":{"start":"08:00","end":"18:00"},
                 "wed":{"start":"08:00","end":"18:00"}, "thu":{"start":"08:00","end":"18:00"},
                 "fri":{"start":"08:00","end":"18:00"}, "sat":{"start":"09:00","end":"13:00"}}
        faq = {"horaires": "Lun-Ven 8h-18h, Sam 9h-13h.", "adresse": "Paris"}
        
        cur.execute(f"INSERT INTO clients (id, name, opening_hours_json, faq_json) VALUES ({p},{p},{p},{p})",
                    (client_id, f"Garage {client_id}", json.dumps(hours), json.dumps(faq)))
        conn.commit()
    finally: conn.close()

def get_client_config(client_id: str):
    conn = get_conn()
    cur = conn.cursor()
    p = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    try:
        cur.execute(f"SELECT * FROM clients WHERE id = {p}", (client_id,))
        row = cur.fetchone()
        if not row:
            ensure_default_client(client_id)
            return get_client_config(client_id)
        return {"id": row["id"], "name": row["name"], 
                "opening_hours": json.loads(row["opening_hours_json"]), 
                "faq": json.loads(row["faq_json"])}
    finally: conn.close()

# --- MESSAGES & HISTORIQUE ---
def save_message(client_id: str, user_id: str, role: str, content: str):
    conn = get_conn()
    cur = conn.cursor()
    p = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    try:
        cur.execute(f"INSERT INTO messages (client_id, user_id, role, content, created_at) VALUES ({p},{p},{p},{p},{p})",
                    (client_id, user_id, role, content, datetime.utcnow().isoformat()))
        conn.commit()
    finally: conn.close()

def get_recent_messages(client_id: str, user_id: str, limit: int = 8):
    conn = get_conn()
    cur = conn.cursor()
    p = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    try:
        cur.execute(f"SELECT role, content FROM messages WHERE client_id={p} AND user_id={p} ORDER BY id DESC LIMIT {limit}", 
                    (client_id, user_id))
        return [{"role": r["role"], "content": r["content"]} for r in reversed(cur.fetchall())]
    finally: conn.close()

# --- SESSIONS ---
def upsert_session(client_id: str, user_id: str, stage: str, draft_json: str):
    conn = get_conn()
    cur = conn.cursor()
    p = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    try:
        query = f"""INSERT INTO sessions (client_id, user_id, stage, draft_json, updated_at) VALUES ({p},{p},{p},{p},{p})
                    ON CONFLICT(client_id, user_id) DO UPDATE SET stage=EXCLUDED.stage, draft_json=EXCLUDED.draft_json, updated_at=EXCLUDED.updated_at"""
        cur.execute(query, (client_id, user_id, stage, draft_json, datetime.utcnow().isoformat()))
        conn.commit()
    finally: conn.close()

def get_session(client_id: str, user_id: str):
    conn = get_conn()
    cur = conn.cursor()
    p = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    try:
        cur.execute(f"SELECT stage, draft_json FROM sessions WHERE client_id={p} AND user_id={p}", (client_id, user_id))
        row = cur.fetchone()
        return {"stage": row["stage"], "draft_json": row["draft_json"]} if row else {"stage": "idle", "draft_json": "{}"}
    finally: conn.close()

def clear_session(client_id: str, user_id: str):
    conn = get_conn()
    cur = conn.cursor()
    p = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    try:
        cur.execute(f"DELETE FROM sessions WHERE client_id={p} AND user_id={p}", (client_id, user_id))
        conn.commit()
    finally: conn.close()

# --- RENDEZ-VOUS ---
def appointment_exists(client_id: str, date: str, time: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    p = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    try:
        cur.execute(f"SELECT 1 FROM appointments WHERE client_id={p} AND date={p} AND time={p} LIMIT 1", (client_id, date, time))
        return cur.fetchone() is not None
    finally: conn.close()

def insert_appointment(client_id: str, user_id: str, name: str, date: str, time: str):
    conn = get_conn()
    cur = conn.cursor()
    p = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    try:
        cur.execute(f"INSERT INTO appointments (client_id, user_id, name, date, time, created_at) VALUES ({p},{p},{p},{p},{p},{p})",
                    (client_id, user_id, name, date, time, datetime.utcnow().isoformat()))
        conn.commit()
    finally: conn.close()

# --- GOOGLE ---
def add_google_column_if_missing():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE clients ADD COLUMN google_credentials TEXT;")
        conn.commit()
    except Exception: conn.rollback()
    finally: conn.close()

def save_google_credentials(client_id, credentials_dict):
    add_google_column_if_missing()
    conn = get_conn()
    cur = conn.cursor()
    p = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    h = json.dumps({"mon":{"start":"08:00","end":"18:00"}, "sat":{"start":"09:00","end":"13:00"}})
    try:
        query = f"INSERT INTO clients (id, name, opening_hours_json, faq_json, google_credentials) VALUES ({p},{p},{p},'{{}}',{p}) ON CONFLICT(id) DO UPDATE SET google_credentials = EXCLUDED.google_credentials"
        cur.execute(query, (client_id, client_id, h, json.dumps(credentials_dict)))
        conn.commit()
    finally: conn.close()

def get_google_credentials(client_id):
    conn = get_conn()
    cur = conn.cursor()
    p = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    try:
        cur.execute(f"SELECT google_credentials FROM clients WHERE id = {p}", (client_id,))
        row = cur.fetchone()
        return json.loads(row['google_credentials']) if row and row['google_credentials'] else None
    except Exception: return None
    finally: conn.close()