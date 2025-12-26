import os
from dotenv import load_dotenv

load_dotenv()

# On force SQLite pour éviter les crashs de connexion Render
DATABASE_URL = "sqlite:///app.db"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") 
OPENAI_MODEL = "gpt-3.5-turbo-0125"

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
# L'adresse exacte validée dans ta console Google
GOOGLE_REDIRECT_URI = "https://bot-rdv.onrender.com/oauth2callback"