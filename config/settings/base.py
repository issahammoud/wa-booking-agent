"""
Base Django settings for the config project, shared by every environment.

Environment-specific settings (DEBUG, security headers, etc.) live in
dev.py and prod.py, which both import everything from this module.
"""

from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# base.py lives at config/settings/base.py, so the project root is two
# directories up.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("DJANGO_SECRET_KEY")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# Must be set before this project's first-ever migration - see the
# StaffUser model in tenants/models.py.
AUTH_USER_MODEL = "tenants.StaffUser"

LOGIN_URL = "login"
# "dashboard-home" (bookings app) is the staff dashboard landing page,
# showing the logged-in staff user's tenant's upcoming bookings.
LOGIN_REDIRECT_URL = "dashboard-home"
LOGOUT_REDIRECT_URL = "login"


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core.apps.CoreConfig",
    "tenants.apps.TenantsConfig",
    "conversations.apps.ConversationsConfig",
    "bookings.apps.BookingsConfig",
    "integrations.apps.IntegrationsConfig",
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

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

DATABASES = {
    "default": env.db("DATABASE_URL"),
}

# Redis connection URL, used for caching, Celery, and the health check.
REDIS_URL = env("REDIS_URL")

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_RESULT_SERIALIZER = "json"

# How long to wait, after the most recent inbound message from an end user,
# before treating a burst of rapid-fire messages as "done" and processing
# them together. See conversations/tasks.py.
DEBOUNCE_WINDOW_SECONDS = env.int("DEBOUNCE_WINDOW_SECONDS", default=5)

# WhatsApp Cloud API webhook - platform-level (one Meta App serves every
# tenant; each tenant is identified inside the payload by phone_number_id).
WHATSAPP_WEBHOOK_VERIFY_TOKEN = env("WHATSAPP_WEBHOOK_VERIFY_TOKEN")
WHATSAPP_APP_SECRET = env("WHATSAPP_APP_SECRET")

# Which agent implementation replies to WhatsApp messages - "mock" (default,
# free, no network calls) or "openrouter" (a real LLM via OpenRouter). See
# integrations/agent/__init__.py::get_agent().
AGENT_BACKEND = env("AGENT_BACKEND", default="mock")

# OpenRouter (https://openrouter.ai/) - a single key/platform for both LLM
# chat completions (the real agent) and audio transcription, routing to
# whichever underlying model AGENT_MODEL/TRANSCRIPTION_MODEL name.
OPENROUTER_API_KEY = env("OPENROUTER_API_KEY")
AGENT_MODEL = env("AGENT_MODEL", default="deepseek/deepseek-chat")
TRANSCRIPTION_MODEL = env("TRANSCRIPTION_MODEL", default="openai/whisper-1")


# Logging
# Without this, every app module's logging.getLogger(__name__).info(...)
# call (webhook resolution, buffer processing, etc.) has no handler
# anywhere in its logger hierarchy and is silently dropped - the request
# lines the dev server prints itself (django.server) are a separate,
# already-configured logger and were never affected by this gap. Only
# root is configured here (not the 'django'/'django.server' loggers
# Django already sets up) to avoid double-printing framework logs.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "app_console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["app_console"],
        "level": "INFO",
    },
}


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = "static/"

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
