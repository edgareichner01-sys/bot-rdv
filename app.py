import os
from fastapi import FastAPI
from fastapi.responses import FileResponse # <--- Indispensable pour lire les fichiers
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from db import init_db, ensure_default_client, save_message, get_recent_messages
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