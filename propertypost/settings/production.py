"""Production settings sourced entirely from the environment."""

import os

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
OBJECT_ADAPTER = "google"
CAPTION_ADAPTER = os.environ.get("CAPTION_ADAPTER", "local")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
AUTOMATION_HMAC_SECRET = required_env("AUTOMATION_HMAC_SECRET")
GCS_PRIVATE_BUCKET = required_env("GCS_PRIVATE_BUCKET")
GOOGLE_CLOUD_PROJECT = required_env("GOOGLE_CLOUD_PROJECT")
SECRET_KEY = required_env("DJANGO_SECRET_KEY")
MAKE_WEBHOOK_URL = required_env("MAKE_WEBHOOK_URL")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": required_env("MYSQL_DATABASE"),
        "USER": required_env("MYSQL_USER"),
        "PASSWORD": required_env("MYSQL_PASSWORD"),
        "HOST": required_env("MYSQL_HOST"),
        "PORT": os.environ.get("MYSQL_PORT", "3306"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"charset": "utf8mb4"},
    }
}
if os.environ.get("MYSQL_SSL_ENABLED", "true").lower() == "true":
    DATABASES["default"]["OPTIONS"].update(
        {
            "ssl_verify_cert": True,
            "ssl_verify_identity": True,
            **({"ssl_ca": os.environ["MYSQL_SSL_CA"]} if os.environ.get("MYSQL_SSL_CA") else {}),
        }
    )
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
