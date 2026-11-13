"""Local development settings. Never use these settings in production."""

from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = "django-insecure-local-development-only-not-for-production"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
MEDIA_URL = "media/"
