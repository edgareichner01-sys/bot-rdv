import json
import re
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

# --- IMPORTS ET CONFIGURATION ---
try:
    from config import OPENAI_API_KEY, OPENAI_MODEL
except ImportError:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = "gpt-3.5-turbo"

from db import (
    get_client_config,
    get_session,
    upsert_session,
    clear_session,
    appointment_exists,
    insert_appointment,
)

from google_services import is_slot_available_google, create_google_event

# =========================================================
# OUTILS DE VALIDATION & HELPER FUNCTIONS
# =========================================================

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

def is_past(date_str: str, time_str: str) -> bool:
    """Vérifie si le créneau est dans le passé par rapport à l'heure actuelle."""
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        # On compare à l'instant T sans les secondes pour la précision
        return dt < datetime.now().replace(second=0, microsecond=0)
    except Exception:
        return False

def in_opening_hours(opening_hours: dict, date_str: str, time_str: str) -> bool:
    """Vérifie les horaires d'ouverture incluant le samedi."""
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        day_key = DAYS[date_obj.weekday()]
        slot = opening_hours.get(day_key)
        
        if not slot: # Garage fermé (ex: Dimanche)
            return False
            
        start = datetime.strptime(slot["start"], "%H:%M").time()
        end = datetime.strptime(slot["end"], "%H:%M").time()
        t = datetime.strptime(time_str, "%H:%M").time()
        
        return start <= t <= end
    except Exception:
        return False

# =========================================================
# EXTRACTION DE DONNÉES (Regex + Intelligence Année)
# =========================================================

def extract_basic_info(message: str) -> Dict[str, Optional[str]]:
    data = {"name": None, "date": None, "time": None}
    msg = message.strip()
    lower = msg.lower()

    # 1. Extraction du Nom (Protection contre les mots-clés)
    blacklist = ["demain", "aujourd'hui", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "rdv", "horaires", "non", "oui", "stop"]
    
    m_name = re.search(r"(je m'appelle|moi c'est|mon nom est)\s+([a-zA-ZÀ-ÿ' -]{2,})", msg, re.I)
    if m_name:
        data["name"] = m_name.group(2).strip()
    elif len(msg.split()) <= 2 and lower not in blacklist and not any(char.isdigit() for char in msg):
        if len(msg) > 1:
            data["name"] = msg

    # 2. Extraction Date (Gestion 2025 -> 2026)
    m_date_no_year = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", msg)
    if m_date_no_year:
        d, m = m_date_no_year.groups()
        now = datetime.now()
        year = now.year
        try:
            # Si le mois demandé est déjà passé dans l'année en cours, on passe à l'année suivante
            if int(m) < now.month or (int(m) == now.month and int(d) < now.day):
                year += 1
            data["date"] = datetime(year, int(m), int(d)).strftime("%Y-%m-%d")
        except ValueError: pass

    # "Demain" / "Après-demain"
    if "demain" in lower:
        data["date"] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    elif "après-demain" in lower:
        data["date"] = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

    # 3. Extraction Heure
    m_time = re.search(r"\b(\d{1,2})(?:[:hH]| ?heures?)?(\d{2})?\b", lower)
    if m_time:
        captured_full = m_time.group(0)
        if any(c in captured_full for c in ['h', ':', 'heure']):
            hh, mm = int(m_time.group(1)), int(m_time.group(2) or 0)
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                data["time"] = f"{hh:02d}:{mm:02d}"

    return data

# =========================================================
# LOGIQUE IA (OpenAI)
# =========================================================

def llm_intent_and_extract(message: str, faq: dict, history: list) -> dict:
    from openai import OpenAI
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        system = (f"Nous sommes le {datetime.now().strftime('%Y-%m-%d')}. Assistant garage. "
                  "Réponds en JSON. Format: {'intent': 'FAQ|BOOK_APPOINTMENT|CONFIRM|CANCEL|OTHER', "
                  "'answer': 'réponse courte', 'name': 'nom', 'date': 'YYYY-MM-DD', 'time': 'HH:MM'}")
        
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": system}] + history[-5:] + [{"role": "user", "content": message}],
            response_format={"type": "json_object"},
            temperature=0
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"❌ Erreur OpenAI : {e}")
        return {"intent": "OTHER", "answer": None, "name": None, "date": None, "time": None}

@dataclass
class BotReply:
    reply: str
    status: str

# =========================================================
# GESTIONNAIRE DE MESSAGES PRINCIPAL
# =========================================================

