from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import datetime
# On utilise l'import sécurisé ici aussi, au cas où
try:
    from db import get_google_credentials
except ImportError:
    # Fallback simple pour éviter l'erreur d'import circulaire
    pass

def get_calendar_service(client_id):
    from db import get_google_credentials # Import local pour éviter les cycles
    creds_dict = get_google_credentials(client_id)
    
    if not creds_dict:
        print(f"⚠️ Aucun identifiant trouvé pour {client_id}")
        return None

    creds = Credentials(
        token=creds_dict['token'],
        refresh_token=creds_dict['refresh_token'],
        token_uri=creds_dict['token_uri'],
        client_id=creds_dict['client_id'],
        client_secret=creds_dict['client_secret'],
        scopes=creds_dict['scopes']
    )

    service = build('calendar', 'v3', credentials=creds)
    return service

def list_next_events(client_id):
    service = get_calendar_service(client_id)
    if not service:
        return "Erreur de connexion à l'agenda (Service non créé)."

    now = datetime.datetime.utcnow().isoformat() + 'Z' 
    
    print(f"🔍 Recherche des événements pour {client_id} depuis {now}...")

    try:
        events_result = service.events().list(
            calendarId='primary', 
            timeMin=now,
            maxResults=10, 
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])

        if not events:
            return "Aucun événement à venir trouvé."

        result_text = "📅 **Vos prochains RDV :**\n"
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            clean_start = start.replace('T', ' ').split('+')[0]
            summary = event.get('summary', '(Sans titre)')
            result_text += f"- {clean_start} : {summary}\n"

        return result_text
        
    except Exception as e:
        return f"❌ Erreur lors de l'appel API : {str(e)}"