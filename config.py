import os
from dotenv import load_dotenv

load_dotenv()

# Configuration de la base de données
DATABASE_URL = "sqlite:///app.db"

# Configuration OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo-0125"

# Configuration Google
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = "https://bot-rdv.onrender.com/oauth2callback"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# SÉCURITÉ ADMIN
# Note : Sur Render, ajoute ADMIN_PASSWORD dans les "Environment Variables"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "GarageMichel2026!")