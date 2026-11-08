"""Базовые настройки проекта. Секреты читаются из переменных окружения (.env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = False
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.contractors",
    "apps.scrapers",
    "apps.documents",
    "apps.reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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
                "apps.core.context.roles",
            ],
        },
    },
]

# PostgreSQL (SQLite по требованиям не используется)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "valdex_check"),
        "USER": os.environ.get("POSTGRES_USER", "valdex"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "valdex"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "OPTIONS": {"connect_timeout": 5},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# Режим каждого источника: mock | api | web (по умолчанию mock)
SOURCE_MODES = {
    name: os.environ.get(f"SOURCE_MODE_{name}", "mock")
    for name in ("EGRUL", "TRANSPARENT", "DISQUALIFIED", "FSSP", "EFRSB", "KAD")
}

# Логирование обращений к источникам и работы приложения
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        "scrapers_file": {
            "class": "logging.FileHandler",
            "filename": LOG_DIR / "scrapers.log",
            "encoding": "utf-8",
            "formatter": "plain",
        },
    },
    "loggers": {
        # источник, ИНН, статус, время — см. apps/scrapers
        "scrapers": {"handlers": ["scrapers_file"], "level": "INFO", "propagate": False},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
}

# Источники данных: общие параметры (ограничения вежливости — см. docs/DECISIONS.md)
FIXTURES_DIR = BASE_DIR / "tests" / "fixtures"
SOURCE_TIMEOUT = 15  # секунд на один HTTP-запрос
SOURCE_USER_AGENT = os.environ.get(
    "SOURCE_USER_AGENT", "ValdexCheck/1.0 (academic research project)"
)
EGRUL_API_KEY = os.environ.get("EGRUL_API_KEY", "")  # DaData; без ключа режим api недоступен
