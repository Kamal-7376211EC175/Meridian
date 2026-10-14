import os, datetime as dt
from pathlib import Path
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3-32b")
_db = os.getenv("DB_PATH", "backend/meridian.db")
DB_PATH = _db if os.path.isabs(_db) else str(ROOT / _db)
CORS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
AS_OF = dt.date(2026, 10, 14)       # fixed "today" so synthetic data is repeatable
CLOSE_DATE = dt.date(2026, 10, 30)  # month-end close deadline
