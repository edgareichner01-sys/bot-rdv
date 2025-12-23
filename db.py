import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from config import DATABASE_URL

# Fonction utilitaire pour se connecter
def get_conn():
    # Si c'est encore l'URL SQLite locale (cas de dev local sans Docker), on prévient
    if DATABASE_URL.startswith("sqlite"):
        import sqlite3
        conn = sqlite3.connect("app.db", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    
    # Sinon, c'est PostgreSQL (Render)
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_conn()
    
    # Adaptation SQLite vs Postgres pour la création automatique des ID
    # En Postgres, on utilise "SERIAL PRIMARY KEY". En SQLite "INTEGER PRIMARY KEY AUTOINCREMENT"
    is_sqlite = DATABASE_URL.startswith("sqlite")
    id_type = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    
    # Création des tables
    create_clients = f"""
    CREATE TABLE IF NOT EXISTS clients (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        opening_hours_json TEXT NOT NULL,
        faq_json TEXT NOT NULL
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
    conn = get_conn()
    cur = conn.cursor()
    
    # Syntax SQL: %s pour Postgres, ? pour SQLite
    placeholder = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    
    try:
        # Note: on utilise des tuples (valeur,) pour éviter les injections SQL
        query_check = f"SELECT id FROM clients WHERE id = {placeholder}"
        cur.execute(query_check, (client_id,))
        if cur.fetchone():
            return

        default_hours = {
            "mon": {"start": "09:00", "end": "18:00"},
            "tue": {"start": "09:00", "end": "18:00"},
            "wed": {"start": "09:00", "end": "18:00"},
            "thu": {"start": "09:00", "end": "18:00"},
            "fri": {"start": "09:00", "end": "18:00"}
        }
        
        default_faq = {
            "horaires": "Nous sommes ouverts du lundi au vendredi de 9h à 18h.",
            "adresse": "Nous sommes au 12 rue de Paris, 75000 Paris.",
            "telephone": "01 23 45 67 89",
            "email": "contact@garage-michel.fr"
        }

        query_insert = f"INSERT INTO clients (id, name, opening_hours_json, faq_json) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})"
        cur.execute(
            query_insert,
            (client_id, f"Client {client_id}", json.dumps(default_hours), json.dumps(default_faq))
        )
        conn.commit()
    finally:
        conn.close()

def get_client_config(client_id: str):
    conn = get_conn()
    cur = conn.cursor()
    placeholder = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    
    try:
        query = f"SELECT * FROM clients WHERE id = {placeholder}"
        cur.execute(query, (client_id,))
        row = cur.fetchone() 
        if not row:
            # Fallback si le client n'existe pas encore
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
    cur = conn.cursor()
    placeholder = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    
    try:
        query = f"""
            INSERT INTO messages (client_id, user_id, role, content, created_at)
            VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
        """
        cur.execute(query, (client_id, user_id, role, content, datetime.utcnow().isoformat()))
        conn.commit()
    finally:
        conn.close()

def get_recent_messages(client_id: str, user_id: str, limit: int = 8):
    conn = get_conn()
    cur = conn.cursor()
    placeholder = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    
    try:
        query = f"""
            SELECT role, content FROM messages
            WHERE client_id={placeholder} AND user_id={placeholder}
            ORDER BY id DESC
            LIMIT {limit}
        """
        cur.execute(query, (client_id, user_id))
        rows = cur.fetchall()
        # On remet dans l'ordre chronologique
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    finally:
        conn.close()

def upsert_session(client_id: str, user_id: str, stage: str, draft_json: str):
    conn = get_conn()
    cur = conn.cursor()
    placeholder = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    
    try:
        # Syntaxe UPSERT compatible Postgres (ON CONFLICT)
        query = f"""
            INSERT INTO sessions (client_id, user_id, stage, draft_json, updated_at)
            VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            ON CONFLICT(client_id, user_id)
            DO UPDATE SET stage=excluded.stage, draft_json=excluded.draft_json, updated_at=excluded.updated_at
        """
        cur.execute(query, (client_id, user_id, stage, draft_json, datetime.utcnow().isoformat()))
        conn.commit()
    finally:
        conn.close()

def get_session(client_id: str, user_id: str):
    conn = get_conn()
    cur = conn.cursor()
    placeholder = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    
    try:
        query = f"SELECT stage, draft_json FROM sessions WHERE client_id={placeholder} AND user_id={placeholder}"
        cur.execute(query, (client_id, user_id))
        row = cur.fetchone()
        if not row:
            return {"stage": "idle", "draft_json": "{}"}
        return {"stage": row["stage"], "draft_json": row["draft_json"]}
    finally:
        conn.close()

def clear_session(client_id: str, user_id: str):
    conn = get_conn()
    cur = conn.cursor()
    placeholder = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    
    try:
        query = f"DELETE FROM sessions WHERE client_id={placeholder} AND user_id={placeholder}"
        cur.execute(query, (client_id, user_id))
        conn.commit()
    finally:
        conn.close()

def appointment_exists(client_id: str, date: str, time: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    placeholder = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    
    try:
        query = f"SELECT 1 FROM appointments WHERE client_id={placeholder} AND date={placeholder} AND time={placeholder} LIMIT 1"
        cur.execute(query, (client_id, date, time))
        return cur.fetchone() is not None
    finally:
        conn.close()

def insert_appointment(client_id: str, user_id: str, name: str, date: str, time: str):
    conn = get_conn()
    cur = conn.cursor()
    placeholder = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    
    try:
        query = f"""
            INSERT INTO appointments (client_id, user_id, name, date, time, created_at)
            VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
        """
        cur.execute(query, (client_id, user_id, name, date, time, datetime.utcnow().isoformat()))
        conn.commit()
    finally:
        conn.close()


# --- Ajoute ça à la fin de db.py ---

# (Pas besoin de réimporter json ici, il est déjà en haut du fichier)

def add_google_column_if_missing():
    """Ajoute la colonne google_credentials si elle n'existe pas encore"""
    conn = get_conn()  # <--- CORRECTION ICI (c'était get_db_connection)
    cur = conn.cursor()
    try:
        # On essaie d'ajouter la colonne.
        cur.execute("ALTER TABLE clients ADD COLUMN google_credentials TEXT;")
        conn.commit()
    except Exception as e:
        # Si l'erreur est "la colonne existe déjà", on annule et on continue
        conn.rollback()
    finally:
        cur.close()
        conn.close()

def save_google_credentials(client_id, credentials_dict):
    """Sauvegarde les clés Google (sous forme de texte) pour un client"""
    # 1. On s'assure que la colonne existe
    add_google_column_if_missing()
    
    # 2. On transforme le dictionnaire (JSON) en texte
    creds_json = json.dumps(credentials_dict)
    
    conn = get_conn()  # <--- CORRECTION ICI (c'était get_db_connection)
    cur = conn.cursor()
    
    # Petite astuce : on vérifie si on est sur SQLite ou Postgres pour le placeholder
    placeholder = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    
    try:
        # On met à jour le client
        query = f"UPDATE clients SET google_credentials = {placeholder} WHERE id = {placeholder}"
        cur.execute(query, (creds_json, client_id))
        conn.commit()
        print(f"✅ Clés Google sauvegardées pour {client_id}")
    except Exception as e:
        print(f"❌ Erreur sauvegarde crédentials : {e}")
    finally:
        cur.close()
        conn.close()

def get_google_credentials(client_id):
    """Récupère les identifiants Google pour un client donné"""
    conn = get_conn()
    cur = conn.cursor()
    placeholder = "?" if DATABASE_URL.startswith("sqlite") else "%s"
    
    try:
        # On sélectionne la colonne google_credentials dans la table clients
        query = f"SELECT google_credentials FROM clients WHERE id = {placeholder}"
        cur.execute(query, (client_id,))
        row = cur.fetchone()
        
        # On vérifie si on a un résultat et si la colonne contient des données
        if row and row['google_credentials']:
            return json.loads(row['google_credentials'])
        return None
    except Exception as e:
        print(f"⚠️ Erreur lecture credentials : {e}")
        return None
    finally:
        conn.close()