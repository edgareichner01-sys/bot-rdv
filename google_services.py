from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import datetime

def get_calendar_service(client_id):
    """Initialise la connexion avec l'API Google Calendar."""
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
    """Affiche les 10 prochains événements (Utile pour le débug)."""
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
    """
    Vérifie si un créneau est libre. 
    Cette version gère les fuseaux horaires et les événements 'journée entière'.
    """
    service = get_calendar_service(client_id)
    if not service: 
        # Si on ne peut pas vérifier, on bloque par sécurité (Politique Admin)
        return False 

    # 1. Fenêtre de recherche : toute la journée concernée
    start_search = f"{date_str}T00:00:00Z"
    end_search = f"{date_str}T23:59:59Z"

    print(f"🔍 [Audit] Vérification Google : {client_id} le {date_str} à {time_str}")

    try:
        events_result = service.events().list(
            calendarId='primary', 
            timeMin=start_search, 
            timeMax=end_search,
            singleEvents=True, 
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # 2. Préparation du créneau demandé (Durée standard : 60 min)
        req_start = datetime.datetime.fromisoformat(f"{date_str}T{time_str}")
        req_end = req_start + datetime.timedelta(minutes=60)

        for event in events:
            # Cas A : Événement "Journée entière"
            if 'date' in event['start']:
                if event['start']['date'] == date_str:
                    print(f"🚫 Bloqué par journée entière : {event.get('summary')}")
                    return False

            # Cas B : Événement avec heures précises
            if 'dateTime' in event['start']:
                # On nettoie le format pour une comparaison fiable
                ev_start_raw = event['start']['dateTime'].replace('Z', '+00:00')
                ev_end_raw = event['end']['dateTime'].replace('Z', '+00:00')
                
                ev_start = datetime.datetime.fromisoformat(ev_start_raw)
                ev_end = datetime.datetime.fromisoformat(ev_end_raw)

                # Normalisation naïve pour la comparaison
                if ev_start.tzinfo is not None:
                    ev_start = ev_start.replace(tzinfo=None)
                if ev_end.tzinfo is not None:
                    ev_end = ev_end.replace(tzinfo=None)

                # Algorithme de collision
                if req_start < ev_end and req_end > ev_start:
                    print(f"🚫 Conflit détecté : {event.get('summary')} ({ev_start.time()} - {ev_end.time()})")
                    return False

        print("✅ Créneau libre sur Google.")
        return True
    except Exception as e:
        print(f"❌ Erreur check Google : {e}")
        return False

def create_google_event(client_id, date_str, time_str, summary, description="Rendez-vous via Bot", duration_mins=60):
    """
    Crée un événement dans l'agenda Google.
    Retourne le lien de l'événement si succès, None sinon.
    """
    service = get_calendar_service(client_id)
    if not service:
        print("❌ Erreur : Impossible de contacter le service Google.")
        return None

    # 1. Calcul des heures de début et de fin
    # On s'assure que le format est correct pour Google (ISO 8601)
    start_time = f"{date_str}T{time_str}Z"
    
    start_dt = datetime.datetime.fromisoformat(f"{date_str}T{time_str}")
    end_dt = start_dt + datetime.timedelta(minutes=duration_mins)
    end_time = f"{date_str}T{end_dt.strftime('%H:%M:%S')}Z"

    # 2. Construction de l'objet Event
    event_body = {
        'summary': summary,
        'description': description,
        'start': {
            'dateTime': start_time,
            'timeZone': 'UTC',
        },
        'end': {
            'dateTime': end_time,
            'timeZone': 'UTC',
        },
        'reminders': {
            'useDefault': True,
        },
    }

    try:
        # 3. Insertion dans l'agenda principal
        created_event = service.events().insert(
            calendarId='primary', 
            body=event_body
        ).execute()

        print(f"✅ Événement créé avec succès : {created_event.get('htmlLink')}")
        return created_event.get('htmlLink')

    except Exception as e:
        print(f"❌ Erreur lors de la création Google Calendar : {e}")
        return None