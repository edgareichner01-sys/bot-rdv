from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import datetime
import json

def get_calendar_service(client_id):
    from db import get_google_credentials, save_google_credentials
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

    # REFRESH AUTOMATIQUE : Si la clé est périmée, on en demande une nouvelle
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # On met à jour la base de données avec le nouveau token
            save_google_credentials(client_id, {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": creds.scopes
            })
            print(f"🔄 Token rafraîchi pour {client_id}")
        except Exception as e:
            print(f"❌ Échec du refresh Google : {e}")
            return None

    return build('calendar', 'v3', credentials=creds)

def is_slot_available_google(client_id, date_str, time_str):
    service = get_calendar_service(client_id)
    if not service:
        return True # On laisse passer si Google est injoignable

    # RFC3339 : Google exige un 'Z' ou un décalage horaire
    start_of_day = f"{date_str}T00:00:00Z"
    end_of_day = f"{date_str}T23:59:59Z"

    print(f"🔥 VÉRIFICATION GOOGLE : {date_str} à {time_str}")

    try:
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_of_day,
            timeMax=end_of_day,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        req_start = datetime.datetime.fromisoformat(f"{date_str}T{time_str}")
        req_end = req_start + datetime.timedelta(minutes=60)

        for event in events:
            # Événement "Toute la journée"
            if 'date' in event['start']:
                if event['start']['date'] == date_str:
                    print(f"🚫 Bloqué (Journée entière) : {event.get('summary')}")
                    return False

            # Événement avec heures
            if 'dateTime' in event['start']:
                # On nettoie le format pour la comparaison
                ev_start_str = event['start']['dateTime'].split('+')[0].replace('Z','')
                ev_end_str = event['end']['dateTime'].split('+')[0].replace('Z','')
                
                ev_start = datetime.datetime.fromisoformat(ev_start_str)
                ev_end = datetime.datetime.fromisoformat(ev_end_str)

                if req_start < ev_end and req_end > ev_start:
                    print(f"🚫 Bloqué (Conflit) : {event.get('summary')}")
                    return False

        print("✅ Créneau libre sur Google !")
        return True
    except Exception as e:
        print(f"❌ Erreur API Google : {e}")
        return True