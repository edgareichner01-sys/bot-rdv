import json
import re
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

# --- CONFIGURATION ---
try:
    from config import OPENAI_API_KEY, OPENAI_MODEL
except ImportError:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = "gpt-3.5-turbo"

from db import (
    get_client_config, get_session, upsert_session,
    clear_session, appointment_exists, insert_appointment
)
from google_services import is_slot_available_google, create_google_event

# --- OUTILS DE VALIDATION ---
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

def is_past(date_str: str, time_str: str) -> bool:
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        return dt < datetime.now().replace(second=0, microsecond=0)
    except: return False

def in_opening_hours(opening_hours: dict, date_str: str, time_str: str) -> bool:
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        day_key = DAYS[date_obj.weekday()]
        slot = opening_hours.get(day_key)
        if not slot: return False
        start = datetime.strptime(slot["start"], "%H:%M").time()
        end = datetime.strptime(slot["end"], "%H:%M").time()
        t = datetime.strptime(time_str, "%H:%M").time()
        return start <= t <= end
    except: return False

# --- EXTRACTION ET LOGIQUE ANNÉE 2026 ---
def extract_basic_info(message: str) -> Dict[str, Optional[str]]:
    data = {"name": None, "date": None, "time": None}
    msg = message.strip()
    lower = msg.lower()

    # 1. NOM : Filtrage strict (évite de prendre "Bonjour" pour un nom)
    blacklist = ["demain", "aujourd'hui", "rdv", "horaires", "non", "oui", "stop", "bonjour", "salut", "prendre", "le", "un"]
    m_name = re.search(r"(je m'appelle|moi c'est|mon nom est)\s+([a-zA-ZÀ-ÿ' -]{2,})", msg, re.I)
    if m_name:
        data["name"] = m_name.group(2).strip()
    elif len(msg.split()) <= 2 and not any(char.isdigit() for char in msg):
        clean_words = lower.replace('?', '').replace('!', '').split()
        if not any(word in blacklist for word in clean_words) and len(msg) > 1:
            data["name"] = msg

    # 2. DATE : Bascule auto 2025 -> 2026 si le mois est déjà passé
    m_date = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", msg)
    if m_date:
        d, m = m_date.groups()
        now = datetime.now()
        year = now.year
        if int(m) < now.month or (int(m) == now.month and int(d) < now.day):
            year += 1
        try: data["date"] = datetime(year, int(m), int(d)).strftime("%Y-%m-%d")
        except: pass

    if "demain" in lower: data["date"] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    # 3. HEURE
    m_time = re.search(r"\b(\d{1,2})(?:[:hH]| ?heures?)?(\d{2})?\b", lower)
    if m_time and any(c in m_time.group(0) for c in ['h', ':', 'heure']):
        hh, mm = int(m_time.group(1)), int(m_time.group(2) or 0)
        if 0 <= hh <= 23 and 0 <= mm <= 59: data["time"] = f"{hh:02d}:{mm:02d}"

    return data

@dataclass
class BotReply:
    reply: str
    status: str

def llm_intent_and_extract(message: str, history: list) -> dict:
    from openai import OpenAI
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        system = f"Date: {datetime.now().strftime('%Y-%m-%d')}. Assistant garage. Réponds en JSON: {{'intent': 'FAQ|BOOK_APPOINTMENT|CONFIRM|CANCEL|OTHER', 'answer': 'string', 'name': 'string', 'date': 'YYYY-MM-DD', 'time': 'HH:MM'}}"
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": system}] + history[-5:] + [{"role": "user", "content": message}],
            response_format={"type": "json_object"}, temperature=0
        )
        return json.loads(response.choices[0].message.content)
    except: return {"intent": "OTHER"}

def handle_message(client_id: str, user_id: str, message: str, history: List[Dict[str, str]]) -> BotReply:
    msg_clean = (message or "").strip().lower()
    cfg = get_client_config(client_id)
    session = get_session(client_id, user_id)
    stage, draft = session["stage"], json.loads(session["draft_json"] or "{}")

    # Analyse et maintien du contexte (Mémoire)
    result = llm_intent_and_extract(message, history)
    regex = extract_basic_info(message)
    for f in ["name", "date", "time"]:
        val = result.get(f) or regex.get(f)
        if val: draft[f] = val
    upsert_session(client_id, user_id, stage, json.dumps(draft))

    if result.get("intent") == "CANCEL" or msg_clean in ["annuler", "stop"]:
        clear_session(client_id, user_id); return BotReply("🚫 Opération annulée.", "ok")

    # ÉTAPE : CONFIRMATION (Action Secrétaire)
    if stage == "confirming" and msg_clean in ["oui", "ok", "d'accord", "yes"]:
        if not is_slot_available_google(client_id, draft["date"], draft["time"]):
            return BotReply("⚠️ Ce créneau vient d'être pris. Une autre heure ?", "needs_info")
        
        link = create_google_event(client_id, draft["date"], draft["time"], f"RDV - {draft['name']}")
        if link:
            insert_appointment(client_id, user_id, draft["name"], draft["date"], draft["time"])
            clear_session(client_id, user_id)
            return BotReply(f"✅ **C'est tout bon, {draft['name']} !**\n\nVotre rendez-vous est bloqué dans notre planning pour le {draft['date']} à {draft['time']}.\n📅 [Voir le rendez-vous]({link})", "ok")
        return BotReply("❌ Erreur lors de la création Google.", "ok")

    if result.get("intent") == "FAQ": return BotReply(result.get("answer") or "Je n'ai pas l'info.", "ok")

    # ÉTAPE : COLLECTE ET VÉRIFICATION
    if result.get("intent") == "BOOK_APPOINTMENT" or stage in ["collecting", "confirming"]:
        missing = []
        if not draft.get("name"): missing.append("votre nom")
        if not draft.get("date"): missing.append("la date")
        if not draft.get("time"): missing.append("l'heure")
        if missing:
            upsert_session(client_id, user_id, "collecting", json.dumps(draft))
            return BotReply(f"Il me manque : {', '.join(missing)}.", "needs_info")

        if is_past(draft["date"], draft["time"]): return BotReply("📅 Ce créneau est déjà passé.", "needs_info")
        if not in_opening_hours(cfg["opening_hours"], draft["date"], draft["time"]):
            return BotReply("Le garage est fermé à cette heure-là.", "needs_info")
        if not is_slot_available_google(client_id, draft["date"], draft["time"]):
            return BotReply("🚫 Ce créneau est déjà occupé dans notre agenda.", "needs_info")

        upsert_session(client_id, user_id, "confirming", json.dumps(draft))
        return BotReply(f"Je réserve pour **{draft['name']}** le **{draft['date']}** à **{draft['time']}**. C'est bon ? (OUI/NON)", "needs_info")

    return BotReply("Bonjour ! Comment puis-je vous aider ?", "ok")