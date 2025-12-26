import os
from dotenv import load_dotenv

load_dotenv()

# 1. Base de données
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")

# 2. Configuration OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") 
OPENAI_MODEL = "gpt-3.5-turbo-0125"

# 3. Configuration Google
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

# 4. Adresse de retour (Doit être identique sur Render et Google Console)
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "https://bot-rdv.onrender.com/oauth2callback")