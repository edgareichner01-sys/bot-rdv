import os
import json
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

# --- DATABASE_URL ---
try:
    from config import DATABASE_URL
except ImportError:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")


def _is_sqlite() -> bool:
    return DATABASE_URL.startswith("sqlite")


def _ph() -> str:
    """Placeholder SQL selon le moteur."""
    return "?" if _is_sqlite() else "%s"


def get_conn():
    """Connexion DB compatible SQLite (local) et Postgres (Render)."""
    if _is_sqlite():
        conn = sqlite3.connect("app.db", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def _fetchone(cur):
    """fetchone compatible sqlite Row et postgres dict"""
    row = cur.fetchone()
    return row


def init_db():
    conn = get_conn()
    is_sqlite = _is_sqlite()
    id_type = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"

    create_clients = """
    CREATE TABLE IF NOT EXISTS clients (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        opening_hours_json TEXT NOT NULL,
        faq_json TEXT NOT NULL,
        google_credentials TEXT
    )
    """

    create_messages = f"""
    CREATE TABLE IF NOT EXISTS messages (
        id {id_type},
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """

    create_sessions = """
    CREATE TABLE IF NOT EXISTS sessions (
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        draft_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (client_id, user_id)
    )
    """

    create_appointments = f"""
    CREATE TABLE IF NOT EXISTS appointments (
        id {id_type},
        client_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(client_id, date, time)
    )
    """

    try:
        cur = conn.cursor()
        cur.execute(create_clients)
        cur.execute(create_messages)
        cur.execute(create_sessions)
        cur.execute(create_appointments)
        conn.commit()
    finally:
        conn.close()


def ensure_default_client(client_id: str):
    """Crée un client par défaut si absent."""
    conn = get_conn()
    ph = _ph()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT id FROM clients WHERE id = {ph}", (client_id,))
        if cur.fetchone():
            return

        default_hours = {
            "mon": {"start": "09:00", "end": "18:00"},
            "tue": {"start": "09:00", "end": "18:00"},
            "wed": {"start": "09:00", "end": "18:00"},
            "thu": {"start": "09:00", "end": "18:00"},
            "fri": {"start": "09:00", "end": "18:00"},
        }

        default_faq = {
            "horaires": "Nous sommes ouverts du lundi au vendredi de 9h à 18h.",
            "adresse": "Nous sommes au 12 rue de Paris, 75000 Paris.",
            "telephone": "01 23 45 67 89",
            "email": "contact@garage-michel.fr",
        }

        cur.execute(
            f"""
            INSERT INTO clients (id, name, opening_hours_json, faq_json)
            VALUES ({ph}, {ph}, {ph}, {ph})
            """,
            (client_id, f"Client {client_id}", json.dumps(default_hours), json.dumps(default_faq)),
        )
        conn.commit()
    finally:
        conn.close()


def get_client_config(client_id: str):
    conn = get_conn()
    ph = _ph()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM clients WHERE id = {ph}", (client_id,))
        row = _fetchone(cur)
        if not row:
            ensure_default_client(client_id)
            return get_client_config(client_id)

        return {
            "id": row["id"],
            "name": row["name"],
            "opening_hours": json.loads(row["opening_hours_json"]),
            "faq": json.loads(row["faq_json"]),
        }
    finally:
        conn.close()


def save_message(client_id: str, user_id: str, role: str, content: str):
    conn = get_conn()
    ph = _ph()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            INSERT INTO messages (client_id, user_id, role, content, created_at)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph})
            """,
            (client_id, user_id, role, content, datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_messages(client_id: str, user_id: str, limit: int = 8):
    conn = get_conn()
    ph = _ph()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT role, content FROM messages
            WHERE client_id={ph} AND user_id={ph}
            ORDER BY id DESC
            LIMIT {int(limit)}
            """,
            (client_id, user_id),
        )
        rows = cur.fetchall() or []
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    finally:
        conn.close()