def handle_message(client_id: str, user_id: str, message: str, history: List[Dict[str, str]]) -> BotReply:
    msg_clean = (message or "").strip().lower()
    cfg = get_client_config(client_id)
    session = get_session(client_id, user_id)
    stage = session["stage"]
    draft = json.loads(session["draft_json"] or "{}")

    # 1. Analyse (Intelligence + Regex de secours)
    result = llm_intent_and_extract(message, cfg["faq"], history)
    regex_data = extract_basic_info(message)
    
    # Mise à jour du brouillon avec persistance (ne pas écraser l'existant si rien de neuf)
    for field in ["name", "date", "time"]:
        val = result.get(field) or regex_data.get(field)
        if val: draft[field] = val

    # Sauvegarde immédiate du contexte
    upsert_session(client_id, user_id, stage, json.dumps(draft))

    # --- ROUTAGE DES INTENTIONS ---

    # CAS A : ANNULATION
    if result.get("intent") == "CANCEL" or msg_clean in ["annuler", "stop"]:
        clear_session(client_id, user_id)
        return BotReply("🚫 L'opération a été annulée. Comment puis-je vous aider ?", "ok")

    # CAS B : CONFIRMATION FINALE
    if stage == "confirming":
        if msg_clean in ["oui", "ok", "d'accord", "confirmer", "yes", "c'est bon"]:
            # Vérification ultime sur Google
            if not is_slot_available_google(client_id, draft["date"], draft["time"]):
                return BotReply("⚠️ Désolé, ce créneau vient juste d'être pris. Une autre heure ?", "needs_info")

            # Création de l'événement Google
            link = create_google_event(
                client_id=client_id,
                date_str=draft["date"],
                time_str=draft["time"],
                summary=f"RDV Garage - {draft['name']}",
                description=f"Rendez-vous confirmé via Chatbot pour {draft['name']}.",
                duration_mins=60
            )

            if link:
                insert_appointment(client_id, user_id, draft["name"], draft["date"], draft["time"])
                clear_session(client_id, user_id)
                # UX MASTERCLASS : Lien Markdown propre
                return BotReply(
                    f"✅ **C'est confirmé pour {draft['name']} !**\n\n"
                    f"Le rendez-vous est bloqué pour le {draft['date']} à {draft['time']}.\n"
                    f"📅 [Cliquez ici pour voir le RDV]({link})", "ok"
                )
            else:
                return BotReply("❌ Erreur lors de la synchronisation avec Google Calendar. Veuillez réessayer.", "ok")

    # CAS C : FAQ
    if result.get("intent") == "FAQ":
        return BotReply(result.get("answer") or "Je n'ai pas cette information, désolé.", "ok")

    # CAS D : PRISE DE RDV / COLLECTE D'INFOS
    if result.get("intent") == "BOOK_APPOINTMENT" or stage in ["collecting", "confirming"]:
        missing = []
        if not draft.get("name"): missing.append("votre nom")
        if not draft.get("date"): missing.append("la date")
        if not draft.get("time"): missing.append("l'heure")

        if missing:
            upsert_session(client_id, user_id, "collecting", json.dumps(draft))
            return BotReply(f"Pour bloquer votre rendez-vous, il me manque : {', '.join(missing)}.", "needs_info")

        # Validation des contraintes métiers
        if is_past(draft["date"], draft["time"]):
            return BotReply(f"📅 Le {draft['date']} est déjà passé. Pourriez-vous choisir une date future ?", "needs_info")
            
        if not in_opening_hours(cfg["opening_hours"], draft["date"], draft["time"]):
            # Message dynamique avec rappel des horaires (fix Edgar)
            return BotReply("Le garage est fermé à ce créneau. Nous sommes ouverts du Lun-Ven (8h-18h) et le Sam (9h-13h).", "needs_info")
            
        if not is_slot_available_google(client_id, draft["date"], draft["time"]):
            return BotReply(f"🚫 Le créneau du {draft['date']} à {draft['time']} est déjà occupé sur notre agenda.", "needs_info")

        # Tout est OK -> Passage en mode confirmation
        upsert_session(client_id, user_id, "confirming", json.dumps(draft))
        return BotReply(f"Dernière étape : je réserve pour **{draft['name']}** le **{draft['date']}** à **{draft['time']}**. Est-ce correct ? (OUI/NON)", "needs_info")

    return BotReply("Bonjour ! Je suis l'assistant du Garage. Voulez-vous prendre un rendez-vous ?", "ok")