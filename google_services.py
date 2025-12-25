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
    """Affiche les 10 prochains événements (pour le test)"""
    service = get_calendar_service(client_id)
    if not service:
        return "Erreur : Pas de connexion Google Agenda."

    now = datetime.datetime.utcnow().isoformat() + 'Z'
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

def is_slot_available_google(client_id, date_str, time_str):
    """
    Vérifie si le créneau est libre sur Google Agenda.
    Retourne True si LIBRE, False si OCCUPÉ.
    """
    service = get_calendar_service(client_id)
    if not service:
        # Si pas connecté, on part du principe que c'est libre (ou bloqué selon la politique)
        # Pour l'instant on laisse passer pour ne pas bloquer le bot si pas de config
        return True

    # 1. Définir la plage de recherche : La journée entière demandée
    # On cherche de 00:00 à 23:59 du jour J pour attraper les événements "Journée entière"
    start_of_day = f"{date_str}T00:00:00Z"
    end_of_day = f"{date_str}T23:59:59Z"

    print(f"🔍 Vérif Google pour {date_str} à {time_str}...")

    events_result = service.events().list(
        calendarId='primary',
        timeMin=start_of_day,
        timeMax=end_of_day,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    
    events = events_result.get('items', [])

    # 2. Convertir l'heure demandée en objet datetime pour comparer
    # On suppose que le RDV dure 1h (60 minutes) par défaut
    req_start = datetime.datetime.fromisoformat(f"{date_str}T{time_str}")
    req_end = req_start + datetime.timedelta(minutes=60)

    for event in events:
        # A) Gestion des événements "Toute la journée"
        # Google renvoie juste une 'date' (pas de dateTime) pour ces événements
        if 'date' in event['start']:
            print(f"🚫 Bloqué par événement journée entière : {event.get('summary')}")
            return False # C'est mort, la journée est bloquée

        # B) Gestion des événements classiques (heures précises)
        if 'dateTime' in event['start']:
            # On nettoie le format (Google met parfois le fuseau horaire à la fin)
            # Pour faire simple, on compare les chaînes ISO ou on parse basiquement
            ev_start_str = event['start']['dateTime'].split('+')[0].replace('Z','')
            ev_end_str = event['end']['dateTime'].split('+')[0].replace('Z','')
            
            ev_start = datetime.datetime.fromisoformat(ev_start_str)
            ev_end = datetime.datetime.fromisoformat(ev_end_str)

            # C) Test de chevauchement (Overlap)
            # Un créneau est occupé si :
            # (Début Demande < Fin Event) ET (Fin Demande > Début Event)
            if req_start < ev_end and req_end > ev_start:
                print(f"🚫 Conflit avec : {event.get('summary')} ({ev_start_str})")
                return False

    print("✅ Créneau libre sur Google !")
    return True