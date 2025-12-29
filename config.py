import os
from dotenv import load_dotenv

load_dotenv()

# Identifiant unique verrouillé côté serveur (Mission 2)
CLIENT_ID = "garage_michel_v6"

# Utilise DATABASE_URL de Render (Postgres) ou SQLite en local
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")

# Configuration OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo-0125"

# Configuration Google
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = "https://bot-rdv.onrender.com/oauth2callback"

# Sécurité Admin : Récupéré via Render (Aucun mot de passe écrit ici !)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")