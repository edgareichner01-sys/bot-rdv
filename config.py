import os

# 1. Base de données
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///app.db")

# 2. Configuration OpenAI
# On enlève la vraie clé d'ici, Render la trouvera dans ses réglages secrets
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") 
OPENAI_MODEL = "gpt-3.5-turbo"

# 3. Configuration Google
# Idem, on enlève les vraies clés
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

# 4. Adresse de retour
REDIRECT_URI = "https://bot-rdv.onrender.com/google/callback"