import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from config import OPENAI_API_KEY, OPENAI_MODEL
from db import (
    get_client_config,
    get_session,
    upsert_session,
    clear_session,
    appointment_exists,
    insert_appointment,
)

# =========================================================
# OUTILS DE VALIDATION (dates / heures)
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

# =========================================================
# COMPRÉHENSION SIMPLE (fallback sans IA)
# =========================================================

def fallback_intent(message: str) -> str:
    m = message.lower()

    if any(x in m for x in ["rdv", "rendez", "rendez-vous", "prendre", "réserver"]):
        return "BOOK_APPOINTMENT"
    if any(x in m for x in ["horaire", "ouvert", "adresse", "tarif", "prix"]):
        return "FAQ"
    if m.strip() in ["oui", "ok", "d'accord", "je confirme"]:
        return "CONFIRM"
    if any(x in m for x in ["annuler", "cancel", "stop"]):
        return "CANCEL"

    return "OTHER"

def extract_basic_info(message: str) -> Dict[str, Optional[str]]:
    data = {"name": None, "date": None, "time": None}

    # Nom
    m_name = re.search(r"(je m'appelle|moi c'est|mon nom est)\s+([a-zA-ZÀ-ÿ ]+)", message, re.I)
    if m_name:
        data["name"] = m_name.group(2).strip()

    # Date YYYY-MM-DD
    m_date = re.search(r"\d{4}-\d{2}-\d{2}", message)
    if m_date:
        data["date"] = m_date.group(0)

    # Heure HH:MM
    m_time = re.search(r"\d{1,2}:\d{2}", message)
    if m_time:
        h = m_time.group(0)
        if len(h.split(":")[0]) == 1:
            h = "0" + h
        data["time"] = h

    # "demain"
    if "demain" in message.lower():
        data["date"] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    return data

# =========================================================
# STRUCTURE DE RÉPONSE
# =========================================================

@dataclass
class BotReply:
    reply: str
    status: str  # ok | needs_info
# =========================================================
# (OPTIONNEL) IA OpenAI — améliore la compréhension
# =========================================================

