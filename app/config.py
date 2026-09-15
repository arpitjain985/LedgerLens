"""
Central config for LedgerLens.
All values load from environment variables (see .env.example).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Database ---
# For local dev, defaults to a local SQLite file so you can run this with
# zero external setup. Swap DATABASE_URL for your Supabase Postgres URL
# when you're ready (postgresql://user:password@host:port/dbname).
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/ledgerlens.db")

# --- File storage ---
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "uploaded_files"))
UPLOAD_DIR.mkdir(exist_ok=True)

# --- Classification ---
# Local, free, no API key needed. Swapped in services/classifier.py
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
CLASSIFICATION_CONFIDENCE_THRESHOLD = float(
    os.getenv("CLASSIFICATION_CONFIDENCE_THRESHOLD", "0.55")
)

# --- LLM fallback (for ambiguous transactions embeddings can't confidently classify) ---
# Groq has a generous free tier and is OpenAI-SDK compatible.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")  # "groq" | "openai" | "none"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# --- OCR ---
# "tesseract" (free, local) or "google_vision" (paid, better accuracy on messy scans)
OCR_ENGINE = os.getenv("OCR_ENGINE", "tesseract")
GOOGLE_VISION_API_KEY = os.getenv("GOOGLE_VISION_API_KEY", "")

# --- Anomaly detection ---
# Two independent rules, either one can flag a transaction:
#   1. Z-score outlier *within its own ledger head group* (catches transactions
#      unusual relative to similar ones, e.g. one huge rent payment among many
#      normal ones). Needs a minimum group size to be statistically meaningful.
#   2. Absolute high-value flag, checked *across all transactions regardless of
#      group* (catches large one-off transactions that a small/wrongly-classified
#      group would otherwise hide from the z-score check — see anomaly.py docstring).
ANOMALY_ZSCORE_THRESHOLD = float(os.getenv("ANOMALY_ZSCORE_THRESHOLD", "2.0"))
ANOMALY_MIN_GROUP_SIZE = int(os.getenv("ANOMALY_MIN_GROUP_SIZE", "3"))
ANOMALY_HIGH_VALUE_THRESHOLD = float(os.getenv("ANOMALY_HIGH_VALUE_THRESHOLD", "100000"))

LEDGER_HEADS_PATH = BASE_DIR / "app" / "data" / "ledger_heads.json"

# --- Security (Section 22) ---
# Comma-separated list of allowed frontend origins for CORS. Defaults to
# common local-dev ports only -- NOT "*". Override via env for a real
# deployment (e.g. ALLOWED_ORIGINS=https://app.yourdomain.com).
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501"
).split(",")

# Upload size limit in bytes -- Section 22 explicitly requires file size
# limits on uploads. Applied in routers/upload.py and routers/invoices.py.
MAX_UPLOAD_SIZE_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_MB", "25")) * 1024 * 1024

# --- Rate limiting (Section 22) ---
# Applied to /auth/login and /auth/register to slow down brute-force /
# credential-stuffing attempts. Format follows slowapi/limits syntax, e.g.
# "5/minute". Keyed by client IP by default (see app/services/rate_limit.py).
LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "5/minute")
REGISTER_RATE_LIMIT = os.getenv("REGISTER_RATE_LIMIT", "10/hour")

# --- Password reset ---
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "30"))

# --- Team invites (Section 19/20) ---
INVITE_TOKEN_EXPIRE_HOURS = int(os.getenv("INVITE_TOKEN_EXPIRE_HOURS", "168"))  # 7 days

# --- Email (zero-cost/local-first, same pattern as LLM_PROVIDER/OCR_ENGINE) ---
# "console" (default, free): logs the reset link instead of sending a real
# email -- fine for local dev/testing. "smtp": sends a real email via the
# SMTP settings below. Never make a paid email provider mandatory to run.
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "console")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_ADDRESS = os.getenv("SMTP_FROM_ADDRESS", "noreply@ledgerlens.local")
# Base URL of wherever your frontend is running, used to build the reset link.
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:8501")

# --- Auth (Section 20) ---
# CRITICAL: the default below is ONLY for local development. Section 22
# (Security) explicitly requires no secrets in source code -- this default
# exists purely so the app runs out of the box for a student/demo setup
# without forcing an .env file before first run. A loud warning is logged
# on startup (see app/services/auth.py) if this default is still in use,
# specifically so it can't accidentally ship to a real deployment silently.
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "INSECURE-DEV-ONLY-CHANGE-ME-IN-PRODUCTION")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
