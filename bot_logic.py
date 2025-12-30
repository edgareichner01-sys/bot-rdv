import json
import re
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from google_services import create_google_event
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
from google_services import is_slot_available_google, create_google_event


# =========================================================
# OUTILS DE VALIDATION & EXTRACTIONinsert_appointment
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
   # On compare sans les secondes pour éviter les faux positifs
   dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
   return dt < datetime.now().replace(second=0, microsecond=0)


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
   lower = msg.lower()


   # 1. EXTRACTION DU NOM AVEC PROTECTION
   # On ajoute "un autre rdv" et les mots courants à la blacklist
   blacklist = [
       "demain", "aujourd'hui", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
       "rdv", "rendez-vous", "bonjour", "salut", "non", "oui", "stop", "un autre", "prendre", "horaires"
   ]


   m_name = re.search(r"(je m'appelle|moi c'est|mon nom est)\s+([a-zA-ZÀ-ÿ' -]{2,})", msg, re.I)
   if m_name:
       data["name"] = m_name.group(2).strip()
  
   # Si pas de phrase type "Moi c'est...", on ne prend le message comme un nom
   # QUE s'il est court, sans chiffres, et pas dans la blacklist
   if not data["name"]:
       if len(msg.split()) <= 2 and lower not in blacklist and not any(char.isdigit() for char in msg):
           # On vérifie aussi que ce n'est pas un message de commande
           if len(msg) > 1: # Évite les lettres isolées
               data["name"] = msg


   # --- TES REGEX DE DATE ET HEURE (ON LES GARDE PRÉCIEUSEMENT) ---
   m_date_iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", msg)
   if m_date_iso: data["date"] = m_date_iso.group(0)


   if not data["date"]:
       m_date_fr = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", msg)
       if m_date_fr:
           d, m, y = m_date_fr.groups()
           try: data["date"] = datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d")
           except ValueError: pass


   if not data["date"]:
       m_date_no_year = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", msg)
       if m_date_no_year:
           d, m = m_date_no_year.groups()
           y = datetime.now().year
           try:
               candidate = datetime(y, int(m), int(d))
               if candidate.date() < datetime.now().date(): candidate = datetime(y + 1, int(m), int(d))
               data["date"] = candidate.strftime("%Y-%m-%d")
           except ValueError: pass


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


def llm_intent_and_extract(message: str, faq: dict, history: list) -> dict:
   import json
   from datetime import datetime
   from openai import OpenAI
  
   try:
       client = OpenAI(api_key=OPENAI_API_KEY)
       system = f"Nous sommes le {datetime.now()}. Tu es un assistant de garage. Réponds UNIQUEMENT en JSON. Format: {{'intent': 'FAQ|BOOK_APPOINTMENT|CONFIRM|CANCEL|OTHER', 'answer': 'réponse ou null', 'name': 'nom ou null', 'date': 'YYYY-MM-DD', 'time': 'HH:MM'}}"
      
       response = client.chat.completions.create(
           model=OPENAI_MODEL,
           messages=[{"role": "system", "content": system}] + history[-5:] + [{"role": "user", "content": message}],
           response_format={"type": "json_object"},
           temperature=0
       )
       return json.loads(response.choices[0].message.content)
   except Exception as e:
       print(f"❌ Erreur OpenAI : {e}")
       # Utilise tes fonctions de secours (regex) déjà présentes dans ton fichier
       return {"intent": "OTHER", "answer": None, "name": None, "date": None, "time": None}


# =========================================================
# LOGIQUE PRINCIPALE
# =========================================================


