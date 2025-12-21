import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db").strip()

def sqlite_path_from_url(url: str) -> str:
    if not url.startswith("sqlite:///"):
        raise RuntimeError("DATABASE_URL doit commencer par sqlite:/// (Palier 1)")
    return url.replace("sqlite:///", "", 1)

DB_PATH = sqlite_path_from_url(DATABASE_URL)
