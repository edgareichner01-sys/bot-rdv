from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import datetime

# Gestion des imports circulaires
try:
    from db import get_google_credentials
except ImportError:
    pass

def get_calendar_service(client_id):
    from db import get_google_credentials
    creds_dict = get_google_credentials(client_id)
    
    if not creds_dict:
        print(f"⚠️ Aucun identifiant Google trouvé pour {client_id}")
        return None

    creds = Credentials(
        token=creds_dict['token'],
        refresh_token=creds_dict['refresh_token'],
        token_uri=creds_dict['token_uri'],
        client_id=creds_dict['client_id'],
        client_secret=creds_dict['client_secret'],
        scopes=creds_dict['scopes']
    )

    return build('calendar', 'v3', credentials=creds)

def list_next_events(client_id):
    service = get_calendar_service(client_id)
    if not service:
        return "Erreur : Pas de connexion Google Agenda."

    now = datetime.datetime.utcnow().isoformat() + 'Z'
    try:
        events_result = service.events().list(
            calendarId='primary', timeMin=now,
            maxResults=10, singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        if not events:
            return "Aucun événement à venir."

        res = "📅 **Agenda Google :**\n"
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            res += f"- {start} : {event.get('summary', 'Occupé')}\n"
        return res
    except Exception as e:
        return f"Erreur API : {str(e)}"

def is_slot_available_google(client_id, date_str, time_str):
    """
    Vérifie si le créneau est libre sur Google Agenda.
    Retourne True si LIBRE, False si OCCUPÉ.
    """
    service = get_calendar_service(client_id)
    if not service:
        return True # Si pas de connexion, on laisse passer (mode dégradé)

    # 1. Définir la plage de recherche : La journée entière demandée
    # IMPORTANT : On retire le 'Z' pour utiliser l'heure locale du calendrier (Paris)
    start_of_day = f"{date_str}T00:00:00"
    end_of_day = f"{date_str}T23:59:59"

    # LE MARQUEUR POUR LES LOGS
    print(f"🔥 VÉRIFICATION ULTIME pour {date_str}...")

    try:
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_of_day,
            timeMax=end_of_day,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # On prépare l'heure demandée pour comparer (RDV de 1h)
        req_start = datetime.datetime.fromisoformat(f"{date_str}T{time_str}")
        req_end = req_start + datetime.timedelta(minutes=60)

        for event in events:
            # CAS A : Événement "Toute la journée" (Juste une date, pas d'heure)
            if 'date' in event['start']:
                # Si c'est le même jour, on bloque tout
                if event['start']['date'] == date_str:
                    print(f"🚫 Bloqué par journée entière : {event.get('summary')}")
                    return False

            # CAS B : Événement classique (Avec heure de début/fin)
            if 'dateTime' in event['start']:
                # Nettoyage bourrin du fuseau horaire pour comparer les chiffres
                ev_start_str = event['start']['dateTime'].split('+')[0].replace('Z','')
                ev_end_str = event['end']['dateTime'].split('+')[0].replace('Z','')
                
                ev_start = datetime.datetime.fromisoformat(ev_start_str)
                ev_end = datetime.datetime.fromisoformat(ev_end_str)

                # Test de chevauchement
                if req_start < ev_end and req_end > ev_start:
                    print(f"🚫 Conflit horaire avec : {event.get('summary')}")
                    return False

        print("✅ Créneau libre sur Google !")
        return True

    except Exception as e:
        print(f"❌ Erreur check Google : {e}")
        return False