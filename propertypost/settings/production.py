"""Production settings sourced entirely from the environment."""

import os
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import MIDDLEWARE as BASE_MIDDLEWARE


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"Required environment variable {name} is not set.")
    return value


DEBUG = False
MIDDLEWARE = BASE_MIDDLEWARE.copy()
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
AUTH_ADAPTER = "firebase"
DATA_ADAPTER = "google"
CAPTION_ADAPTER = os.environ.get("CAPTION_ADAPTER", "local")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
AUTOMATION_HMAC_SECRET = required_env("AUTOMATION_HMAC_SECRET")
GOOGLE_CLOUD_PROJECT = required_env("GOOGLE_CLOUD_PROJECT")
FIRESTORE_DATABASE = os.environ.get("FIRESTORE_DATABASE", "(default)")
GCS_PRIVATE_BUCKET = required_env("GCS_PRIVATE_BUCKET")
FIREBASE_PROJECT_ID = required_env("FIREBASE_PROJECT_ID")
FIREBASE_WEB_API_KEY = required_env("FIREBASE_WEB_API_KEY")
SECRET_KEY = required_env("DJANGO_SECRET_KEY")
database_url = urlparse(required_env("DATABASE_URL"))
if database_url.scheme not in {"postgres", "postgresql"} or not database_url.hostname:
    raise ImproperlyConfigured("DATABASE_URL must be a PostgreSQL URL.")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": database_url.path.lstrip("/"),
        "USER": database_url.username,
        "PASSWORD": database_url.password,
        "HOST": database_url.hostname,
        "PORT": database_url.port or 5432,
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"sslmode": "require"},
    }
}
ALLOWED_HOSTS = [
    host.strip() for host in required_env("DJANGO_ALLOWED_HOSTS").split(",") if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "true").lower() == "true"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
