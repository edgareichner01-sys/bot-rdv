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
    # Mots-clés élargis pour l'annulation
    if any(x in m for x in ["annuler", "cancel", "stop", "non", "pas de rdv", "pas besoin", "laisse tomber", "abort"]):
        return "CANCEL"
    if any(x in m for x in ["rdv", "rendez", "rendez-vous", "prendre", "réserver"]):
        return "BOOK_APPOINTMENT"
    if any(x in m for x in ["horaire", "ouvert", "adresse", "tarif", "prix", "coût", "tel", "téléphone"]):
        return "FAQ"
    return "OTHER"

def extract_basic_info(message: str) -> Dict[str, Optional[str]]:
    data = {"name": None, "date": None, "time": None}
    msg = message.strip()

    # 1) Nom (phrases)
    m_name = re.search(r"(je m'appelle|moi c'est|mon nom est)\s+([a-zA-ZÀ-ÿ' -]{2,})", msg, re.I)
    if m_name:
        data["name"] = m_name.group(2).strip()

    # 2) Nom "libre"
    if not data["name"]:
        blacklist = ["demain", "aujourd'hui", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche", "rdv", "rendez-vous", "bonjour", "salut", "hello", "non", "oui", "stop"]
        if re.fullmatch(r"[a-zA-ZÀ-ÿ' -]{2,40}", msg) and not re.search(r"\d", msg):
            if msg.lower() not in blacklist:
                words = [w for w in msg.split() if w]
                if 1 <= len(words) <= 3:
                    data["name"] = msg

    # 3) Date ISO YYYY-MM-DD
    m_date_iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", msg)
    if m_date_iso:
        data["date"] = m_date_iso.group(0)

    # 4) Date FR : DD/MM/YYYY
    if not data["date"]:
        m_date_fr = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", msg)
        if m_date_fr:
            d, m, y = m_date_fr.groups()
            try:
                data["date"] = datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d")
            except ValueError: pass

    # 5) Date FR sans année : DD/MM
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

    # 6) Mots relatifs
    lower = msg.lower()
    if "demain" in lower:
        data["date"] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    if "après-demain" in lower or "apres-demain" in lower:
        data["date"] = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

    # 7) Heure : 14:30, 14h30, 14h, 14 heures
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
# IA / LLM
# =========================================================

def llm_intent_and_extract(message: str, faq: dict, history: List[Dict[str, str]]) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        intent = fallback_intent(message)
        data = extract_basic_info(message)
        return {"intent": intent, "answer": None, **data}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        faq_text = "\n".join([f"- {k}: {v}" for k, v in faq.items()])

        system = f"""
Nous sommes le {now_str}.
Tu es un assistant de prise de rendez-vous.
Tu dois produire un JSON strict :
- intent: "FAQ" | "BOOK_APPOINTMENT" | "CONFIRM" | "CANCEL" | "OTHER"
- answer: string ou null (réponse courte si FAQ)
- name, date (YYYY-MM-DD), time (HH:MM) : null si non trouvé.
FAQ :
{faq_text}
""".strip()

        input_messages = [{"role": "system", "content": system}]
        for h in history[-6:]:
            input_messages.append(h)
        input_messages.append({"role": "user", "content": message})

        resp = client.responses.create(
            model=OPENAI_MODEL,
            input=input_messages,
            text={
                "format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "result",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "intent": {"type": "string", "enum": ["FAQ", "BOOK_APPOINTMENT", "CONFIRM", "CANCEL", "OTHER"]},
                                "answer": {"type": ["string", "null"]},
                                "name": {"type": ["string", "null"]},
                                "date": {"type": ["string", "null"]},
                                "time": {"type": ["string", "null"]}
                            },
                            "required": ["intent", "answer", "name", "date", "time"]
                        }
                    }
                }
            }
        )
        return json.loads(resp.output_text)
    except Exception:
        intent = fallback_intent(message)
        data = extract_basic_info(message)
        return {"intent": intent, "answer": None, **data}

# =========================================================
# LOGIQUE PRINCIPALE CORRECTIVE
# =========================================================

