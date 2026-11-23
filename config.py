import os
from typing import Optional
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

# App settings (Render injects PORT)
APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT: int = int(os.getenv("PORT", os.getenv("APP_PORT", "8000")))
DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")

# Google ADK / Gemini API Key (optional/stub-ready)
GOOGLE_API_KEY: Optional[str] = os.getenv("GOOGLE_API_KEY", "")

# Workflow 1 (PGlite / Local fallback configuration)
PGLITE_DATA_DIR: str = os.getenv("PGLITE_DATA_DIR", "./data/pglite")
W1_SQLITE_FALLBACK_FILE: str = os.getenv("W1_SQLITE_FALLBACK_FILE", "./data/workflow1_pglite_fallback.db")

# Workflow 2 (Firebase Data Connect / Cloud SQL configuration)
FIREBASE_PROJECT_ID: str = os.getenv("FIREBASE_PROJECT_ID", "shopify-adk-mvp")
FIREBASE_DATA_CONNECT_SERVICE: str = os.getenv("FIREBASE_DATA_CONNECT_SERVICE", "shopify-service")
FIREBASE_POSTGRES_URL: str = os.getenv("FIREBASE_POSTGRES_URL", "postgresql://user:pass@localhost:5432/dataconnect")
W2_SQLITE_FALLBACK_FILE: str = os.getenv("W2_SQLITE_FALLBACK_FILE", "./data/workflow2_dataconnect.db")
