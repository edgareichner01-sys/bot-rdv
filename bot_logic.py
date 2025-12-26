import json
import re
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

# --- GESTION IMPORTS ---
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

# NOUVEAU : On importe le checker Google
from google_services import is_slot_available_google

# =========================================================
# OUTILS DE VALIDATION & EXTRACTION
# =========================================================

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

def valid_date(date_str: str) -> bool:
    if not DATE_RE.match(date_str):
        return False
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False

def valid_time(time_str: str) -> bool:
    if not TIME_RE.match(time_str):
        return False
    try:
        datetime.strptime(time_str, "%H:%M")
        return True
    except ValueError:
        return False

def is_past(date_str: str, time_str: str) -> bool:
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return dt < datetime.now()

def in_opening_hours(opening_hours: dict, date_str: str, time_str: str) -> bool:
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    day_key = DAYS[date_obj.weekday()]
    slot = opening_hours.get(day_key)
    if not slot:
        return False
    start = datetime.strptime(slot["start"], "%H:%M").time()
    end = datetime.strptime(slot["end"], "%H:%M").time()
    t = datetime.strptime(time_str, "%H:%M").time()
    return start <= t <= end

def suggest_next_time(time_str: str, minutes: int = 60) -> str:
    t = datetime.strptime(time_str, "%H:%M")
    return (t + timedelta(minutes=minutes)).strftime("%H:%M")

def fallback_intent(message: str) -> str:
    m = message.lower()
    cancel_keywords = ["annuler", "cancel", "stop", "non", "pas de rdv", "pas besoin", "laisse tomber", "abort", "oublie", "quitter"]
    if any(x in m for x in cancel_keywords):
        return "CANCEL"
    if any(x in m for x in ["rdv", "rendez", "rendez-vous", "prendre", "réserver", "dispo"]):
        return "BOOK_APPOINTMENT"
    if any(x in m for x in ["horaire", "ouvert", "adresse", "tarif", "prix", "coût", "tel", "téléphone", "bonjour", "salut"]):
        return "FAQ"
    return "OTHER"

