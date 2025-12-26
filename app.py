import os
import json
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from google_auth_oauthlib.flow import Flow

# --- IMPORTS DE TES FICHIERS ---
from config import OPENAI_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
from db import init_db, get_session, upsert_session, save_google_credentials
from bot_logic import handle_message

# Initialisation de l'app et de la DB
app = FastAPI()
init_db()

# Configuration CORS (pour que le widget marche partout)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration Google OAuth
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

def get_flow():
    """Crée l'objet Flow pour l'authentification Google"""
    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow

# ==========================================
# ROUTES PRINCIPALES
# ==========================================

@app.get("/")
async def home():
    # Page d'accueil simple pour éviter l'erreur 404
    return HTMLResponse("<h1>🤖 Le Bot est en ligne !</h1><p>Allez sur <a href='/admin'>/admin</a> pour configurer.</p>")

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """Affiche la page d'administration"""
    try:
        with open("admin.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Erreur : Fichier admin.html introuvable."

@app.get("/test", response_class=HTMLResponse)
async def test_page():
    """Affiche la page de test du widget"""
    try:
        with open("test_client.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Erreur : Fichier test_client.html introuvable."

# ==========================================
# ROUTE DE CONNEXION GOOGLE (Celle qui manquait !)
# ==========================================

@app.get("/google_login")
async def google_login(client_id: str = "test_user"):
    """
    Démarre la connexion Google.
    On passe le 'client_id' dans le paramètre 'state' pour le récupérer au retour.
    """
    flow = get_flow()
    # On génère l'URL Google, et on cache le client_id dans le 'state'
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        state=client_id 
    )
    return RedirectResponse(auth_url)

@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    """
    Google nous renvoie ici après la validation de l'utilisateur.
    """
    code = request.query_params.get("code")
    # On récupère le client_id qu'on avait caché dans le state
    client_id_recupere = request.query_params.get("state", "defaut")

    if not code:
        return JSONResponse({"error": "Pas de code reçu de Google."})

    try:
        flow = get_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials

        # On sauvegarde les tokens dans la DB pour CE client spécifique
        creds_dict = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes
        }
        
        save_google_credentials(client_id_recupere, creds_dict)
        
        return JSONResponse({
            "message": f"🎉 VICTOIRE ! Token généré et sauvegardé pour le client : {client_id_recupere}",
            "status": "success"
        })

    except Exception as e:
        return JSONResponse({"error": str(e)})

# ==========================================
# ROUTE DU CHATBOT (L'intelligence)
# ==========================================

@app.post("/chat")
async def chat_endpoint(request: Request):
    try:
        data = await request.json()
        user_message = data.get("message", "")
        # L'ID client vient du widget, sinon "test_user" par défaut
        client_id = request.query_params.get("clientID", "test_user")
        # L'ID utilisateur (visiteur du site)
        user_id = request.query_params.get("requestID", "unknown_visitor")

        history = data.get("history", [])

        # On lance le cerveau du bot
        bot_response = handle_message(client_id, user_id, user_message, history)

        return {
            "reply": bot_response.reply,
            "status": bot_response.status
        }
    except Exception as e:
        print(f"🔥 ERREUR CRITIQUE DANS /chat : {e}")
        return {"reply": "Oups, j'ai eu un petit bug technique.", "status": "error"}

# Pour lancer en local (optionnel sur Render)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)