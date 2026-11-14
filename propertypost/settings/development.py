"""Local development settings. Never use these settings in production."""

import os

from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = "django-insecure-local-development-only-not-for-production"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
MEDIA_URL = "media/"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("MYSQL_DATABASE", "propertypost"),
        "USER": os.environ.get("MYSQL_USER", "propertypost"),
        "PASSWORD": os.environ.get("MYSQL_PASSWORD", ""),
        "HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "PORT": os.environ.get("MYSQL_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            **(
                {"ssl_disabled": True}
                if os.environ.get("MYSQL_SSL_ENABLED", "false").lower() != "true"
                else {"ssl_verify_cert": True, "ssl_verify_identity": True}
            ),
        },
    }
}