def extract_basic_info(message: str) -> Dict[str, Optional[str]]:
    data = {"name": None, "date": None, "time": None}
    msg = message.strip()

    m_name = re.search(r"(je m'appelle|moi c'est|mon nom est)\s+([a-zA-ZÀ-ÿ' -]{2,})", msg, re.I)
    if m_name:
        data["name"] = m_name.group(2).strip()

    if not data["name"]:
        blacklist = ["demain", "aujourd'hui", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche", "rdv", "rendez-vous", "bonjour", "salut", "non", "oui", "stop"]
        if re.fullmatch(r"[a-zA-ZÀ-ÿ' -]{2,40}", msg) and not re.search(r"\d", msg):
            if msg.lower() not in blacklist:
                words = [w for w in msg.split() if w]
                if 1 <= len(words) <= 3:
                    data["name"] = msg

    m_date_iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", msg)
    if m_date_iso:
        data["date"] = m_date_iso.group(0)

    if not data["date"]:
        m_date_fr = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", msg)
        if m_date_fr:
            d, m, y = m_date_fr.groups()
            try:
                data["date"] = datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d")
            except ValueError: pass

    if not data["date"]:
        m_date_no_year = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", msg)
        if m_date_no_year:
            d, m = m_date_no_year.groups()
            y = datetime.now().year
            try:
                candidate = datetime(y, int(m), int(d))
                if candidate.date() < datetime.now().date():
                    candidate = datetime(y + 1, int(m), int(d))
                data["date"] = candidate.strftime("%Y-%m-%d")
            except ValueError: pass

    lower = msg.lower()
    if "demain" in lower:
        data["date"] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    if "après-demain" in lower:
        data["date"] = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

    m_time = re.search(r"\b(\d{1,2})(?:[:hH]| ?heures?)?(\d{2})?\b", lower)
    if m_time:
        captured_full = m_time.group(0)
        is_explicit_time = any(c in captured_full for c in ['h', ':', 'heure'])
        if is_explicit_time:
            hh = int(m_time.group(1))
            mm = int(m_time.group(2) or 0)
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                data["time"] = f"{hh:02d}:{mm:02d}"

    return data

@dataclass
class BotReply:
    reply: str
    status: str

# =========================================================
# IA / LLM (Avec gestion erreur comme avant)
# =========================================================

def llm_intent_and_extract(message: str, faq: dict, history: List[Dict[str, str]]) -> Dict[str, Any]:
    # 1. Vérification de la présence de la clé
    if not OPENAI_API_KEY:
        print("⚠️ ALERTE : Pas de clé OPENAI_API_KEY détectée dans le code !")
        intent = fallback_intent(message)
        data = extract_basic_info(message)
        return {"intent": intent, "answer": None, **data}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        faq_text = "\n".join([f"- {k}: {v}" for k, v in faq.items()])

        # On simplifie le prompt pour garantir le JSON
        system = f"""
Nous sommes le {now_str}.
Tu es un assistant de prise de rendez-vous pour un garage.
Ton but est d'extraire les informations ou de répondre aux questions FAQ.

RÈGLES STRICTES DE RÉPONSE (JSON ONLY) :
Tu dois répondre UNIQUEMENT avec un objet JSON valide. Pas de texte avant ni après.
Format attendu :
{{
  "intent": "FAQ" | "BOOK_APPOINTMENT" | "CONFIRM" | "CANCEL" | "OTHER",
  "answer": "Texte de la réponse si FAQ, sinon null",
  "name": "Nom du client ou null",
  "date": "YYYY-MM-DD ou null (convertis les 'lundi prochain', 'demain' etc)",
  "time": "HH:MM ou null"
}}

FAQ du garage :
{faq_text}
""".strip()

        input_messages = [{"role": "system", "content": system}]
        for h in history[-6:]:
            input_messages.append(h)
        input_messages.append({"role": "user", "content": message})

        print("🤖 Appel OpenAI Standard...") 
        
        # UTILISATION DE LA MÉTHODE STANDARD (ChatCompletion)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=input_messages,
            response_format={"type": "json_object"}, # Force le mode JSON
            temperature=0
        )
        
        content = response.choices[0].message.content
        print(f"✅ Réponse OpenAI reçue : {content}")
        return json.loads(content)

    except Exception as e:
        print(f"❌ ERREUR CRITIQUE OPENAI : {str(e)}")
        intent = fallback_intent(message)
        data = extract_basic_info(message)
        return {"intent": intent, "answer": None, **data}

# =========================================================
# LOGIQUE PRINCIPALE
# =========================================================

