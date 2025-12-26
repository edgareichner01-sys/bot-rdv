from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import datetime

def get_calendar_service(client_id):
    from db import get_google_credentials
    creds_dict = get_google_credentials(client_id)
    if not creds_dict:
        print(f"⚠️ Aucun identifiant Google trouvé pour {client_id}")
        return None
    creds = Credentials(
        token=creds_dict['token'],
        refresh_token=creds_dict.get('refresh_token'),
        token_uri=creds_dict['token_uri'],
        client_id=creds_dict['client_id'],
        client_secret=creds_dict['client_secret'],
        scopes=creds_dict['scopes']
    )
    return build('calendar', 'v3', credentials=creds)

def list_next_events(client_id):
    service = get_calendar_service(client_id)
    if not service: return "Erreur : Pas de connexion Google Agenda."
    now = datetime.datetime.utcnow().isoformat() + 'Z'
    try:
        events_result = service.events().list(
            calendarId='primary', timeMin=now, maxResults=10, 
            singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        if not events: return "Aucun événement à venir."
        res = "📅 **Agenda Google :**\n"
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            res += f"- {start} : {event.get('summary', 'Occupé')}\n"
        return res
    except Exception as e: return f"Erreur API : {str(e)}"

def is_slot_available_google(client_id, date_str, time_str):
    service = get_calendar_service(client_id)
    if not service: return True

    # LE FIX DU 'Z' : Indispensable pour que Google réponde au 7 Janvier
    start_day = f"{date_str}T00:00:00Z"
    end_day = f"{date_str}T23:59:59Z"

    print(f"🔍 VÉRIFICATION GOOGLE : {client_id} le {date_str} à {time_str}")

    try:
        events_result = service.events().list(
            calendarId='primary', timeMin=start_day, timeMax=end_day,
            singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        
        req_start = datetime.datetime.fromisoformat(f"{date_str}T{time_str}")
        req_end = req_start + datetime.timedelta(minutes=60)

        for event in events:
            # Cas A : Événement journée entière
            if 'date' in event['start']:
                if event['start']['date'] == date_str:
                    print(f"🚫 Bloqué par journée entière : {event.get('summary')}")
                    return False

            # Cas B : Événement avec heures (ex: ton Test du 7 Janvier)
            if 'dateTime' in event['start']:
                ev_start = datetime.datetime.fromisoformat(event['start']['dateTime'].split('+')[0].replace('Z',''))
                ev_end = datetime.datetime.fromisoformat(event['end']['dateTime'].split('+')[0].replace('Z',''))
                
                if req_start < ev_end and req_end > ev_start:
                    print(f"🚫 Conflit détecté avec : {event.get('summary')}")
                    return False

        print("✅ Créneau libre sur Google.")
        return True
    except Exception as e:
        print(f"❌ Erreur check Google : {e}")
        return True