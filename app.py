import os
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from google_auth_oauthlib.flow import Flow
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
from db import save_google_credentials, init_db
from bot_logic import handle_message

app = FastAPI()

@app.on_event("startup")
def startup_event():
    init_db()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_flow():
    client_config = {"web": {"client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET, 
                             "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}}
    flow = Flow.from_client_config(client_config, scopes=['https://www.googleapis.com/auth/calendar.events'])
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow

@app.get("/")
async def home(): return HTMLResponse("<h1>🤖 Bot Live</h1>")

@app.get("/admin")
async def get_admin(): return FileResponse("admin.html")

@app.get("/widget.js")
async def get_widget(): return FileResponse("widget.js")

@app.get("/logo.png")
async def get_logo():
    return FileResponse("logo.png")

@app.get("/demo")
async def get_demo():
    # Cette ligne renvoie le fichier HTML de votre widget de test
    return FileResponse("test_client.html")

@app.get("/google_login")
async def google_login(client_id: str = "garage_michel_v6"):
    flow = get_flow()
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline', state=client_id)
    return RedirectResponse(auth_url)

@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    code = request.query_params.get("code")
    client_id = request.query_params.get("state", "test_user")
    flow = get_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    save_google_credentials(client_id, {"token": creds.token, "refresh_token": creds.refresh_token, "token_uri": creds.token_uri, "client_id": creds.client_id, "client_secret": creds.client_secret, "scopes": creds.scopes})
    return HTMLResponse(f"<h1>✅ Succès</h1><p>Agenda lié pour {client_id}</p>")

@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    client_id = request.query_params.get("clientID", "test_user")
    user_id = request.query_params.get("requestID", "visitor")
    res = handle_message(client_id, user_id, data.get("message", ""), data.get("history", []))
    return {"reply": res.reply, "status": res.status}