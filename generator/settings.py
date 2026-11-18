"""Settings for signal-bot-reminder-generator. Everything deployment-specific comes from env."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_list(name, default=""):
    return [x.strip() for x in os.environ.get(name, default).split(";") if x.strip()]


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "reminders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
]

ROOT_URLCONF = "generator.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "generator.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DB_PATH", BASE_DIR / "db.sqlite3"),
    }
}

AUTHENTICATION_BACKENDS = [
    # Local accounts (createsuperuser) first: fast, and works while LDAP is unreachable.
    # LDAP users get an unusable local password, so they always fall through to LDAP.
    "django.contrib.auth.backends.ModelBackend",
    "reminders.ldap_backend.LDAPBackend",
]

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# UI languages: English source strings, German translation in locale/. The language comes from
# the switcher (cookie), else the browser's Accept-Language, else LANGUAGE_CODE.
LANGUAGE_CODE = "de"
LANGUAGES = [("de", "Deutsch"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
LANGUAGE_COOKIE_AGE = 365 * 24 * 3600
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = os.environ.get("STATIC_ROOT", BASE_DIR / "staticfiles")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- LDAP --------------------------------------------------------------------
LDAP_URI = os.environ.get("LDAP_URI", "ldap://ldap.schollheim.net:389")
LDAP_START_TLS = os.environ.get("LDAP_START_TLS", "0") == "1"
LDAP_BIND_DN = os.environ.get("LDAP_BIND_DN", "")
LDAP_BIND_PASSWORD = os.environ.get("LDAP_BIND_PASSWORD", "")
LDAP_BASE_DN = os.environ.get("LDAP_BASE_DN", "dc=schollheim,dc=net")
LDAP_USER_BASE = os.environ.get("LDAP_USER_BASE", f"ou=users,{LDAP_BASE_DN}")
LDAP_USER_ATTR = os.environ.get("LDAP_USER_ATTR", "cn")
# Semicolon-separated (DNs contain commas).
LDAP_GROUP_BASES = env_list(
    "LDAP_GROUP_BASES", f"ou=groups,{LDAP_BASE_DN};ou=roles,{LDAP_BASE_DN};ou=groups2,{LDAP_BASE_DN}"
)
# Members of these groups become staff (admin dashboard).
LDAP_ADMIN_GROUPS = [g.lower() for g in env_list("LDAP_ADMIN_GROUPS", f"cn=admin,ou=roles,{LDAP_BASE_DN}")]
LDAP_TIMEOUT = int(os.environ.get("LDAP_TIMEOUT", "5"))

# --- signal-bot API -------------------------------------------------------------
SIGNAL_BOT_API_URL = os.environ.get("SIGNAL_BOT_API_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
SIGNAL_BOT_API_TOKEN = os.environ.get("SIGNAL_BOT_API_TOKEN", "")
DEFAULT_TIMEZONE = os.environ.get("REMINDER_DEFAULT_TZ", "Europe/Berlin")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"v": {"format": "%(asctime)s [%(name)s] %(levelname)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "v"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