def handle_message(client_id: str, user_id: str, message: str, history: List[Dict[str, str]]) -> BotReply:
    msg = (message or "").strip().lower()
    cfg = get_client_config(client_id)
    opening_hours = cfg["opening_hours"]
    faq = cfg["faq"]

    session = get_session(client_id, user_id)
    stage = session["stage"]
    draft = json.loads(session["draft_json"] or "{}")
    changed = False

    # 1. ANALYSE
    result = llm_intent_and_extract(message, faq, history)
    intent = result.get("intent", "OTHER")
    
    regex_data = extract_basic_info(message)
    extracted_name = result.get("name") or regex_data.get("name")
    extracted_date = result.get("date") or regex_data.get("date")
    extracted_time = result.get("time") or regex_data.get("time")

    # --- CAS 1 : ANNULATION ---
    cancel_keywords = ["annuler", "cancel", "stop", "non", "pas de rdv", "pas besoin", "laisse tomber", "abort", "oublie", "quitter"]
    if intent == "CANCEL" or any(kw in msg for kw in cancel_keywords):
        clear_session(client_id, user_id)
        return BotReply("🚫 C'est noté, j'annule tout.", "ok")

    # --- CAS 2 : CONFIRMATION ---
    if stage == "confirming":
        # A) Confirmation explicite
        if intent == "CONFIRM" or msg in ["oui", "ok", "d'accord", "je confirme", "yes"]:
            name, date, time = draft.get("name"), draft.get("date"), draft.get("time")
            
            # VERIF ULTIME : DB Locale + Google Agenda
            is_taken_local = appointment_exists(client_id, date, time)
            is_taken_google = not is_slot_available_google(client_id, date, time) # <-- Le Check Google

            if is_taken_local or is_taken_google:
                alt = suggest_next_time(time, 60)
                upsert_session(client_id, user_id, "collecting", json.dumps(draft))
                raison = "déjà pris dans ma base" if is_taken_local else "occupé sur votre Google Agenda"
                return BotReply(f"⚠️ Aïe, ce créneau est {raison}. Tu veux plutôt **{alt}** ?", "needs_info")
            
            insert_appointment(client_id, user_id, name, date, time)
            clear_session(client_id, user_id)
            return BotReply(f"✅ C'est confirmé **{name}** ! RDV le **{date}** à **{time}**.", "ok")

        # B) Modification
        if extracted_name: draft["name"] = extracted_name; changed = True
        if extracted_date: draft["date"] = extracted_date; changed = True
        if extracted_time: draft["time"] = extracted_time; changed = True
        
        if changed:
            upsert_session(client_id, user_id, "collecting", json.dumps(draft))
            pass 
        else:
            if intent == "FAQ":
                clear_session(client_id, user_id)
            else:
                return BotReply("Je n'ai pas compris. Réponds **OUI** ou change l'heure.", "needs_info")

    # --- CAS 3 : FAQ ---
    if intent == "FAQ":
        # ... (Logique FAQ habituelle) ...
        if "horaire" in msg: return BotReply(faq.get("horaires"), "ok")
        if "adresse" in msg: return BotReply(faq.get("adresse"), "ok")
        if result.get("answer"): return BotReply(result.get("answer"), "ok")
        # Petit message d'accueil sympa si on détecte "Bonjour" via fallback
        if "bonjour" in msg or "salut" in msg:
             return BotReply("Bonjour ! 👋 Je suis l'assistant du garage. Comment puis-je vous aider ?", "ok")
        return BotReply("Tu veux les horaires ou l'adresse ?", "ok")

    # --- CAS 4 : PRISE DE RDV ---
    if intent == "BOOK_APPOINTMENT" or stage == "collecting" or (stage == "confirming" and changed):
        if extracted_name: draft["name"] = extracted_name
        if extracted_date: draft["date"] = extracted_date
        if extracted_time: draft["time"] = extracted_time

        if draft.get("date") and not valid_date(draft["date"]): draft["date"] = None
        if draft.get("time") and not valid_time(draft["time"]): draft["time"] = None

        missing = []
        if not draft.get("name"): missing.append("ton nom")
        if not draft.get("date"): missing.append("la date")
        if not draft.get("time"): missing.append("l'heure")

        if missing:
            upsert_session(client_id, user_id, "collecting", json.dumps(draft))
            return BotReply(f"Ça marche. Il me manque juste : {', '.join(missing)}.", "needs_info")

        # Vérifications
        if is_past(draft["date"], draft["time"]):
            return BotReply("Ce créneau est passé.", "needs_info")
        
        if not in_opening_hours(opening_hours, draft["date"], draft["time"]):
            return BotReply("Le garage est fermé à cette heure-là.", "needs_info")

        # VERIF INTERMÉDIAIRE (Pour ne pas proposer un créneau pris)
        # On vérifie Google ici aussi
        if not is_slot_available_google(client_id, draft["date"], draft["time"]):
             alt = suggest_next_time(draft["time"], 60)
             return BotReply(f"⚠️ Oups, l'agenda Google indique que c'est occupé à cette heure. Essaye vers **{alt}** ?", "needs_info")
             
        if appointment_exists(client_id, draft["date"], draft["time"]):
            alt = suggest_next_time(draft["time"], 60)
            return BotReply(f"Ce créneau est déjà pris (autre client). Tu es dispo à **{alt}** ?", "needs_info")

        upsert_session(client_id, user_id, "confirming", json.dumps(draft))
        return BotReply(
            f"Je récapitule : RDV pour **{draft['name']}** le **{draft['date']}** à **{draft['time']}**.\nC'est bon ? (Réponds OUI)",
            "needs_info"
        )

    return BotReply("Je suis l'assistant du garage. Je peux te donner les horaires ou prendre un rendez-vous.", "ok")