def handle_message(client_id: str, user_id: str, message: str, history: List[Dict[str, str]]) -> BotReply:
   msg = (message or "").strip().lower()
   cfg = get_client_config(client_id)
   session = get_session(client_id, user_id)
   stage = session["stage"]
   draft = json.loads(session["draft_json"] or "{}")


   # 1. ANALYSE ET SAUVEGARDE IMMÉDIATE
   result = llm_intent_and_extract(message, cfg["faq"], history)
   regex_data = extract_basic_info(message)
  
   # On met à jour le brouillon dès qu'une info tombe
   if result.get("name") or regex_data.get("name"):
       draft["name"] = result.get("name") or regex_data.get("name")
   if result.get("date") or regex_data.get("date"):
       draft["date"] = result.get("date") or regex_data.get("date")
   if result.get("time") or regex_data.get("time"):
       draft["time"] = result.get("time") or regex_data.get("time")


   # ACTION CRUCIALE : On enregistre en DB avant toute autre logique
   upsert_session(client_id, user_id, stage, json.dumps(draft))


   # CAS 1 : ANNULATION
   if result.get("intent") == "CANCEL":
       clear_session(client_id, user_id)
       return BotReply("🚫 Annulé.", "ok")


    # CAS 2 : CONFIRMATION
   if stage == "confirming":
    if msg in ["oui", "ok", "d'accord", "je confirme", "yes"]:

        if not is_slot_available_google(client_id, draft["date"], draft["time"]):
            return BotReply(
                "⚠️ Finalement, l'agenda Google vient d'être pris. Une autre heure ?",
                "needs_info"
            )

        inserted = insert_appointment(client_id, user_id, draft["name"], draft["date"], draft["time"])
        if not inserted:
            clear_session(client_id, user_id)
            return BotReply(
                f"✅ C’est déjà confirmé pour {draft['name']} le {draft['date']} à {draft['time']}.",
                "ok"
            )

        link = create_google_event(
            client_id=client_id,
            date_str=draft["date"],
            time_str=draft["time"],
            summary=f"RDV - {draft['name']}",
            description=f"Rendez-vous pris via le bot pour {draft['name']}.",
            duration_mins=60
        )

        if not link:
            return BotReply(
                "❌ Je n'ai pas réussi à créer l'événement dans Google Agenda. "
                "Vérifie la connexion Google dans l'admin puis réessaie.",
                "needs_info"
            )

        clear_session(client_id, user_id)
        return BotReply(
            f"✅ Confirmé pour {draft['name']} !\n📅 Votre rendez-vous est bien enregistré.",
            "ok"
        )

    # si l'utilisateur ne confirme pas
    clear_session(client_id, user_id)
    return BotReply("❌ Annulé.", "ok")


   # CAS 3 : FAQ
   if result.get("intent") == "FAQ":
       return BotReply(result.get("answer") or "Je n'ai pas l'info.", "ok")


   # CAS 4 : PRISE DE RDV
   if result.get("intent") == "BOOK_APPOINTMENT" or stage in ["collecting", "confirming"]:
       missing = []
       if not draft.get("name"): missing.append("ton nom")
       if not draft.get("date"): missing.append("la date")
       if not draft.get("time"): missing.append("l'heure")


       if missing:
           upsert_session(client_id, user_id, "collecting", json.dumps(draft))
           return BotReply(f"Il me manque : {', '.join(missing)}.", "needs_info")


       if is_past(draft["date"], draft["time"]):
           return BotReply("Ce créneau est déjà passé. Choisis une autre date.", "needs_info")
       if not in_opening_hours(cfg["opening_hours"], draft["date"], draft["time"]):
           return BotReply("Le garage est fermé à cette heure-là.", "needs_info")
       if not is_slot_available_google(client_id, draft["date"], draft["time"]):
           return BotReply("🚫 Ce créneau est occupé sur Google Agenda.", "needs_info")


       upsert_session(client_id, user_id, "confirming", json.dumps(draft))
       return BotReply(f"RDV pour {draft['name']} le {draft['date']} à {draft['time']}. C'est bon ? (OUI)", "needs_info")


   return BotReply("Bonjour ! Comment puis-je vous aider ?", "ok")