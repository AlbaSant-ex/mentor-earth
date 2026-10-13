"""Django settings for the mentoring app.

Configuration that differs between environments is read from environment variables.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Optional local configuration; real environment variables take precedence.
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


DEV_SECRET_KEY = "django-insecure-dev-only-change-me-in-production"
SECRET_KEY = os.environ.get("SECRET_KEY", DEV_SECRET_KEY)
DEBUG = env_bool("DEBUG", True)
if not DEBUG and SECRET_KEY == DEV_SECRET_KEY:
    raise ImproperlyConfigured("Set SECRET_KEY in the environment or .env when DEBUG is false.")
ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "mentoring",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "accounts.middleware.ProfileCompletionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "mentoring.context_processors.notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("SQLITE_PATH", BASE_DIR / "db.sqlite3"),
        # Take the write lock when a transaction starts, so the capacity check in
        # services.choose_mentor can't race with another request (SQLite has no row locks).
        "OPTIONS": {"transaction_mode": "IMMEDIATE"},
    }
}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "mentoring:home"
LOGOUT_REDIRECT_URL = "accounts:login"
# Login is by one-time email code only; there are no usable passwords.
AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "Europe/Madrid")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

# Email. Without EMAIL_HOST, messages (including login codes) are printed to the console.
if os.environ.get("EMAIL_HOST"):
    MAILERS = {
        "default": {
            "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "OPTIONS": {
                "host": os.environ["EMAIL_HOST"],
                "port": int(os.environ.get("EMAIL_PORT", 587)),
                "username": os.environ.get("EMAIL_HOST_USER", ""),
                "password": os.environ.get("EMAIL_HOST_PASSWORD", ""),
                "use_tls": env_bool("EMAIL_USE_TLS", True),
            },
        },
    }
else:
    MAILERS = {
        "default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"},
    }
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "mentoring@localhost")

# Mentoring program rules
MAX_MENTEES_PER_MENTOR = int(os.environ.get("MAX_MENTEES_PER_MENTOR", 2))
# Relationships automatically end after this long (~4 months).
MENTORING_RELATIONSHIP_DURATION_DAYS = int(os.environ.get("MENTORING_RELATIONSHIP_DURATION_DAYS", 120))
LOGIN_CODE_TTL_MINUTES = 10
LOGIN_CODE_MAX_ATTEMPTS = 5
LOGIN_CODE_RESEND_SECONDS = 60

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
