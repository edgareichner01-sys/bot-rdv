import os
from dotenv import load_dotenv

load_dotenv()

# Clés API
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

# Base de Données
# Sur Render, l'URL commence parfois par "postgres://", mais Python veut "postgresql://"
raw_db_url = os.getenv("DATABASE_URL", "sqlite:///./app.db").strip()
DATABASE_URL = raw_db_url.replace("postgres://", "postgresql://")