def handle_message(client_id: str, user_id: str, message: str, history: List[Dict[str, str]]) -> BotReply:
    msg = (message or "").strip().lower()
    cfg = get_client_config(client_id)
    opening_hours = cfg["opening_hours"]
    faq = cfg["faq"]

    session = get_session(client_id, user_id)
    stage = session["stage"]
    draft = json.loads(session["draft_json"] or "{}")

    # Initialisation
    changed = False

    # 1. ANALYSE (IA ou Regex)
    result = llm_intent_and_extract(message, faq, history)
    intent = result.get("intent", "OTHER")
    
    # On mixe les infos trouvées
    regex_data = extract_basic_info(message)
    extracted_name = result.get("name") or regex_data.get("name")
    extracted_date = result.get("date") or regex_data.get("date")
    extracted_time = result.get("time") or regex_data.get("time")

    # --- CAS 1 : ANNULATION (Prioritaire et Élargie) ---
    # Liste de mots déclencheurs d'annulation plus complète
    cancel_keywords = ["annuler", "cancel", "stop", "non", "pas de rdv", "pas besoin", "laisse tomber", "abort", "oublie", "quitter"]
    
    if intent == "CANCEL" or any(kw in msg for kw in cancel_keywords):
        clear_session(client_id, user_id)
        return BotReply("🚫 C'est noté, j'annule la demande. Dis-moi si tu as besoin d'autre chose.", "ok")

    # --- CAS 2 : GESTION DE LA CONFIRMATION ---
    if stage == "confirming":
        # A) Confirmation explicite
        if intent == "CONFIRM" or msg in ["oui", "ok", "d'accord", "je confirme", "yes"]:
            name, date, time = draft.get("name"), draft.get("date"), draft.get("time")
            
            if appointment_exists(client_id, date, time):
                alt = suggest_next_time(time, 60)
                upsert_session(client_id, user_id, "collecting", json.dumps(draft))
                return BotReply(f"⚠️ Aïe, ce créneau vient d'être pris. Tu veux plutôt **{alt}** ?", "needs_info")
            
            insert_appointment(client_id, user_id, name, date, time)
            clear_session(client_id, user_id)
            return BotReply(f"✅ C'est confirmé **{name}** ! RDV le **{date}** à **{time}**.", "ok")

        # B) Modification implicite
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
                return BotReply("Je n'ai pas compris. Réponds **OUI** pour confirmer le RDV, ou donne-moi une autre date.", "needs_info")

    # --- CAS 3 : FAQ ---
    if intent == "FAQ":
        if "horaire" in msg: return BotReply(faq.get("horaires"), "ok")
        if "adresse" in msg: return BotReply(faq.get("adresse"), "ok")
        if "tarif" in msg or "prix" in msg: return BotReply(faq.get("tarifs", "Tarifs sur devis."), "ok")
        
        if result.get("answer"):
            return BotReply(result.get("answer"), "ok")
            
        return BotReply("Tu veux les horaires ou l'adresse ?", "ok")

    # --- CAS 4 : PRISE DE RDV ---
    if intent == "BOOK_APPOINTMENT" or stage == "collecting" or (stage == "confirming" and changed):
        # Reset simple : si on est en "collecting" mais que l'utilisateur dit juste "Bonjour" sans infos
        # et que le draft est vide, on peut reset. Mais c'est risqué.
        # Mieux : on s'en tient à la collecte.

        # Mise à jour du brouillon
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
            # Petit ajout de politesse : si on boucle trop, on pourrait varier, mais restons simples.
            return BotReply(f"Ça marche. Il me manque juste : {', '.join(missing)}.", "needs_info")

        # Vérifications
        if is_past(draft["date"], draft["time"]):
            return BotReply("Ce créneau est déjà passé. Choisis une date future.", "needs_info")
        
        if not in_opening_hours(opening_hours, draft["date"], draft["time"]):
            return BotReply("Le garage est fermé à cette heure-là.", "needs_info")

        if appointment_exists(client_id, draft["date"], draft["time"]):
            alt = suggest_next_time(draft["time"], 60)
            return BotReply(f"Ce créneau est déjà pris. Tu es dispo à **{alt}** ?", "needs_info")

        # Tout est bon -> Confirmation
        upsert_session(client_id, user_id, "confirming", json.dumps(draft))
        return BotReply(
            f"Je récapitule : RDV pour **{draft['name']}** le **{draft['date']}** à **{draft['time']}**.\nC'est bon pour toi ? (Réponds OUI)",
            "needs_info"
        )

    # --- CAS 5 : DÉFAUT ---
    return BotReply("Je suis l'assistant du garage. Je peux te donner les horaires ou prendre un rendez-vous.", "ok")