def upsert_session(client_id: str, user_id: str, stage: str, draft_json: str):
    conn = get_conn()
    ph = _ph()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            INSERT INTO sessions (client_id, user_id, stage, draft_json, updated_at)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph})
            ON CONFLICT(client_id, user_id)
            DO UPDATE SET
                stage=excluded.stage,
                draft_json=excluded.draft_json,
                updated_at=excluded.updated_at
            """,
            (client_id, user_id, stage, draft_json, datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def get_session(client_id: str, user_id: str):
    conn = get_conn()
    ph = _ph()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT stage, draft_json FROM sessions WHERE client_id={ph} AND user_id={ph}",
            (client_id, user_id),
        )
        row = _fetchone(cur)
        if not row:
            return {"stage": "idle", "draft_json": "{}"}
        return {"stage": row["stage"], "draft_json": row["draft_json"]}
    finally:
        conn.close()


def clear_session(client_id: str, user_id: str):
    conn = get_conn()
    ph = _ph()
    try:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM sessions WHERE client_id={ph} AND user_id={ph}", (client_id, user_id))
        conn.commit()
    finally:
        conn.close()


def appointment_exists(client_id: str, date: str, time: str) -> bool:
    conn = get_conn()
    ph = _ph()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT 1 FROM appointments WHERE client_id={ph} AND date={ph} AND time={ph} LIMIT 1",
            (client_id, date, time),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def insert_appointment(client_id: str, user_id: str, name: str, date: str, time: str) -> bool:
    """True si inséré, False si déjà existant."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        if _is_sqlite():
            cur.execute(
                """
                INSERT OR IGNORE INTO appointments (client_id, user_id, name, date, time, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (client_id, user_id, name, date, time, datetime.utcnow().isoformat()),
            )
            conn.commit()
            return cur.rowcount == 1
        else:
            cur.execute(
                """
                INSERT INTO appointments (client_id, user_id, name, date, time, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (client_id, date, time) DO NOTHING
                """,
                (client_id, user_id, name, date, time, datetime.utcnow().isoformat()),
            )
            conn.commit()
            return cur.rowcount == 1
    finally:
        conn.close()


# ---------------------------
# Google credentials
# ---------------------------

def _add_google_column_if_missing():
    """
    Sécurisé SQLite + Postgres.
    Utile si tu as déjà une vieille DB sans la colonne google_credentials.
    """
    conn = get_conn()
    try:
        cur = conn.cursor()

        if _is_sqlite():
            # SQLite: inspect table columns
            cur.execute("PRAGMA table_info(clients)")
            cols = [r[1] for r in cur.fetchall()]
            if "google_credentials" not in cols:
                cur.execute("ALTER TABLE clients ADD COLUMN google_credentials TEXT")
                conn.commit()
            return

        # Postgres: check information_schema
        cur.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_name='clients' AND column_name='google_credentials'
            LIMIT 1
        """)
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE clients ADD COLUMN google_credentials TEXT")
            conn.commit()

    finally:
        conn.close()


def save_google_credentials(client_id: str, credentials_dict: dict):
    """
    Stocke les credentials Google dans clients.google_credentials (JSON).
    On crée le client s'il n'existe pas.
    """
    _add_google_column_if_missing()
    ensure_default_client(client_id)

    conn = get_conn()
    ph = _ph()
    creds_json = json.dumps(credentials_dict)

    try:
        cur = conn.cursor()
        if _is_sqlite():
            cur.execute(
                f"""
                UPDATE clients
                SET google_credentials = {ph}
                WHERE id = {ph}
                """,
                (creds_json, client_id),
            )
        else:
            cur.execute(
                f"""
                UPDATE clients
                SET google_credentials = {ph}
                WHERE id = {ph}
                """,
                (creds_json, client_id),
            )

        conn.commit()
        print(f"✅ Google credentials sauvegardés pour {client_id}")
    finally:
        conn.close()


def get_google_credentials(client_id: str):
    conn = get_conn()
    ph = _ph()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT google_credentials FROM clients WHERE id = {ph}", (client_id,))
        row = _fetchone(cur)
        if row and row["google_credentials"]:
            return json.loads(row["google_credentials"])
        return None
    except Exception as e:
        print(f"⚠️ Erreur lecture credentials : {e}")
        return None
    finally:
        conn.close()
