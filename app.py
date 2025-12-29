import os
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from google_auth_oauthlib.flow import Flow
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, ADMIN_PASSWORD, CLIENT_ID
from db import save_google_credentials, init_db, save_message
from bot_logic import handle_message

app = FastAPI()
security = HTTPBasic()

@app.on_event("startup")
def startup_event():
    init_db()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- FONCTION DE SÉCURITÉ ADMIN ---
def check_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != "admin" or credentials.password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Accès refusé",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

def get_flow():
    client_config = {"web": {"client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}}
    flow = Flow.from_client_config(client_config, scopes=['https://www.googleapis.com/auth/calendar.events'])
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow

# Routes Protégées par check_admin
@app.get("/admin")
async def get_admin(username: str = Depends(check_admin)):
    return FileResponse("admin.html")

@app.get("/google_login")
async def google_login(username: str = Depends(check_admin)):
    flow = get_flow()
    # On force l'usage du CLIENT_ID sécurisé du serveur
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline', state=CLIENT_ID)
    return RedirectResponse(auth_url)

# Routes Publiques
@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    user_id = request.query_params.get("requestID", "visitor")
    save_message(CLIENT_ID, user_id, "user", data.get("message", ""))
    res = handle_message(CLIENT_ID, user_id, data.get("message", ""), data.get("history", []))
    save_message(CLIENT_ID, user_id, "assistant", res.reply)
    return {"reply": res.reply, "status": res.status}

@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    code = request.query_params.get("code")
    client_target = request.query_params.get("state", CLIENT_ID)
    flow = get_flow()
    flow.fetch_token(code=code)
    save_google_credentials(client_target, flow.credentials.__dict__)
    return HTMLResponse(f"<h1>✅ Succès</h1><p>Agenda lié pour {client_target}</p>")

@app.get("/demo")
async def get_demo(): return FileResponse("test_client.html")
@app.get("/widget.js")
async def get_widget(): return FileResponse("widget.js")
@app.get("/logo.png")
async def get_logo(): return FileResponse("logo.png")