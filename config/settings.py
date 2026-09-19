from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_list(name: str, default: str = "") -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-change-me")
DEBUG = get_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = get_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,api.toolvya.com")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "apps.core.apps.CoreConfig",
    "apps.users.apps.UsersConfig",
    "apps.tools.apps.ToolsConfig",
    "apps.pdf.apps.PDFConfig",
    "apps.jobs.apps.JobsConfig",
    "apps.files.apps.FilesConfig",
    "apps.analytics.apps.AnalyticsConfig",
]

MIDDLEWARE = [
    "apps.core.middleware.RequestLoggingMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
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
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

database_url = os.getenv("DATABASE_URL")
database_engine = os.getenv("DATABASE_ENGINE", "django.db.backends.sqlite3")
if database_url:
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(database_url)}
elif database_engine == "django.db.backends.postgresql":
    DATABASES = {
        "default": {
            "ENGINE": database_engine,
            "NAME": os.getenv("DATABASE_NAME", "toolvaya"),
            "USER": os.getenv("DATABASE_USER", "toolvaya"),
            "PASSWORD": os.getenv("DATABASE_PASSWORD", ""),
            "HOST": os.getenv("DATABASE_HOST", "127.0.0.1"),
            "PORT": os.getenv("DATABASE_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

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

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

PDF_MAX_INPUT_FILES = int(os.getenv("PDF_MAX_INPUT_FILES", "10"))
PDF_MAX_INPUT_BYTES = int(os.getenv("PDF_MAX_INPUT_BYTES", str(50 * 1024 * 1024)))
PDF_MAX_PAGES = int(os.getenv("PDF_MAX_PAGES", "500"))
PDF_JOB_TTL_HOURS = int(os.getenv("PDF_JOB_TTL_HOURS", "24"))
PDF_CLEANUP_BATCH_SIZE = int(os.getenv("PDF_CLEANUP_BATCH_SIZE", "100"))

CORS_ALLOWED_ORIGINS = get_list("CORS_ALLOWED_ORIGINS", "https://toolvya.com")
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://toolvya-frontend-[\w-]+-raunakaga2004s-projects\.vercel\.app$",
]
CORS_ALLOW_CREDENTIALS = True

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "EXCEPTION_HANDLER": "apps.core.exception_handler.core_exception_handler",
}

REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = [
    "rest_framework.throttling.AnonRateThrottle",
    "rest_framework.throttling.UserRateThrottle",
]
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "anon": "60/min",
    "user": "120/min",
    "pdf_tools": "30/min",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Toolvaya API",
    "DESCRIPTION": "Toolvaya backend API for PDF tools and related services.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
X_FRAME_OPTIONS = "DENY"
REFERRER_POLICY = "strict-origin-when-cross-origin"

FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("FILE_UPLOAD_MAX_MEMORY_SIZE", str(5 * 1024 * 1024)))
DATA_UPLOAD_MAX_NUMBER_FILES = PDF_MAX_INPUT_FILES * 2
DATA_UPLOAD_MAX_MEMORY_SIZE = PDF_MAX_INPUT_BYTES * 2

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = get_bool("CELERY_TASK_ALWAYS_EAGER", DEBUG)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "cleanup-expired-pdf-jobs": {
        "task": "apps.pdf.tasks.cleanup_expired_pdf_jobs",
        "schedule": 3600.0,
    }
}

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)-8s %(name)s [%(module)s:%(lineno)d] %(message)s",
        },
        "simple": {
            "format": "%(asctime)s %(levelname)-8s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple" if DEBUG else "verbose",
        },
        "app_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "app.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "error.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "level": "ERROR",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console", "app_file", "error_file"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "app_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "app_file", "error_file"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console", "app_file", "error_file"],
            "level": "WARNING",
            "propagate": False,
        },
        "celery": {
            "handlers": ["console", "app_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console", "app_file", "error_file"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}
