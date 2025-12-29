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

    # Capture du nom avec mots-clés (en bonus)
    m_name = re.search(r"(je m'appelle|moi c'est|mon nom est|c'est)\s+([a-zA-ZÀ-ÿ' -]{2,})", msg, re.I)
    if m_name:
        data["name"] = m_name.group(2).strip()

    # Capture Date JJ/MM
    m_date = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", msg)
    if m_date:
        d, m = map(int, m_date.groups())
        now = get_now_paris()
        year = now.year + 1 if (m < now.month or (m == now.month and d < now.day)) else now.year
        try: data["date"] = datetime(year, m, d).strftime("%Y-%m-%d")
        except: pass

    # Capture Heure HH:MM
    m_time = re.search(r"\b(\d{1,2})[hH:](\d{2})?\b", lower)
    if m_time:
        hh, mm = int(m_time.group(1)), int(m_time.group(2) or 0)
        if 0 <= hh < 24 and 0 <= mm < 60: data["time"] = f"{hh:02d}:{mm:02d}"
            
    return data

def llm_process(message: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    from openai import OpenAI
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        # Le mot 'json' est obligatoire pour éviter l'erreur 400
        prompt = (
            f"Date: {get_now_paris().strftime('%Y-%m-%d')}. Assistant Garage Michel. "
            "Extrais les infos au format json : {'intent': 'FAQ|BOOK_APPOINTMENT|CONFIRM|CANCEL', "
            "'name': 'string|null', 'date': 'YYYY-MM-DD', 'time': 'HH:MM'}. "
            "Si l'utilisateur salue simplement, le name est null."
        )
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": prompt}] + history[-5:] + [{"role": "user", "content": message}],
            response_format={"type": "json_object"}, temperature=0
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"Erreur OpenAI: {e}")
        return {"intent": "OTHER"}

# --- CORE LOGIC ---

def handle_message(client_id: str, user_id: str, message: str, history: List[Dict[str, str]]) -> BotReply:
    msg_clean = (message or "").strip()
    msg_lower = msg_clean.lower()
    cfg = get_client_config(client_id)
    session = get_session(client_id, user_id)
    draft = json.loads(session["draft_json"] or "{}")
    stage = session["stage"]

    # 1. Extraction initiale
    llm_data = llm_process(message, history)
    regex_data = extract_regex_info(message)
    
    # 2. LOGIQUE DE CAPTURE DU NOM (Ta demande spécifique)
    blacklist_salutations = ["bonjour", "bonsoir", "salut", "hello", "rdv", "rendez-vous", "rendez vous"]
    
    # On cherche d'abord si un nom est extrait explicitement
    extracted_name = llm_data.get("name") or regex_data.get("name")
    
    # SI le bot a déjà demandé des infos ET qu'on n'a toujours pas de nom :
    if stage == "collecting" and not draft.get("name"):
        # SI ce n'est pas une salutation ET que ce n'est pas une date/heure :
        if msg_lower not in blacklist_salutations and not regex_data.get("date") and not regex_data.get("time"):
            # ALORS on considère que le message entier est le nom (ex: "Basile")
            extracted_name = msg_clean

    # Mise à jour du brouillon (ne jamais écraser par du vide)
    for key in ["name", "date", "time"]:
        val = extracted_name if key == "name" else (llm_data.get(key) or regex_data.get(key))
        if val and str(val).lower() not in ["null", "none", "string", ""]:
            draft[key] = val
    
    upsert_session(client_id, user_id, stage, json.dumps(draft))

    # 3. Détection d'Intention
    intent = llm_data.get("intent", "OTHER")
    if any(k in msg_lower for k in ["rdv", "rendez-vous", "prendre", "réserver"]):
        intent = "BOOK_APPOINTMENT"

    if intent == "CANCEL" or msg_lower in ["annuler", "stop"]:
        clear_session(client_id, user_id); return BotReply("🚫 Opération annulée.", "ok")

    # 4. Machine à états
    if stage == "confirming" and any(word in msg_lower for word in ["oui", "ok", "d'accord", "yes"]):
        if not is_slot_available_google(client_id, draft["date"], draft["time"]):
            return BotReply("⚠️ Créneau pris entre temps. Autre heure ?", "needs_info")
        if create_google_event(client_id, draft["date"], draft["time"], f"RDV - {draft['name']}"):
            insert_appointment(client_id, user_id, draft["name"], draft["date"], draft["time"])
            clear_session(client_id, user_id)
            return BotReply(f"✅ **C'est bon, {draft['name']} !**\nRDV le {draft['date']} à {draft['time']}.", "ok")
        return BotReply("❌ Erreur Google.", "ok")

    if intent == "BOOK_APPOINTMENT" or stage in ["collecting", "confirming"]:
        # Vérification de ce qu'il manque
        missing = []
        if not draft.get("name"): missing.append("votre nom")
        if not draft.get("date"): missing.append("la date")
        if not draft.get("time"): missing.append("l'heure")
        
        if missing:
            upsert_session(client_id, user_id, "collecting", json.dumps(draft))
            return BotReply(f"Il me manque : {', '.join(missing)}.", "needs_info")

        # Validations
        if is_past(draft["date"], draft["time"]):
            return BotReply("📅 Ce créneau est déjà passé. Un autre horaire ?", "needs_info")
        if not in_opening_hours(cfg["opening_hours"], draft["date"], draft["time"]):
            return BotReply("Le garage est fermé à cette heure-là.", "needs_info")
        if not is_slot_available_google(client_id, draft["date"], draft["time"]):
            return BotReply("🚫 Ce créneau est déjà occupé.", "needs_info")

        upsert_session(client_id, user_id, "confirming", json.dumps(draft))
        return BotReply(f"Je réserve pour **{draft['name']}** le **{draft['date']}** à **{draft['time']}**. C'est bon ? (OUI/NON)", "needs_info")

    return BotReply(llm_data.get("answer") or "Bonjour ! Comment puis-je vous aider ?", "ok")