import json
import re
import os
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo

# --- CONFIGURATION ---
PARIS_TZ = ZoneInfo("Europe/Paris")
LOG = logging.getLogger(__name__)
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

try:
    from config import OPENAI_API_KEY, OPENAI_MODEL
except ImportError:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = "gpt-3.5-turbo-0125"

from db import (
    get_client_config, get_session, upsert_session,
    clear_session, appointment_exists, insert_appointment
)
from google_services import is_slot_available_google, create_google_event

@dataclass
class BotReply:
    reply: str
    status: str

# --- ENGINE : VALIDATION ---

def get_now_paris() -> datetime:
    return datetime.now(PARIS_TZ)

def is_past(date_str: str, time_str: str) -> bool:
    try:
        target_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=PARIS_TZ)
        return target_dt < (get_now_paris() + timedelta(minutes=2))
    except: return True

def in_opening_hours(opening_hours: dict, date_str: str, time_str: str) -> bool:
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        day_key = DAYS[date_obj.weekday()]
        slot = opening_hours.get(day_key)
        if not slot: return False
        t, s, e = [datetime.strptime(x, "%H:%M").time() for x in [time_str, slot["start"], slot["end"]]]
        return s <= t <= e
    except: return False

# --- ENGINE : EXTRACTION ---

def extract_regex_info(message: str) -> Dict[str, Optional[str]]:
    data = {"name": None, "date": None, "time": None}
    msg = message.strip()
    lower = msg.lower()

    # Capture du nom
    blacklist = ["demain", "aujourd'hui", "rdv", "horaires", "non", "oui", "stop", "bonjour", "salut"]
    m_name = re.search(r"(je m'appelle|moi c'est|mon nom est|c'est)\s+([a-zA-ZÀ-ÿ' -]{2,})", msg, re.I)
    if m_name:
        data["name"] = m_name.group(2).strip()
    elif len(msg.split()) <= 2 and not any(char.isdigit() for char in msg):
        if not any(word in blacklist for word in lower.split()):
            data["name"] = msg

    # Capture Date / Heure
    m_date = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", msg)
    if m_date:
        d, m = map(int, m_date.groups())
        now = get_now_paris()
        year = now.year + 1 if (m < now.month or (m == now.month and d < now.day)) else now.year
        try: data["date"] = datetime(year, m, d).strftime("%Y-%m-%d")
        except: pass

    m_time = re.search(r"\b(\d{1,2})[hH:](\d{2})?\b", lower)
    if m_time:
        hh, mm = int(m_time.group(1)), int(m_time.group(2) or 0)
        if 0 <= hh < 24 and 0 <= mm < 60: data["time"] = f"{hh:02d}:{mm:02d}"
            
    return data

def llm_process(message: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    from openai import OpenAI
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        # FIX : Inclusion impérative du mot 'json' pour éviter l'erreur 400
        prompt = (
            f"Date actuelle: {get_now_paris().strftime('%Y-%m-%d')}. "
            "Tu es l'assistant du Garage Michel. Extrais les infos suivantes au format **json** : "
            "{'intent': 'FAQ|BOOK_APPOINTMENT|CONFIRM|CANCEL', 'name': 'string|null', 'date': 'YYYY-MM-DD', 'time': 'HH:MM'}"
        )
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": prompt}] + history[-5:] + [{"role": "user", "content": message}],
            response_format={"type": "json_object"}, 
            temperature=0
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"Erreur OpenAI: {e}") # Pour voir l'erreur dans les logs Render
        return {"intent": "OTHER"}

# --- CORE LOGIC ---

def handle_message(client_id: str, user_id: str, message: str, history: List[Dict[str, str]]) -> BotReply:
    msg_clean = (message or "").strip().lower()
    cfg = get_client_config(client_id)
    session = get_session(client_id, user_id)
    draft = json.loads(session["draft_json"] or "{}")
    stage = session["stage"]

    # Extraction
    llm_data = llm_process(message, history)
    regex_data = extract_regex_info(message)
    
    # Mise à jour sélective (évite d'écraser avec du vide)
    for key in ["name", "date", "time"]:
        val = llm_data.get(key) or regex_data.get(key)
        if val and str(val).lower() not in ["null", "none", "string", ""]:
            draft[key] = val
    
    upsert_session(client_id, user_id, stage, json.dumps(draft))

    # Intent Fallback
    intent = llm_data.get("intent", "OTHER")
    if any(k in msg_clean for k in ["rdv", "rendez-vous", "prendre", "réserver"]):
        intent = "BOOK_APPOINTMENT"

    if intent == "CANCEL" or msg_clean in ["annuler", "stop"]:
        clear_session(client_id, user_id)
        return BotReply("🚫 L'opération a été annulée.", "ok")

    # Machine à états
    if stage == "confirming" and any(word in msg_clean for word in ["oui", "ok", "d'accord", "yes"]):
        if not is_slot_available_google(client_id, draft["date"], draft["time"]):
            return BotReply("⚠️ Ce créneau vient d'être réservé. Une autre heure ?", "needs_info")
        if create_google_event(client_id, draft["date"], draft["time"], f"RDV - {draft['name']}"):
            insert_appointment(client_id, user_id, draft["name"], draft["date"], draft["time"])
            clear_session(client_id, user_id)
            return BotReply(f"✅ **C'est tout bon, {draft['name']} !**\nVotre rendez-vous est bloqué pour le {draft['date']} à {draft['time']}.", "ok")
        return BotReply("❌ Erreur Google.", "ok")

    if intent == "BOOK_APPOINTMENT" or stage in ["collecting", "confirming"]:
        missing = [m for m, v in [("votre nom", "name"), ("la date", "date"), ("l'heure", "time")] if not draft.get(v)]
        if missing:
            upsert_session(client_id, user_id, "collecting", json.dumps(draft))
            return BotReply(f"Pour organiser cela, il me manque : {', '.join(missing)}.", "needs_info")

        if is_past(draft["date"], draft["time"]):
            return BotReply("📅 Ce créneau est déjà passé. Un autre horaire ?", "needs_info")
        if not in_opening_hours(cfg["opening_hours"], draft["date"], draft["time"]):
            return BotReply("Le garage est fermé à cette heure-là.", "needs_info")
        if not is_slot_available_google(client_id, draft["date"], draft["time"]):
            return BotReply("🚫 Ce créneau est déjà occupé.", "needs_info")

        upsert_session(client_id, user_id, "confirming", json.dumps(draft))
        return BotReply(f"Je réserve pour **{draft['name']}** le **{draft['date']}** à **{draft['time']}**. C'est bon ? (OUI/NON)", "needs_info")

    return BotReply(llm_data.get("answer") or "Bonjour ! Comment puis-je vous aider ?", "ok")