import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from google_auth_oauthlib.flow import Flow
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
from db import save_google_credentials, init_db
from bot_logic import handle_message

app = FastAPI()
init_db()

# Sécurité pour que le widget puisse parler au bot depuis n'importe quel site
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_flow(client_id: str):
    return Flow.from_client_config(
        {"web": {"client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET, 
                 "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}},
        scopes=['https://www.googleapis.com/auth/calendar.events'],
        state=client_id
    )

@app.get("/")
async def home(): return HTMLResponse("<h1>🤖 Bot en ligne</h1>")

@app.get("/admin")
async def get_admin(): return FileResponse("admin.html")

# CETTE LIGNE EST IMPORTANTE POUR TON WIDGET
@app.get("/widget.js")
async def get_widget(): return FileResponse("widget.js")

@app.get("/google_login")
async def google_login(client_id: str = "garage_michel_v6"):
    flow = get_flow(client_id)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    return RedirectResponse(auth_url)

@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    code = request.query_params.get("code")
    client_id = request.query_params.get("state", "test_user")
    flow = get_flow(client_id)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    flow.fetch_token(code=code)
    save_google_credentials(client_id, {
        "token": flow.credentials.token, "refresh_token": flow.credentials.refresh_token,
        "token_uri": flow.credentials.token_uri, "client_id": flow.credentials.client_id,
        "client_secret": flow.credentials.client_secret, "scopes": flow.credentials.scopes
    })
    return HTMLResponse(f"<h1>✅ Connecté !</h1><p>Le calendrier de {client_id} est lié.</p>")

@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    client_id = request.query_params.get("clientID", "test_user")
    user_id = request.query_params.get("requestID", "visitor")
    res = handle_message(client_id, user_id, data.get("message", ""), data.get("history", []))
    return {"reply": res.reply, "status": res.status}