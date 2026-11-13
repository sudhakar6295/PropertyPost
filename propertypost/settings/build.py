"""Static asset build settings with no production credentials required."""

from .base import MIDDLEWARE as BASE_MIDDLEWARE
from .development import *  # noqa: F403

DEBUG = False
MIDDLEWARE = BASE_MIDDLEWARE.copy()
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
