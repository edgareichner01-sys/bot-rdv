import os
import json
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from google_auth_oauthlib.flow import Flow
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, ADMIN_PASSWORD
from db import save_google_credentials, init_db
from bot_logic import handle_message

app = FastAPI()
security = HTTPBasic()

@app.on_event("startup")
def startup_event():
    init_db()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- SÉCURITÉ ---
def check_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Vérifie le login/password pour accéder aux pages sensibles."""
    correct_username = "admin"
    if credentials.username != correct_username or credentials.password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Accès refusé : Identifiants incorrects",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

def get_flow():
    client_config = {"web": {"client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}}
    flow = Flow.from_client_config(client_config, scopes=['https://www.googleapis.com/auth/calendar.events'])
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow

# --- ROUTES PUBLIQUES ---
@app.get("/")
async def home(): return HTMLResponse("<h1>🤖 Bot Live</h1>")

@app.get("/widget.js")
async def get_widget(): return FileResponse("widget.js")

@app.get("/logo.png")
async def get_logo(): return FileResponse("logo.png")

@app.get("/demo")
async def get_demo(): return FileResponse("test_client.html")

@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    client_id = request.query_params.get("clientID", "test_user")
    user_id = request.query_params.get("requestID", "visitor")
    res = handle_message(client_id, user_id, data.get("message", ""), data.get("history", []))
    return {"reply": res.reply, "status": res.status}

@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    code = request.query_params.get("code")
    client_id = request.query_params.get("state", "test_user")
    flow = get_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    save_google_credentials(client_id, {"token": creds.token, "refresh_token": creds.refresh_token, "token_uri": creds.token_uri, "client_id": creds.client_id, "client_secret": creds.client_secret, "scopes": creds.scopes})
    return HTMLResponse(f"<h1>✅ Succès</h1><p>Agenda lié pour {client_id}</p>")

# --- ROUTES PROTÉGÉES (ADMIN) ---
@app.get("/admin")
async def get_admin(username: str = Depends(check_admin)): 
    return FileResponse("admin.html")

@app.get("/google_login")
async def google_login(client_id: str = "garage_michel_v6", username: str = Depends(check_admin)):
    flow = get_flow()
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline', state=client_id)
    return RedirectResponse(auth_url)