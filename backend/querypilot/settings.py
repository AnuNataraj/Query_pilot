"""Django settings for QueryPilot (local demo configuration)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "analyst",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "querypilot.urls"
WSGI_APPLICATION = "querypilot.wsgi.application"

# Templates are only used by the Django admin and DRF's browsable API pages.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

STATIC_URL = "static/"

# App database: knowledge base + query history (Django ORM).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "app.db",
    }
}

# The analytics warehouse is a *separate* database that the AI can only read.
WAREHOUSE_PATH = Path(env("WAREHOUSE_PATH", str(DATA_DIR / "warehouse.db")))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

REST_FRAMEWORK = {
    # JSON for code (Angular, curl); clickable HTML pages when opened in a browser.
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    # Local demo: no login needed for the API. The admin site has its own login.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}

# --- LLM -------------------------------------------------------------------
# demo | openai (any OpenAI-compatible API: OpenAI, Gemini, Ollama, ...) | anthropic
LLM_PROVIDER = env("LLM_PROVIDER", "demo").lower()
LLM_MODEL = env("LLM_MODEL")
LLM_API_KEY = env("LLM_API_KEY")
LLM_BASE_URL = env("LLM_BASE_URL")
LLM_TIMEOUT_S = int(env("LLM_TIMEOUT_S", "60"))

# --- Retrieval (RAG) -----------------------------------------------------------
# tfidf (offline, default) | openai (OpenAI-compatible /embeddings endpoint)
EMBEDDINGS_BACKEND = env("EMBEDDINGS_BACKEND", "tfidf").lower()
EMBEDDINGS_MODEL = env("EMBEDDINGS_MODEL", "text-embedding-3-small")
EMBEDDINGS_BASE_URL = env("EMBEDDINGS_BASE_URL") or LLM_BASE_URL
EMBEDDINGS_API_KEY = env("EMBEDDINGS_API_KEY") or LLM_API_KEY
RAG_TOP_K = int(env("RAG_TOP_K", "5"))

# --- Query safety limits -----------------------------------------------------------
MAX_ROWS = int(env("MAX_ROWS", "500"))
QUERY_TIMEOUT_S = float(env("QUERY_TIMEOUT_S", "5"))
MAX_SQL_ATTEMPTS = int(env("MAX_SQL_ATTEMPTS", "3"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "loggers": {"analyst": {"handlers": ["console"], "level": "INFO"}},
}
