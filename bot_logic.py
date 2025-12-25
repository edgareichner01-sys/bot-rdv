import json
import re
import os # <--- Ajout de l'import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

# --- CORRECTION IMPORT ---
try:
    from config import OPENAI_API_KEY, OPENAI_MODEL
except ImportError:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = "gpt-3.5-turbo"
# -------------------------

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
# Si le message contient une date ou une heure, on suppose que c'est pour un RDV
if re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?\b", m) or re.search(r"\b(\d{1,2})(?:[:hH](\d{2}))?\b", m):
    return "BOOK_APPOINTMENT"

    return "OTHER"

def extract_basic_info(message: str) -> Dict[str, Optional[str]]:
    data = {"name": None, "date": None, "time": None}
    msg = message.strip()

    # 1) Nom (phrases)
    m_name = re.search(r"(je m'appelle|moi c'est|mon nom est)\s+([a-zA-ZÀ-ÿ' -]{2,})", msg, re.I)
    if m_name:
        data["name"] = m_name.group(2).strip()
        return data  # on peut return tôt si on veut

    # 2) Nom "libre" : si l'utilisateur répond juste "Edgar" / "Edgar Eichner"
    #    (sans chiffres, 1 à 3 mots, pas trop long)
    if data["name"] is None:
        if re.fullmatch(r"[a-zA-ZÀ-ÿ' -]{2,40}", msg) and not re.search(r"\d", msg):
            words = [w for w in msg.split() if w]
            if 1 <= len(words) <= 3:
                data["name"] = msg

    # 3) Date ISO YYYY-MM-DD
    m_date_iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", msg)
    if m_date_iso:
        data["date"] = m_date_iso.group(0)

    # 4) Date FR : DD/MM/YYYY ou DD-MM-YYYY
    if data["date"] is None:
        m_date_fr = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", msg)
        if m_date_fr:
            d, m, y = m_date_fr.groups()
            try:
                data["date"] = datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d")
            except ValueError:
                pass

    # 5) Date FR sans année : DD/MM ou DD-MM -> année courante (si date passée -> +1 an)
    if data["date"] is None:
        m_date_no_year = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", msg)
        if m_date_no_year:
            d, m = m_date_no_year.groups()
            y = datetime.now().year
            try:
                candidate = datetime(y, int(m), int(d))
                if candidate.date() < datetime.now().date():
                    candidate = datetime(y + 1, int(m), int(d))
                data["date"] = candidate.strftime("%Y-%m-%d")
            except ValueError:
                pass

    # 6) Mots relatifs
    lower = msg.lower()
    if "demain" in lower:
        data["date"] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    if "après-demain" in lower or "apres-demain" in lower:
        data["date"] = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

    # 7) Heure : 14:30, 14h30, 14h, 9h, 9:05
    m_time = re.search(r"\b(\d{1,2})(?:[:hH](\d{2}))?\b", msg)
    if m_time:
        hh = int(m_time.group(1))
        mm = int(m_time.group(2) or 0)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            data["time"] = f"{hh:02d}:{mm:02d}"

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

    # 1) Annuler explicitement
    if intent == "CANCEL" or msg in ["annuler", "cancel", "stop", "non"]:
        clear_session(client_id, user_id)
        return BotReply("D’accord, j’annule. Donne-moi une autre date/heure si tu veux réserver.", "ok")

    # 2) Confirmer explicitement
    if intent == "CONFIRM" or msg in ["oui", "ok", "d'accord", "daccord", "je confirme"]:
        name = draft.get("name")
        date = draft.get("date")
        time = draft.get("time")

        if appointment_exists(client_id, date, time):
            # On garde la session mais on repasse en collecte
            alt = suggest_next_time(time, 60)
            upsert_session(client_id, user_id, "collecting", json.dumps(draft))
            return BotReply(f"⚠️ Ce créneau vient d’être pris. Tu veux plutôt **{alt}** ?", "needs_info")

        insert_appointment(client_id, user_id, name, date, time)
        clear_session(client_id, user_id)
        return BotReply(f"✅ Rendez-vous confirmé pour **{name}** le **{date}** à **{time}**.", "ok")

    # 3) Sinon: l'utilisateur est probablement en train de modifier (ex: "à 14h", "13/01 à 10h")
    # On tente d'extraire des infos depuis son message
    mod = extract_basic_info(message)  # <-- utilise ta fonction améliorée

    changed = False
    if mod.get("name"):
        draft["name"] = mod["name"]; changed = True
    if mod.get("date"):
        draft["date"] = mod["date"]; changed = True
    if mod.get("time"):
        draft["time"] = mod["time"]; changed = True

    # Re-valider si besoin
    if draft.get("date") and not valid_date(draft["date"]):
        draft["date"] = None
    if draft.get("time") and not valid_time(draft["time"]):
        draft["time"] = None

    if changed:
        # On repasse en collecting puis on renvoie un récap + confirmation
        upsert_session(client_id, user_id, "collecting", json.dumps(draft))
        missing = []
        if not draft.get("name"):
            missing.append("ton nom")
        if not draft.get("date"):
            missing.append("la date (ex: demain, 13/01, 13/01/2026)")
        if not draft.get("time"):
            missing.append("l’heure (ex: 14h, 14h30)")

        if missing:
            return BotReply("Parfait 👍 Il me manque juste : " + ", ".join(missing) + ".", "needs_info")

        # Tout est complet → demander confirmation à nouveau
        upsert_session(client_id, user_id, "confirming", json.dumps(draft))
        return BotReply(
            f"Ok, je mets à jour : RDV pour **{draft['name']}** le **{draft['date']}** à **{draft['time']}**. "
            f"Réponds **OUI** pour confirmer ou **ANNULER**.",
            "needs_info"
        )

    # 4) Si aucune modif détectée → là seulement on annule
    clear_session(client_id, user_id)
    return BotReply("D’accord, je ne confirme pas. Donne-moi une autre date/heure si tu veux réserver.", "ok")


    # ---- 3) FAQ
    if intent == "FAQ":
        msg = message.lower().strip()

        # Réponses directes basées sur mots-clés
        if "horaire" in msg:
            return BotReply(faq.get("horaires", "Horaires non disponibles."), "ok")

        if "adresse" in msg or "où" in msg or "c'est où" in msg or "vous êtes où" in msg:
            return BotReply(faq.get("adresse", "Adresse non disponible."), "ok")

        if "tarif" in msg or "prix" in msg or "combien" in msg or "coût" in msg:
            return BotReply(faq.get("tarifs", "Tarifs non disponibles."), "ok")

        if "telephone" in msg or "téléphone" in msg or "tel" in msg or "numéro" in msg:
            return BotReply(faq.get("telephone", "Téléphone non disponible."), "ok")

        if "email" in msg or "mail" in msg:
            return BotReply(faq.get("email", "Email non disponible."), "ok")

        if "service" in msg or "prestation" in msg:
            return BotReply(faq.get("services", "Services non disponibles."), "ok")

        # Réponse IA si dispo
        answer = result.get("answer")
        if answer:
            return BotReply(answer, "ok")

        # ⚠️ RETURN FINAL OBLIGATOIRE
        return BotReply(
            "Tu veux les **horaires**, l’**adresse**, les **tarifs**, le **téléphone** ou les **services** ?",
            "ok"
        )


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
