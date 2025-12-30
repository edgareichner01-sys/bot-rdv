from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Paris")


# =========================================================
# CONNEXION GOOGLE CALENDAR
# =========================================================

def get_calendar_service(client_id):
    """Initialise la connexion avec l'API Google Calendar + refresh auto."""
    from db import get_google_credentials, save_google_credentials

    creds_dict = get_google_credentials(client_id)
    if not creds_dict:
        print(f"⚠️ Aucun identifiant Google trouvé pour {client_id}")
        return None

    creds = Credentials(
        token=creds_dict.get("token"),
        refresh_token=creds_dict.get("refresh_token"),
        token_uri=creds_dict.get("token_uri"),
        client_id=creds_dict.get("client_id"),
        client_secret=creds_dict.get("client_secret"),
        scopes=creds_dict.get("scopes"),
    )

    # 🔄 Refresh automatique si expiré
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            creds_dict["token"] = creds.token
            if creds.expiry:
                creds_dict["expiry"] = creds.expiry.isoformat()
            save_google_credentials(client_id, creds_dict)
            print("🔄 Token Google rafraîchi")
        except Exception as e:
            print("❌ Erreur refresh token Google :", repr(e))
            return None

    try:
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        print("❌ Erreur build Google Calendar service :", repr(e))
        return None


# =========================================================
# VÉRIFICATION DISPONIBILITÉ
# =========================================================

def is_slot_available_google(client_id, date_str, time_str, duration_mins=60):
    """Vérifie si un créneau est libre (Europe/Paris)."""
    service = get_calendar_service(client_id)
    if not service:
        return False

    day = datetime.date.fromisoformat(date_str)
    start_of_day = datetime.datetime.combine(day, datetime.time(0, 0), TZ)
    end_of_day = datetime.datetime.combine(day, datetime.time(23, 59, 59), TZ)

    req_start = datetime.datetime.fromisoformat(f"{date_str}T{time_str}").replace(tzinfo=TZ)
    req_end = req_start + datetime.timedelta(minutes=duration_mins)

    try:
        events = service.events().list(
            calendarId="primary",
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute().get("items", [])

        for event in events:
            # Journée entière
            if "date" in event["start"]:
                if event["start"]["date"] == date_str:
                    return False

            # Événement horaire
            if "dateTime" in event["start"]:
                ev_start = datetime.datetime.fromisoformat(
                    event["start"]["dateTime"]
                ).astimezone(TZ)
                ev_end = datetime.datetime.fromisoformat(
                    event["end"]["dateTime"]
                ).astimezone(TZ)

                if req_start < ev_end and req_end > ev_start:
                    return False

        return True

    except Exception as e:
        print("❌ Erreur check Google :", repr(e))
        return False


# =========================================================
# CRÉATION ÉVÉNEMENT
# =========================================================

def create_google_event(
    client_id,
    date_str,
    time_str,
    summary,
    description="Rendez-vous via Bot",
    duration_mins=60,
):
    """Crée un événement Google Calendar en Europe/Paris."""
    service = get_calendar_service(client_id)
    if not service:
        print("❌ Service Google indisponible")
        return None

    start_dt = datetime.datetime.fromisoformat(
        f"{date_str}T{time_str}"
    ).replace(tzinfo=TZ)
    end_dt = start_dt + datetime.timedelta(minutes=duration_mins)

    event_body = {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": "Europe/Paris",
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "Europe/Paris",
        },
    }

    try:
        print("🟦 Création événement Google :", summary, date_str, time_str)
        event = service.events().insert(
            calendarId="primary",
            body=event_body,
        ).execute()

        print("🟩 Événement Google créé :", event.get("id"))
        return event.get("htmlLink")

    except Exception as e:
        print("❌ Erreur création Google Calendar :", repr(e))
        return None