def llm_intent_and_extract(message: str, faq: dict, history: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Retour attendu :
    {
      "intent": "FAQ" | "BOOK_APPOINTMENT" | "CONFIRM" | "CANCEL" | "OTHER",
      "answer": "..." ou None,
      "name": "..." ou None,
      "date": "YYYY-MM-DD" ou None,
      "time": "HH:MM" ou None
    }
    """
    # Si pas de clé OpenAI -> fallback simple
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
Tu es un assistant de prise de rendez-vous pour une entreprise.

Tu dois produire un JSON strict, avec ces champs EXACTS :
- intent: "FAQ" | "BOOK_APPOINTMENT" | "CONFIRM" | "CANCEL" | "OTHER"
- answer: string ou null
- name: string ou null
- date: "YYYY-MM-DD" ou null
- time: "HH:MM" ou null

Règles :
- Ne pas inventer. Si tu ne sais pas -> null.
- Si intent=FAQ : réponds brièvement dans "answer" en utilisant la FAQ ci-dessous.
- Si intent=BOOK_APPOINTMENT : essaie d'extraire name/date/time si présent.
FAQ :
{faq_text}
""".strip()

        input_messages = [{"role": "system", "content": system}]
        # petit historique (facultatif)
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
                        "name": "LLMResult",
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
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

        data = json.loads(resp.output_text)
        return data

    except Exception:
        # si l'API plante, on retombe en fallback
        intent = fallback_intent(message)
        data = extract_basic_info(message)
        return {"intent": intent, "answer": None, **data}


# =========================================================
# LOGIQUE PRINCIPALE : handle_message (LE COEUR)
# =========================================================

def handle_message(client_id: str, user_id: str, message: str, history: List[Dict[str, str]]) -> BotReply:
    cfg = get_client_config(client_id)
    opening_hours = cfg["opening_hours"]
    faq = cfg["faq"]

    # session = mémoire d'état (collecte / confirmation)
    session = get_session(client_id, user_id)
    stage = session["stage"]
    draft = json.loads(session["draft_json"] or "{}")

    # Compréhension (IA si possible sinon fallback)
    result = llm_intent_and_extract(message, faq, history)
    intent = result.get("intent", "OTHER")

    extracted_name = result.get("name")
    extracted_date = result.get("date")
    extracted_time = result.get("time")

    # ---- 1) ANNULER : marche à n'importe quel moment
    if intent == "CANCEL":
        clear_session(client_id, user_id)
        return BotReply("✅ Ok, j’annule la demande en cours. Si tu veux, donne-moi une autre date/heure.", "ok")

    # ---- 2) Si on est en attente de confirmation
    if stage == "confirming":
        msg = message.strip().lower()

        if intent == "CONFIRM" or msg in ["oui", "ok", "d'accord", "daccord", "je confirme"]:
            # Finaliser le RDV
            name = draft.get("name")
            date = draft.get("date")
            time = draft.get("time")

            # re-check conflit
            if appointment_exists(client_id, date, time):
                clear_session(client_id, user_id)
                alt = suggest_next_time(time, 60)
                return BotReply(f"⚠️ Ce créneau vient d’être pris. Tu veux plutôt à **{alt}** ?", "needs_info")

            insert_appointment(client_id, user_id, name, date, time)
            clear_session(client_id, user_id)
            return BotReply(f"✅ Rendez-vous confirmé pour **{name}** le **{date}** à **{time}**.", "ok")

        # si pas "oui" -> on annule
        clear_session(client_id, user_id)
        return BotReply("D’accord, je ne confirme pas. Donne-moi une autre date/heure si tu veux réserver.", "ok")

    # ---- 3) FAQ
    if intent == "FAQ":
        answer = result.get("answer")
        if answer:
            return BotReply(answer, "ok")
        # fallback FAQ simple
        return BotReply("Je peux t’aider : tu veux les **horaires**, l’**adresse** ou les **tarifs** ?", "ok")

    # ---- 4) Prise de RDV (ou poursuite collecte)
    if intent == "BOOK_APPOINTMENT" or stage == "collecting":
        # on complète draft avec ce qu'on a trouvé
        if extracted_name:
            draft["name"] = extracted_name
        if extracted_date:
            draft["date"] = extracted_date
        if extracted_time:
            draft["time"] = extracted_time

        # Validation simple
        if draft.get("date") and not valid_date(draft["date"]):
            draft["date"] = None
        if draft.get("time") and not valid_time(draft["time"]):
            draft["time"] = None

        # Infos manquantes ?
        missing = []
        if not draft.get("name"):
            missing.append("ton nom")
        if not draft.get("date"):
            missing.append("la date (YYYY-MM-DD ou 'demain')")
        if not draft.get("time"):
            missing.append("l’heure (HH:MM)")

        if missing:
            upsert_session(client_id, user_id, "collecting", json.dumps(draft))
            return BotReply("Pour prendre le rendez-vous, j’ai besoin de : " + ", ".join(missing) + ".", "needs_info")

        # Règles métier
        if is_past(draft["date"], draft["time"]):
            upsert_session(client_id, user_id, "collecting", json.dumps(draft))
            return BotReply("Ce créneau est déjà passé. Donne-moi une date/heure dans le futur.", "needs_info")

        if not in_opening_hours(opening_hours, draft["date"], draft["time"]):
            upsert_session(client_id, user_id, "collecting", json.dumps(draft))
            return BotReply("Je ne peux pas à cette heure (hors horaires). Donne-moi une autre date/heure.", "needs_info")

        if appointment_exists(client_id, draft["date"], draft["time"]):
            alt = suggest_next_time(draft["time"], 60)
            upsert_session(client_id, user_id, "collecting", json.dumps(draft))
            return BotReply(f"Ce créneau est déjà pris. Tu veux plutôt à **{alt}** ?", "needs_info")

        # Demander confirmation
        upsert_session(client_id, user_id, "confirming", json.dumps(draft))
        return BotReply(
            f"Je récapitule : RDV pour **{draft['name']}** le **{draft['date']}** à **{draft['time']}**. "
            f"Réponds **OUI** pour confirmer ou **ANNULER**.",
            "needs_info"
        )

    # ---- 5) Autre
    return BotReply(
        "Je peux répondre aux questions (horaires, adresse, tarifs) ou prendre un rendez-vous. Que veux-tu faire ?",
        "ok"
    )
