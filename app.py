# --- Nouveaux imports pour Google ---
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
import config  # On importe notre fichier de configuration
# ------------------------------------
import os
from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse # <--- Indispensable pour lire les fichiers
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from db import init_db, ensure_default_client, save_message, get_recent_messages, save_google_credentials
from bot_logic import handle_message

app = FastAPI(title="Bot RDV - Palier 2")

# --- SÉCURITÉ : Autoriser tout le monde ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatIn(BaseModel):
    client_id: str = Field(..., description="Identifiant de l'entreprise")
    user_id: str = Field(..., description="Identifiant utilisateur")
    message: str = Field(..., min_length=1, max_length=2000)

class ChatOut(BaseModel):
    reply: str
    status: str

@app.on_event("startup")
def startup():
    init_db()

# --- API (Le cerveau du bot) ---
@app.post("/chat", response_model=ChatOut)
def chat(payload: ChatIn):
    ensure_default_client(payload.client_id)
    history = get_recent_messages(payload.client_id, payload.user_id, limit=8)
    save_message(payload.client_id, payload.user_id, "user", payload.message)
    br = handle_message(payload.client_id, payload.user_id, payload.message, history)
    save_message(payload.client_id, payload.user_id, "assistant", br.reply)
    return ChatOut(reply=br.reply, status=br.status)

# ============================================================
# C'EST ICI QUE TU CRÉES LES PAGES POUR TON ASSOCIÉ
# ============================================================

# 1. Cette route permet d'accéder au script JS en ligne
@app.get("/widget.js")
async def get_widget():
    # Vérifie que le fichier existe bien sur le serveur
    if os.path.exists("widget.js"):
        return FileResponse("widget.js", media_type="application/javascript")
    return {"error": "Fichier widget.js introuvable"}

# 2. Cette route crée la page de DÉMO accessible via URL
@app.get("/demo")
async def get_demo():
    if os.path.exists("test_client.html"):
        return FileResponse("test_client.html", media_type="text/html")
    return {"error": "Fichier test_client.html introuvable"}

# 3. Cette route crée la page ADMIN accessible via URL
@app.get("/admin")
async def get_admin():
    if os.path.exists("admin.html"):
        return FileResponse("admin.html", media_type="text/html")
    return {"error": "Fichier admin.html introuvable"}

# ==========================================
# 🔐 ROUTES GOOGLE CALENDAR (Version FastAPI)
# ==========================================

@app.get("/google/login")
async def google_login():
    # On configure la demande de permission
    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        # On demande le droit de gérer les événements
        scopes=['https://www.googleapis.com/auth/calendar.events'],
        # IMPORTANT : Cela doit correspondre exactement à ce qu'il y a dans ta console Google
        redirect_uri=config.REDIRECT_URI
    )
    
    # On génère l'URL et on redirige l'utilisateur
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    return RedirectResponse(authorization_url)


@app.get("/google/callback")
async def google_callback(code: str):
    # 1. On configure le gestionnaire d'échange (exactement comme pour le login)
    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=['https://www.googleapis.com/auth/calendar.events'],
        redirect_uri=config.REDIRECT_URI
    )

    # 2. On échange le CODE reçu contre des TOKENS (le vrai sésame)
    flow.fetch_token(code=code)
    
    # 3. On récupère les infos utiles
    credentials = flow.credentials
    creds_dict = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

    # 4. SAUVEGARDE EN BASE DE DONNÉES !
    # On utilise "test_user" pour être sûr que ça marche avec ton interface de test
    mon_client_id = "test_user" 
    
    # On s'assure que le client existe avant de sauvegarder ses clés
    ensure_default_client(mon_client_id)
    save_google_credentials(mon_client_id, creds_dict)

    return {"message": "🎉 VICTOIRE ! Token généré et sauvegardé en base de données. Le bot est prêt à travailler !"}