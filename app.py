from fastapi import FastAPI
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware # <--- L'outil magique

from db import init_db, ensure_default_client, save_message, get_recent_messages
from bot_logic import handle_message

app = FastAPI(title="Bot RDV - Palier 2")

# --- AUTORISER LE WIDGET (CORS) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Autorise tout le monde (pour le développement)
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

@app.post("/chat", response_model=ChatOut)
def chat(payload: ChatIn):
    ensure_default_client(payload.client_id)
    history = get_recent_messages(payload.client_id, payload.user_id, limit=8)
    save_message(payload.client_id, payload.user_id, "user", payload.message)
    
    # Appel au cerveau
    br = handle_message(payload.client_id, payload.user_id, payload.message, history)
    
    save_message(payload.client_id, payload.user_id, "assistant", br.reply)
    return ChatOut(reply=br.reply, status=br.status)